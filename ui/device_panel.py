"""
device_panel.py — 设备管理

设备列表（筛选 + 搜索）、Excel 导入、手工添加、删除（软删除）。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QLineEdit, QHeaderView, QGroupBox,
    QFormLayout, QMessageBox, QFileDialog, QDialog, QDialogButtonBox,
    QMenu,
)
from PyQt5.QtCore import Qt, pyqtSignal
import json

try:
    import openpyxl
except ImportError:
    openpyxl = None


class AddDeviceDialog(QDialog):
    """手工添加设备对话框"""

    def __init__(self, db, device: dict = None):
        super().__init__()
        self.db = db
        self.device = device or {}
        self._init_ui()
        if device:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("添加设备" if not self.device else "编辑设备")
        layout = QFormLayout(self)

        self.hostname_input = QLineEdit()
        self.hostname_input.setPlaceholderText("如: WH-AZ1-Core01")
        layout.addRow("设备名:", self.hostname_input)

        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("如: 10.0.1.1")
        layout.addRow("IP地址:", self.ip_input)

        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("如: RegionA")
        layout.addRow("Region:", self.region_input)

        self.section_input = QLineEdit()
        self.section_input.setPlaceholderText("如: Rack1-Core")
        layout.addRow("网络分区:", self.section_input)

        self.role_combo = QComboBox()
        self.role_combo.setEditable(True)
        self._load_roles()
        layout.addRow("角色:", self.role_combo)

        self.vendor_combo = QComboBox()
        self._load_vendors()
        layout.addRow("厂商:", self.vendor_combo)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("备注信息")
        layout.addRow("备注:", self.desc_input)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

        self.adjustSize()

    def _load_data(self):
        self.hostname_input.setText(self.device.get("hostname", ""))
        self.ip_input.setText(self.device.get("ip", ""))
        self.region_input.setText(self.device.get("region", ""))
        self.section_input.setText(self.device.get("section", ""))
        idx = self.role_combo.findText(self.device.get("role", ""))
        if idx >= 0:
            self.role_combo.setCurrentIndex(idx)
        else:
            self.role_combo.setEditText(self.device.get("role", ""))
        idx = self.vendor_combo.findText(self.device.get("vendor", ""))
        if idx >= 0:
            self.vendor_combo.setCurrentIndex(idx)

    def _load_vendors(self):
        """从数据库加载已有厂商列表"""
        self.vendor_combo.addItem("")
        try:
            vendors = self.db.conn.execute(
                "SELECT DISTINCT vendor FROM devices WHERE vendor != '' ORDER BY vendor"
            ).fetchall()
            for v in vendors:
                self.vendor_combo.addItem(v["vendor"])
        except Exception:
            pass

    def _load_roles(self):
        """从数据库加载角色列表"""
        try:
            roles = self.db.list_roles()
            for r in roles:
                self.role_combo.addItem(r["name"])
        except Exception:
            self.role_combo.addItems(["fa", "cnt", "dcc", "dsw", "tor"])

    def _on_save(self):
        hostname = self.hostname_input.text().strip()
        ip = self.ip_input.text().strip()
        region = self.region_input.text().strip()
        section = self.section_input.text().strip()
        role = self.role_combo.currentText().strip()
        if not all([hostname, ip, region, section, role]):
            QMessageBox.warning(self, "提示", "设备名/IP/Region/Section/Role 为必填项")
            return
        self.device = {
            "hostname": hostname,
            "ip": ip,
            "region": region,
            "section": section,
            "role": role,
            "vendor": self.vendor_combo.currentText(),
            "description": self.desc_input.text().strip(),
            "source": "manual",
        }
        self.accept()


class DevicePanel(QWidget):
    """设备管理面板"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 筛选栏
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Region:"))
        self.region_filter = QComboBox()
        self.region_filter.setMinimumWidth(120)
        self.region_filter.addItem("全部", "")
        filter_layout.addWidget(self.region_filter)

        filter_layout.addWidget(QLabel("网络分区:"))
        self.section_filter = QComboBox()
        self.section_filter.setMinimumWidth(100)
        self.section_filter.addItem("全部", "")
        filter_layout.addWidget(self.section_filter)

        self.region_filter.currentIndexChanged.connect(self._on_region_changed)

        filter_layout.addWidget(QLabel("角色:"))
        self.role_filter = QComboBox()
        self.role_filter.addItem("全部", "")
        filter_layout.addWidget(self.role_filter)

        filter_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("设备名 / IP")
        self.search_input.setMaximumWidth(180)
        filter_layout.addWidget(self.search_input)

        btn_search = QPushButton("查询")
        btn_search.clicked.connect(self._on_search)
        filter_layout.addWidget(btn_search)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # 操作按钮栏
        btn_layout = QHBoxLayout()
        btn_template = QPushButton("📄 下载模板")
        btn_template.clicked.connect(self._download_template)
        btn_layout.addWidget(btn_template)
        btn_import = QPushButton("📥 导入Excel")
        btn_import.clicked.connect(self._import_excel)
        btn_layout.addWidget(btn_import)
        btn_add = QPushButton("➕ 手工添加")
        btn_add.clicked.connect(self._add_device)
        btn_layout.addWidget(btn_add)
        btn_layout.addStretch()
        self.device_count_label = QLabel("共 0 台设备")
        btn_layout.addWidget(self.device_count_label)
        layout.addLayout(btn_layout)

        # 设备列表
        self.device_table = QTableWidget(0, 8)
        self.device_table.setHorizontalHeaderLabels([
            "设备名", "IP地址", "Region", "网络分区", "角色", "厂商", "来源", "备注"
        ])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.device_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.device_table)

        # 底部操作
        bottom = QHBoxLayout()
        btn_edit = QPushButton("编辑")
        btn_edit.clicked.connect(self._edit_device)
        bottom.addWidget(btn_edit)
        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self._delete_device)
        bottom.addWidget(btn_delete)
        bottom.addStretch()
        layout.addLayout(bottom)

    def _load_sections(self):
        """加载网络分区到筛选下拉框，按当前Region筛选"""
        section_text = self.section_filter.currentText()
        self.section_filter.blockSignals(True)
        self.section_filter.clear()
        self.section_filter.addItem("全部", "")
        region = self.region_filter.currentData() or None
        try:
            sql = "SELECT DISTINCT section FROM devices WHERE is_active=1"
            params = []
            if region:
                sql += " AND region=?"
                params.append(region)
            sql += " ORDER BY section"
            rows = self.db.conn.execute(sql, params).fetchall()
            for r in rows:
                self.section_filter.addItem(r["section"], r["section"])
        except Exception:
            pass
        idx = self.section_filter.findText(section_text)
        if idx >= 0:
            self.section_filter.setCurrentIndex(idx)
        self.section_filter.blockSignals(False)

    def _on_region_changed(self):
        self._load_sections()

    def _load_role_filter(self):
        """加载角色到筛选下拉框"""
        role = self.role_filter.currentText()
        self.role_filter.clear()
        self.role_filter.addItem("全部", "")
        try:
            roles = self.db.list_roles()
            for r in roles:
                self.role_filter.addItem(r["name"], r["name"])
        except Exception:
            for n in ["fa", "cnt", "dcc", "dsw", "tor"]:
                self.role_filter.addItem(n, n)
        idx = self.role_filter.findText(role)
        if idx >= 0:
            self.role_filter.setCurrentIndex(idx)

    # ── 数据加载 ──────────────────────────────────────

    def on_activated(self, params=None):
        self._load_regions()
        self._load_sections()
        self._load_role_filter()
        self._on_search()

    def _load_regions(self):
        """加载 Region 列表到下拉框"""
        rows = self.db.conn.execute(
            "SELECT DISTINCT region FROM devices WHERE is_active=1 ORDER BY region"
        ).fetchall()
        current = self.region_filter.currentData()
        self.region_filter.clear()
        self.region_filter.addItem("全部", "")
        for r in rows:
            self.region_filter.addItem(r["region"], r["region"])
        if current:
            idx = self.region_filter.findData(current)
            if idx >= 0:
                self.region_filter.setCurrentIndex(idx)

    def _download_template(self):
        """导出 Excel 导入模板"""
        from pathlib import Path
        import shutil
        template_src = Path(__file__).parent.parent / "config" / "device_import_template.xlsx"
        if not template_src.exists():
            QMessageBox.warning(self, "提示", "模板文件不存在")
            return
        dst, _ = QFileDialog.getSaveFileName(
            self, "保存模板", "device_import_template.xlsx",
            "Excel files (*.xlsx);;All Files (*)"
        )
        if dst:
            shutil.copy(template_src, dst)
            QMessageBox.information(self, "提示", f"模板已保存到:\n{dst}")

    def _on_search(self):
        region = self.region_filter.currentData() or None
        section = self.section_filter.currentText() if self.section_filter.currentIndex() > 0 else None
        role = self.role_filter.currentText() if self.role_filter.currentIndex() > 0 else None
        keyword = self.search_input.text().strip().lower()

        devices = self.db.list_devices(region=region, section=section, role=role)

        # 客户端搜索过滤
        if keyword:
            devices = [d for d in devices if
                       keyword in d.get("hostname", "").lower() or
                       keyword in d.get("ip", "").lower()]

        self._populate_table(devices)
        self.device_count_label.setText(f"共 {len(devices)} 台设备")

    def _populate_table(self, devices: list):
        self.device_table.setRowCount(len(devices))
        for row, dev in enumerate(devices):
            self.device_table.setItem(row, 0, QTableWidgetItem(dev.get("hostname", "")))
            self.device_table.setItem(row, 1, QTableWidgetItem(dev.get("ip", "")))
            self.device_table.setItem(row, 2, QTableWidgetItem(dev.get("region", "")))
            self.device_table.setItem(row, 3, QTableWidgetItem(dev.get("section", "")))
            self.device_table.setItem(row, 4, QTableWidgetItem(dev.get("role", "")))
            self.device_table.setItem(row, 5, QTableWidgetItem(dev.get("vendor", "")))
            source = dev.get("source", "manual")
            self.device_table.setItem(row, 6, QTableWidgetItem("Excel" if source == "excel" else "手工"))
            self.device_table.setItem(row, 7, QTableWidgetItem(dev.get("description", "")))
            self.device_table.item(row, 0).setData(Qt.UserRole, dev["id"])

    # ── 设备操作 ──────────────────────────────────────

    def _add_device(self):
        dialog = AddDeviceDialog(self.db)
        if dialog.exec_() == QDialog.Accepted:
            self.db.add_device(dialog.device)
            self._on_search()
            QMessageBox.information(self, "提示", "设备添加成功")

    def _edit_device(self):
        row = self.device_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一台设备")
            return
        device_id = self.device_table.item(row, 0).data(Qt.UserRole)
        device = self.db.conn.execute(
            "SELECT * FROM devices WHERE id=?", (device_id,)
        ).fetchone()
        if not device:
            return
        device_dict = dict(device)
        dialog = AddDeviceDialog(self.db, device_dict)
        if dialog.exec_() == QDialog.Accepted:
            self.db.update_device(device_id, dialog.device)
            self._on_search()
            QMessageBox.information(self, "提示", "设备更新成功")

    def _delete_device(self):
        row = self.device_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一台设备")
            return
        device_id = self.device_table.item(row, 0).data(Qt.UserRole)
        hostname = self.device_table.item(row, 0).text()
        ret = QMessageBox.question(self, "确认删除",
                                   f"确定要删除设备「{hostname}」吗？\n（软删除，可恢复）",
                                   QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.db.delete_device(device_id)
            self._on_search()

    def _on_context_menu(self, pos):
        menu = QMenu(self)
        edit_action = menu.addAction("编辑")
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.device_table.viewport().mapToGlobal(pos))
        if action == edit_action:
            self._edit_device()
        elif action == delete_action:
            self._delete_device()

    # ── Excel 导入 ────────────────────────────────────

    def _import_excel(self):
        if openpyxl is None:
            QMessageBox.warning(self, "提示", "需要安装 openpyxl 库：\npip install openpyxl")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Excel 文件", "",
            "Excel files (*.xlsx *.xls *.csv);;All Files (*)"
        )
        if not path:
            return

        try:
            devices = self._parse_excel(path)
        except Exception as e:
            QMessageBox.critical(self, "导入错误", f"文件读取失败：{e}")
            return

        if not devices:
            QMessageBox.warning(self, "提示", "未解析到有效设备数据")
            return

        # 预览确认
        preview = "\n".join(
            f"{d.get('hostname','?')}\t{d.get('ip','?')}\t"
            f"{d.get('region','?')}\t{d.get('section','?')}\t{d.get('role','?')}"
            for d in devices[:5]
        )
        more = f"\n... 共 {len(devices)} 条" if len(devices) > 5 else ""
        ret = QMessageBox.question(
            self, "导入预览",
            f"解析到 {len(devices)} 台设备，前5行预览：\n\n{preview}{more}\n\n"
            f"策略：同名设备覆盖更新，新增设备追加，不在 Excel 中的不删除。\n\n确认导入？",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            # 预校验
            errors = []
            for i, d in enumerate(devices):
                for field in ["hostname", "ip", "region", "section", "role"]:
                    if not d.get(field):
                        errors.append(f"第{i+2}行缺少必填字段: {field}")
            if errors:
                QMessageBox.warning(self, "校验失败", "\n".join(errors[:10]))
                return

            self.db.import_devices(devices)
            self._on_search()
            self._load_regions()
            QMessageBox.information(self, "提示", f"导入成功：{len(devices)} 台设备")

    def _parse_excel(self, path: str) -> list:
        """解析 Excel/CSV 文件"""
        if path.endswith(".csv"):
            import csv
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                devices = []
                for row in reader:
                    row.setdefault("vendor", "")
                    row.setdefault("description", "")
                    row.setdefault("source", "excel")
                    if row.get("hostname") and row.get("ip"):
                        devices.append(row)
                return devices

        wb = openpyxl.load_workbook(path)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        headers = [str(h).strip().lower() if h else "" for h in rows[0]]
        required_map = {
            "hostname": ["hostname", "设备名", "host", "host name", "host_name", "name"],
            "ip": ["ip", "ip地址", "address", "ip address", "ip_address"],
            "region": ["region", "区域"],
            "section": ["section", "分区"],
            "role": ["role", "角色"],
            "vendor": ["vendor", "厂商"],
            "description": ["description", "备注", "说明"],
        }

        col_map = {}
        for key, candidates in required_map.items():
            for c in candidates:
                for i, h in enumerate(headers):
                    if c in h:
                        col_map[key] = i
                        break
                if key in col_map:
                    break

        if "hostname" not in col_map or "ip" not in col_map:
            raise ValueError("Excel 缺少必填列：hostname / ip")

        devices = []
        for row in rows[1:]:
            if not row or all(v is None or str(v).strip() == "" for v in row):
                continue
            device = {"vendor": "", "description": "", "source": "excel"}
            for key, idx in col_map.items():
                val = row[idx] if idx < len(row) else ""
                device[key] = str(val).strip() if val is not None else ""
            if device.get("hostname") and device.get("ip"):
                devices.append(device)

        return devices
