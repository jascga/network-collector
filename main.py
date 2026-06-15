"""
main.py — 网络设备采集分析平台 入口

用法:
    python main.py                          # 使用默认数据库
    python main.py --db my_collector.db     # 指定数据库文件
"""
import sys
import os
import argparse
from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 确保项目根目录在 sys.path 中，方便 core 导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.db import Database
from core.crypto import init_master, load_cipher
from ui.main_window import MainWindow


class MasterPasswordDialog(QDialog):
    """主密码对话框（首次设置 / 后续解锁）"""

    def __init__(self, db_dir: str, is_first_time: bool = False):
        super().__init__()
        self.db_dir = db_dir
        self.is_first_time = is_first_time
        self.cipher = None
        self._init_ui()

    def _init_ui(self):
        if self.is_first_time:
            self.setWindowTitle("首次使用 — 设置主密码")
        else:
            self.setWindowTitle("请输入主密码")

        self.setFixedSize(400, 200)
        layout = QVBoxLayout()

        title = QLabel()
        if self.is_first_time:
            title.setText("<h3>欢迎使用网络设备采集分析平台</h3><p>请设置一个主密码，用于加密存储 SSH 私钥密码。</p>")
        else:
            title.setText("<p>请输入主密码以解锁数据库中的加密凭据：</p>")
        title.setWordWrap(True)
        layout.addWidget(title)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("输入主密码")
        layout.addWidget(self.password_input)

        if self.is_first_time:
            self.confirm_input = QLineEdit()
            self.confirm_input.setEchoMode(QLineEdit.Password)
            self.confirm_input.setPlaceholderText("确认主密码")
            layout.addWidget(self.confirm_input)

        btn_layout = QVBoxLayout()
        btn_ok = QPushButton("确 定" if self.is_first_time else "解 锁")
        btn_ok.clicked.connect(self._on_confirm)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _on_confirm(self):
        password = self.password_input.text()

        if not password:
            QMessageBox.warning(self, "提示", "密码不能为空")
            return

        if self.is_first_time:
            confirm = self.confirm_input.text()
            if password != confirm:
                QMessageBox.warning(self, "提示", "两次输入的密码不一致")
                return

        try:
            if self.is_first_time:
                self.cipher = init_master(self.db_dir, password)
            else:
                self.cipher = load_cipher(self.db_dir, password)
            self.accept()
        except FileNotFoundError:
            QMessageBox.warning(self, "提示", f"未找到加密文件，请检查数据库目录是否正确：\n{self.db_dir}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"密码验证失败：{e}")


def main():
    parser = argparse.ArgumentParser(description="网络设备采集分析平台")
    parser.add_argument("--db", default="network_collector.db", help="数据库文件路径 (默认: network_collector.db)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("网络设备采集分析平台")
    # 全局默认字体（setPointSize 自动适配 DPI）
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)

    # 确定数据库目录
    db_path = os.path.abspath(args.db)
    db_dir = os.path.dirname(db_path) or "."

    # 判断是否首次使用（检查 salt 文件）
    from core.crypto import SALT_FILE
    salt_path = os.path.join(db_dir, SALT_FILE)
    is_first_time = not os.path.exists(salt_path)

    # 主密码认证
    dialog = MasterPasswordDialog(db_dir, is_first_time)
    if dialog.exec_() != QDialog.Accepted:
        sys.exit(0)

    cipher = dialog.cipher

    # 打开数据库
    db = Database(db_path)
    try:
        db.open()
    except Exception as e:
        QMessageBox.critical(None, "错误", f"数据库打开失败：{e}")
        sys.exit(1)

    # 启动主窗口
    window = MainWindow(db, cipher)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
