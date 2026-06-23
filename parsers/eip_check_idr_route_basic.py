"""
idr 设备 — display ip routing-table {网段} 输出解析

华为 VRP 标准格式（精确查询）：
    Destination/Mask    Proto   Pre  Cost  Flags NextHop    Interface
    1.2.3.0/24          Static  60   0     D     10.0.1.1   Vlanif10
    5.6.7.0/24          OSPF    10   2     D    192.168.1.1  GE0/0/1
"""
import re

ROUTE_LINE_RE = re.compile(
    r"^\s*(\d+\.\d+\.\d+\.\d+)/(\d+)\s+\S+\s+\d+\s+\d+\s+\S+\s+(\S+)\s+(\S+)"
)


def parse(raw_output: str, params: dict = None) -> list:
    """解析精确查询的路由表输出。

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
