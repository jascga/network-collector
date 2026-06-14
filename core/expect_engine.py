"""
expect_engine.py — SSH 交互式会话引擎

通过 paramiko 连接堡垒机，按 expect/send 流程交互，
最终跳到目标设备，执行采集命令。
"""

import re
import time
import logging
import paramiko
from typing import Optional

logger = logging.getLogger("expect_engine")


class ExpectFlow:
    """单次 expect/send 交互"""

    def __init__(self, expect_pattern: str, send_text: str):
        self.expect_pattern = expect_pattern
        self.send_text = send_text


class VariableResolver:
    """变量解析器：将 {device_ip} 等运行时变量替换为真实值"""

    def __init__(self, variables: dict = None):
        self.variables = variables or {}

    def resolve(self, text: str) -> str:
        for key, value in self.variables.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text


class SSHExpectSession:
    """
    SSH + Expect 会话

    用法:
        session = SSHExpectSession(
            hostname="bastion.example.com",
            port=22,
            username="admin",
            key_filename="/path/to/id_rsa",
            key_password="xxx"
        )
        session.connect()
        session.run_expect_flow([
            {"expect": "Opt or ID>:", "send": "n"},
            {"expect": "Opt or ID>:", "send": "0"},
            {"expect": "Opt or ID>:", "send": "=10.0.1.1"},
            {"expect": "ID>:", "send": "0"},
        ])
        output = session.execute_command("display ip routing-table")
        session.close()
    """

    def __init__(
        self,
        hostname: str,
        port: int = 22,
        username: str = None,
        key_filename: str = None,
        key_password: str = None,
        timeout: int = 30,
    ):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.key_filename = key_filename
        self.key_password = key_password or None
        self.timeout = timeout
        self.client: Optional[paramiko.SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None
        self.buffer = ""

    def connect(self):
        """建立 SSH 连接"""
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }

        # 加载私钥
        if self.key_filename:
            try:
                key = paramiko.RSAKey.from_private_key_file(
                    self.key_filename, password=self.key_password
                )
                connect_kwargs["pkey"] = key
            except paramiko.SSHException as e:
                raise RuntimeError(f"私钥加载失败: {e}")

        try:
            self.client.connect(**connect_kwargs)
            self.channel = self.client.invoke_shell(term="vt100", width=200, height=50)
            self.channel.settimeout(self.timeout)
            logger.info(f"SSH 连接成功: {self.hostname}:{self.port}")
        except Exception as e:
            raise RuntimeError(f"SSH 连接失败: {self.hostname}:{self.port} — {e}")

    def _read_until(self, pattern: str, timeout: int = 30) -> str:
        """
        读取输出直到匹配到 expect 模式
        返回：匹配到的输出文本
        """
        deadline = time.time() + timeout
        buffer = ""

        while time.time() < deadline:
            if self.channel and self.channel.recv_ready():
                try:
                    data = self.channel.recv(65536).decode("utf-8", errors="replace")
                    buffer += data
                except:
                    break

            if pattern in buffer:
                logger.debug(f"匹配到 '{pattern}', 已收 {len(buffer)} 字符")
                return buffer

            time.sleep(0.1)

        # 超时，返回已收内容
        logger.warning(f"expect 超时：等待 '{pattern}' {timeout}s，已收 {len(buffer)} 字符")
        return buffer

    def send(self, text: str):
        """发送命令（自动补换行符）"""
        if self.channel:
            self.channel.send(text + "\n")
            logger.debug(f"发送: {text}")
            time.sleep(0.3)  # 等待设备响应

    def run_expect_flow(self, flow: list, variables: dict = None) -> str:
        """
        执行 expect/send 流程

        参数:
            flow: [{"expect": "看到什么", "send": "发什么"}, ...]
            variables: 运行时变量，如 {"device_ip": "10.0.1.1"}

        返回: 最终输出
        """
        resolver = VariableResolver(variables)

        for step in flow:
            expect_text = step.get("expect", "")
            send_text = resolver.resolve(step.get("send", ""))

            output = self._read_until(expect_text)
            self.send(send_text)

        # 最后等待一下，收尾输出
        time.sleep(0.5)
        final_output = ""
        if self.channel:
            while self.channel.recv_ready():
                try:
                    final_output += self.channel.recv(65536).decode("utf-8", errors="replace")
                except:
                    break
        return final_output

    def execute_command(self, command: str, cmd_timeout: int = 60) -> str:
        """
        在设备上执行命令并返回输出

        参数:
            command: 要执行的命令
            cmd_timeout: 命令超时秒数

        返回: 命令输出文本
        """
        self.channel.send(command + "\n")
        logger.info(f"执行命令: {command}")

        deadline = time.time() + cmd_timeout
        output = ""

        while time.time() < deadline:
            if self.channel and self.channel.recv_ready():
                try:
                    data = self.channel.recv(65536).decode("utf-8", errors="replace")
                    output += data
                except:
                    break
            else:
                time.sleep(0.1)

        return output.strip()

    def close(self):
        """关闭 SSH 连接"""
        if self.channel:
            try:
                self.channel.close()
            except:
                pass
        if self.client:
            try:
                self.client.close()
            except:
                pass
        logger.info("SSH 连接已关闭")
