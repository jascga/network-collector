"""
runner.py — 任务执行器（新机制）

负责：
  1. 加载场景插件
  2. 匹配设备（region + 插件 DEVICE_RULES）
  3. 拼装设备→命令
  4. SSH 采集
  5. 调用解析器，得到结构化数据
  6. 调用插件的 analyze()，得到结果
"""
import json
import re
import time
from ipaddress import ip_network
from pathlib import Path
from typing import Optional

from core.expect_engine import SSHExpectSession
from core.scene_registry import SceneInfo, get_registry
from core.parser_loader import load_parser
from core.db import Database


class TaskRunner:
    """单次任务执行器（同步版本，CLI 入口使用）。"""

    def __init__(self, db: Database, task_id: int, output_base: Path = None,
                 cipher=None):
        self.db = db
        self.task_id = task_id
        self.output_base = Path(output_base) if output_base else db.get_output_dir()
        self.cipher = cipher
        self._cancel_flag = False
        self.task_dir: Optional[Path] = None

    # ── 任务入口 ──────────────────────────────────────

    def run(self) -> dict:
        task = self.db.get_task(self.task_id)
        if not task:
            raise ValueError(f"任务不存在: {self.task_id}")

        plugin_name = task["plugin_name"]
        plugin_version = task.get("plugin_version", "") or ""
        params = self._parse_json_field(task.get("plugin_params")) or {}

        # 1. 加载插件
        scene = get_registry().get(plugin_name)
        if not scene:
            raise RuntimeError(f"插件未安装: {plugin_name}")
        if plugin_version and scene.version != plugin_version:
            print(f"[Runner] 警告: 插件版本不匹配 (任务={plugin_version}, 当前={scene.version})")

        # 2. 准备任务目录
        self.task_dir = self.output_base / f"task_{self.task_id:04d}"
        (self.task_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.task_dir / "parsed").mkdir(parents=True, exist_ok=True)

        # 3. 同步插件自带的命令（如不存在则写入 commands 表）
        self._sync_bundled_commands(scene)

        # 4. 匹配设备
        region = params.get("region", "")
        devices = self._match_devices(scene, region)
        if not devices:
            err = {"error": f"未匹配到设备 (region={region}, rules={scene.device_rules})"}
            self.db.update_task_status(self.task_id, "completed", err)
            return err

        # 5. 写回设备清单
        self.db.conn.execute(
            "UPDATE tasks SET device_list=? WHERE id=?",
            (json.dumps(devices, ensure_ascii=False, default=str), self.task_id),
        )
        self.db.conn.commit()

        self.db.update_task_status(self.task_id, "running")

        # 6. 采集 + 解析
        parsed_data = {}
        for dev in devices:
            if self._cancel_flag:
                break
            role = dev.get("role", "")
            cmd_names = scene.command_mapping.get(role, [])
            if not cmd_names:
                print(f"[Runner] 跳过 {dev['ip']}: 角色 {role} 无命令映射")
                continue
            print(f"[Runner] 采集 {dev['hostname']} ({dev['ip']}) role={role} cmds={cmd_names}")

            dev_parsed = {
                "hostname": dev.get("hostname", ""),
                "section":  dev.get("section", ""),
                "role":     role,
                "results":  {},
            }
            for cmd_name in cmd_names:
                if self._cancel_flag:
                    break
                self._run_one_command(scene, dev, cmd_name, params, dev_parsed)

            parsed_data[dev["ip"]] = dev_parsed
            with open(self.task_dir / "parsed" / f"{dev['ip']}.json", "w", encoding="utf-8") as f:
                json.dump(dev_parsed, f, ensure_ascii=False, indent=2)

        # 7. 分析
        if self._cancel_flag:
            self.db.update_task_status(self.task_id, "cancelled")
            return {"cancelled": True}

        result = scene.analyze(self.task_dir, parsed_data, params)
        with open(self.task_dir / "result.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        self.db.update_task_status(self.task_id, "completed", result.get("summary", {}))
        return result

    # ── 取消 ──────────────────────────────────────────

    def cancel(self):
        """标记取消（协作式，已跑的设备结果保留）。"""
        self._cancel_flag = True
        self.db.update_task_status(self.task_id, "cancelled")

    # ── 内部方法 ──────────────────────────────────────

    def _parse_json_field(self, value) -> Optional[dict]:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    def _match_devices(self, scene: SceneInfo, region: str) -> list:
        """按插件 DEVICE_RULES 在 devices 表里匹配设备。"""
        seen = set()
        devices = []
        for rule in scene.device_rules:
            rows = self.db.conn.execute("""
                SELECT hostname, ip, region, section, role, vendor
                FROM devices
                WHERE is_active=1 AND region=?
                  AND section GLOB ?
                  AND role=?
                ORDER BY hostname
            """, (region, rule["section_glob"], rule["role"])).fetchall()
            for r in rows:
                d = dict(r)
                if d["ip"] not in seen:
                    seen.add(d["ip"])
                    devices.append(d)
        return devices

    def _sync_bundled_commands(self, scene: SceneInfo):
        """把插件自带的命令写入 commands 表（如不存在）。"""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for cmd in scene.bundled_commands:
            existing = self.db.conn.execute(
                "SELECT id FROM commands WHERE name=?", (cmd["name"],)
            ).fetchone()
            if existing:
                continue
            self.db.conn.execute("""
                INSERT INTO commands
                    (name, cmd, cmd_type, vendor, description, parser, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cmd["name"], cmd["cmd"], cmd.get("cmd_type", "simple"),
                cmd.get("vendor"), cmd.get("description"),
                cmd.get("parser"), now, now,
            ))
        self.db.conn.commit()
        print(f"[Runner] 已同步 {len(scene.bundled_commands)} 条插件自带命令")

    def _run_one_command(self, scene: SceneInfo, dev: dict, cmd_name: str,
                         params: dict, dev_parsed: dict):
        """采集 + 解析单条命令（可能为命令模板的每个变量实例跑一次）。"""
        cmd_row = self.db.conn.execute(
            "SELECT name, cmd, parser FROM commands WHERE name=?", (cmd_name,)
        ).fetchone()
        if not cmd_row:
            print(f"[Runner] 警告: 命令 {cmd_name} 不存在")
            return

        cmd_template = cmd_row["cmd"]
        parser_name = cmd_row["parser"] or cmd_name  # 默认 parser 与 command 同名
        parser_fn = load_parser(parser_name)

        # 计算需要循环的变量值
        # 当前场景只识别 {eip_cidr} / {eip_mask}（以及含 /24、IP 段）
        instances = self._expand_cmd_instances(cmd_template, params)
        if not instances:
            instances = [(cmd_template, "")]  # 至少跑一次（占位）

        all_routes = []
        for inst_cmd, inst_label in instances:
            if self._cancel_flag:
                break
            output = self._ssh_collect(dev, inst_cmd)
            safe_label = re.sub(r"[\\/*?:\"<>|\s]", "_", inst_label) or "default"
            raw_file = self.task_dir / "raw" / f"{dev['ip']}_{cmd_name}_{safe_label}.txt"
            raw_file.write_text(output or "", encoding="utf-8")

            if parser_fn:
                try:
                    routes = parser_fn(output, params) or []
                    all_routes.extend(routes)
                except Exception as e:
                    print(f"[ParserLoader] 解析失败 {parser_name}: {e}")

        dev_parsed["results"][cmd_name] = all_routes

    def _expand_cmd_instances(self, cmd_template: str, params: dict) -> list:
        """根据命令模板的变量和用户参数，展开为多个具体命令实例。

        返回: [(具体命令, 实例标签), ...]
        """
        # 简单实现：识别 {eip_input} 字段
        if "{eip_cidr}" not in cmd_template and "{eip_mask}" not in cmd_template:
            return [(cmd_template, "")]

        cidrs = []
        for token in re.split(r"[,\s\n]+", params.get("eip_input", "") or ""):
            token = token.strip()
            if not token:
                continue
            try:
                cidrs.append(ip_network(token, strict=False))
            except ValueError:
                continue

        results = []
        for cidr in cidrs:
            cmd = cmd_template.replace("{eip_cidr}", str(cidr.network_address))
            cmd = cmd.replace("{eip_mask}", str(cidr.prefixlen))
            results.append((cmd, str(cidr)))
        return results

    def _ssh_collect(self, dev: dict, command: str) -> str:
        """单次 SSH 采集（复用 core.expect_engine.SSHExpectSession）。"""
        ssh = self.db.resolve_ssh(dev.get("region", ""), dev.get("section", ""))
        if not ssh:
            return f"[ERROR] 未找到 SSH 配置: {dev.get('region','')}/{dev.get('section','')}"

        # 解密 key 密码（如有）
        key_password = ssh.get("key_password", "")
        if key_password and self.cipher:
            from core.crypto import decrypt
            try:
                key_password = decrypt(self.cipher, key_password) or None
            except Exception:
                key_password = None

        session = None
        try:
            session = SSHExpectSession(
                hostname=ssh["host"],
                port=ssh.get("port", 22),
                username=ssh.get("username"),
                key_filename=ssh.get("key_path"),
                key_password=key_password,
                timeout=30,
            )
            session.connect()

            if ssh.get("expect_flow"):
                flow = ssh["expect_flow"]
                if isinstance(flow, str):
                    try:
                        flow = json.loads(flow)
                    except json.JSONDecodeError:
                        flow = []
                if flow:
                    session.run_expect_flow(flow, variables={"device_ip": dev["ip"]})

            return session.execute_command(command, cmd_timeout=60)
        except Exception as e:
            return f"[ERROR] {e}"
        finally:
            if session:
                try:
                    session.close()
                except Exception:
                    pass
