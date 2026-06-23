"""
plugin_manager.py — 插件管理页（新机制）

只读视图，展示已安装的场景插件：
  - 名称、版本、图标
  - 描述
  - 设备规则数、命令数
  - 创建任务提示（任务走 CLI）

不提供安装/卸载/启停功能（v1 范围）。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextEdit, QSplitter, QGroupBox, QPushButton,
    QMessageBox,
)
from PyQt5.QtCore import Qt
from pathlib import Path


class PluginManager(QWidget):
    """场景插件管理面板。"""

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 顶部说明
        header = QLabel(
            "<b>场景插件</b> &nbsp;&nbsp; "
            "<span style='color:#666;'>"
            "v1.0 — 任务创建请使用 CLI: "
            "<code>python -m cli.create_task &lt;plugin_name&gt; ...</code>"
            "</span>"
        )
        layout.addWidget(header)

        # 主体：左列表 + 右详情
        splitter = QSplitter(Qt.Horizontal)

        # ── 左：插件列表 ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.plugin_list = QListWidget()
        self.plugin_list.currentItemChanged.connect(self._on_plugin_selected)
        left_layout.addWidget(self.plugin_list)
        splitter.addWidget(left)

        # ── 右：插件详情 ──
        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.title_label = QLabel("选择一个插件查看详情")
        self.title_label.setStyleSheet("font-size: 14pt; padding: 8px;")
        right_layout.addWidget(self.title_label)

        self.version_label = QLabel("")
        self.version_label.setStyleSheet("color: #666; padding: 0 8px;")
        right_layout.addWidget(self.version_label)

        # 设备规则
        dev_group = QGroupBox("设备筛选规则")
        dev_layout = QVBoxLayout(dev_group)
        self.dev_text = QTextEdit()
        self.dev_text.setReadOnly(True)
        self.dev_text.setMaximumHeight(110)
        dev_layout.addWidget(self.dev_text)
        right_layout.addWidget(dev_group)

        # 命令映射
        cmd_group = QGroupBox("命令映射（设备角色 → 命令）")
        cmd_layout = QVBoxLayout(cmd_group)
        self.cmd_text = QTextEdit()
        self.cmd_text.setReadOnly(True)
        self.cmd_layout_max = 160
        self.cmd_text.setMaximumHeight(self.cmd_layout_max)
        cmd_layout.addWidget(self.cmd_text)
        right_layout.addWidget(cmd_group)

        # 输入参数
        param_group = QGroupBox("输入参数")
        param_layout = QVBoxLayout(param_group)
        self.param_text = QTextEdit()
        self.param_text.setReadOnly(True)
        self.param_text.setMaximumHeight(130)
        param_layout.addWidget(self.param_text)
        right_layout.addWidget(param_group)

        # 创建任务按钮（只提示，不实际做）
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_create = QPushButton("查看 CLI 用法")
        btn_create.clicked.connect(self._show_cli_usage)
        btn_layout.addWidget(btn_create)
        right_layout.addLayout(btn_layout)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

    # ── 数据加载 ──────────────────────────────────────

    def on_activated(self, params=None):
        self._refresh_list()

    def _refresh_list(self):
        self.plugin_list.clear()
        try:
            from core.scene_registry import get_registry
            reg = get_registry()
        except Exception as e:
            self.plugin_list.addItem(f"[加载失败] {e}")
            return

        scenes = reg.list_scenes()
        if not scenes:
            self.plugin_list.addItem("（未发现任何场景插件）")
            return

        for s in scenes:
            label = f"{s.icon}  {s.display_name}  v{s.version}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, s.name)
            self.plugin_list.addItem(item)

        if scenes:
            self.plugin_list.setCurrentRow(0)

    def _on_plugin_selected(self, current, previous):
        if not current:
            return
        name = current.data(Qt.UserRole)
        if not name:
            return
        from core.scene_registry import get_registry
        scene = get_registry().get(name)
        if not scene:
            return

        self.title_label.setText(f"{scene.icon}  {scene.display_name}")
        self.version_label.setText(f"插件 ID: <code>{scene.name}</code>  &nbsp;|&nbsp;  版本: <b>v{scene.version}</b>")

        # 设备规则
        lines = []
        for r in scene.device_rules:
            lines.append(f"• {r.get('label', '?')}  →  section={r.get('section_glob','?')}, role={r.get('role','?')}")
        self.dev_text.setPlainText("\n".join(lines) if lines else "（无）")

        # 命令映射
        lines = []
        for role, cmds in scene.command_mapping.items():
            lines.append(f"[role={role}]")
            for c in cmds:
                lines.append(f"  - {c}")
        self.cmd_text.setPlainText("\n".join(lines) if lines else "（无）")

        # 输入参数
        lines = []
        for p in scene.input_params:
            req = "必填" if p.get("required") else "选填"
            t = p.get("type", "text")
            lines.append(f"• <b>{p.get('label', p.get('key',''))}</b>")
            lines.append(f"    key=<code>{p.get('key','')}</code>, type={t}, {req}")
            if p.get("placeholder"):
                lines.append(f"    示例: {p['placeholder']}")
        self.param_text.setPlainText("\n".join(lines) if lines else "（无）")

    # ── 操作 ──────────────────────────────────────────

    def _show_cli_usage(self):
        current = self.plugin_list.currentItem()
        if not current:
            return
        name = current.data(Qt.UserRole)
        from core.scene_registry import get_registry
        scene = get_registry().get(name)
        if not scene:
            return

        # 构造 CLI 用法示例
        eip_param = next((p for p in scene.input_params if "eip" in p.get("key", "").lower()), None)
        if eip_param:
            example = (
                f"# 1. 创建任务\n"
                f"python -m cli.create_task {name} \\\n"
                f"    --name \"测试任务\" \\\n"
                f"    --region <your_region> \\\n"
                f"    --eip \"1.2.3.0/24, 5.6.7.0/24\"\n\n"
                f"# 2. 列出所有插件\n"
                f"python -m cli.list_scenes\n\n"
                f"# 3. 执行任务（会提示输入主密码）\n"
                f"python -m cli.run_task <task_id>"
            )
        else:
            example = (
                f"python -m cli.create_task {name} \\\n"
                f"    --name \"测试任务\" \\\n"
                f"    --region <your_region>\n\n"
                f"（具体参数见插件定义）"
            )

        QMessageBox.information(self, f"{scene.display_name} — CLI 用法", example)
