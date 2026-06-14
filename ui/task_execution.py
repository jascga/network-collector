"""
task_execution.py — 任务执行进度页

实时显示采集进度：设备状态、当前命令、数据量、耗时。
支持取消任务。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QProgressBar, QMessageBox, QHeaderView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from core.collector import Collector
import json
import time
import os


class CollectThread(QThread):
    """后台采集线程"""
    progress = pyqtSignal(dict)   # 进度更新
    finished = pyqtSignal(int, dict, str)  # task_id, summary, status
    error = pyqtSignal(str)

    def __init__(self, db, task_id: int, output_base: str = "tasks"):
        super().__init__()
        self.db = db
        self.task_id = task_id
        self.output_base = output_base

    def run(self):
        try:
            collector = Collector(self.db, self.output_base)

            # 定义进度回调
            def on_device_progress(device_ip, status, idx, total, elapsed):
                self.progress.emit({
                    "type": "device_status",
                    "device_ip": device_ip,
                    "status": status,
                    "idx": idx,
                    "total": total,
                    "elapsed": elapsed,
                })

            def on_task_complete(task_id, summary):
                self.finished.emit(task_id, summary, "completed")

            collector.run_task(self.task_id, callback=on_task_complete)

        except Exception as e:
            self.error.emit(str(e))


class TaskExecutionPanel(QWidget):
    """任务执行进度面板"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self.collector = None
        self._task_id = None
        self._start_time = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 标题行
        title_layout = QHBoxLayout()
        self.title_label = QLabel("<h3>任务执行</h3>")
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        self.status_label = QLabel("● 准备中")
        self.status_label.setStyleSheet("font-size: 14px; color: #0078d4;")
        title_layout.addWidget(self.status_label)
        layout.addLayout(title_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # 设备状态表格
        self.device_table = QTableWidget(0, 5)
        self.device_table.setHorizontalHeaderLabels([
            "设备", "IP", "状态", "当前命令", "耗时"
        ])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.device_table)

        # 统计
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("已采集: 0MB | 已耗时: 0s")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()

        btn_cancel = QPushButton("取消任务")
        btn_cancel.clicked.connect(self._cancel)
        btn_cancel.setStyleSheet(
            "QPushButton { padding: 6px 16px; background-color: #d32f2f; color: white; border-radius: 4px; }"
        )
        stats_layout.addWidget(btn_cancel)
        layout.addLayout(stats_layout)

        # 返回按钮
        btn_back = QPushButton("← 返回任务历史")
        btn_back.clicked.connect(lambda: self.main_window.navigate_to("task_history"))
        layout.addWidget(btn_back)

    # ── 任务管理 ──────────────────────────────────────

    def on_activated(self, params=None):
        if not params or "task_id" not in params:
            return
        task_id = params["task_id"]
        self._start_task(task_id)

    def _start_task(self, task_id: int):
        self._task_id = task_id
        self._start_time = time.time()

        task = self.db.get_task(task_id)
        if not task:
            QMessageBox.warning(self, "错误", f"任务不存在: {task_id}")
            return

        title = task.get("name", f"Task_{task_id}")
        self.title_label.setText(f"<h3>任务执行 — {title}</h3>")

        # 加载设备列表
        device_list = task.get("device_list", "")
        if isinstance(device_list, str):
            device_list = json.loads(device_list)
        self._init_device_table(device_list)

        # 更新状态并启动采集
        self.db.update_task_status(task_id, "running")
        self.status_label.setText("● 采集中")
        self.status_label.setStyleSheet("font-size: 14px; color: #0078d4;")

        # 启动后台采集线程
        self.collect_thread = CollectThread(self.db, task_id)
        self.collect_thread.progress.connect(self._on_progress)
        self.collect_thread.finished.connect(self._on_finished)
        self.collect_thread.error.connect(self._on_error)
        self.collect_thread.start()

        # 启动定时器更新耗时
        from PyQt5.QtCore import QTimer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_stats)
        self.timer.start(1000)

    def _init_device_table(self, devices: list):
        self.device_table.setRowCount(len(devices))
        for row, dev in enumerate(devices):
            self.device_table.setItem(row, 0, QTableWidgetItem(dev.get("hostname", "")))
            self.device_table.setItem(row, 1, QTableWidgetItem(dev.get("ip", "")))
            self.device_table.setItem(row, 2, QTableWidgetItem("⏳ 排队中"))
            self.device_table.setItem(row, 3, QTableWidgetItem("—"))
            self.device_table.setItem(row, 4, QTableWidgetItem("—"))

    def _on_progress(self, data: dict):
        """接收后台线程发出的进度信号"""
        dtype = data.get("type", "")
        if dtype == "device_status":
            ip = data.get("device_ip", "")
            status = data.get("status", "")
            idx = data.get("idx", 0)
            total = data.get("total", 0)
            elapsed = data.get("elapsed", 0)

            # 更新设备表中的状态
            for row in range(self.device_table.rowCount()):
                item = self.device_table.item(row, 1)
                if item and item.text() == ip:
                    status_display = {
                        "pending": "⏳ 排队中",
                        "running": "● 采集中",
                        "completed": "✅ 完成",
                        "failed": "❌ 失败",
                        "cancelled": "⊘ 已取消",
                    }.get(status, status)
                    self.device_table.setItem(row, 2, QTableWidgetItem(status_display))
                    self.device_table.setItem(row, 4, QTableWidgetItem(f"{elapsed:.0f}s"))
                    break

            # 更新进度条
            if total > 0:
                pct = int((idx / total) * 100)
                self.progress_bar.setValue(min(pct, 100))

    def _on_finished(self, task_id: int, summary: dict, status: str):
        self.timer.stop()
        self.status_label.setText("✅ 完成" if status == "completed" else "⚠ 部分失败")
        self.status_label.setStyleSheet(
            "font-size: 14px; color: green;" if status == "completed"
            else "font-size: 14px; color: orange;"
        )
        self.progress_bar.setValue(100)
        self._update_stats()

        # 更新主窗口状态栏
        self.main_window.update_last_task(
            f"上次任务: {task_id}  {time.strftime('%H:%M')}  {status}"
        )

        QMessageBox.information(self, "任务完成",
                                f"任务 {task_id} 执行完成\n"
                                f"成功: {summary.get('completed', 0)} / "
                                f"失败: {summary.get('failed', 0)}")

        # 跳转到结果页
        self.main_window.show_task_result(task_id)

    def _on_error(self, err_msg: str):
        self.timer.stop()
        self.status_label.setText("❌ 错误")
        self.status_label.setStyleSheet("font-size: 14px; color: red;")
        QMessageBox.critical(self, "采集错误", f"任务执行失败：\n{err_msg}")

    def _update_stats(self):
        if self._start_time:
            elapsed = time.time() - self._start_time
            self.stats_label.setText(f"已耗时: {elapsed:.0f}s")

    def _cancel(self):
        if self._task_id is None:
            return
        ret = QMessageBox.question(self, "确认取消",
                                   "确定要取消当前任务吗？\n已采集的数据将被保留。",
                                   QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.collector = Collector(self.db)
            self.collector.cancel_task(self._task_id)
            if hasattr(self, 'collect_thread') and self.collect_thread.isRunning():
                self.collect_thread.quit()
                self.collect_thread.wait(3000)
            self.timer.stop()
            self.status_label.setText("⊘ 已取消")
            self.status_label.setStyleSheet("font-size: 14px; color: gray;")
            QMessageBox.information(self, "提示", "任务已取消")
