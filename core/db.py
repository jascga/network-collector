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
        section TEXT NOT NULL,  -- 设备归属路径，多级用/分隔，如 Rack1-Core-01
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
        vendor TEXT,                   -- VendorA/VendorB/null(通用)
        description TEXT,
        commands TEXT NOT NULL,        -- JSON: [{"cmd":"...", "output_format":{...}}]
        created_at TEXT,
        updated_at TEXT
    )""",
    # 场景模板（v7 已删除，场景系统改为 plugins/ 目录）

    # 任务
    """CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        plugin_name TEXT,              -- 场景插件 ID (=plugins/下的目录名)
        plugin_version TEXT,           -- 插件版本
        plugin_params TEXT,            -- JSON: 运行时参数（含 region）
        region TEXT,                   -- 独立字段（方便查询/筛选）
        status TEXT DEFAULT 'pending', -- pending/running/completed/failed/cancelled
        device_list TEXT,              -- JSON: 实际采集的设备
        result_summary TEXT,           -- JSON: 分析结论摘要
        created_at TEXT,
        started_at TEXT,
        completed_at TEXT,
        error_message TEXT             -- 失败原因
    )""",

    # 数据库版本
    """CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    )""",

    # 配置项
    """CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )""",

    # 角色
    """CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT
    )""",
]

INSERT_DEFAULTS = [
    """INSERT OR IGNORE INTO schema_version (version) VALUES (?)""",
    """INSERT OR IGNORE INTO config (key, value) VALUES ('output_dir', '')""",
]


SCHEMA_VERSION = 7

MIGRATIONS = {
    2: [
        "ALTER TABLE ssh_connections ADD COLUMN status TEXT DEFAULT 'untested'",
        "ALTER TABLE ssh_connections ADD COLUMN last_test_at TEXT",
    ],
    3: [
        "CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)",
        "INSERT OR IGNORE INTO config (key, value) VALUES ('output_dir', '')",
    ],
    4: [
        "CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, sort_order INTEGER DEFAULT 0, created_at TEXT)",
        "INSERT OR IGNORE INTO roles (name, sort_order) VALUES ('fa', 1)",
        "INSERT OR IGNORE INTO roles (name, sort_order) VALUES ('cnt', 2)",
        "INSERT OR IGNORE INTO roles (name, sort_order) VALUES ('dcc', 3)",
        "INSERT OR IGNORE INTO roles (name, sort_order) VALUES ('dsw', 4)",
        "INSERT OR IGNORE INTO roles (name, sort_order) VALUES ('tor', 5)",
    ],
    5: [
        "CREATE TABLE IF NOT EXISTS commands (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            name TEXT UNIQUE NOT NULL,\n            cmd TEXT NOT NULL,\n            cmd_type TEXT DEFAULT 'simple',\n            vendor TEXT,\n            description TEXT,\n            created_at TEXT,\n            updated_at TEXT\n        )",
    ],
    6: [
        # v6: commands 表增加 parser 字段（解析器名），支持新机制下的"命令→解析器"绑定
        "ALTER TABLE commands ADD COLUMN parser TEXT",
    ],
    7: [
        # v7: 场景系统从 scene_templates 改为 plugins/ 目录
        #     tasks 表去掉老字段，加新字段
        "DROP TABLE IF EXISTS scene_templates",
        "CREATE TABLE IF NOT EXISTS tasks_new ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name TEXT,"
        "  plugin_name TEXT,"
        "  plugin_version TEXT,"
        "  plugin_params TEXT,"
        "  region TEXT,"
        "  status TEXT DEFAULT 'pending',"
        "  device_list TEXT,"
        "  result_summary TEXT,"
        "  created_at TEXT,"
        "  started_at TEXT,"
        "  completed_at TEXT,"
        "  error_message TEXT"
        ")",
        "INSERT INTO tasks_new (id, name, region, status, device_list, result_summary, created_at, completed_at)"
        "  SELECT id, name, region, status, device_list, result_summary, created_at, completed_at FROM tasks",
        "DROP TABLE tasks",
        "ALTER TABLE tasks_new RENAME TO tasks",
    ],
}


def get_default_output_dir() -> Path:
    """获取默认输出目录：用户文档目录/network-collector/tasks"""
    return Path.home() / "Documents" / "network-collector" / "tasks"


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
        # 迁移
        current_version = self.conn.execute("SELECT version FROM schema_version").fetchone()
        current_version = current_version[0] if current_version else 0
        for ver in range(current_version + 1, SCHEMA_VERSION + 1):
            for sql in MIGRATIONS.get(ver, []):
                try:
                    self.conn.execute(sql)
                except sqlite3.OperationalError as e:
                    # 忽略"列已存在"等重复迁移错误
                    if "duplicate column" not in str(e).lower():
                        raise
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

    def update_ssh_status(self, conn_id: int, status: str):
        """更新SSH连接测试状态：untested/ok/failed"""
        now = datetime.datetime.now().isoformat()
        self.conn.execute(
            "UPDATE ssh_connections SET status=?, last_test_at=? WHERE id=?",
            (status, now, conn_id),
        )
        self.conn.commit()

    # ── 配置项 ────────────────────────────────────────

    def get_config(self, key: str, default: str = "") -> str:
        r = self.conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_config(self, key: str, value: str):
        self.conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def get_output_dir(self) -> Path:
        """获取输出目录，优先用自定义路径，否则用默认"""
        custom = self.get_config("output_dir")
        if custom:
            return Path(custom)
        return get_default_output_dir()

    def get_task_path(self, task_id: int) -> Path:
        """获取任务输出路径"""
        return self.get_output_dir() / f"task_{task_id:04d}"

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
        """根据 Region+Section 查找对应的 SSH 连接，支持层级路径匹配（精确 > 通配符 > default）"""
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
        """按 Region + Section通配符 + Role 匹配设备
        section_glob: 支持 LIKE 通配符，格式如 Rack1-Core（精确）或 Rack1-%（通配多级）"""
        rows = self.conn.execute("""
            SELECT * FROM devices
            WHERE region=? AND section GLOB ? AND role=? AND is_active=1
            ORDER BY hostname
        """, (region, section_glob, role)).fetchall()
        return [dict(r) for r in rows]

    # ── 场景插件 ──
    # v7+ 场景系统改为 plugins/ 目录
    # 场景列表由 core.scene_registry 扫描获取，不再存数据库
    # tasks 表只存 plugin_name + plugin_version 引用

    # ── 任务 ──────────────────────────────────────────

    def create_task(self, data: dict) -> int:
        """创建任务（v7+ 新格式）

        data 必填字段:
            name, plugin_name, plugin_version, plugin_params (dict)
        可选字段:
            region, status, device_list
        """
        now = datetime.datetime.now().isoformat()
        data.setdefault("created_at", now)
        if isinstance(data.get("plugin_params"), (list, dict)):
            data["plugin_params"] = json.dumps(data["plugin_params"], ensure_ascii=False)
        if isinstance(data.get("device_list"), (list, dict)):
            data["device_list"] = json.dumps(data["device_list"], ensure_ascii=False)
        cur = self.conn.execute("""INSERT INTO tasks
            (name, plugin_name, plugin_version, plugin_params, region, status, device_list, created_at)
            VALUES (:name, :plugin_name, :plugin_version, :plugin_params, :region, :status, :device_list, :created_at)""", data)
        self.conn.commit()
        return cur.lastrowid

    def update_task_status(self, task_id: int, status: str, result_summary: dict = None,
                            error_message: str = None):
        now = datetime.datetime.now().isoformat()
        data = {
            "id":             task_id,
            "status":         status,
            "result_summary": json.dumps(result_summary, ensure_ascii=False) if result_summary else None,
            "completed_at":   now if status in ("completed", "failed", "cancelled") else None,
            "error_message":  error_message,
        }
        self.conn.execute("""UPDATE tasks SET
            status=:status, result_summary=:result_summary,
            completed_at=:completed_at, error_message=:error_message
            WHERE id=:id""", data)
        self.conn.commit()

    def list_tasks(self, limit: int = 50, plugin_name: str = None) -> list:
        sql = "SELECT * FROM tasks"
        params: list = []
        if plugin_name:
            sql += " WHERE plugin_name=?"
            params.append(plugin_name)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(r) if r else None

    def delete_task(self, task_id: int):
        """删除任务记录（任务输出目录不删，交给用户手动清理）"""
        self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    # ── 角色 ──────────────────────────────────────────

    def list_roles(self) -> list:
        """获取所有角色，按 sort_order 排序"""
        rows = self.conn.execute("SELECT * FROM roles ORDER BY sort_order").fetchall()
        return [dict(r) for r in rows]

    def save_role(self, name: str, sort_order: int = 0) -> int:
        """新增角色"""
        import datetime
        now = datetime.datetime.now().isoformat()
        cur = self.conn.execute(
            "INSERT INTO roles (name, sort_order, created_at) VALUES (?, ?, ?)",
            (name, sort_order, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_role(self, role_id: int, name: str, sort_order: int = 0):
        """更新角色"""
        self.conn.execute(
            "UPDATE roles SET name=?, sort_order=? WHERE id=?",
            (name, sort_order, role_id),
        )
        self.conn.commit()

    def delete_role(self, role_id: int):
        """删除角色"""
        self.conn.execute("DELETE FROM roles WHERE id=?", (role_id,))
        self.conn.commit()

    # ── 命令（原子）────────────────────────────────────

    def list_commands(self) -> list:
        """获取所有命令"""
        rows = self.conn.execute("SELECT * FROM commands ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def get_command(self, cmd_id: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM commands WHERE id=?", (cmd_id,)).fetchone()
        return dict(r) if r else None

    def save_command(self, data: dict) -> int:
        now = datetime.datetime.now().isoformat()
        data["created_at"] = now
        data["updated_at"] = now
        cur = self.conn.execute("""INSERT INTO commands (name,cmd,cmd_type,vendor,description,parser,created_at,updated_at)
            VALUES (:name,:cmd,:cmd_type,:vendor,:description,:parser,:created_at,:updated_at)""", data)
        self.conn.commit()
        return cur.lastrowid

    def update_command(self, cmd_id: int, data: dict):
        data["updated_at"] = datetime.datetime.now().isoformat()
        data["id"] = cmd_id
        self.conn.execute("""UPDATE commands SET
            name=:name,cmd=:cmd,cmd_type=:cmd_type,vendor=:vendor,
            description=:description,parser=:parser,updated_at=:updated_at
            WHERE id=:id""", data)
        self.conn.commit()

    def delete_command(self, cmd_id: int):
        self.conn.execute("DELETE FROM commands WHERE id=?", (cmd_id,))
        self.conn.commit()

    def get_command_names(self, cmd_ids: list) -> list:
        """根据命令 ID 列表获取名称列表"""
        if not cmd_ids:
            return []
        placeholders = ",".join(["?"] * len(cmd_ids))
        rows = self.conn.execute(
            f"SELECT id, name FROM commands WHERE id IN ({placeholders})", cmd_ids
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 命令集（组合）──────────────────────────────────

    def list_command_sets(self) -> list:
        rows = self.conn.execute("SELECT * FROM command_sets ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def get_command_set(self, cmd_set_id: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM command_sets WHERE id=?", (cmd_set_id,)).fetchone()
        return dict(r) if r else None

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

    def update_command_set(self, cmd_set_id: int, data: dict):
        """更新命令集"""
        data["updated_at"] = datetime.datetime.now().isoformat()
        if isinstance(data.get("commands"), list):
            data["commands"] = json.dumps(data["commands"], ensure_ascii=False)
        data["id"] = cmd_set_id
        self.conn.execute("""UPDATE command_sets SET
            name=:name,vendor=:vendor,description=:description,
            commands=:commands,updated_at=:updated_at
            WHERE id=:id""", data)
        self.conn.commit()

    def delete_command_set(self, cmd_set_id: int):
        """删除命令集"""
        self.conn.execute("DELETE FROM command_sets WHERE id=?", (cmd_set_id,))
        self.conn.commit()

    def get_command_set_commands(self, cmd_set_id: int) -> list:
        """获取命令集引用的所有命令详情"""
        row = self.conn.execute(
            "SELECT commands FROM command_sets WHERE id=?", (cmd_set_id,)
        ).fetchone()
        if not row:
            return []
        cmd_ids = row["commands"]
        if isinstance(cmd_ids, str):
            try:
                cmd_ids = json.loads(cmd_ids)
            except json.JSONDecodeError:
                cmd_ids = []
        if not cmd_ids:
            return []
        # cmd_ids 可能是旧格式（dict 列表）或新格式（int 列表）
        if cmd_ids and isinstance(cmd_ids[0], dict):
            return cmd_ids  # 旧格式，直接返回
        # 新格式：ID 列表
        placeholders = ",".join(["?"] * len(cmd_ids))
        rows = self.conn.execute(
            f"SELECT * FROM commands WHERE id IN ({placeholders})", cmd_ids
        ).fetchall()
        return [dict(r) for r in rows]

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
        """导入全局配置（如有同名连接则覆盖）"""
        for conn in config.get("ssh_connections", []):
            conn["key_password"] = ""
            existing = self.get_ssh_connection_by_name(conn.get("name", ""))
            if existing:
                self.update_ssh_connection(existing["id"], conn)
            else:
                self.save_ssh_connection(conn)
        for mapping in config.get("region_mapping", []):
            existing = self.conn.execute(
                "SELECT id FROM region_mapping WHERE region=? AND section=?",
                (mapping.get("region"), mapping.get("section")),
            ).fetchone()
            if existing:
                self.conn.execute("""UPDATE region_mapping SET
                    ssh_connection_id=:ssh_connection_id, is_default=:is_default
                    WHERE region=:region AND section=:section""", mapping)
            else:
                self.save_region_mapping(mapping)
        self.conn.commit()
