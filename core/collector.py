"""
collector.py — 采集引擎

负责执行一个完整的采集任务：
1. 解析任务信息（场景、设备、命令）
2. 按 Section 分组，每组复用 SSH 连接
3. 每台设备串行执行命令
4. 命令类型支持：简单 / 参数化 / 派生 (foreach)
5. 大结果分块写入文件
6. 错误隔离（单设备/单命令失败不影响其他）
"""

import os
import re
import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .expect_engine import SSHExpectSession, VariableResolver

logger = logging.getLogger("collector")


# ── 数据模型 ──────────────────────────────────────────

@dataclass
class DeviceTask:
    """单台设备的采集任务"""
    ip: str
    hostname: str
    region: str
    section: str
    role: str
    vendor: str
    commands: list          # 执行命令列表（已解析）
    ssh_config: dict        # SSH 连接配置
    device_dir: Path        # 结果存储目录


@dataclass
class CollectionTask:
    """完整的采集任务"""
    task_id: int
    task_name: str
    region: str
    devices: list[DeviceTask]
    output_dir: Path        # tasks/<task_id>/
    status: str = "pending"  # pending/running/completed/failed/cancelled
    cancel_flag: bool = False


# ── 命令执行器 ────────────────────────────────────────

class CommandExecutor:
    """单条命令执行器"""

    @staticmethod
    def execute(session: SSHExpectSession, command_spec: dict, variables: dict, cmd_timeout: int = 60) -> dict:
        """
        执行一条命令

        参数:
            session: SSH 会话
            command_spec: 命令定义
                {"cmd": "...", "type": "simple|parameterized|foreach"}

        返回:
            {"success": bool, "raw_output": str, "error": str}
        """
        cmd_type = command_spec.get("type", "simple")

        if cmd_type == "foreach":
            return CommandExecutor._execute_foreach(session, command_spec, variables, cmd_timeout)
        else:
            return CommandExecutor._execute_simple(session, command_spec, variables, cmd_timeout)

    @staticmethod
    def _execute_simple(session, cmd_spec, variables, timeout) -> dict:
        """简单命令 / 参数化命令"""
        resolver = VariableResolver(variables)
        cmd = resolver.resolve(cmd_spec.get("cmd", ""))

        try:
            output = session.execute_command(cmd, cmd_timeout=timeout)
            return {
                "success": True,
                "command": cmd,
                "raw_output": output,
                "size": len(output),
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "command": cmd,
                "raw_output": "",
                "size": 0,
                "error": str(e),
            }

    @staticmethod
    def _execute_foreach(session, cmd_spec, variables, timeout) -> dict:
        """派生命令：先执行父命令，解析出值，再为每个值执行子命令"""
        resolver = VariableResolver(variables)

        # 1. 执行父命令
        parent_cmd = resolver.resolve(cmd_spec.get("cmd", ""))
        parent_output = session.execute_command(parent_cmd, cmd_timeout=timeout)

        # 2. 提取迭代值
        parse_pattern = cmd_spec.get("parse", "")
        values = CommandExecutor._parse_values(parent_output, parse_pattern)

        # 3. 为每个值执行子命令
        foreach_var = cmd_spec.get("foreach_var", "value")
        sub_results = []
        for val in values:
            sub_vars = {**variables, foreach_var: val}
            for sub_cmd_spec in cmd_spec.get("sub_commands", []):
                result = CommandExecutor._execute_simple(session, sub_cmd_spec, sub_vars, timeout)
                result["foreach_value"] = val
                sub_results.append(result)

        return {
            "success": True,
            "command": parent_cmd,
            "raw_output": parent_output,
            "foreach_values": values,
            "sub_results": sub_results,
            "size": len(parent_output),
        }

    @staticmethod
    def _parse_values(output: str, pattern: str) -> list:
        """从命令输出中解析迭代值"""
        if not pattern:
            return []

        # regex: xxx 格式
        if pattern.startswith("regex:"):
            regex = pattern[6:].strip()
            return re.findall(regex, output)

        # split: 按分隔符拆分
        if pattern.startswith("split:"):
            sep = pattern[6:].strip()
            return [line.strip() for line in output.split(sep) if line.strip()]

        return []


