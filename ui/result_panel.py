"""
result_panel.py — 结果展示页

显示任务结论摘要、问题列表（可折叠展开）、原始命令输出。
支持导出 TXT/CSV/HTML。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QGroupBox, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QSplitter, QFileDialog,
)
from PyQt5.QtCore import Qt
import json
import os
import datetime


class ResultPanel(QWidget):
    """任务结果面板"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.db = main_window.db
        self._task_id = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 标题行
        title_layout = QHBoxLayout()
        self.title_label = QLabel("<h3>任务结果</h3>")
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()

        btn_export = QPushButton("导出 TXT")
        btn_export.clicked.connect(lambda: self._export("txt"))
        title_layout.addWidget(btn_export)
        btn_export_csv = QPushButton("导出 CSV")
        btn_export_csv.clicked.connect(lambda: self._export("csv"))
        title_layout.addWidget(btn_export_csv)
        btn_export_html = QPushButton("导出 HTML")
        btn_export_html.clicked.connect(lambda: self._export("html"))
        title_layout.addWidget(btn_export_html)
        btn_rerun = QPushButton("重新执行")
        btn_rerun.clicked.connect(self._rerun)
        title_layout.addWidget(btn_rerun)
        layout.addLayout(title_layout)

        # 结论摘要
        self.summary_widget = QGroupBox("结论摘要")
        summary_layout = QVBoxLayout(self.summary_widget)
        self.summary_content = QLabel("")
        self.summary_content.setWordWrap(True)
        summary_layout.addWidget(self.summary_content)
        self.compare_label = QLabel("")
        summary_layout.addWidget(self.compare_label)
        layout.addWidget(self.summary_widget)

        # 上下分屏
        splitter = QSplitter(Qt.Vertical)

        # 问题/冲突列表
        issue_group = QGroupBox("分析结果")
        issue_layout = QVBoxLayout(issue_group)
        self.issue_tree = QTreeWidget()
        self.issue_tree.setHeaderLabels(["严重度", "问题描述", "涉及设备"])
        self.issue_tree.itemClicked.connect(self._on_issue_clicked)
        issue_layout.addWidget(self.issue_tree)
        splitter.addWidget(issue_group)

        # 原始输出/证据
        evidence_group = QGroupBox("命令输出")
        ev_layout = QVBoxLayout(evidence_group)
        self.evidence_text = QTextEdit()
        self.evidence_text.setReadOnly(True)
        self.evidence_text.setPlaceholderText("点击上方问题查看原始命令输出...")
        ev_layout.addWidget(self.evidence_text)
        splitter.addWidget(evidence_group)

        splitter.setSizes([300, 300])
        layout.addWidget(splitter)

        # 返回
        btn_back = QPushButton("← 返回任务历史")
        btn_back.clicked.connect(lambda: self.main_window.navigate_to("task_history"))
        layout.addWidget(btn_back)

    # ── 数据加载 ──────────────────────────────────────

    def on_activated(self, params=None):
        if not params or "task_id" not in params:
            return
        task_id = params["task_id"]
        self._load_result(task_id)

    def _load_result(self, task_id: int):
        self._task_id = task_id
        task = self.db.get_task(task_id)
        if not task:
            QMessageBox.warning(self, "错误", f"任务不存在: {task_id}")
            return

        self.title_label.setText(f"<h3>任务结果 — {task.get('name', '')}</h3>")

        # 摘要
        status = task.get("status", "")
        status_emoji = {"completed": "✅ 通过", "completed_with_errors": "⚠ 部分失败",
                        "failed": "❌ 失败", "cancelled": "⊘ 已取消"}.get(status, status)

        summary_text = f"状态: {status_emoji}"

        result_summary = task.get("result_summary", "")
        if isinstance(result_summary, str):
            try:
                result_summary = json.loads(result_summary)
            except:
                result_summary = {}

        if isinstance(result_summary, dict):
            total = result_summary.get("total", 0)
            completed = result_summary.get("completed", 0)
            failed = result_summary.get("failed", 0)
            summary_text += f"  |  设备: {completed}/{total} 成功"
            if failed > 0:
                summary_text += f"  |  {failed} 失败"

        created = task.get("created_at", "")[:19] or "—"
        completed_at = task.get("completed_at", "")[:19] or "—"
        summary_text += f"  |  创建: {created}"
        if completed_at != "—":
            summary_text += f"  |  完成: {completed_at}"

        self.summary_content.setText(summary_text)

        # 对比上次
        self._load_compare(task)

        # 解析场景中的分析结果
        self.issue_tree.clear()

        # 尝试从文件加载详细结果
        task_dir = str(self.db.get_task_path(task_id))
        summary_path = os.path.join(task_dir, "summary.json")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                file_summary = json.load(f)
            self._load_issues_from_summary(file_summary)
        else:
            # 从数据库加载设备列表
            self._load_issues_from_task(task)

    def _load_issues_from_summary(self, summary: dict):
        """从 summary.json 构建问题树"""
        # 设备级结果
        for result in summary.get("results", []):
            status = result.get("status", "pending")
            severity = "error" if status == "failed" else "info"
            desc = f"设备 {result.get('device_ip','')} ({result.get('hostname','')}) — {status}"
            item = QTreeWidgetItem([severity, desc, result.get("device_ip", "")])

            error = result.get("error")
            if error:
                err_child = QTreeWidgetItem(["", f"错误: {error}", ""])
                item.addChild(err_child)

            for cmd in result.get("commands", []):
                cmd_status = "✓" if cmd.get("success") else "✗"
                cmd_desc = f"{cmd_status} {cmd.get('command','')}"
                output_file = cmd.get("output_file", "")
                child = QTreeWidgetItem(["", cmd_desc, output_file])
                child.setData(0, Qt.UserRole, output_file)
                item.addChild(child)

            self.issue_tree.addTopLevelItem(item)

    def _load_issues_from_task(self, task: dict):
        """从任务记录中展示设备列表"""
        device_list = task.get("device_list", "")
        if isinstance(device_list, str):
            try:
                device_list = json.loads(device_list)
            except:
                device_list = []

        for dev in device_list:
            item = QTreeWidgetItem(["", dev.get("hostname", ""), dev.get("ip", "")])
            self.issue_tree.addTopLevelItem(item)

    def _load_compare(self, task: dict):
        """加载与上次任务的对比"""
        # 查找同场景同Region的上一个任务
        rows = self.db.conn.execute("""
            SELECT id, status, result_summary, created_at FROM tasks
            WHERE scene_template_id=? AND region=? AND id < ? AND status IN ('completed','completed_with_errors')
            ORDER BY id DESC LIMIT 1
        """, (task.get("scene_template_id"), task.get("region"), task.get("id"))).fetchall()

        if rows:
            prev = dict(rows[0])
            self.compare_label.setText(
                f"对比上次 ({prev.get('created_at','')[:10]}): 状态={prev.get('status','?')}"
            )
        else:
            self.compare_label.setText("对比上次: 无历史记录")

    def _on_issue_clicked(self, item, column):
        """点击问题展开原始输出"""
        output_file = item.data(0, Qt.UserRole)
        if output_file and os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # 截断显示
            if len(content) > 100000:
                content = content[:100000] + "\n\n... (输出过长，已截断)"
            self.evidence_text.setPlainText(content)
        elif output_file:
            self.evidence_text.setPlainText(f"[文件不存在] {output_file}")

    # ── 导出 ──────────────────────────────────────────

    def _export(self, fmt: str):
        task = self.db.get_task(self._task_id) if self._task_id else None
        if not task:
            QMessageBox.warning(self, "提示", "没有可导出的结果")
            return

        file_ext = {"txt": "txt", "csv": "csv", "html": "html"}
        ext = file_ext.get(fmt, "txt")
        path, _ = QFileDialog.getSaveFileName(self, "导出结果",
                                              f"{task.get('name','result')}.{ext}",
                                              f"{ext.upper()} files (*.{ext})")
        if not path:
            return

        try:
            if fmt == "txt":
                self._export_txt(path, task)
            elif fmt == "csv":
                self._export_csv(path, task)
            elif fmt == "html":
                self._export_html(path, task)
            QMessageBox.information(self, "提示", f"已导出到：{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_txt(self, path: str, task: dict):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"任务名称: {task.get('name','')}\n")
            f.write(f"场景: {task.get('scene_template_id','')}\n")
            f.write(f"Region: {task.get('region','')}\n")
            f.write(f"状态: {task.get('status','')}\n")
            f.write(f"创建时间: {task.get('created_at','')}\n")
            f.write("=" * 60 + "\n\n")
            # 采集结果
            task_dir = str(self.db.get_task_path(self._task_id))
            summary_path = os.path.join(task_dir, "summary.json")
            if os.path.exists(summary_path):
                with open(summary_path, "r", encoding="utf-8") as sf:
                    summary = json.load(sf)
                for result in summary.get("results", []):
                    f.write(f"设备: {result.get('device_ip','')} ({result.get('hostname','')})\n")
                    f.write(f"状态: {result.get('status','')}\n")
                    f.write("-" * 40 + "\n")
                    for cmd in result.get("commands", []):
                        f.write(f"  命令: {cmd.get('command','')}\n")
                        f.write(f"  成功: {cmd.get('success','')}\n")
                        f.write(f"  输出大小: {cmd.get('size',0)} bytes\n")
                    f.write("\n")

    def _export_csv(self, path: str, task: dict):
        import csv
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["设备IP", "设备名", "状态", "命令", "成功", "输出大小"])
            task_dir = str(self.db.get_task_path(self._task_id))
            summary_path = os.path.join(task_dir, "summary.json")
            if os.path.exists(summary_path):
                with open(summary_path, "r", encoding="utf-8") as sf:
                    summary = json.load(sf)
                for result in summary.get("results", []):
                    for cmd in result.get("commands", []):
                        writer.writerow([
                            result.get("device_ip", ""),
                            result.get("hostname", ""),
                            result.get("status", ""),
                            cmd.get("command", ""),
                            cmd.get("success", ""),
                            cmd.get("size", 0),
                        ])

    def _export_html(self, path: str, task: dict):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{task.get('name','')}</title>
