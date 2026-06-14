"""
db.py — SQLite 数据库操作层

所有配置数据存储：SSH连接、设备、Region映射、命令集、场景、任务。
"""

import sqlite3
import json
import datetime
from pathlib import Path
from typing import Optional


# ── 数据库初始化 ──────────────────────────────────────

SCHEMA_VERSION = 1

CREATE_TABLES = [
    # SSH连接
    """CREATE TABLE IF NOT EXISTS ssh_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        host TEXT NOT NULL,
        port INTEGER DEFAULT 22,
        username TEXT,
        key_path TEXT,
        key_password TEXT,       -- AES 加密存储
        expect_flow TEXT,         -- JSON: [{"expect":"...", "send":"..."}]
        created_at TEXT,
        updated_at TEXT
    )""",

    # Region+Section → SSH 映射
    """CREATE TABLE IF NOT EXISTS region_mapping (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region TEXT NOT NULL,
        section TEXT NOT NULL,         -- 通配符: all, az*, 具体名
        ssh_connection_id INTEGER REFERENCES ssh_connections(id),
        is_default INTEGER DEFAULT 0,  -- 该Region的默认连接
        UNIQUE(region, section)
    )""",

    # 设备
    """CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname TEXT NOT NULL,
        ip TEXT NOT NULL,
        region TEXT NOT NULL,
        section TEXT NOT NULL,
        role TEXT NOT NULL,
        vendor TEXT,
        description TEXT,
        source TEXT DEFAULT 'manual',  -- excel / manual
        is_active INTEGER DEFAULT 1,   -- 0=已下线
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(region, section, hostname)
    )""",

    # 全局设备组模板
    """CREATE TABLE IF NOT EXISTS device_group_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        section_pattern TEXT NOT NULL,
        role TEXT NOT NULL,
        description TEXT,
        created_at TEXT
    )""",

    # 命令集
    """CREATE TABLE IF NOT EXISTS command_sets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        vendor TEXT,                   -- 华为/锐捷/null(通用)
        description TEXT,
        commands TEXT NOT NULL,        -- JSON: [{"cmd":"...", "output_format":{...}}]
        created_at TEXT,
        updated_at TEXT
    )""",

    # 场景模板
    """CREATE TABLE IF NOT EXISTS scene_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        scene_type TEXT NOT NULL,
        description TEXT,
        analyzer_plugin TEXT NOT NULL,   -- 绑定的分析插件
        web_system TEXT DEFAULT '',
        version INTEGER DEFAULT 1,
        input_params TEXT,               -- JSON: 输入参数定义
        sub_scenes TEXT,                 -- JSON: 子场景
        device_groups TEXT,              -- JSON: 设备组
        command_set_ids TEXT,            -- JSON: [1, 2, 3]
        is_template INTEGER DEFAULT 0,   -- 预置模板
        created_at TEXT,
        updated_at TEXT
    )""",

    # 任务
    """CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        scene_template_id INTEGER,
        scene_version INTEGER,
        scene_snapshot TEXT,          -- JSON: 创建时的完整场景快照
        region TEXT,
        status TEXT DEFAULT 'pending', -- pending/running/completed/failed/cancelled
        input_params TEXT,             -- JSON: 用户填的输入参数
        device_list TEXT,              -- JSON: 实际采集的设备
        result_summary TEXT,           -- JSON: 分析结论摘要
        created_at TEXT,
        completed_at TEXT
    )""",

    # 数据库版本
    """CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    )""",
]

INSERT_DEFAULTS = [
    """INSERT OR IGNORE INTO schema_version (version) VALUES (?)""",
]