# ── 设备采集器 ────────────────────────────────────────

class DeviceCollector:
    """单台设备采集器"""

    def __init__(self, device: DeviceTask, cancel_flag: callable, output_dir: Path):
        self.device = device
        self.is_cancelled = cancel_flag
        self.device_dir = output_dir
        self.result = {
            "device_ip": device.ip,
            "hostname": device.hostname,
            "status": "pending",
            "commands": [],
            "error": None,
            "started_at": None,
            "completed_at": None,
        }

        # 创建设备结果目录
        self.device_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict:
        """执行设备采集"""
        self.result["started_at"] = time.time()
        session = None

        try:
            # 1. SSH 连接
            ssh_config = self.device.ssh_config
            session = SSHExpectSession(
                hostname=ssh_config["host"],
                port=ssh_config.get("port", 22),
                username=ssh_config.get("username"),
                key_filename=ssh_config.get("key_path"),
                key_password=ssh_config.get("key_password"),
            )
            session.connect()

            # 2. 执行 expect 流程跳到目标设备
            if ssh_config.get("expect_flow"):
                session.run_expect_flow(
                    ssh_config["expect_flow"],
                    variables={"device_ip": self.device.ip},
                )

            # 3. 串行执行所有命令
            for idx, cmd_spec in enumerate(self.device.commands):
                if self.is_cancelled():
                    break

                cmd_result = CommandExecutor.execute(session, cmd_spec, {"device_ip": self.device.ip})

                # 保存输出到文件
                cmd_safe_name = f"cmd_{idx+1}_{cmd_spec.get('cmd','unknown')[:30]}"
                cmd_safe_name = re.sub(r'[\\/*?:"<>|]', "_", cmd_safe_name)
                output_file = self.device_dir / f"{cmd_safe_name}.txt"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(cmd_result.get("raw_output", ""))

                # 保存子命令结果（foreach 类型）
                for sub_idx, sub in enumerate(cmd_result.get("sub_results", [])):
                    sub_file = self.device_dir / f"{cmd_safe_name}_foreach_{sub_idx}.txt"
                    with open(sub_file, "w", encoding="utf-8") as f:
                        f.write(sub.get("raw_output", ""))

                cmd_result["output_file"] = str(output_file)
                self.result["commands"].append(cmd_result)

            self.result["status"] = "cancelled" if self.is_cancelled() else "completed"

        except Exception as e:
            self.result["status"] = "failed"
            self.result["error"] = str(e)
            logger.error(f"设备 {self.device.ip} 采集失败: {e}")

        finally:
            if session:
                session.close()
            self.result["completed_at"] = time.time()

        # 写状态文件
        status_file = self.device_dir / "status.json"
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(self.result, f, ensure_ascii=False, indent=2)

        return self.result


# ── 采集引擎 ──────────────────────────────────────────

