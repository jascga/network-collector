"""
idr 设备 — display ip routing-table {网段} {掩码} longer-match 输出解析

华为 VRP 长匹配查询输出格式与 basic 相同，但只返回比目标更具体（更小子网）的路由。
"""
import re

ROUTE_LINE_RE = re.compile(
    r"^\s*(\d+\.\d+\.\d+\.\d+)/(\d+)\s+\S+\s+\d+\s+\d+\s+\S+\s+(\S+)\s+(\S+)"
)


def parse(raw_output: str, params: dict = None) -> list:
    """解析长匹配查询的路由表输出。

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
