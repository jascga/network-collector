# 网络设备采集分析平台

现网设备信息采集分析工具。通过 SSH 登录堡垒机跳转目标设备，执行命令采集数据，分析并输出结论。

## 项目结构

```
network-collector/
├── core/                  # ← OpenClaw 维护，不依赖 GUI
│   ├── db.py              # SQLite 数据库层
│   ├── expect_engine.py   # SSH + expect 会话引擎
│   ├── collector.py       # 采集调度引擎
│   └── crypto.py          # AES 密码加密
├── ui/                    # ← Claude Code 写（PyQt5）
│   ├── main_window.py     # 主窗口
│   ├── config_panel.py    # SSH连接/Region配置
│   ├── device_panel.py    # 设备管理
│   ├── scene_editor.py    # 场景编辑
│   ├── task_panel.py      # 任务创建/执行
│   └── result_panel.py    # 结果展示
├── plugins/               # 分析插件（后续开发）
├── docs/
│   ├── 技术方案.md         # 完整设计文档
│   ├── UI原型.md           # 界面布局
│   └── 讨论记录.md
└── requirements.txt
```

## 分工

| 谁 | 负责 | 技术栈 |
|----|------|--------|
| **OpenClaw（服务器）** | `core/` 层 + `plugins/` 分析插件 | Python 后端 |
| **Claude Code（Windows）** | `ui/` 层 + `main.py` | PyQt5 |

## 开始开发

```bash
# 1. 克隆
git clone git@github.com:jascga/network-collector.git
cd network-collector

# 2. 装依赖
pip install -r requirements.txt
pip install PyQt5  # Windows 上装

# 3. 读设计文档
# docs/技术方案.md → 理解完整设计
# docs/UI原型.md → 每个页面的布局

# 4. 写 ui/ 层
# 从 main_window.py 开始，逐页实现
# core/ 层的 API 可以直接 import 使用
```

## core/ 层 API 速查

### 数据库
```python
from core.db import Database
db = Database("network_collector.db")
db.open()

# SSH 连接
db.list_ssh_connections()
db.save_ssh_connection({...})

# 设备
db.list_devices(region="芜湖202")
db.match_devices(region="芜湖202", section_glob="az*", role="cnt")
# Excel 导入示例:
# hostname,ip,region,section,role,vendor,description
# WH-AZ1-Core01,10.0.1.1,芜湖202,az1/nc01,cnt,华为,核心
# WH-AZ2-Agg01,10.0.2.1,芜湖202,az1/nc02/nws01,dsw,锐捷,汇聚
db.import_devices([{...}, ...])  # Excel 导入用

# Region 映射
db.resolve_ssh(region="芜湖202", section="az1")  # → SSH连接配置

# 场景
db.list_scenes()
db.save_scene({...})

# 任务
task_id = db.create_task({...})
db.update_task_status(task_id, "running")
```

### SSH 采集
```python
from core.expect_engine import SSHExpectSession

session = SSHExpectSession(hostname="...", port=22, username="admin", key_filename="...")
session.connect()
session.run_expect_flow([{"expect": "Opt or ID>:", "send": "n"}, ...])
output = session.execute_command("display ip routing-table")
session.close()
```

### 采集引擎
```python
from core.collector import Collector

collector = Collector(db)
collector.run_task(task_id)  # 后台线程执行
collector.cancel_task(task_id)  # 取消
```

### 加密
```python
from core.crypto import init_master, load_cipher, encrypt, decrypt
cipher = init_master("db_dir", "mypassword")
encrypted = encrypt(cipher, "my_secret")
decrypted = decrypt(cipher, encrypted)
```
