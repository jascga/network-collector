"""
main_window.py — 主窗口

左侧导航树 + 右侧 QStackedWidget 内容区 + 底部状态栏。
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTreeWidget,
    QTreeWidgetItem, QStackedWidget, QStatusBar, QLabel, QSplitter,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal


class MainWindow(QMainWindow):
    """主窗口"""

    # 信号：页面切换
    page_changed = pyqtSignal(str, dict)  # page_key, params

    def __init__(self, db, cipher):
        super().__init__()
        self.db = db
        self.cipher = cipher
        self._pages = {}  # key → widget 实例
        self._init_ui()
        self._load_pages()
        self._navigate_to("config_ssh")  # 默认首页

    def _init_ui(self):
        self.setWindowTitle("网络设备采集分析平台 v1.0")
        self.resize(1200, 800)

        # 中心部件
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # 分割器
        splitter = QSplitter(Qt.Horizontal)

        # ── 左侧导航树 ──
        self.nav_tree = QTreeWidget()
        self.nav_tree.setHeaderHidden(True)
        self.nav_tree.setFixedWidth(220)
        self.nav_tree.setIndentation(16)
        self.nav_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #f5f5f5;
                border-right: 1px solid #ddd;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 6px 8px;
            }
            QTreeWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QTreeWidget::item:hover:!selected {
                background-color: #e5e5e5;
            }
        """)
        self._build_nav_tree()
        self.nav_tree.itemClicked.connect(self._on_nav_clicked)
        splitter.addWidget(self.nav_tree)

        # ── 右侧内容区 ──
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("background-color: white;")
        splitter.addWidget(self.content_stack)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        # ── 状态栏 ──
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label, 1)
        self.last_task_label = QLabel("")
        self.status_bar.addPermanentWidget(self.last_task_label)

    def _build_nav_tree(self):
        """构建导航树"""
        # 配置分组
        config_group = QTreeWidgetItem(["⚙ 配置"])
        config_group.setFlags(config_group.flags() & ~Qt.ItemIsSelectable)
        config_group.setData(0, Qt.UserRole, "group_config")
        config_group.setExpanded(True)
        self.nav_tree.addTopLevelItem(config_group)

        nav_items = [
            ("📡 SSH连接", "config_ssh"),
            ("🖥️ 设备管理", "config_device"),
            ("📐 场景编辑", "config_scene"),
            ("⌨️ 命令集", "config_commands"),
        ]
        for label, key in nav_items:
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, key)
            config_group.addChild(item)

        # 任务分组
        task_group = QTreeWidgetItem(["📋 任务"])
        task_group.setFlags(task_group.flags() & ~Qt.ItemIsSelectable)
        task_group.setData(0, Qt.UserRole, "group_task")
        task_group.setExpanded(True)
        self.nav_tree.addTopLevelItem(task_group)

        task_items = [
            ("➕ 创建任务", "task_create"),
            ("📊 历史记录", "task_history"),
        ]
        for label, key in task_items:
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, key)
            task_group.addChild(item)

    def _on_nav_clicked(self, item, column):
        key = item.data(0, Qt.UserRole)
        if key and not key.startswith("group_"):
            self._navigate_to(key)

    # ── 页面导航 ──────────────────────────────────────

    def _navigate_to(self, key: str, params: dict = None):
        """切换到指定页面"""
        if key not in self._pages:
            return
        widget = self._pages[key]
        self.content_stack.setCurrentWidget(widget)
        # 通知页面被激活（可用于刷新数据）
        if hasattr(widget, 'on_activated'):
            widget.on_activated(params)
        self.page_changed.emit(key, params or {})

    def navigate_to(self, key: str, params: dict = None):
        """外部调用：页面切换（如任务创建完跳进度页）"""
        self._navigate_to(key, params)

    # ── 加载页面 ──────────────────────────────────────

    def _load_pages(self):
        """延迟导入并加载所有页面"""
        from ui.config_panel import ConfigPanel
        from ui.device_panel import DevicePanel
        from ui.scene_editor import SceneEditor
        from ui.command_set_panel import CommandSetPanel
        from ui.task_panel import TaskPanel
        from ui.task_execution import TaskExecutionPanel
        from ui.result_panel import ResultPanel

        self._pages = {
            "config_ssh": ConfigPanel(self),
            "config_device": DevicePanel(self),
            "config_scene": SceneEditor(self),
            "config_commands": CommandSetPanel(self),
            "task_create": TaskPanel(self),
            "task_history": TaskPanel(self, show_history=True),
            "task_execution": TaskExecutionPanel(self),
            "task_result": ResultPanel(self),
        }
        for w in self._pages.values():
            self.content_stack.addWidget(w)

    def show_task_progress(self, task_id: int):
        """跳转到任务执行进度页"""
        self._navigate_to("task_execution", {"task_id": task_id})

    def show_task_result(self, task_id: int):
        """跳转到任务结果页"""
        self._navigate_to("task_result", {"task_id": task_id})

    def set_status(self, text: str):
        """更新状态栏"""
        self.status_label.setText(text)

    def update_last_task(self, info: str):
        self.last_task_label.setText(info)
