"""
web_collector.py — Web 系统信息采集器（IP管理系统等）

用于 network-collector 平台，在 Windows 端运行。
支持两种模式：
  1. API 直调模式（推荐）：抓取 SPA 后端 API 请求，直接用 requests 调
  2. 浏览器模式（兜底）：Playwright 控制浏览器操作

用法：
    # API 模式
    wc = WebCollector(mode="api")
    wc.login(url="http://ipam.company.com", username="admin", password="xxx")
    result = wc.query_ip("10.0.0.100")
    
    # 浏览器模式
    wc = WebCollector(mode="browser")
    result = wc.query_ip("10.0.0.100", {
        "url": "http://ipam.company.com",
        "username": "admin",
        "password": "xxx",
        "login_url": "/#/login",
        "search_url": "/#/search",
        "ip_input_selector": "#ipInput",
        "search_btn_selector": "#searchBtn",
        "result_selector": "#resultTable"
    })
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Optional


# ============================================================
# 数据模型
# ============================================================

@dataclass
class IPQueryResult:
    """IP 查询结果"""
    ip: str
    status: str            # 已分配 / 未分配 / 冲突
    owner: str             # 归属人/部门
    device: str            # 绑定设备
    description: str       # 描述/用途
    segment: str           # 所属网段
    raw: str               # 原始数据


# ============================================================
# 模式一：API 直调（推荐）
# ============================================================

class APICollector:
    """
    SPA 后端 API 直调模式。
    需要先通过 F12 → Network 抓包，找到实际的 API 接口。
    """
    
    def __init__(self):
        self.session = None
        self.base_url = ""
        self.api_conf = {
            "login": "",     # 登录 API，如 /api/auth/login
            "query": "",     # 查询 API，如 /api/ip/query
        }
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
    
    def configure(self, base_url: str, login_api: str, query_api: str,
                  auth_type: str = "cookie", extra_headers: dict = None):
        """
        配置 API 接口路径。
        
        参数说明：
        - base_url: IP管理系统根地址，如 http://ipam.company.com:8080
        - login_api: 登录 API 路径，如 /api/auth/login 或 /api/v1/login
        - query_api: 查询 API 路径，如 /api/ip/query 或 /api/v1/ip/search
        - auth_type: 认证方式，"cookie" 或 "token" 或 "basic"
        - extra_headers: 额外的请求头（如 X-Requested-With 等）
        
        如何获取这些路径？
        1. 打开 IP 管理系统网页
        2. F12 → Network（网络）标签
        3. 点登录 → 看发到哪个 URL → 那个就是 login_api
        4. 查询一个 IP → 看发到哪个 URL → 那个就是 query_api
        5. 查看请求头 → 确认 auth_type（是否有 Authorization header）
        """
        import requests
        
        self.base_url = base_url.rstrip("/")
        self.api_conf["login"] = login_api
        self.api_conf["query"] = query_api
        self.auth_type = auth_type
        
        if extra_headers:
            self.headers.update(extra_headers)
        
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def login(self, username: str, password: str, extra_data: dict = None):
        """
        登录 IP 管理系统。
        
        extra_data: 额外的登录参数（如验证码、rememberMe 等）
        """
        if not self.session:
            raise RuntimeError("请先调用 configure()")
        
        data = {"username": username, "password": password}
        if extra_data:
            data.update(extra_data)
        
        url = f"{self.base_url}{self.api_conf['login']}"
        resp = self.session.post(url, json=data, timeout=10)
        
        if resp.status_code != 200:
            raise RuntimeError(f"登录失败 (HTTP {resp.status_code}): {resp.text[:200]}")
        
        # 判断认证方式
        if self.auth_type == "token":
            # 从返回的 JSON 中提取 token
            token_data = resp.json()
            token = token_data.get("token") or token_data.get("data", {}).get("token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        print(f"[WebCollector] 登录成功: {url}")
        return resp.json()
    
    def query_ip(self, ip: str, query_params: dict = None) -> list[IPQueryResult]:
        """查询 IP 信息。query_params 为额外的查询参数。"""
        if not self.session:
            raise RuntimeError("请先 login()")
        
        params = {"ip": ip, "keyword": ip}
        if query_params:
            params.update(query_params)
        
        url = f"{self.base_url}{self.api_conf['query']}"
        
        # 有些 API 用 GET 参数，有些用 POST body
        # 先尝试 GET
        try:
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 405:
                # 405 Method Not Allowed → 换 POST
                resp = self.session.post(url, json=params, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"查询失败: {e}")
        
        data = resp.json()
        
        # 解析结果（不同 API 返回格式不同，需要适配）
        return self._parse_response(data, ip)
    
    def _parse_response(self, data: dict, query_ip: str) -> list[IPQueryResult]:
        """
        解析 API 返回数据。
        这是最需要根据实际 API 返回格式来修改的地方！
        
        常见格式示例：
        { "code": 0, "data": [{ "ip": "10.0.0.1", "owner": "张三", ... }] }
        { "status": "ok", "result": { "ip": "10.0.0.1", ... } }
        [{ "ip": "10.0.0.1", ... }]
        """
        results = []
        
        # 兼容多种 JSON 结构
        raw_list = []
        if isinstance(data, list):
            raw_list = data
        elif isinstance(data, dict):
            # 尝试从常见字段提取数据列表
            for key in ["data", "result", "results", "rows", "list", "items"]:
                if key in data and isinstance(data[key], list):
                    raw_list = data[key]
                    break
            if not raw_list:
                # 单条结果
                raw_list = [data]
        
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            result = IPQueryResult(
                ip=item.get("ip") or item.get("address") or item.get("host") or query_ip,
                status=item.get("status") or item.get("state") or "未知",
                owner=item.get("owner") or item.get("user") or item.get("department") or "",
                device=item.get("device") or item.get("hostname") or item.get("name") or "",
                description=item.get("description") or item.get("remark") or item.get("memo") or "",
                segment=item.get("segment") or item.get("subnet") or item.get("network") or "",
                raw=json.dumps(item, ensure_ascii=False),
            )
            results.append(result)
        
        return results


# ============================================================
# 模式二：Playwright 浏览器自动化（兜底）
# ============================================================

class BrowserCollector:
    """
    浏览器全自动化模式。
    适用于：SPA 页面加密/混淆严重，无法直接调 API。
    
    前置条件：pip install playwright && playwright install chromium
    """
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
    
    def query_ip(self, ip: str, config: dict) -> list[IPQueryResult]:
        """
        浏览器自动查询 IP。
        
        config 参数（需要你根据实际页面填）：
        {
            "url": "http://ipam.company.com",      # 系统地址
            "username": "admin",                     # 用户名
            "password": "xxx",                       # 密码
            "login_url": "/#/login",                 # 登录页路径
            "search_url": "/#/search",               # 查询页路径
            "ip_input_selector": "#ipInput",          # IP输入框 CSS选择器
            "search_btn_selector": "#searchBtn",      # 查询按钮 CSS选择器
            "result_selector": "#resultTable",        # 结果表格 CSS选择器
            "wait_after_login": 2,                    # 登录后等待秒数
            "wait_after_search": 2,                   # 查询后等待秒数
        }
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError("需要安装 playwright: pip install playwright && playwright install chromium")
        
        results = []
        base = config.get("url", "").rstrip("/")
        
        with sync_playwright() as p:
            # 启动浏览器
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            
            try:
                # 第一步：登录
                login_url = base + config.get("login_url", "/login")
                print(f"[BrowserCollector] 访问登录页: {login_url}")
                page.goto(login_url, timeout=30000)
                page.wait_for_load_state("networkidle")
                
                page.fill(config.get("username_selector", "#username"),
                         config.get("username", ""))
                page.fill(config.get("password_selector", "#password"),
                         config.get("password", ""))
                
                login_btn = config.get("login_btn_selector", "#loginBtn")
                page.click(login_btn)
                page.wait_for_timeout(config.get("wait_after_login", 2000))
                
                # 第二步：导航到查询页
                search_url = base + config.get("search_url", "/search")
                print(f"[BrowserCollector] 访问查询页: {search_url}")
                page.goto(search_url, timeout=30000)
                page.wait_for_load_state("networkidle")
                
                # 第三步：输入 IP 查询
                ip_selector = config.get("ip_input_selector", "#ipInput")
                page.fill(ip_selector, ip)
                
                search_btn = config.get("search_btn_selector", "#searchBtn")
                page.click(search_btn)
                page.wait_for_timeout(config.get("wait_after_search", 2000))
                
                # 第四步：等待结果出现
                result_selector = config.get("result_selector", "#resultTable")
                try:
                    page.wait_for_selector(result_selector, timeout=10000)
                except:
                    print(f"[BrowserCollector] 未找到结果选择器 '{result_selector}'，尝试获取页面全部内容")
                
                # 第五步：提取数据
                page.wait_for_timeout(1000)
                html = page.content()
                results = self._extract_data(html, ip)
                
            finally:
                browser.close()
        
        return results
    
    def _extract_data(self, html: str, query_ip: str) -> list[IPQueryResult]:
        """
        从 HTML 中提取查询结果。
        需要根据实际页面结构修改。
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        
        # 尝试从表格提取
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # 跳过表头
                cells = row.find_all("td")
                if len(cells) >= 3:
                    result = IPQueryResult(
                        ip=cells[0].get_text(strip=True) if len(cells) > 0 else query_ip,
                        status=cells[1].get_text(strip=True) if len(cells) > 1 else "",
                        owner=cells[2].get_text(strip=True) if len(cells) > 2 else "",
                        device=cells[3].get_text(strip=True) if len(cells) > 3 else "",
                        description=cells[4].get_text(strip=True) if len(cells) > 4 else "",
                        segment="",
                        raw=row.prettify(),
                    )
                    results.append(result)
        
        # 如果没找到表格，返回整页文本
        if not results:
            results.append(IPQueryResult(
                ip=query_ip,
                status="未知",
                owner="",
                device="",
                description="",
                segment="",
                raw=soup.get_text("\n", strip=True)[:1000],
            ))
        
        return results


# ============================================================
# 统一入口
# ============================================================

class WebCollector:
    """
    Web 系统采集器统一入口。
    mode="api" → 直调后端 API（推荐，先 F12 抓接口）
    mode="browser" → 浏览器自动化
    """
    
    def __init__(self, mode: str = "api"):
        self.mode = mode
        if mode == "api":
            self._impl = APICollector()
        elif mode == "browser":
            self._impl = BrowserCollector()
        else:
            raise ValueError(f"未知模式: {mode}")
    
    @property
    def impl(self):
        return self._impl
    
    def query_ip(self, ip: str, **kwargs) -> list[IPQueryResult]:
        if self.mode == "api":
            return self._impl.query_ip(ip, kwargs.get("query_params"))
        else:
            return self._impl.query_ip(ip, kwargs)
    
    @staticmethod
    def auto_detect(base_url: str, username: str, password: str) -> "WebCollector":
        """
        自动检测：先尝试 API 模式，失败后推荐使用浏览器模式。
        使用前需要先确认 query_api 路径。
        """
        print("[WebCollector] 推荐先 F12 → Network 抓到 API 路径")
        print("  1. 登录时发的请求路径 → login_api")
        print("  2. 查询时发的请求路径 → query_api")
        print("  3. 确认后调用 configure() 配置")
        return WebCollector(mode="api")


# ============================================================
# 使用示例
# ============================================================

if __name__ == "__main__":
    # 示例：API 模式
    # ==============
    # wc = WebCollector(mode="api")
    # wc.impl.configure(
    #     base_url="http://ipam.company.com:8080",
    #     login_api="/api/auth/login",
    #     query_api="/api/ip/query",
    #     auth_type="token",
    # )
    # wc.impl.login("admin", "password123")
    # results = wc.query_ip("10.0.0.100")
    # for r in results:
    #     print(f"{r.ip} | {r.status} | {r.owner} | {r.device}")
    
    # 示例：浏览器模式
    # ================
    # wc = WebCollector(mode="browser")
    # results = wc.query_ip("10.0.0.100", {
    #     "url": "http://ipam.company.com:8080",
    #     "username": "admin",
    #     "password": "xxx",
    #     "login_url": "/#/login",
    #     "search_url": "/#/ip/search",
    #     "ip_input_selector": "input[placeholder='请输入IP地址']",
    #     "search_btn_selector": "button:has-text('查询')",
    #     "result_selector": "table",
    # })
    pass
