"""
cnt 设备 — display ip routing-table vpn-instance internet {网段} 输出解析

VPN 实例下的路由表，输出格式与公网一致，但只显示该 VPN 内的路由。
"""
import re

ROUTE_LINE_RE = re.compile(
    r"^\s*(\d+\.\d+\.\d+\.\d+)/(\d+)\s+\S+\s+\d+\s+\d+\s+\S+\s+(\S+)\s+(\S+)"
)


def parse(raw_output: str, params: dict = None) -> list:
    """解析 internet VPN 实例下的精确查询路由表输出。

    返回: [{"dest", "mask", "nexthop", "interface", "raw"}, ...]
    """
    routes = []
    for line in (raw_output or "").splitlines():
        m = ROUTE_LINE_RE.match(line)
        if m:
            routes.append({
                "dest":      m.group(1),
                "mask":      int(m.group(2)),
                "nexthop":   m.group(3),
                "interface": m.group(4),
                "raw":       line.strip(),
            })
    return routes
