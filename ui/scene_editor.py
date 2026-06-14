"""
scene_editor.py — 场景编辑器

场景模板的创建、编辑、删除。
子场景 + 设备组 + 命令集引用。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QHeaderView, QGroupBox,
    QFormLayout, QMessageBox, QTreeWidget, QTreeWidgetItem, QCheckBox,
    QInputDialog, QListWidget, QListWidgetItem, QTextEdit, QSplitter,
    QMenu, QDialog, QDialogButtonBox,
)
from PyQt5.QtCore import Qt
import json


SCENE_TYPES = [
    ("ip_conflict", "IP冲突检测"),
    ("route_permit", "路由放通冲突检查"),
    ("config_diff", "配置对比"),
    ("arp_check", "ARP表检查"),
    ("port_inspection", "端口状态巡检"),
]

WEB_SYSTEMS = [
    ("", "无"),
    ("ipam", "IPAM系统"),
    ("config_mgmt", "配置管理系统"),
    ("cmdb", "CMDB"),
    ("other", "其他"),
]

ANALYZER_MAP = {
    "ip_conflict": "ip_conflict_analyzer",
    "route_permit": "route_permit_analyzer",
    "config_diff": "config_diff_analyzer",
    "arp_check": "arp_check_analyzer",
    "port_inspection": "port_inspection_analyzer",
}


class SceneEditor(QWidget):
    """场景编辑器"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self._current_id = None
        self._sub_scenes = []       # 子场景列表
        self._device_groups = []    # 直接设备组列表（无子场景时）
        self._command_set_ids = []  # 引用的命令集 ID
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)

        # ── 左侧：场景列表 ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_top = QHBoxLayout()
        left_top.addWidget(QLabel("<b>场景列表</b>"))
        left_top.addStretch()
        btn_new = QPushButton("+ 新建")
        btn_new.clicked.connect(self._new_scene)
        left_top.addWidget(btn_new)
        left_layout.addLayout(left_top)

        self.scene_tree = QTreeWidget()
        self.scene_tree.setHeaderLabels(["名称", "类型"])
        self.scene_tree.setRootIsDecorated(True)
        self.scene_tree.setMaximumWidth(300)
        self.scene_tree.itemClicked.connect(self._on_scene_clicked)
        self.scene_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scene_tree.customContextMenuRequested.connect(self._on_scene_context_menu)
        left_layout.addWidget(self.scene_tree)
        layout.addWidget(left)

        # ── 右侧：编辑区 ──
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # 基本信息
        basic = QGroupBox("基本信息")
        basic_layout = QFormLayout(basic)
        self.name_input = QLineEdit()
        basic_layout.addRow("场景名称:", self.name_input)
        self.desc_input = QTextEdit()
        self.desc_input.setMaximumHeight(60)
        basic_layout.addRow("场景说明:", self.desc_input)

        type_layout = QHBoxLayout()
        self.type_combo = QComboBox()
        for code, label in SCENE_TYPES:
            self.type_combo.addItem(label, code)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        type_layout.addWidget(QLabel("← 选择即自动绑定分析插件"))
        basic_layout.addRow("场景类型:", type_layout)

        self.analyzer_label = QLabel("")
        basic_layout.addRow("绑定分析插件:", self.analyzer_label)

        self.web_combo = QComboBox()
        for code, label in WEB_SYSTEMS:
            self.web_combo.addItem(label, code)
        basic_layout.addRow("关联Web系统:", self.web_combo)

        self.version_label = QLabel("v1")
        basic_layout.addRow("版本:", self.version_label)
        right_layout.addWidget(basic)

        # 输入参数
        param_group = QGroupBox("输入参数")
        param_layout = QVBoxLayout(param_group)
        self.param_table = QTableWidget(0, 3)
        self.param_table.setHorizontalHeaderLabels(["变量名", "类型", "说明"])
        self.param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.param_table.setMaximumHeight(100)
        param_layout.addWidget(self.param_table)
        param_btns = QHBoxLayout()
        btn_add_param = QPushButton("+ 添加")
        btn_add_param.clicked.connect(lambda: self.param_table.insertRow(self.param_table.rowCount()))
        param_btns.addWidget(btn_add_param)
        btn_del_param = QPushButton("- 删除")
        btn_del_param.clicked.connect(lambda: self.param_table.removeRow(self.param_table.currentRow()))
        param_btns.addWidget(btn_del_param)
        param_btns.addStretch()
        param_layout.addLayout(param_btns)
        right_layout.addWidget(param_group)

        # 子场景
        sub_group = QGroupBox("子场景 (可选)")
        sub_layout = QVBoxLayout(sub_group)
        self.sub_check = QCheckBox("含子场景")
        self.sub_check.toggled.connect(self._toggle_sub)
        sub_layout.addWidget(self.sub_check)

        self.sub_list = QTreeWidget()
        self.sub_list.setHeaderLabels(["子场景名", "设备组数"])
        self.sub_list.setMaximumHeight(100)
        self.sub_list.setVisible(False)
        sub_layout.addWidget(self.sub_list)

        sub_btns = QHBoxLayout()
        btn_add_sub = QPushButton("+ 添加子场景")
        btn_add_sub.clicked.connect(self._add_sub_scene)
        sub_btns.addWidget(btn_add_sub)
        btn_del_sub = QPushButton("- 删除子场景")
        btn_del_sub.clicked.connect(self._del_sub_scene)
        sub_btns.addWidget(btn_del_sub)
        sub_btns.addStretch()
        self.sub_btns_widget = QWidget()
        self.sub_btns_widget.setLayout(sub_btns)
        self.sub_btns_widget.setVisible(False)
        sub_layout.addWidget(self.sub_btns_widget)

        # 子场景编辑弹出对话框占位
        self._current_sub_index = -1
        right_layout.addWidget(sub_group)

        # 设备组（无子场景时直接配置）
        self.dg_group = QGroupBox("设备组 (直接配置)")
        dg_layout = QVBoxLayout(self.dg_group)
        self.dg_table = QTableWidget(0, 4)
        self.dg_table.setHorizontalHeaderLabels(["Section", "Role", "说明", "命令集"])
        self.dg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.dg_table.setMaximumHeight(100)
        dg_layout.addWidget(self.dg_table)
        dg_btns = QHBoxLayout()
        btn_add_dg = QPushButton("+ 添加")
        btn_add_dg.clicked.connect(self._add_device_group)
        dg_btns.addWidget(btn_add_dg)
        btn_del_dg = QPushButton("- 删除")
        btn_del_dg.clicked.connect(lambda: self.dg_table.removeRow(self.dg_table.currentRow()))
        dg_btns.addWidget(btn_del_dg)
        dg_btns.addStretch()
        dg_layout.addLayout(dg_btns)
        right_layout.addWidget(self.dg_group)

        # 命令集引用
        cmd_group = QGroupBox("引用命令集")
        cmd_layout = QVBoxLayout(cmd_group)
        self.cmd_check_list = QListWidget()
        self.cmd_check_list.setMaximumHeight(80)
        cmd_layout.addWidget(self.cmd_check_list)
        right_layout.addWidget(cmd_group)

        # 保存
        btn_save = QPushButton("保 存")
        btn_save.clicked.connect(self._save)
        btn_save.setStyleSheet(
            "QPushButton { padding: 8px 30px; background-color: #0078d4; color: white; "
            "border-radius: 4px; font-weight: bold; }"
        )
        right_layout.addWidget(btn_save, alignment=Qt.AlignRight)

        layout.addWidget(right, 1)

    # ── 数据加载 ──────────────────────────────────────

    def on_activated(self, params=None):
        self._refresh_tree()
        self._refresh_cmd_check_list()

    def _refresh_tree(self):
        self.scene_tree.clear()
        scenes = self.db.list_scenes()
        for s in scenes:
            item = QTreeWidgetItem([s.get("name", ""), s.get("scene_type", "")])
            item.setData(0, Qt.UserRole, s["id"])
            self.scene_tree.addTopLevelItem(item)

    def _refresh_cmd_check_list(self):
        self.cmd_check_list.clear()
        for cs in self.db.list_command_sets():
            item = QListWidgetItem(cs["name"])
            item.setData(Qt.UserRole, cs["id"])
            item.setCheckState(Qt.Unchecked)
            self.cmd_check_list.addItem(item)

    def _on_scene_clicked(self, item, column):
        scene_id = item.data(0, Qt.UserRole)
        if scene_id:
            self._load_scene(scene_id)

    def _load_scene(self, scene_id: int):
        scene = self.db.get_scene(scene_id)
        if not scene:
            return
        self._current_id = scene_id
        self.name_input.setText(scene.get("name", ""))
        self.desc_input.setPlainText(scene.get("description", ""))

        idx = self.type_combo.findData(scene.get("scene_type", ""))
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self._update_analyzer_label()

        idx = self.web_combo.findData(scene.get("web_system", ""))
        if idx >= 0:
            self.web_combo.setCurrentIndex(idx)

        self.version_label.setText(f"v{scene.get('version', 1)}")

        # 输入参数
        params = scene.get("input_params", "")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except:
                params = []
        self.param_table.setRowCount(len(params))
        for i, p in enumerate(params):
            self.param_table.setItem(i, 0, QTableWidgetItem(p.get("name", "")))
            self.param_table.setItem(i, 1, QTableWidgetItem(p.get("type", "")))
            self.param_table.setItem(i, 2, QTableWidgetItem(p.get("desc", "")))

        # 子场景
        sub_scenes = scene.get("sub_scenes", "")
        if isinstance(sub_scenes, str):
            try:
                sub_scenes = json.loads(sub_scenes)
            except:
                sub_scenes = []
        self._sub_scenes = sub_scenes
        has_sub = bool(sub_scenes)
        self.sub_check.setChecked(has_sub)
        self._refresh_sub_list()

        # 设备组
        dgs = scene.get("device_groups", "")
        if isinstance(dgs, str):
            try:
                dgs = json.loads(dgs)
            except:
                dgs = []
        self._device_groups = dgs
        self._refresh_dg_table()

        # 命令集
        cmd_ids = scene.get("command_set_ids", "")
        if isinstance(cmd_ids, str):
            try:
                cmd_ids = json.loads(cmd_ids)
            except:
                cmd_ids = []
        self._command_set_ids = cmd_ids
        self._refresh_cmd_checks()

    def _new_scene(self):
        self._current_id = None
        self.name_input.clear()
        self.desc_input.clear()
        self.type_combo.setCurrentIndex(0)
        self.web_combo.setCurrentIndex(0)
        self.version_label.setText("v1")
        self.param_table.setRowCount(0)
        self._sub_scenes = []
        self.sub_check.setChecked(False)
        self._device_groups = []
        self._refresh_dg_table()
        self._command_set_ids = []
        self._refresh_cmd_checks()
        self._refresh_cmd_check_list()
        self._update_analyzer_label()

    # ── 类型联动 ──────────────────────────────────────

    def _on_type_changed(self):
        self._update_analyzer_label()

    def _update_analyzer_label(self):
        code = self.type_combo.currentData()
        plugin = ANALYZER_MAP.get(code, "(未绑定)")
        self.analyzer_label.setText(plugin)

    # ── 子场景切换 ────────────────────────────────────

    def _toggle_sub(self, checked):
        self.sub_list.setVisible(checked)
        self.sub_btns_widget.setVisible(checked)
        self.dg_group.setVisible(not checked)
        if checked:
            self._device_groups = []

    def _refresh_sub_list(self):
        self.sub_list.clear()
        for i, sub in enumerate(self._sub_scenes):
            dg_count = len(sub.get("device_groups", []))
            item = QTreeWidgetItem([sub.get("name", f"子场景{i+1}"), str(dg_count)])
            item.setData(0, Qt.UserRole, i)
            self.sub_list.addTopLevelItem(item)

    def _add_sub_scene(self):
        dialog = SubSceneDialog(self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            self._sub_scenes.append(dialog.result)
            self._refresh_sub_list()

    def _del_sub_scene(self):
        items = self.sub_list.selectedItems()
        if not items:
            return
        idx = items[0].data(0, Qt.UserRole)
        del self._sub_scenes[idx]
        self._refresh_sub_list()

    # ── 设备组 ────────────────────────────────────────

    def _refresh_dg_table(self):
        self.dg_table.setRowCount(len(self._device_groups))
        for i, dg in enumerate(self._device_groups):
            self.dg_table.setItem(i, 0, QTableWidgetItem(dg.get("section", "")))
            self.dg_table.setItem(i, 1, QTableWidgetItem(dg.get("role", "")))
            self.dg_table.setItem(i, 2, QTableWidgetItem(dg.get("desc", "")))
            cmd_ids = dg.get("command_set_ids", [])
            cmd_names = self._get_cmd_names(cmd_ids)
            self.dg_table.setItem(i, 3, QTableWidgetItem(", ".join(cmd_names)))

    def _add_device_group(self):
        dialog = DeviceGroupDialog(self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            self._device_groups.append(dialog.result)
            self._refresh_dg_table()

    def _get_cmd_names(self, cmd_ids: list) -> list:
        names = []
        for cid in cmd_ids:
            row = self.db.conn.execute(
                "SELECT name FROM command_sets WHERE id=?", (cid,)
            ).fetchone()
            if row:
                names.append(row["name"])
        return names

    # ── 命令集引用 ────────────────────────────────────

    def _refresh_cmd_checks(self):
        for i in range(self.cmd_check_list.count()):
            item = self.cmd_check_list.item(i)
            cid = item.data(Qt.UserRole)
            item.setCheckState(Qt.Checked if cid in self._command_set_ids else Qt.Unchecked)

    # ── 保存 ──────────────────────────────────────────

    def _save(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "场景名称不能为空")
            return

        # 收集输入参数
        input_params = []
        for row in range(self.param_table.rowCount()):
            name_item = self.param_table.item(row, 0)
            type_item = self.param_table.item(row, 1)
            desc_item = self.param_table.item(row, 2)
            input_params.append({
                "name": name_item.text().strip() if name_item else "",
                "type": type_item.text().strip() if type_item else "",
                "desc": desc_item.text().strip() if desc_item else "",
            })

        # 收集命令集引用（从 check list）
        self._command_set_ids = []
        for i in range(self.cmd_check_list.count()):
            item = self.cmd_check_list.item(i)
            if item.checkState() == Qt.Checked:
                self._command_set_ids.append(item.data(Qt.UserRole))

        # 收集设备组（从表格）
        if not self.sub_check.isChecked():
            self._device_groups = []
            for row in range(self.dg_table.rowCount()):
                section_item = self.dg_table.item(row, 0)
                role_item = self.dg_table.item(row, 1)
                desc_item = self.dg_table.item(row, 2)
                self._device_groups.append({
                    "section": section_item.text().strip() if section_item else "",
                    "role": role_item.text().strip() if role_item else "",
                    "desc": desc_item.text().strip() if desc_item else "",
                    "command_set_ids": self._command_set_ids,
                })

        scene_type = self.type_combo.currentData()
        data = {
            "name": name,
            "scene_type": scene_type,
            "description": self.desc_input.toPlainText().strip(),
            "analyzer_plugin": ANALYZER_MAP.get(scene_type, ""),
            "web_system": self.web_combo.currentData(),
            "version": 1,
            "input_params": input_params,
            "sub_scenes": self._sub_scenes if self.sub_check.isChecked() else [],
            "device_groups": self._device_groups,
            "command_set_ids": self._command_set_ids,
            "is_template": 0,
        }

        if self._current_id:
            self.db.update_scene(self._current_id, data)
        else:
            self._current_id = self.db.save_scene(data)

        self._refresh_tree()
        QMessageBox.information(self, "提示", "保存成功")

    def _on_scene_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.scene_tree.viewport().mapToGlobal(pos))
        if action == delete_action:
            item = self.scene_tree.currentItem()
            if item:
                scene_id = item.data(0, Qt.UserRole)
                ret = QMessageBox.question(self, "确认", "确定要删除此场景吗？",
                                           QMessageBox.Yes | QMessageBox.No)
                if ret == QMessageBox.Yes:
                    self.db.delete_scene(scene_id)
                    self._new_scene()
                    self._refresh_tree()


class DeviceGroupDialog(QDialog):
    """设备组编辑对话框"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.result = {}
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("添加设备组")
        self.setFixedSize(400, 250)
        layout = QFormLayout(self)

        self.section_input = QLineEdit()
        self.section_input.setPlaceholderText("如: az* / transit* / *")
        layout.addRow("Section:", self.section_input)

        self.role_input = QLineEdit()
        self.role_input.setPlaceholderText("如: cnt / fa / acc / fw")
        layout.addRow("Role:", self.role_input)

        self.desc_input = QLineEdit()
        layout.addRow("说明:", self.desc_input)

        layout.addRow(QLabel("命令集 (可多选):"))
        self.cmd_list = QListWidget()
        for cs in self.db.list_command_sets():
            item = QListWidgetItem(cs["name"])
            item.setData(Qt.UserRole, cs["id"])
            item.setCheckState(Qt.Unchecked)
            self.cmd_list.addItem(item)
        layout.addRow(self.cmd_list)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

    def _on_ok(self):
        cmd_ids = []
        for i in range(self.cmd_list.count()):
            item = self.cmd_list.item(i)
            if item.checkState() == Qt.Checked:
                cmd_ids.append(item.data(Qt.UserRole))
        self.result = {
            "section": self.section_input.text().strip(),
            "role": self.role_input.text().strip(),
            "desc": self.desc_input.text().strip(),
            "command_set_ids": cmd_ids,
        }
        self.accept()


class SubSceneDialog(QDialog):
    """子场景编辑对话框"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.result = {"name": "", "desc": "", "device_groups": []}
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("添加子场景")
        self.setFixedSize(450, 300)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_input = QLineEdit()
        form.addRow("名称:", self.name_input)
        self.desc_input = QLineEdit()
        form.addRow("说明:", self.desc_input)
        layout.addLayout(form)

        layout.addWidget(QLabel("<b>设备组:</b>"))
        self.dg_table = QTableWidget(0, 3)
        self.dg_table.setHorizontalHeaderLabels(["Section", "Role", "说明"])
        self.dg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.dg_table)

        dg_btns = QHBoxLayout()
        btn_add = QPushButton("+ 添加")
        btn_add.clicked.connect(lambda: self.dg_table.insertRow(self.dg_table.rowCount()))
        dg_btns.addWidget(btn_add)
        btn_del = QPushButton("- 删除")
        btn_del.clicked.connect(lambda: self.dg_table.removeRow(self.dg_table.currentRow()))
        dg_btns.addWidget(btn_del)
        dg_btns.addStretch()
        layout.addLayout(dg_btns)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_ok(self):
        dgs = []
        for row in range(self.dg_table.rowCount()):
            s_item = self.dg_table.item(row, 0)
            r_item = self.dg_table.item(row, 1)
            d_item = self.dg_table.item(row, 2)
            dgs.append({
                "section": s_item.text().strip() if s_item else "",
                "role": r_item.text().strip() if r_item else "",
                "desc": d_item.text().strip() if d_item else "",
            })
        self.result = {
            "name": self.name_input.text().strip(),
            "desc": self.desc_input.text().strip(),
            "device_groups": dgs,
        }
        self.accept()
