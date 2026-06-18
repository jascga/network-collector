"""
command_set_panel.py — 命令与命令集管理

双面板布局：
- 上半：命令管理（原子命令的增删改查）
- 下半：命令集管理（从命令列表中勾选组合成命令集）
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QHeaderView, QGroupBox,
    QFormLayout, QMessageBox, QMenu, QTextEdit, QSplitter, QListWidget,
    QListWidgetItem, QTabWidget,
)
from PyQt5.QtCore import Qt
import json


class CommandSetPanel(QWidget):
    """命令与命令集管理面板"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 用 QSplitter 上下分栏
        splitter = QSplitter(Qt.Vertical)

        # ── 上半：命令管理 ──
        cmd_group = QGroupBox("命令管理")
        cmd_layout = QVBoxLayout(cmd_group)

        # 命令操作栏
        cmd_top = QHBoxLayout()
        cmd_top.addWidget(QLabel("<b>命令列表</b>"))
        cmd_top.addStretch()
        btn_cmd_new = QPushButton("+ 新增命令")
        btn_cmd_new.clicked.connect(self._cmd_new)
        cmd_top.addWidget(btn_cmd_new)
        btn_cmd_del = QPushButton("删除命令")
        btn_cmd_del.clicked.connect(self._cmd_delete_selected)
        cmd_top.addWidget(btn_cmd_del)
        cmd_layout.addLayout(cmd_top)

        # 命令表格
        self.cmd_table = QTableWidget(0, 5)
        self.cmd_table.setHorizontalHeaderLabels(["名称", "命令", "类型", "厂商", "描述"])
        self.cmd_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.cmd_table.horizontalHeader().setStretchLastSection(True)
        self.cmd_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cmd_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cmd_table.selectionModel().selectionChanged.connect(self._cmd_on_selected)
        self.cmd_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cmd_table.customContextMenuRequested.connect(self._cmd_on_context_menu)
        cmd_layout.addWidget(self.cmd_table)

        # 命令编辑表单
        cmd_form = QGroupBox("编辑命令")
        cmd_form_layout = QVBoxLayout(cmd_form)
        cmd_fields = QFormLayout()
        self.cmd_name_input = QLineEdit()
        cmd_fields.addRow("名称:", self.cmd_name_input)
        self.cmd_text_input = QLineEdit()
        self.cmd_text_input.setPlaceholderText("如: display ip routing-table")
        cmd_fields.addRow("命令:", self.cmd_text_input)
        self.cmd_type_combo = QComboBox()
        self.cmd_type_combo.addItems(["simple", "parameterized", "foreach"])
        cmd_fields.addRow("类型:", self.cmd_type_combo)
        self.cmd_vendor_input = QLineEdit()
        self.cmd_vendor_input.setPlaceholderText("通用留空")
        cmd_fields.addRow("厂商:", self.cmd_vendor_input)
        self.cmd_desc_input = QLineEdit()
        cmd_fields.addRow("描述:", self.cmd_desc_input)
        cmd_form_layout.addLayout(cmd_fields)

        cmd_btn_row = QHBoxLayout()
        cmd_btn_row.addStretch()
        btn_cmd_save = QPushButton("保存命令")
        btn_cmd_save.clicked.connect(self._cmd_save)
        cmd_btn_row.addWidget(btn_cmd_save)
        cmd_form_layout.addLayout(cmd_btn_row)

        cmd_layout.addWidget(cmd_form)
        splitter.addWidget(cmd_group)

        # ── 下半：命令集管理 ──
        cs_group = QGroupBox("命令集管理")
        cs_layout = QVBoxLayout(cs_group)

        # 命令集操作栏
        cs_top = QHBoxLayout()
        cs_top.addWidget(QLabel("<b>命令集列表</b>"))
        cs_top.addStretch()
        btn_cs_new = QPushButton("+ 新增命令集")
        btn_cs_new.clicked.connect(self._cs_new)
        cs_top.addWidget(btn_cs_new)
        btn_cs_del = QPushButton("删除命令集")
        btn_cs_del.clicked.connect(self._cs_delete_selected)
        cs_top.addWidget(btn_cs_del)
        cs_layout.addLayout(cs_top)

        # 命令集表格 + 编辑区（左右分栏）
        cs_splitter = QSplitter(Qt.Horizontal)

        # 左侧：命令集列表
        cs_left = QWidget()
        cs_left_layout = QVBoxLayout(cs_left)
        cs_left_layout.setContentsMargins(0, 0, 0, 0)
        self.cs_table = QTableWidget(0, 3)
        self.cs_table.setHorizontalHeaderLabels(["名称", "厂商", "描述"])
        self.cs_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.cs_table.horizontalHeader().setStretchLastSection(True)
        self.cs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cs_table.selectionModel().selectionChanged.connect(self._cs_on_selected)
        self.cs_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cs_table.customContextMenuRequested.connect(self._cs_on_context_menu)
        cs_left_layout.addWidget(self.cs_table)
        cs_splitter.addWidget(cs_left)

        # 右侧：命令集编辑
        cs_right = QGroupBox("编辑命令集")
        cs_right_layout = QVBoxLayout(cs_right)

        cs_form = QFormLayout()
        self.cs_name_input = QLineEdit()
        cs_form.addRow("名称:", self.cs_name_input)
        self.cs_vendor_combo = QComboBox()
        self.cs_vendor_combo.setEditable(True)
        self.cs_vendor_combo.addItem("通用")
        cs_form.addRow("厂商:", self.cs_vendor_combo)
        self.cs_desc_input = QLineEdit()
        cs_form.addRow("描述:", self.cs_desc_input)
        cs_right_layout.addLayout(cs_form)

        cs_right_layout.addWidget(QLabel("<b>选择命令（勾选加入命令集）:</b>"))
        self.cs_cmd_list = QListWidget()
        cs_right_layout.addWidget(self.cs_cmd_list)

        cs_btn_row = QHBoxLayout()
        cs_btn_row.addStretch()
        btn_cs_save = QPushButton("保存命令集")
        btn_cs_save.clicked.connect(self._cs_save)
        cs_btn_row.addWidget(btn_cs_save)
        cs_right_layout.addLayout(cs_btn_row)

        cs_splitter.addWidget(cs_right)
        cs_layout.addWidget(cs_splitter)
        splitter.addWidget(cs_group)

        layout.addWidget(splitter)

        # 内部状态
        self._cmd_current_id = None
        self._cs_current_id = None

    # ══════════════════════════════════════════════════
    # 命令管理
    # ══════════════════════════════════════════════════

    def on_activated(self, params=None):
        self._cmd_refresh_list()
        self._cs_refresh_list()
        self._cs_refresh_cmd_list()

    def _cmd_refresh_list(self):
        cmds = self.db.list_commands()
        self.cmd_table.setRowCount(len(cmds))
        for row, c in enumerate(cmds):
            self.cmd_table.setItem(row, 0, QTableWidgetItem(c.get("name", "")))
            self.cmd_table.setItem(row, 1, QTableWidgetItem(c.get("cmd", "")))
            self.cmd_table.setItem(row, 2, QTableWidgetItem(c.get("cmd_type", "simple")))
            self.cmd_table.setItem(row, 3, QTableWidgetItem(c.get("vendor", "")))
            self.cmd_table.setItem(row, 4, QTableWidgetItem(c.get("description", "")))
            self.cmd_table.item(row, 0).setData(Qt.UserRole, c["id"])

    def _cmd_on_selected(self):
        rows = self.cmd_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        cmd_id = self.cmd_table.item(row, 0).data(Qt.UserRole)
        self._cmd_load_detail(cmd_id)

    def _cmd_load_detail(self, cmd_id: int):
        c = self.db.get_command(cmd_id)
        if not c:
            return
        self._cmd_current_id = cmd_id
        self.cmd_name_input.setText(c.get("name", ""))
        self.cmd_text_input.setText(c.get("cmd", ""))
        idx = self.cmd_type_combo.findText(c.get("cmd_type", "simple"))
        if idx >= 0:
            self.cmd_type_combo.setCurrentIndex(idx)
        self.cmd_vendor_input.setText(c.get("vendor", ""))
        self.cmd_desc_input.setText(c.get("description", ""))

    def _cmd_new(self):
        self._cmd_current_id = None
        self.cmd_name_input.clear()
        self.cmd_text_input.clear()
        self.cmd_type_combo.setCurrentIndex(0)
        self.cmd_vendor_input.clear()
        self.cmd_desc_input.clear()
        self.cmd_table.clearSelection()

    def _cmd_save(self):
        name = self.cmd_name_input.text().strip()
        cmd_text = self.cmd_text_input.text().strip()
        if not name or not cmd_text:
            QMessageBox.warning(self, "提示", "名称和命令不能为空")
            return

        data = {
            "name": name,
            "cmd": cmd_text,
            "cmd_type": self.cmd_type_combo.currentText(),
            "vendor": self.cmd_vendor_input.text().strip() or None,
            "description": self.cmd_desc_input.text().strip(),
        }

        if self._cmd_current_id:
            self.db.update_command(self._cmd_current_id, data)
        else:
            self._cmd_current_id = self.db.save_command(data)

        self._cmd_refresh_list()
        self._cs_refresh_cmd_list()
        QMessageBox.information(self, "提示", "命令保存成功")

    def _cmd_on_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.cmd_table.viewport().mapToGlobal(pos))
        if action == delete_action:
            row = self.cmd_table.currentRow()
            if row >= 0:
                cmd_id = self.cmd_table.item(row, 0).data(Qt.UserRole)
                ret = QMessageBox.question(
                    self, "确认", "确定要删除此命令吗？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if ret == QMessageBox.Yes:
                    self.db.delete_command(cmd_id)
                    self._cmd_refresh_list()
                    self._cs_refresh_cmd_list()
                    self._cmd_new()

    def _cmd_delete_selected(self):
        row = self.cmd_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中要删除的命令")
            return
        cmd_id = self.cmd_table.item(row, 0).data(Qt.UserRole)
        ret = QMessageBox.question(
            self, "确认", "确定要删除此命令吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            self.db.delete_command(cmd_id)
            self._cmd_refresh_list()
            self._cs_refresh_cmd_list()
            self._cmd_new()

    # ══════════════════════════════════════════════════
    # 命令集管理
    # ══════════════════════════════════════════════════

    def _cs_refresh_list(self):
        sets = self.db.list_command_sets()
        self.cs_table.setRowCount(len(sets))
        for row, s in enumerate(sets):
            self.cs_table.setItem(row, 0, QTableWidgetItem(s.get("name", "")))
            self.cs_table.setItem(row, 1, QTableWidgetItem(s.get("vendor", "通用")))
            self.cs_table.setItem(row, 2, QTableWidgetItem(s.get("description", "")))
            self.cs_table.item(row, 0).setData(Qt.UserRole, s["id"])

    def _cs_refresh_cmd_list(self):
        """刷新命令集编辑区的命令勾选列表"""
        self.cs_cmd_list.clear()
        for c in self.db.list_commands():
            item = QListWidgetItem(f"{c['name']}  ({c['cmd']})")
            item.setData(Qt.UserRole, c["id"])
            item.setCheckState(Qt.Unchecked)
            self.cs_cmd_list.addItem(item)

    def _cs_on_selected(self):
        rows = self.cs_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        cs_id = self.cs_table.item(row, 0).data(Qt.UserRole)
        self._cs_load_detail(cs_id)

    def _cs_load_detail(self, cs_id: int):
        s = self.db.get_command_set(cs_id)
        if not s:
            return
        self._cs_current_id = cs_id
        self.cs_name_input.setText(s.get("name", ""))
        vendor = s.get("vendor", "通用") or "通用"
        idx = self.cs_vendor_combo.findText(vendor)
        if idx >= 0:
            self.cs_vendor_combo.setCurrentIndex(idx)
        else:
            self.cs_vendor_combo.setEditText(vendor)
        self.cs_desc_input.setText(s.get("description", ""))

        # 解析命令 ID 列表，勾选对应项
        cmds = s.get("commands", "[]")
        if isinstance(cmds, str):
            try:
                cmds = json.loads(cmds)
            except json.JSONDecodeError:
                cmds = []
        cmd_ids = []
        if cmds and isinstance(cmds[0], dict):
            # 旧格式：dict 列表，尝试找 name 匹配
            old_names = {c.get("cmd", "") for c in cmds}
            for i in range(self.cs_cmd_list.count()):
                item = self.cs_cmd_list.item(i)
                item.setCheckState(Qt.Unchecked)
        else:
            cmd_ids = cmds if isinstance(cmds, list) else []

        for i in range(self.cs_cmd_list.count()):
            item = self.cs_cmd_list.item(i)
            cid = item.data(Qt.UserRole)
            item.setCheckState(Qt.Checked if cid in cmd_ids else Qt.Unchecked)

    def _cs_new(self):
        self._cs_current_id = None
        self.cs_name_input.clear()
        self.cs_vendor_combo.setCurrentIndex(0)
        self.cs_desc_input.clear()
        self.cs_table.clearSelection()
        # 取消所有勾选
        for i in range(self.cs_cmd_list.count()):
            self.cs_cmd_list.item(i).setCheckState(Qt.Unchecked)

    def _cs_save(self):
        name = self.cs_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "命令集名称不能为空")
            return

        # 收集勾选的命令 ID
        cmd_ids = []
        for i in range(self.cs_cmd_list.count()):
            item = self.cs_cmd_list.item(i)
            if item.checkState() == Qt.Checked:
                cmd_ids.append(item.data(Qt.UserRole))

        if not cmd_ids:
            QMessageBox.warning(self, "提示", "请至少选择一个命令")
            return

        vendor = self.cs_vendor_combo.currentText().strip()
        if vendor == "通用":
            vendor = None

        data = {
            "name": name,
            "vendor": vendor,
            "description": self.cs_desc_input.text().strip(),
            "commands": cmd_ids,  # 存命令 ID 列表
        }

        if self._cs_current_id:
            self.db.update_command_set(self._cs_current_id, data)
        else:
            self._cs_current_id = self.db.save_command_set(data)

        self._cs_refresh_list()
        QMessageBox.information(self, "提示", "命令集保存成功")

    def _cs_on_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.cs_table.viewport().mapToGlobal(pos))
        if action == delete_action:
            row = self.cs_table.currentRow()
            if row >= 0:
                cs_id = self.cs_table.item(row, 0).data(Qt.UserRole)
                ret = QMessageBox.question(
                    self, "确认", "确定要删除此命令集吗？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if ret == QMessageBox.Yes:
                    self.db.delete_command_set(cs_id)
                    self._cs_refresh_list()
                    self._cs_new()

    def _cs_delete_selected(self):
        row = self.cs_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中要删除的命令集")
            return
        cs_id = self.cs_table.item(row, 0).data(Qt.UserRole)
        ret = QMessageBox.question(
            self, "确认", "确定要删除此命令集吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            self.db.delete_command_set(cs_id)
            self._cs_refresh_list()
            self._cs_new()