class Collector:
    """采集引擎主类"""

    def __init__(self, db, output_base: str = "tasks"):
        self.db = db
        self.output_base = Path(output_base)
        self._cancel_flags: dict[int, bool] = {}
        self._active_threads: dict[int, threading.Thread] = {}

    def _is_cancelled(self, task_id: int) -> bool:
        return self._cancel_flags.get(task_id, False)

    def cancel_task(self, task_id: int):
        """取消任务"""
        self._cancel_flags[task_id] = True
        self.db.update_task_status(task_id, "cancelled")

    def run_task(self, task_id: int, callback: callable = None):
        """
        执行采集任务（后台线程调用）

        参数:
            task_id: 任务ID
            callback: 完成回调函数
        """
        self._cancel_flags[task_id] = False

        # 获取任务信息
        task_info = self.db.get_task(task_id)
        if not task_info:
            raise ValueError(f"任务不存在: {task_id}")

        # 解析设备列表
        device_list = json.loads(task_info["device_list"]) if isinstance(task_info["device_list"], str) else task_info["device_list"]

        # 采集参数
        input_params = json.loads(task_info["input_params"]) if isinstance(task_info["input_params"], str) else task_info["input_params"]
        cmd_timeout = input_params.get("timeout", 60)

        # 创建任务目录
        task_dir = self.output_base / f"task_{task_id:04d}"
        task_dir.mkdir(parents=True, exist_ok=True)

        # 写任务信息
        with open(task_dir / "task.json", "w", encoding="utf-8") as f:
            json.dump(task_info, f, ensure_ascii=False, indent=2)

        self.db.update_task_status(task_id, "running")

        # 按 Section 分组（同 Section 复用 SSH 连接）
        sections = {}
        for dev in device_list:
            sec = dev.get("section", "default")
            if sec not in sections:
                sections[sec] = []
            sections[sec].append(dev)

        all_results = []
        max_concurrent = 3  # 最大并行 Section 数

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = []

            for section, devices in sections.items():
                # 获取该 Section 对应的 SSH 连接
                ssh_conn = self.db.resolve_ssh(task_info.get("region", ""), section)
                if not ssh_conn:
                    logger.warning(f"Section {section} 未配置 SSH 连接，跳过")
                    continue

                # 解析命令集
                commands = self._build_commands(devices[0].get("command_sets", []))

                for dev in devices:
                    device_task = DeviceTask(
                        ip=dev["ip"],
                        hostname=dev.get("hostname", ""),
                        region=task_info.get("region", ""),
                        section=section,
                        role=dev.get("role", ""),
                        vendor=dev.get("vendor", ""),
                        commands=commands,
                        ssh_config=ssh_conn,
                        device_dir=task_dir / f"devices/{dev['ip']}",
                    )

                    collector = DeviceCollector(
                        device=device_task,
                        cancel_flag=lambda tid=task_id: self._is_cancelled(tid),
                        output_dir=task_dir / f"devices/{dev['ip']}",
                    )

                    futures.append(executor.submit(collector.run))

            # 收集结果
            for future in as_completed(futures):
                try:
                    result = future.result()
                    all_results.append(result)
                except Exception as e:
                    logger.error(f"采集线程异常: {e}")

        # 写汇总
        summary = {
            "total": len(device_list),
            "completed": sum(1 for r in all_results if r["status"] == "completed"),
            "failed": sum(1 for r in all_results if r["status"] == "failed"),
            "cancelled": sum(1 for r in all_results if r["status"] == "cancelled"),
            "results": all_results,
        }
        with open(task_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # 更新任务状态
        final_status = "completed" if summary["failed"] == 0 else "completed_with_errors"
        if self._is_cancelled(task_id):
            final_status = "cancelled"
        self.db.update_task_status(task_id, final_status, summary)

        if callback:
            callback(task_id, summary)

    def _build_commands(self, command_set_ids: list) -> list:
        """从命令集 ID 列表构建命令列表"""
        commands = []
        if not command_set_ids:
            return commands
        for cmd_id in command_set_ids:
            row = self.db.conn.execute(
                "SELECT id, commands FROM command_sets WHERE id=?", (cmd_id,)
            ).fetchone()
            if not row:
                logger.warning(f"命令集 ID {cmd_id} 不存在，跳过")
                continue
            cmds_json = row["commands"]
            if isinstance(cmds_json, str):
                try:
                    cmds = json.loads(cmds_json)
                except json.JSONDecodeError as e:
                    logger.warning(f"命令集 {cmd_id} JSON 解析失败: {e}")
                    continue
            elif isinstance(cmds_json, list):
                cmds = cmds_json
            else:
                continue
            if isinstance(cmds, list):
                commands.extend(cmd if isinstance(cmd, dict) else {"cmd": str(cmd)} for cmd in cmds)
        return commands
