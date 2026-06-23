# 场景系统迁移说明 (v6 → v7)

## 概要

从 **v7.0** 开始，`network-collector` 抛弃了旧的"场景模板"概念，
改用 **场景插件**（`plugins/` 目录）作为场景的统一管理方式。

> 老的 `scene_templates` 数据表已被删除；老的 4 个 UI 页面（场景编辑、任务创建、任务执行、结果展示）也已删除。
> 任务创建和执行现在只通过 **CLI 命令**完成，GUI 仅用于管理设备、SSH、命令和查看插件列表。

---

## 🗑️ 删除的内容

### 老数据表
- `scene_templates` — **已 DROP**（迁移过程中自动删除老数据）

### 老 UI 页面
| 文件 | 替代 |
|------|------|
| `ui/scene_editor.py` | `ui/plugin_manager.py`（只读） |
| `ui/task_panel.py` | `cli/create_task.py` |
| `ui/task_execution.py` | `cli/run_task.py` |
| `ui/result_panel.py` | `tasks/task_NNNN/result.json`（文件查看） |

### 老核心模块
- `core/collector.py` — 被 `core/runner.py` 替代（新采集引擎，按插件 + 设备角色拼装命令）

### 老任务表字段
- `scene_template_id` / `scene_version` / `scene_snapshot` / `input_params` — 已删除
- 新字段：`plugin_name` / `plugin_version` / `plugin_params` / `started_at` / `error_message`

---

## ⚠️ 升级前必读

### 1. 备份老数据

升级前请手动备份 `scene_templates` 表：

```bash
sqlite3 network_collector.db "SELECT * FROM scene_templates;" > scene_templates_backup_$(date +%Y%m%d).sql
```

v7 迁移会自动 DROP 该表，**老场景数据不可恢复**。

### 2. 老任务记录

v7 迁移会把 `tasks` 表的 `region` / `status` / `device_list` / `result_summary` / `created_at` / `completed_at` 字段保留。
但 `scene_template_id` / `scene_version` / `scene_snapshot` / `input_params` 4 个字段会被丢失。

迁移后**老任务可以查询**，但**无法重新执行**（因为没有 plugin_name 字段）。

建议：升级前对**老任务做归档**或导出报告（`result_summary` 还在）。

### 3. 老 SSH 配置 / 设备 / 命令集

完全兼容，不受影响。

---

## 🆕 新机制使用方式

### 1. 创建任务

```bash
# 先看可用插件
python -m cli.list_scenes

# 创建任务
python -m cli.create_task eip_conflict_check \
    --name "EIP 扩容检查-2024-01-15" \
    --region beijing4 \
    --eip "1.2.3.0/24, 5.6.7.0/24"
```

### 2. 执行任务

```bash
# 会提示输入主密码
python -m cli.run_task 42
```

### 3. 查看任务结果

任务结果在 `tasks/task_0042/result.json`，结构由插件的 `RESULT_LAYOUT` 决定。

---

## 🧩 场景插件结构

每个插件是一个 `plugins/<name>/__init__.py`：

```python
SCENE = {"name": "...", "version": "1.0.0", "icon": "🔌"}
DEVICE_RULES = [{"section_glob": "pop", "role": "idr"}, ...]
COMMAND_MAPPING = {"idr": ["cmd1", "cmd2"], ...}
BUNDLED_COMMANDS = [{"name": "cmd1", "cmd": "...", "parser": "..."}]
INPUT_PARAMS = [{"key": "eip_input", "type": "textarea"}]
RESULT_LAYOUT = {...}
def render_task_form(stage, context): ...
def analyze(task_dir, parsed_data, params): ...
```

完整说明见 `docs/SCENE_PLUGIN_GUIDE.md`（待写）。

---

## 🔧 常见问题

### Q1: 我有老的场景数据，迁移后还能用吗？

**不能**。老的 `scene_templates` 表已被删除。**升级前请手动备份**。

### Q2: 怎么从老的 GUI 升级？

GUI 仍然能打开，只是少了"场景编辑"和"任务"相关的入口。任务创建请改用 CLI。

### Q3: 我不想用 CLI，能不能恢复老的 GUI？

不能。老的 4 个 UI 页面已被删除。如果要恢复，需要从 git 历史里找回。

### Q4: 新插件怎么写？

参考 `plugins/eip_conflict_check/__init__.py`，或者等 `docs/SCENE_PLUGIN_GUIDE.md`（待写）。

### Q5: 解析器在哪？

`parsers/<parser_name>.py`，每个解析器对应一条命令（1对1）。
命令的 `parser` 字段指向解析器名（在 `commands` 表，v6 引入）。

---

## 📅 升级日志

- **v7.0** (2026-06-24)
  - 删 `scene_templates` 表
  - `tasks` 表字段调整
  - 删 5 个老文件
  - 新增 `plugins/` / `parsers/` / `cli/` 目录
  - 引入 `core/runner.py` / `core/scene_registry.py` / `core/parser_loader.py`
