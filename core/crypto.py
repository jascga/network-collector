"""
crypto.py — AES 加密工具

用于加密存储 SSH 私钥密码。
密钥来自用户设定的主密码（首次使用时设置）。
"""

import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# ── 常量 ──────────────────────────────────────────────
SALT_FILE = "master.salt"  # 盐值文件，跟数据库放一起


def _derive_key(master_password: str, salt: bytes) -> bytes:
    """用 PBKDF2 从主密码派生出 AES 密钥"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))


def init_master(db_dir: str, master_password: str):
    """首次初始化：生成盐值并返回加密器"""
    salt = os.urandom(16)
    with open(os.path.join(db_dir, SALT_FILE), "wb") as f:
        f.write(salt)
    key = _derive_key(master_password, salt)
    return Fernet(key)


def load_cipher(db_dir: str, master_password: str):
    """加载已有盐值，返回加密器"""
    salt_path = os.path.join(db_dir, SALT_FILE)
    if not os.path.exists(salt_path):
        raise FileNotFoundError(f"未找到盐值文件: {salt_path}，请先初始化")
    with open(salt_path, "rb") as f:
        salt = f.read()
    key = _derive_key(master_password, salt)
    return Fernet(key)


def encrypt(cipher: Fernet, plaintext: str) -> str:
    """加密明文 → 返回 base64 密文字符串"""
    return cipher.encrypt(plaintext.encode()).decode()


def decrypt(cipher: Fernet, ciphertext: str) -> str:
    """解密密文 → 返回明文字符串"""
    return cipher.decrypt(ciphertext.encode()).decode()
