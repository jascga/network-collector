"""
command_set_panel.py — 命令集管理

管理可复用的设备命令集，支持厂商差异化（VendorA/VendorB/通用）。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QHeaderView, QGroupBox,
    QFormLayout, QMessageBox, QMenu, QTextEdit,
)
from PyQt5.QtCore import Qt, QSplitter
import json


class CommandSetPanel(QWidget):
    """命令集管理面板"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self._current_id = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 顶部操作栏
        top = QHBoxLayout()
        top.addWidget(QLabel("<b>命令集列表</b>"))
        top.addStretch()
        btn_new = QPushButton("+ 新增")
        btn_new.clicked.connect(self._new)
        top.addWidget(btn_new)
        layout.addLayout(top)

        # 左右分栏（可拖拽）
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.cmd_table = QTableWidget(0, 3)
        self.cmd_table.setHorizontalHeaderLabels(["名称", "厂商", "描述"])
        self.cmd_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.cmd_table.setMinimumWidth(200)
        self.cmd_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cmd_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cmd_table.selectionModel().selectionChanged.connect(self._on_selected)
        self.cmd_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cmd_table.customContextMenuRequested.connect(self._on_context_menu)
        left_layout.addWidget(self.cmd_table)
        splitter.addWidget(left_widget)

        # 右侧：编辑表单
        right = QGroupBox("编辑命令集")
        right_layout = QVBoxLayout(right)

        form = QFormLayout()
        self.name_input = QLineEdit()
        form.addRow("名称:", self.name_input)
        self.vendor_combo = QComboBox()
        self._load_vendors()
        form.addRow("厂商:", self.vendor_combo)
        self.desc_input = QLineEdit()
        form.addRow("描述:", self.desc_input)
        right_layout.addLayout(form)

        right_layout.addWidget(QLabel("<b>命令列表:</b>"))
        right_layout.addWidget(QLabel("(类型: simple | parameterized | foreach)"))
        self.cmd_edit = QTextEdit()
        self.cmd_edit.setPlaceholderText(
            '每行一个命令，格式支持：\n'
            '  简单命令: display ip routing-table\n'
            '  参数化: display ip routing-table {target_network}\n'
            '  JSON格式（含类型/子命令等高级配置）'
        )
        self.cmd_edit.setMinimumHeight(200)
        right_layout.addWidget(self.cmd_edit)

        btn_save = QPushButton("保 存")
        btn_save.clicked.connect(self._save)
        btn_save.setStyleSheet("QPushButton { padding: 6px 24px; }")
        right_layout.addWidget(btn_save, alignment=Qt.AlignRight)

        splitter.addWidget(right)
        layout.addWidget(splitter)

    # ── 数据加载 ──────────────────────────────────────

    def _load_vendors(self):
        """从设备表加载已有厂商列表"""
        self.vendor_combo.addItem("通用")
        try:
            vendors = self.db.conn.execute(
                "SELECT DISTINCT vendor FROM devices WHERE vendor != '' ORDER BY vendor"
            ).fetchall()
            for v in vendors:
                self.vendor_combo.addItem(v["vendor"])
        except Exception:
            pass

    def on_activated(self, params=None):
        self._refresh_list()

    def _refresh_list(self):
        sets = self.db.list_command_sets()
        self.cmd_table.setRowCount(len(sets))
        for row, s in enumerate(sets):
            self.cmd_table.setItem(row, 0, QTableWidgetItem(s.get("name", "")))
            self.cmd_table.setItem(row, 1, QTableWidgetItem(s.get("vendor", "通用")))
            self.cmd_table.setItem(row, 2, QTableWidgetItem(s.get("description", "")))
            self.cmd_table.item(row, 0).setData(Qt.UserRole, s["id"])

    def _on_selected(self):
        rows = self.cmd_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        cmd_id = self.cmd_table.item(row, 0).data(Qt.UserRole)
        self._load_detail(cmd_id)

    def _load_detail(self, cmd_id: int):
        row = self.db.conn.execute(
            "SELECT * FROM command_sets WHERE id=?", (cmd_id,)
        ).fetchone()
        if not row:
            return
        self._current_id = cmd_id
        self.name_input.setText(row["name"] or "")
        vendor = row["vendor"] or "通用"
        idx = self.vendor_combo.findText(vendor)
        if idx >= 0:
            self.vendor_combo.setCurrentIndex(idx)
        self.desc_input.setText(row["description"] or "")

        # 解析命令
        cmds = row["commands"]
        if isinstance(cmds, str):
            try:
                cmds = json.loads(cmds)
            except:
                cmds = [cmds]
        if isinstance(cmds, list):
            lines = []
            for c in cmds:
                if isinstance(c, dict):
                    if c.get("type") == "foreach":
                        lines.append(json.dumps(c, ensure_ascii=False))
                    elif c.get("type") == "parameterized" or "{" in c.get("cmd", ""):
                        lines.append(c.get("cmd", json.dumps(c, ensure_ascii=False)))
                    else:
                        lines.append(c.get("cmd", json.dumps(c, ensure_ascii=False)))
                else:
                    lines.append(str(c))
            self.cmd_edit.setPlainText("\n".join(lines))

    def _new(self):
        self._current_id = None
        self.name_input.clear()
        self.vendor_combo.setCurrentIndex(0)
        self.desc_input.clear()
        self.cmd_edit.clear()
        self.cmd_table.clearSelection()

    def _save(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "命令集名称不能为空")
            return

        # 解析命令文本为 JSON
        raw = self.cmd_edit.toPlainText().strip()
        commands = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                try:
                    commands.append(json.loads(line))
                except json.JSONDecodeError:
                    commands.append({"cmd": line, "type": "simple"})
            else:
                # 判断是否参数化
                if "{" in line and "}" in line:
                    commands.append({"cmd": line, "type": "parameterized"})
                else:
                    commands.append({"cmd": line, "type": "simple"})

        vendor = self.vendor_combo.currentText()
        if vendor == "通用":
            vendor = None

        data = {
            "name": name,
            "vendor": vendor,
            "description": self.desc_input.text().strip(),
            "commands": commands,
        }

        if self._current_id:
            self.db.update_command_set(self._current_id, data)
        else:
            self._current_id = self.db.save_command_set(data)

        self._refresh_list()
        QMessageBox.information(self, "提示", "保存成功")

    def _on_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.cmd_table.viewport().mapToGlobal(pos))
        if action == delete_action:
            row = self.cmd_table.currentRow()
            if row >= 0:
                cmd_id = self.cmd_table.item(row, 0).data(Qt.UserRole)
                ret = QMessageBox.question(self, "确认", "确定要删除此命令集吗？",
                                           QMessageBox.Yes | QMessageBox.No)
                if ret == QMessageBox.Yes:
                    self.db.delete_command_set(cmd_id)
                    self._refresh_list()
                    self._new()