<style>
body {{ font-family: sans-serif; margin: 20px; }}
.device {{ border: 1px solid #ddd; margin: 10px 0; padding: 10px; }}
.success {{ color: green; }} .failed {{ color: red; }}
</style></head><body>
<h1>{task.get('name','')}</h1>
<p>场景: {task.get('scene_template_id','')} | Region: {task.get('region','')} | 状态: {task.get('status','')}</p>
<p>创建: {task.get('created_at','')}</p>
"""
        task_dir = str(self.db.get_task_path(self._task_id))
        summary_path = os.path.join(task_dir, "summary.json")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as sf:
                summary = json.load(sf)
            for result in summary.get("results", []):
                html += f"<div class='device'><h3>{result.get('hostname','')} ({result.get('device_ip','')}) — {result.get('status','')}</h3>\n"
                for cmd in result.get("commands", []):
                    cls = "success" if cmd.get("success") else "failed"
                    html += f"<p class='{cls}'>{cmd.get('command','')}: {cmd.get('size',0)} bytes</p>\n"
                if result.get("error"):
                    html += f"<p class='failed'>错误: {result['error']}</p>\n"
                html += "</div>\n"

        html += "</body></html>"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    # ── 重跑 ──────────────────────────────────────────

    def _rerun(self):
        if self._task_id:
            QMessageBox.information(self, "提示", "将使用相同参数创建新任务...")
            self.main_window.show_task_progress(self._task_id)