class Database:
    """数据库操作封装"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self):
        """打开数据库并初始化表结构"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()

    def close(self):
        if self.conn:
            self.conn.close()

    def _init_tables(self):
        for sql in CREATE_TABLES:
            self.conn.execute(sql)
        self.conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        self.conn.commit()

    # ── SSH 连接 ──────────────────────────────────────

    def list_ssh_connections(self) -> list:
        rows = self.conn.execute("SELECT * FROM ssh_connections ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def get_ssh_connection(self, conn_id: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM ssh_connections WHERE id=?", (conn_id,)).fetchone()
        return dict(r) if r else None

    def get_ssh_connection_by_name(self, name: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM ssh_connections WHERE name=?", (name,)).fetchone()
        return dict(r) if r else None

    def save_ssh_connection(self, data: dict) -> int:
        now = datetime.datetime.now().isoformat()
        data["created_at"] = now
        data["updated_at"] = now
        if isinstance(data.get("expect_flow"), list):
            data["expect_flow"] = json.dumps(data["expect_flow"], ensure_ascii=False)
        cur = self.conn.execute("""INSERT INTO ssh_connections (name,host,port,username,key_path,key_password,expect_flow,created_at,updated_at)
            VALUES (:name,:host,:port,:username,:key_path,:key_password,:expect_flow,:created_at,:updated_at)""", data)
        self.conn.commit()
        return cur.lastrowid

    def update_ssh_connection(self, conn_id: int, data: dict):
        data["updated_at"] = datetime.datetime.now().isoformat()
        if isinstance(data.get("expect_flow"), list):
            data["expect_flow"] = json.dumps(data["expect_flow"], ensure_ascii=False)
        data["id"] = conn_id
        self.conn.execute("""UPDATE ssh_connections SET name=:name,host=:host,port=:port,
            username=:username,key_path=:key_path,key_password=:key_password,
            expect_flow=:expect_flow,updated_at=:updated_at WHERE id=:id""", data)
        self.conn.commit()

    def delete_ssh_connection(self, conn_id: int):
        self.conn.execute("DELETE FROM ssh_connections WHERE id=?", (conn_id,))
        self.conn.commit()

    # ── Region 映射 ───────────────────────────────────

    def list_region_mapping(self) -> list:
        rows = self.conn.execute("""
            SELECT rm.*, sc.name as ssh_name
            FROM region_mapping rm
            LEFT JOIN ssh_connections sc ON rm.ssh_connection_id = sc.id
            ORDER BY rm.region, rm.section
        """).fetchall()
        return [dict(r) for r in rows]

    def resolve_ssh(self, region: str, section: str) -> Optional[dict]:
        """根据 Region+Section 查找对应的 SSH 连接"""
        # 精确匹配
        r = self.conn.execute("""
            SELECT sc.* FROM region_mapping rm
            JOIN ssh_connections sc ON rm.ssh_connection_id = sc.id
            WHERE rm.region=? AND rm.section=?
        """, (region, section)).fetchone()
        if r:
            return dict(r)
        # 通配符匹配
        r = self.conn.execute("""
            SELECT sc.* FROM region_mapping rm
            JOIN ssh_connections sc ON rm.ssh_connection_id = sc.id
            WHERE rm.region=? AND rm.section LIKE ?
            ORDER BY LENGTH(rm.section) DESC
            LIMIT 1
        """, (region, section)).fetchone()
        if r:
            return dict(r)
        # default 回退
        r = self.conn.execute("""
            SELECT sc.* FROM region_mapping rm
            JOIN ssh_connections sc ON rm.ssh_connection_id = sc.id
            WHERE rm.region=? AND rm.is_default=1
        """, (region,)).fetchone()
        return dict(r) if r else None

    def save_region_mapping(self, data: dict):
        self.conn.execute("""INSERT OR REPLACE INTO region_mapping (region,section,ssh_connection_id,is_default)
            VALUES (:region,:section,:ssh_connection_id,:is_default)""", data)
        self.conn.commit()

    # ── 设备 ──────────────────────────────────────────

    def list_devices(self, region: str = None, section: str = None, role: str = None) -> list:
        sql = "SELECT * FROM devices WHERE is_active=1"
        params = []
        if region:
            sql += " AND region=?"
            params.append(region)
        if section:
            sql += " AND section GLOB ?"
            params.append(section)
        if role:
            sql += " AND role=?"
            params.append(role)
        sql += " ORDER BY hostname"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def add_device(self, data: dict) -> int:
        now = datetime.datetime.now().isoformat()
        data["created_at"] = now
        data["updated_at"] = now
        cur = self.conn.execute("""INSERT OR REPLACE INTO devices
            (hostname,ip,region,section,role,vendor,description,source,is_active,created_at,updated_at)
            VALUES (:hostname,:ip,:region,:section,:role,:vendor,:description,:source,1,:created_at,:updated_at)""", data)
        self.conn.commit()
        return cur.lastrowid

    def update_device(self, device_id: int, data: dict):
        """更新设备信息"""
        data["updated_at"] = datetime.datetime.now().isoformat()
        data["id"] = device_id
        self.conn.execute("""UPDATE devices SET
            hostname=:hostname,ip=:ip,region=:region,section=:section,
            role=:role,vendor=:vendor,description=:description,
            source=:source,is_active=:is_active,updated_at=:updated_at
            WHERE id=:id""", data)
        self.conn.commit()

    def delete_device(self, device_id: int):
        """软删除设备"""
        self.conn.execute("UPDATE devices SET is_active=0, updated_at=? WHERE id=?",
                          (datetime.datetime.now().isoformat(), device_id))
        self.conn.commit()

    def import_devices(self, devices: list[dict]):
        """批量导入设备（Excel导入用）"""
        now = datetime.datetime.now().isoformat()
        for d in devices:
            d["created_at"] = now
            d["updated_at"] = now
            d["source"] = "excel"
            self.conn.execute("""INSERT OR REPLACE INTO devices
                (hostname,ip,region,section,role,vendor,description,source,is_active,created_at,updated_at)
                VALUES (:hostname,:ip,:region,:section,:role,:vendor,:description,:source,1,:created_at,:updated_at)""", d)
        self.conn.commit()

    def match_devices(self, region: str, section_glob: str, role: str) -> list:
        """按 Region + Section通配符 + Role 匹配设备"""
        rows = self.conn.execute("""
            SELECT * FROM devices
            WHERE region=? AND section GLOB ? AND role=? AND is_active=1
            ORDER BY hostname
        """, (region, section_glob, role)).fetchall()
        return [dict(r) for r in rows]

    # ── 场景模板 ──────────────────────────────────────

    def list_scenes(self) -> list:
        rows = self.conn.execute("SELECT * FROM scene_templates ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def get_scene(self, scene_id: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM scene_templates WHERE id=?", (scene_id,)).fetchone()
        return dict(r) if r else None

    def save_scene(self, data: dict) -> int:
        now = datetime.datetime.now().isoformat()
        data["created_at"] = now
        data["updated_at"] = now
        for field in ("input_params", "sub_scenes", "device_groups", "command_set_ids"):
            if isinstance(data.get(field), (list, dict)):
                data[field] = json.dumps(data[field], ensure_ascii=False)
        cur = self.conn.execute("""INSERT INTO scene_templates
            (name,scene_type,description,analyzer_plugin,web_system,version,
             input_params,sub_scenes,device_groups,command_set_ids,is_template,created_at,updated_at)
            VALUES (:name,:scene_type,:description,:analyzer_plugin,:web_system,:version,
             :input_params,:sub_scenes,:device_groups,:command_set_ids,:is_template,:created_at,:updated_at)""", data)
        self.conn.commit()
        return cur.lastrowid

    def update_scene(self, scene_id: int, data: dict):
        """更新场景"""
        data["updated_at"] = datetime.datetime.now().isoformat()
        for field in ("input_params", "sub_scenes", "device_groups", "command_set_ids"):
            if isinstance(data.get(field), (list, dict)):
                data[field] = json.dumps(data[field], ensure_ascii=False)
        data["id"] = scene_id
        self.conn.execute("""UPDATE scene_templates SET
            name=:name,scene_type=:scene_type,description=:description,
            analyzer_plugin=:analyzer_plugin,web_system=:web_system,version=:version,
            input_params=:input_params,sub_scenes=:sub_scenes,
            device_groups=:device_groups,command_set_ids=:command_set_ids,
            is_template=:is_template,updated_at=:updated_at
            WHERE id=:id""", data)
        self.conn.commit()

    def delete_scene(self, scene_id: int):
        """删除场景"""
        self.conn.execute("DELETE FROM scene_templates WHERE id=?", (scene_id,))
        self.conn.commit()

    # ── 任务 ──────────────────────────────────────────

    def create_task(self, data: dict) -> int:
        now = datetime.datetime.now().isoformat()
        data["created_at"] = now
        for field in ("scene_snapshot", "input_params", "device_list"):
            if isinstance(data.get(field), (list, dict)):
                data[field] = json.dumps(data[field], ensure_ascii=False)
        cur = self.conn.execute("""INSERT INTO tasks
            (name,scene_template_id,scene_version,scene_snapshot,region,status,input_params,device_list,created_at)
            VALUES (:name,:scene_template_id,:scene_version,:scene_snapshot,:region,:status,:input_params,:device_list,:created_at)""", data)
        self.conn.commit()
        return cur.lastrowid

    def update_task_status(self, task_id: int, status: str, result_summary: dict = None):
        data = {"id": task_id, "status": status}
        if result_summary:
            data["result_summary"] = json.dumps(result_summary, ensure_ascii=False)
        if status in ("completed", "failed", "cancelled"):
            data["completed_at"] = datetime.datetime.now().isoformat()
        self.conn.execute("""UPDATE tasks SET status=:status,result_summary=:result_summary,completed_at=:completed_at WHERE id=:id""", data)
        self.conn.commit()

    def list_tasks(self, limit: int = 50) -> list:
        rows = self.conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(r) if r else None

    # ── 命令集 ────────────────────────────────────────

    def list_command_sets(self) -> list:
        rows = self.conn.execute("SELECT * FROM command_sets ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def save_command_set(self, data: dict) -> int:
        now = datetime.datetime.now().isoformat()
        data["created_at"] = now
        data["updated_at"] = now
        if isinstance(data.get("commands"), list):
            data["commands"] = json.dumps(data["commands"], ensure_ascii=False)
        cur = self.conn.execute("""INSERT INTO command_sets (name,vendor,description,commands,created_at,updated_at)
            VALUES (:name,:vendor,:description,:commands,:created_at,:updated_at)""", data)
        self.conn.commit()
        return cur.lastrowid

    def update_command_set(self, cmd_id: int, data: dict):
        """更新命令集"""
        data["updated_at"] = datetime.datetime.now().isoformat()
        if isinstance(data.get("commands"), list):
            data["commands"] = json.dumps(data["commands"], ensure_ascii=False)
        data["id"] = cmd_id
        self.conn.execute("""UPDATE command_sets SET
            name=:name,vendor=:vendor,description=:description,
            commands=:commands,updated_at=:updated_at
            WHERE id=:id""", data)
        self.conn.commit()

    def delete_command_set(self, cmd_id: int):
        """删除命令集"""
        self.conn.execute("DELETE FROM command_sets WHERE id=?", (cmd_id,))
        self.conn.commit()

    # ── 导入导出 ──────────────────────────────────────

    def export_config(self) -> dict:
        """导出全局配置（密码清空）"""
        return {
            "version": "1.0",
            "ssh_connections": [
                {k: v for k, v in dict(r).items() if k != "key_password"}
                for r in self.conn.execute("SELECT * FROM ssh_connections").fetchall()
            ],
            "region_mapping": [dict(r) for r in self.conn.execute("SELECT * FROM region_mapping").fetchall()],
        }

    def import_config(self, config: dict):
        """导入全局配置"""
        for conn in config.get("ssh_connections", []):
            conn["key_password"] = ""
            self.save_ssh_connection(conn)
        for mapping in config.get("region_mapping", []):
            self.save_region_mapping(mapping)
