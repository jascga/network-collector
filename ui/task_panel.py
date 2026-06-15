"""
task_panel.py — 任务面板

支持两种模式：
  1. 任务创建向导（步骤式：选场景 → 填参数 → 选Region+设备 → 开始采集）
  2. 任务历史列表
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QHeaderView, QGroupBox,
    QFormLayout, QMessageBox, QListWidget, QListWidgetItem, QSpinBox,
    QDateEdit, QCheckBox, QStackedWidget, QTextEdit, QRadioButton,
    QButtonGroup,
)
from PyQt5.QtCore import Qt, QDate
from core.collector import Collector
import json
import datetime


class TaskPanel(QWidget):
    """任务面板：创建向导 / 历史记录"""

    def __init__(self, main_window, parent=None, show_history: bool = False):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self.show_history = show_history

        # 向导步骤状态
        self._selected_scene_id = None
        self._selected_scene = None
        self._matched_devices = []

        self._init_ui()

    def _init_ui(self):
        if self.show_history:
            self._init_history_ui()
        else:
            self._init_wizard_ui()

    # ═══════════════════════════════════════════════════
    #  任务创建向导
    # ═══════════════════════════════════════════════════

    def _init_wizard_ui(self):
        layout = QVBoxLayout(self)

        # 步骤指示器
        self.step_stack = QStackedWidget()
        layout.addWidget(self.step_stack)

        # 步骤1：选场景
        self.step1 = QWidget()
        self._build_step1()
        self.step_stack.addWidget(self.step1)

        # 步骤2：填参数
        self.step2 = QWidget()
        self._build_step2()
        self.step_stack.addWidget(self.step2)

        # 步骤3：选Region + 确认设备 + 启动
        self.step3 = QWidget()
        self._build_step3()
        self.step_stack.addWidget(self.step3)

    def _build_step1(self):
        layout = QVBoxLayout(self.step1)
        layout.addWidget(QLabel("<h3>步骤 1/3: 选择场景</h3>"))
        layout.addWidget(QLabel("选择一个场景模板开始任务："))

        self.scene_list = QListWidget()
        layout.addWidget(self.scene_list)

        layout.addWidget(QLabel("版本:"))
        self.version_combo = QComboBox()
        layout.addWidget(self.version_combo)

        btn_next = QPushButton("下一步 →")
        btn_next.clicked.connect(self._step1_next)
        btn_next.setStyleSheet("QPushButton { padding: 8px 20px; }")
        layout.addWidget(btn_next, alignment=Qt.AlignRight)

    def _build_step2(self):
        layout = QVBoxLayout(self.step2)
        layout.addWidget(QLabel("<h3>步骤 2/3: 填写输入参数</h3>"))

        self.param_info_label = QLabel()
        layout.addWidget(self.param_info_label)

        self.param_form = QFormLayout()
        layout.addLayout(self.param_form)

        # 动态生成参数输入控件，存放在列表中
        self.param_widgets = []

        btn_layout = QHBoxLayout()
        btn_prev = QPushButton("← 上一步")
        btn_prev.clicked.connect(lambda: self.step_stack.setCurrentIndex(0))
        btn_layout.addWidget(btn_prev)
        btn_layout.addStretch()
        btn_next = QPushButton("下一步 →")
        btn_next.clicked.connect(self._step2_next)
        btn_next.setStyleSheet("QPushButton { padding: 8px 20px; }")
        btn_layout.addWidget(btn_next)
        layout.addLayout(btn_layout)

    def _build_step3(self):
        layout = QVBoxLayout(self.step3)
        layout.addWidget(QLabel("<h3>步骤 3/3: 选择 Region 并确认设备</h3>"))

        # Region 选择
        reg_layout = QHBoxLayout()
        reg_layout.addWidget(QLabel("Region:"))
        self.region_combo = QComboBox()
        self.region_combo.currentTextChanged.connect(self._on_region_changed)
        reg_layout.addWidget(self.region_combo)
        reg_layout.addStretch()
        layout.addLayout(reg_layout)

        # 匹配设备列表
        layout.addWidget(QLabel("自动匹配的设备 (勾选确认):"))
        self.matched_device_table = QTableWidget(0, 6)
        self.matched_device_table.setHorizontalHeaderLabels([
            "", "设备名", "IP", "Section", "Role", "厂商"
        ])
        self.matched_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.matched_device_table.setMaximumHeight(200)
        layout.addWidget(self.matched_device_table)

        # 任务配置
        task_cfg = QGroupBox("任务配置")
        task_cfg_layout = QFormLayout(task_cfg)
        self.task_name_input = QLineEdit()
        self.task_name_input.setPlaceholderText("自动生成")
        task_cfg_layout.addRow("任务名称:", self.task_name_input)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 600)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix(" 秒/设备")
        task_cfg_layout.addRow("采集超时:", self.timeout_spin)
        layout.addWidget(task_cfg)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_prev = QPushButton("← 上一步")
        btn_prev.clicked.connect(lambda: self.step_stack.setCurrentIndex(1))
        btn_layout.addWidget(btn_prev)
        btn_layout.addStretch()
        btn_start = QPushButton("🚀 开始采集")
        btn_start.clicked.connect(self._start_task)
        btn_start.setStyleSheet(
            "QPushButton { padding: 8px 24px; background-color: #0078d4; color: white; "
            "border-radius: 4px; font-weight: bold; }"
        )
        btn_layout.addWidget(btn_start)
        layout.addLayout(btn_layout)

    # ── 向导逻辑 ──────────────────────────────────────

    def on_activated(self, params=None):
        if self.show_history:
            self._refresh_history()
        else:
            self._load_scene_list()
            self._load_regions()

    def _load_scene_list(self):
        self.scene_list.clear()
        for scene in self.db.list_scenes():
            item = QListWidgetItem(f"{scene['name']}  [{scene.get('scene_type','')}]  v{scene.get('version',1)}")
            item.setData(Qt.UserRole, scene)
            self.scene_list.addItem(item)

    def _load_regions(self):
        self.region_combo.clear()
        rows = self.db.conn.execute(
            "SELECT DISTINCT region FROM devices WHERE is_active=1 ORDER BY region"
        ).fetchall()
        for r in rows:
            self.region_combo.addItem(r["region"])

    def _step1_next(self):
        item = self.scene_list.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先选择一个场景")
            return
        scene = item.data(Qt.UserRole)
        self._selected_scene = scene
        self._selected_scene_id = scene["id"]

        # 解析输入参数，生成表单
        self._build_param_form(scene)
        self.step_stack.setCurrentIndex(1)

    def _build_param_form(self, scene: dict):
        # 清除旧的参数控件
        while self.param_form.rowCount() > 0:
            self.param_form.removeRow(0)
        self.param_widgets.clear()

        params = scene.get("input_params", "")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except:
                params = []

        if params:
            self.param_info_label.setText(f"场景「{scene['name']}」需要以下参数：")
        else:
            self.param_info_label.setText(f"场景「{scene['name']}」无需额外参数")

        for p in params:
            widget = QLineEdit()
            widget.setPlaceholderText(p.get("desc", ""))
            self.param_form.addRow(f"{p['name']} ({p.get('type','文本')}):", widget)
            self.param_widgets.append((p["name"], widget))

    def _step2_next(self):
        self._load_regions()
        self._on_region_changed(self.region_combo.currentText())
        self.step_stack.setCurrentIndex(2)

    def _on_region_changed(self, region: str):
        if not region:
            return
        # 自动匹配设备
        scene = self._selected_scene
        if not scene:
            return

        # 解析设备组
        dgs = scene.get("device_groups", "")
        if isinstance(dgs, str):
            try:
                dgs = json.loads(dgs)
            except:
                dgs = []
        sub_scenes = scene.get("sub_scenes", "")
        if isinstance(sub_scenes, str):
            try:
                sub_scenes = json.loads(sub_scenes)
            except:
                sub_scenes = []
        # 从子场景中收集设备组
        for sub in sub_scenes:
            dgs.extend(sub.get("device_groups", []))

        if not dgs:
            # 没有设备组，显示所有设备
            devices = self.db.list_devices(region=region)
        else:
            devices = []
            seen = set()
            for dg in dgs:
                matched = self.db.match_devices(
                    region=region,
                    section_glob=dg.get("section", "*"),
                    role=dg.get("role", "*"),
                )
                for d in matched:
                    key = (d["hostname"], d["ip"])
                    if key not in seen:
                        seen.add(key)
                        devices.append(d)

        self._matched_devices = devices
        self._populate_matched_table(devices)

    def _populate_matched_table(self, devices: list):
        self.matched_device_table.setRowCount(len(devices))
        for row, dev in enumerate(devices):
            # 勾选 checkbox
            cb = QCheckBox("")
            cb.setChecked(True)
            self.matched_device_table.setCellWidget(row, 0, cb)
            self.matched_device_table.setItem(row, 1, QTableWidgetItem(dev.get("hostname", "")))
            self.matched_device_table.setItem(row, 2, QTableWidgetItem(dev.get("ip", "")))
            self.matched_device_table.setItem(row, 3, QTableWidgetItem(dev.get("section", "")))
            self.matched_device_table.setItem(row, 4, QTableWidgetItem(dev.get("role", "")))
            self.matched_device_table.setItem(row, 5, QTableWidgetItem(dev.get("vendor", "")))

    def _start_task(self):
        # 收集输入参数
        input_params = {}
        for name, widget in self.param_widgets:
            val = widget.text().strip()
            if val:
                input_params[name] = val
        input_params["timeout"] = self.timeout_spin.value()

        # 收集选中的设备
        selected_devices = []
        for row in range(self.matched_device_table.rowCount()):
            cb = self.matched_device_table.cellWidget(row, 0)
            if cb and cb.isChecked():
                selected_devices.append(self._matched_devices[row])

        if not selected_devices:
            QMessageBox.warning(self, "提示", "请至少选择一台设备")
            return

        # 自动生成任务名称
        task_name = self.task_name_input.text().strip()
        if not task_name and self._selected_scene:
            now = datetime.datetime.now()
            task_name = f"{self._selected_scene['name']}_{now.strftime('%y%m%d_%H%M')}"

        region = self.region_combo.currentText()

        # 场景快照
        scene_snapshot = json.loads(json.dumps(self._selected_scene, default=str))

        # 创建任务记录
        task_id = self.db.create_task({
            "name": task_name,
            "scene_template_id": self._selected_scene_id,
            "scene_version": self._selected_scene.get("version", 1),
            "scene_snapshot": scene_snapshot,
            "region": region,
            "status": "pending",
            "input_params": input_params,
            "device_list": selected_devices,
        })

        QMessageBox.information(self, "任务创建", f"任务已创建 (ID: {task_id})\n即将开始采集...")

        # 跳转到执行进度页
        self.main_window.show_task_progress(task_id)

    # ═══════════════════════════════════════════════════
    #  任务历史
    # ═══════════════════════════════════════════════════

    def _init_history_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("<b>任务历史</b>"))
        top.addStretch()
        self.hist_search = QLineEdit()
        self.hist_search.setPlaceholderText("搜索任务名...")
        self.hist_search.setMaximumWidth(200)
        self.hist_search.textChanged.connect(self._refresh_history)
        top.addWidget(self.hist_search)
        layout.addLayout(top)

        self.hist_table = QTableWidget(0, 6)
        self.hist_table.setHorizontalHeaderLabels([
            "任务名", "场景", "Region", "状态", "结论", "创建时间"
        ])
        self.hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.hist_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.hist_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.hist_table.doubleClicked.connect(self._on_hist_double_clicked)
        layout.addWidget(self.hist_table)

    def _refresh_history(self):
        tasks = self.db.list_tasks(limit=200)
        keyword = self.hist_search.text().strip().lower() if hasattr(self, 'hist_search') else ""
        if keyword:
            tasks = [t for t in tasks if keyword in t.get("name", "").lower()]

        self.hist_table.setRowCount(len(tasks))
        for row, t in enumerate(tasks):
            self.hist_table.setItem(row, 0, QTableWidgetItem(t.get("name", "")))
            self.hist_table.setItem(row, 1, QTableWidgetItem(t.get("scene_template_id", "")))
            self.hist_table.setItem(row, 2, QTableWidgetItem(t.get("region", "")))
            status = t.get("status", "pending")
            status_display = {"pending": "⏳ 待执行", "running": "● 运行中",
                              "completed": "✅ 完成", "failed": "❌ 失败",
                              "cancelled": "⊘ 已取消"}.get(status, status)
            self.hist_table.setItem(row, 3, QTableWidgetItem(status_display))
            # 结论摘要
            summary = t.get("result_summary", "")
            if isinstance(summary, str) and summary:
                try:
                    summary = json.loads(summary)
                except:
                    summary = summary
            if isinstance(summary, dict):
                total = summary.get("total", 0)
                failed = summary.get("failed", 0)
                self.hist_table.setItem(row, 4, QTableWidgetItem(f"{total - failed}/{total} 成功" if total else "—"))
            else:
                self.hist_table.setItem(row, 4, QTableWidgetItem("—"))
            self.hist_table.setItem(row, 5, QTableWidgetItem(t.get("created_at", "")[:19]))
            self.hist_table.item(row, 0).setData(Qt.UserRole, t["id"])

    def _on_hist_double_clicked(self, index):
        row = index.row()
        task_id = self.hist_table.item(row, 0).data(Qt.UserRole)
        task = self.db.get_task(task_id)
        if task:
            status = task.get("status", "")
            if status in ("running",):
                self.main_window.show_task_progress(task_id)
            elif status in ("completed", "completed_with_errors", "failed", "cancelled"):
                self.main_window.show_task_result(task_id)
            else:
                QMessageBox.information(self, "提示", f"任务状态: {status}")
