"""
config_panel.py — SSH连接配置 + Region映射

提供 SSH 堡垒机连接管理和 Region→Section→SSH 映射配置。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QLineEdit, QSpinBox,
    QTextEdit, QMessageBox, QHeaderView, QGroupBox, QFormLayout,
    QComboBox, QCheckBox, QSplitter, QDialog, QDialogButtonBox,
    QFileDialog, QInputDialog, QMenu,
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QColor
from core.db import Database
from core.crypto import encrypt, decrypt
from core.expect_engine import SSHExpectSession
import json


class SSHTester(QThread):
    """后台测试 SSH 连接"""
    finished = pyqtSignal(bool, str)

    def __init__(self, config: dict, key_password: str = None):
        super().__init__()
        self.config = config
        self.key_password = key_password

    def run(self):
        session = None
        try:
            session = SSHExpectSession(
                hostname=self.config.get("host", ""),
                port=self.config.get("port", 22),
                username=self.config.get("username", ""),
                key_filename=self.config.get("key_path", ""),
                key_password=self.key_password,
                timeout=10,
            )
            session.connect()
            session.close()
            self.finished.emit(True, "连接成功")
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            if session:
                try:
                    session.close()
                except:
                    pass


class RegionMappingDialog(QDialog):
    """Region 映射编辑对话框"""

    def __init__(self, db: Database, mapping: dict = None):
        super().__init__()
        self.db = db
        self.mapping = mapping or {}
        self._init_ui()
        if mapping:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("编辑 Region 映射")
        self.setFixedSize(450, 250)
        layout = QFormLayout(self)

        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("如: RegionA")
        layout.addRow("Region:", self.region_input)

        self.section_input = QLineEdit()
        self.section_input.setPlaceholderText("如: Rack1-Core / Rack1-% / %")
        layout.addRow("Section:", self.section_input)

        self.ssh_combo = QComboBox()
        self._load_ssh_list()
        layout.addRow("SSH连接:", self.ssh_combo)

        self.default_check = QCheckBox("设为该 Region 的默认连接")
        layout.addRow("", self.default_check)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

    def _load_ssh_list(self):
        self.ssh_combo.clear()
        self.ssh_combo.addItem("(无)", None)
        for conn in self.db.list_ssh_connections():
            self.ssh_combo.addItem(conn["name"], conn["id"])

    def _load_data(self):
        self.region_input.setText(self.mapping.get("region", ""))
        self.section_input.setText(self.mapping.get("section", ""))
        idx = self.ssh_combo.findData(self.mapping.get("ssh_connection_id"))
        if idx >= 0:
            self.ssh_combo.setCurrentIndex(idx)
        self.default_check.setChecked(bool(self.mapping.get("is_default", 0)))

    def _on_save(self):
        region = self.region_input.text().strip()
        section = self.section_input.text().strip()
        if not region or not section:
            QMessageBox.warning(self, "提示", "Region 和 Section 不能为空")
            return
        self.mapping = {
            "region": region,
            "section": section,
            "ssh_connection_id": self.ssh_combo.currentData(),
            "is_default": 1 if self.default_check.isChecked() else 0,
        }
        self.accept()


class ConfigPanel(QWidget):
    """SSH 连接 + Region 映射配置"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self.cipher = main_window.cipher
        self._current_conn_id = None
        self._init_ui()
        self._refresh_connection_list()
        self._refresh_region_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 标签页
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ── Tab 1: SSH连接 ──
        ssh_tab = QWidget()
        ssh_layout = QVBoxLayout(ssh_tab)

        # 上半部分：连接列表 + 操作按钮
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("<b>SSH 连接列表</b>"))
        top_bar.addStretch()
        btn_new = QPushButton("+ 新增")
        btn_new.clicked.connect(self._new_connection)
        top_bar.addWidget(btn_new)
        btn_import = QPushButton("导入")
        btn_import.clicked.connect(self._import_config)
        top_bar.addWidget(btn_import)
        btn_export = QPushButton("导出")
        btn_export.clicked.connect(self._export_config)
        top_bar.addWidget(btn_export)
        ssh_layout.addLayout(top_bar)

        self.conn_table = QTableWidget(0, 5)
        self.conn_table.setHorizontalHeaderLabels(["名称", "主机", "端口", "用户名", "状态"])
        header = self.conn_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        self.conn_table.setColumnWidth(0, 160)
        self.conn_table.setColumnWidth(1, 200)
        self.conn_table.setColumnWidth(2, 70)
        self.conn_table.setColumnWidth(3, 120)
        self.conn_table.setColumnWidth(4, 80)
        self.conn_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.conn_table.setSelectionMode(QTableWidget.SingleSelection)
        self.conn_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.conn_table.selectionModel().selectionChanged.connect(self._on_conn_selected)
        self.conn_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conn_table.customContextMenuRequested.connect(self._on_conn_context_menu)
        ssh_layout.addWidget(self.conn_table)

        # 下半部分：编辑表单
        edit_group = QGroupBox("编辑连接")
        edit_layout = QVBoxLayout(edit_group)

        form_layout = QFormLayout()
        self.name_input = QLineEdit()
        form_layout.addRow("名称:", self.name_input)
        self.host_input = QLineEdit()
        form_layout.addRow("主机:", self.host_input)
        port_layout = QHBoxLayout()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        port_layout.addWidget(self.port_spin)
        port_layout.addStretch()
        form_layout.addRow("端口:", port_layout)
        self.username_input = QLineEdit()
        form_layout.addRow("用户名:", self.username_input)
        key_layout = QHBoxLayout()
        self.key_path_input = QLineEdit()
        key_layout.addWidget(self.key_path_input)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_key)
        key_layout.addWidget(btn_browse)
        form_layout.addRow("私钥路径:", key_layout)
        self.key_password_input = QLineEdit()
        self.key_password_input.setEchoMode(QLineEdit.Password)
        self.key_password_input.setPlaceholderText("无密码则留空")
        form_layout.addRow("私钥密码:", self.key_password_input)
        edit_layout.addLayout(form_layout)

        # Expect 流程编辑器
        edit_layout.addWidget(QLabel("<b>Expect 流程:</b>"))
        self.expect_table = QTableWidget(0, 2)
        self.expect_table.setHorizontalHeaderLabels(["看到 (expect)", "发送 (send)"])
        self.expect_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.expect_table.setMaximumHeight(160)
        self.expect_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        edit_layout.addWidget(self.expect_table)

        # 变量提示
        var_hint = QLabel("💡 send 中可用 <code>{device_ip}</code>，自动替换为每台设备的实际IP")
        var_hint.setStyleSheet("color: #666; font-size: 14px; padding: 4px 0;")
        edit_layout.addWidget(var_hint)

        expect_btn_layout = QHBoxLayout()
        btn_add_row = QPushButton("+ 新增行")
        btn_add_row.clicked.connect(lambda: self.expect_table.insertRow(self.expect_table.rowCount()))
        expect_btn_layout.addWidget(btn_add_row)
        btn_del_row = QPushButton("- 删除行")
        btn_del_row.clicked.connect(lambda: self.expect_table.removeRow(self.expect_table.currentRow()))
        expect_btn_layout.addWidget(btn_del_row)
        expect_btn_layout.addStretch()
        edit_layout.addLayout(expect_btn_layout)

        # 保存/测试按钮
        btn_layout = QHBoxLayout()
        btn_test = QPushButton("测试连接")
        btn_test.clicked.connect(self._test_connection)
        btn_layout.addWidget(btn_test)
        btn_layout.addStretch()
        btn_save = QPushButton("保 存")
        btn_save.setStyleSheet("QPushButton { padding: 6px 24px; }")
        btn_save.clicked.connect(self._save_connection)
        btn_layout.addWidget(btn_save)
        edit_layout.addLayout(btn_layout)

        ssh_layout.addWidget(edit_group)

        self.tabs.addTab(ssh_tab, "SSH 连接")

        # ── Tab 2: Region 映射 ──
        region_tab = QWidget()
        region_layout = QVBoxLayout(region_tab)

        region_bar = QHBoxLayout()
        region_bar.addWidget(QLabel("<b>Region + Section → SSH 映射</b>"))
        region_bar.addStretch()
        btn_add_map = QPushButton("+ 添加")
        btn_add_map.clicked.connect(self._add_region_mapping)
        region_bar.addWidget(btn_add_map)
        region_layout.addLayout(region_bar)

        self.region_table = QTableWidget(0, 4)
        self.region_table.setHorizontalHeaderLabels(["Region", "Section", "SSH连接", "默认"])
        self.region_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.region_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.region_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.region_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.region_table.customContextMenuRequested.connect(self._on_region_context_menu)
        region_layout.addWidget(self.region_table)

        self.tabs.addTab(region_tab, "Region 映射")

    # ── SSH 连接列表 ──────────────────────────────────

    def _refresh_connection_list(self):
        connections = self.db.list_ssh_connections()
        self.conn_table.setRowCount(len(connections))
        for row, conn in enumerate(connections):
            self.conn_table.setItem(row, 0, QTableWidgetItem(conn.get("name", "")))
            self.conn_table.setItem(row, 1, QTableWidgetItem(conn.get("host", "")))
            self.conn_table.setItem(row, 2, QTableWidgetItem(str(conn.get("port", 22))))
            self.conn_table.setItem(row, 3, QTableWidgetItem(conn.get("username", "")))
            # 状态列
            status = conn.get("status", "untested")
            status_map = {
                "ok": "✅ 正常",
                "failed": "❌ 失败",
                "testing": "⏳ 测试中",
                "untested": "—",
            }
            status_text = status_map.get(status, "—")
            status_item = QTableWidgetItem(status_text)
            if status == "ok":
                status_item.setForeground(QColor("#16a34a"))
            elif status == "failed":
                status_item.setForeground(QColor("#dc2626"))
            self.conn_table.setItem(row, 4, status_item)
            self.conn_table.item(row, 0).setData(Qt.UserRole, conn["id"])
        self._clear_edit_form()

    def _on_conn_selected(self):
        rows = self.conn_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        conn_id = self.conn_table.item(row, 0).data(Qt.UserRole)
        conn = self.db.get_ssh_connection(conn_id)
        if conn:
            self._current_conn_id = conn_id
            self.name_input.setText(conn.get("name", ""))
            self.host_input.setText(conn.get("host", ""))
            self.port_spin.setValue(conn.get("port", 22))
            self.username_input.setText(conn.get("username", ""))
            self.key_path_input.setText(conn.get("key_path", ""))
            # 解密密码
            try:
                enc_pwd = conn.get("key_password", "")
                if enc_pwd and self.cipher:
                    self.key_password_input.setText(decrypt(self.cipher, enc_pwd))
                else:
                    self.key_password_input.setText(enc_pwd)
            except Exception:
                self.key_password_input.setText("")
            # expect_flow
            flow = conn.get("expect_flow", "")
            if isinstance(flow, str):
                try:
                    flow = json.loads(flow)
                except:
                    flow = []
            self.expect_table.setRowCount(len(flow))
            for i, step in enumerate(flow):
                self.expect_table.setItem(i, 0, QTableWidgetItem(step.get("expect", "")))
                self.expect_table.setItem(i, 1, QTableWidgetItem(step.get("send", "")))

    def _clear_edit_form(self):
        self._current_conn_id = None
        self.name_input.clear()
        self.host_input.clear()
        self.port_spin.setValue(22)
        self.username_input.clear()
        self.key_path_input.clear()
        self.key_password_input.clear()
        self.expect_table.setRowCount(0)

    def _new_connection(self):
        self._clear_edit_form()
        self.conn_table.clearSelection()

    def _on_conn_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.conn_table.viewport().mapToGlobal(pos))
        if action == delete_action:
            row = self.conn_table.currentRow()
            if row >= 0:
                conn_id = self.conn_table.item(row, 0).data(Qt.UserRole)
                ret = QMessageBox.question(self, "确认", "确定要删除此 SSH 连接吗？",
                                           QMessageBox.Yes | QMessageBox.No)
                if ret == QMessageBox.Yes:
                    self.db.delete_ssh_connection(conn_id)
                    self._refresh_connection_list()

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 SSH 私钥文件", "",
                                               "SSH Key (*.pem *.ppk *id_rsa*);;All Files (*)")
        if path:
            self.key_path_input.setText(path)

    def _collect_flow(self) -> list:
        flow = []
        for row in range(self.expect_table.rowCount()):
            expect_item = self.expect_table.item(row, 0)
            send_item = self.expect_table.item(row, 1)
            expect = expect_item.text().strip() if expect_item else ""
            send = send_item.text().strip() if send_item else ""
            if expect or send:
                flow.append({"expect": expect, "send": send})
        return flow

    def _save_connection(self):
        name = self.name_input.text().strip()
        host = self.host_input.text().strip()
        if not name or not host:
            QMessageBox.warning(self, "提示", "名称和主机不能为空")
            return

        # 加密私钥密码
        key_pwd_plain = self.key_password_input.text()
        key_pwd_encrypted = encrypt(self.cipher, key_pwd_plain) if key_pwd_plain and self.cipher else ""

        data = {
            "name": name,
            "host": host,
            "port": self.port_spin.value(),
            "username": self.username_input.text().strip(),
            "key_path": self.key_path_input.text().strip(),
            "key_password": key_pwd_encrypted,
            "expect_flow": self._collect_flow(),
        }

        if self._current_conn_id:
            self.db.update_ssh_connection(self._current_conn_id, data)
        else:
            self._current_conn_id = self.db.save_ssh_connection(data)

        self._refresh_connection_list()
        QMessageBox.information(self, "提示", "保存成功")

    def _test_connection(self):
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "提示", "请先填写主机地址")
            return

        # 测试前自动保存（新建连接先存到DB，已有连接更新）
        key_pwd_raw = self.key_password_input.text()
        key_pwd_encrypted = encrypt(self.cipher, key_pwd_raw) if self.cipher and key_pwd_raw else ""
        data = {
            "name": self.name_input.text().strip() or host,
            "host": host,
            "port": self.port_spin.value(),
            "username": self.username_input.text().strip(),
            "key_path": self.key_path_input.text().strip(),
            "key_password": key_pwd_encrypted,
            "expect_flow": self._collect_flow(),
        }
        if self._current_conn_id:
            self.db.update_ssh_connection(self._current_conn_id, data)
        else:
            self._current_conn_id = self.db.save_ssh_connection(data)
        self._refresh_connection_list()

        config = {
            "host": host,
            "port": self.port_spin.value(),
            "username": self.username_input.text().strip(),
            "key_path": self.key_path_input.text().strip(),
        }
        self.tester = SSHTester(config, key_pwd_raw)
        self.tester.finished.connect(self._on_test_finished)
        self.tester.start()
        # 先更新状态列为"测试中"
        self.db.update_ssh_status(self._current_conn_id, "testing")
        self._refresh_connection_list()
        # 用状态栏提示，不弹模态框
        parent = self.window()
        if hasattr(parent, 'statusBar'):
            parent.statusBar().showMessage("⏳ 正在测试连接...", 0)

    def _on_test_finished(self, success: bool, message: str):
        # 清除状态栏提示
        parent = self.window()
        if hasattr(parent, 'statusBar'):
            parent.statusBar().clearMessage()
        # 从当前选中行获取连接ID（_current_conn_id可能已被clear掉）
        conn_id = None
        rows = self.conn_table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            item = self.conn_table.item(row, 0)
            if item:
                conn_id = item.data(Qt.UserRole)
        else:
            conn_id = self._current_conn_id
        # 更新状态到数据库和列表
        status = "ok" if success else "failed"
        if conn_id:
            self.db.update_ssh_status(conn_id, status)
            self._refresh_connection_list()
        if success:
            QMessageBox.information(self, "连接测试", f"✅ 连接成功！\n{message}")
        else:
            QMessageBox.warning(self, "连接测试", f"❌ 连接失败：\n{message}")

    # ── Region 映射 ───────────────────────────────────

    def _refresh_region_table(self):
        mappings = self.db.list_region_mapping()
        self.region_table.setRowCount(len(mappings))
        for row, m in enumerate(mappings):
            self.region_table.setItem(row, 0, QTableWidgetItem(m.get("region", "")))
            self.region_table.setItem(row, 1, QTableWidgetItem(m.get("section", "")))
            self.region_table.setItem(row, 2, QTableWidgetItem(m.get("ssh_name", "—")))
            self.region_table.setItem(row, 3, QTableWidgetItem("✓" if m.get("is_default") else ""))
            self.region_table.item(row, 0).setData(Qt.UserRole, m["id"])

    def _add_region_mapping(self):
        dialog = RegionMappingDialog(self.db)
        if dialog.exec_() == QDialog.Accepted:
            self.db.save_region_mapping(dialog.mapping)
            self._refresh_region_table()

    def _on_region_context_menu(self, pos):
        menu = QMenu(self)
        edit_action = menu.addAction("编辑")
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.region_table.viewport().mapToGlobal(pos))
        row = self.region_table.currentRow()
        if row < 0:
            return
        map_id = self.region_table.item(row, 0).data(Qt.UserRole)
        if action == delete_action:
            ret = QMessageBox.question(self, "确认", "确定要删除此映射吗？",
                                       QMessageBox.Yes | QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.db.conn.execute("DELETE FROM region_mapping WHERE id=?", (map_id,))
                self.db.conn.commit()
                self._refresh_region_table()
        elif action == edit_action:
            # 加载数据到对话框
            # 这里简化为重新添加，实际项目可扩展
            pass

    # ── 导入导出 ──────────────────────────────────────

    def _export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出全局配置", "network_config.json",
                                               "JSON files (*.json)")
        if path:
            config = self.db.export_config()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "提示", f"已导出到：{path}\n注意：私钥密码已自动清空。")

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入全局配置", "", "JSON files (*.json)")
        if path:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.db.import_config(config)
            self._refresh_connection_list()
            self._refresh_region_table()
            QMessageBox.information(self, "提示", f"导入成功！\n注意：私钥密码需手动补填。")

    def on_activated(self, params=None):
        """页面被激活时刷新"""
        self._refresh_connection_list()
        self._refresh_region_table()
