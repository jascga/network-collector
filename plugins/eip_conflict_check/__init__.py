"""
EIP 扩容冲突检查 — 场景插件

在 pop 分区 idr 设备和 transitx/transity 分区 cnt 设备的路由表上查询
用户输入的 EIP 网段，路由表中有匹配即视为冲突。

设备规则：
  - pop 分区，角色 idr
  - transitx 分区，角色 cnt
  - transity 分区，角色 cnt

命令（每台设备跑 2 条：basic + longer-match）：
  idr: display ip routing-table {eip_cidr}  /  display ip routing-table {eip_cidr} {eip_mask} longer-match
  cnt: display ip routing-table vpn-instance internet {eip_cidr}
       display ip routing-table vpn-instance internet {eip_cidr} {eip_mask} longer-match

冲突判断：
  - 精确匹配：路由表里存在与目标完全相同的路由条目
  - 长匹配：目标网段被更小的子网占用（路由表里有目标的真子集）
  - 包含匹配：路由表里有覆盖目标的更大网段
"""
from ipaddress import ip_network
import re
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# 1. 元数据
# ═══════════════════════════════════════════════════════════════
SCENE = {
    "name": "EIP 扩容冲突检查",
    "description": (
        "在 pop 分区 idr 设备和 transitx/transity 分区 cnt 设备的"
        "路由表中查询待扩容 EIP 网段，命中既有路由即视为冲突。"
    ),
    "version": "1.0.0",
    "icon": "⚠️",
}


# ═══════════════════════════════════════════════════════════════
# 2. 设备筛选规则（分区+角色）
# ═══════════════════════════════════════════════════════════════
DEVICE_RULES = [
    {"section_glob": "pop",      "role": "idr", "label": "POP 接入设备"},
    {"section_glob": "transitx", "role": "cnt", "label": "TransitX 核心设备"},
    {"section_glob": "transity", "role": "cnt", "label": "TransitY 核心设备"},
]


# ═══════════════════════════════════════════════════════════════
# 3. 设备→命令映射
# ═══════════════════════════════════════════════════════════════
COMMAND_MAPPING = {
    "idr": [
        "eip_check_idr_route_basic",
        "eip_check_idr_route_longer",
    ],
    "cnt": [
        "eip_check_cnt_route_basic",
        "eip_check_cnt_route_longer",
    ],
}


# ═══════════════════════════════════════════════════════════════
# 4. 插件自带命令（捆绑发布）
# ═══════════════════════════════════════════════════════════════
BUNDLED_COMMANDS = [
    {
        "name":        "eip_check_idr_route_basic",
        "cmd":         "display ip routing-table {eip_cidr}",
        "cmd_type":    "parameterized",
        "vendor":      "huawei",
        "description": "idr 设备：精确查询 EIP 网段路由",
        "parser":      "eip_check_idr_route_basic",
    },
    {
        "name":        "eip_check_idr_route_longer",
        "cmd":         "display ip routing-table {eip_cidr} {eip_mask} longer-match",
        "cmd_type":    "parameterized",
        "vendor":      "huawei",
        "description": "idr 设备：长匹配查询 EIP 网段路由",
        "parser":      "eip_check_idr_route_longer",
    },
    {
        "name":        "eip_check_cnt_route_basic",
        "cmd":         "display ip routing-table vpn-instance internet {eip_cidr}",
        "cmd_type":    "parameterized",
        "vendor":      "huawei",
        "description": "cnt 设备：internet VPN 实例精确查询",
        "parser":      "eip_check_cnt_route_basic",
    },
    {
        "name":        "eip_check_cnt_route_longer",
        "cmd":         "display ip routing-table vpn-instance internet {eip_cidr} {eip_mask} longer-match",
        "cmd_type":    "parameterized",
        "vendor":      "huawei",
        "description": "cnt 设备：internet VPN 实例长匹配查询",
        "parser":      "eip_check_cnt_route_longer",
    },
]


# ═══════════════════════════════════════════════════════════════
# 5. 输入参数定义
# ═══════════════════════════════════════════════════════════════
INPUT_PARAMS = [
    {
        "key":         "eip_input",
        "label":       "EIP 网段（单个 IP / IP 段 / 多个用逗号或换行分隔）",
        "type":        "textarea",
        "required":    True,
        "placeholder": "示例:\n1.2.3.4\n5.6.7.0/24\n10.0.0.0/16, 172.16.0.0/12",
    },
    {
        "key":      "region",
        "label":    "检查区域（Region）",
        "type":     "text",
        "required": True,
        "placeholder": "如: beijing4 / wuhu202",
    },
]


# ═══════════════════════════════════════════════════════════════
# 6. 任务创建时的 UI 渲染
# ═══════════════════════════════════════════════════════════════
def render_task_form(stage: str, context: dict) -> dict:
    if stage == "params":
        return {
            "title":       "EIP 扩容冲突检查 — 参数配置",
            "description": (
                "输入待扩容的 EIP 地址和检查区域。系统会自动：\n"
                "  • 归一化所有输入为网段格式（X.X.X.X/Y）\n"
                "  • 在 pop/idr 与 transitx,transity/cnt 设备上查询路由表\n"
                "  • 路由表中有匹配 = 冲突"
            ),
            "fields": INPUT_PARAMS,
        }
    if stage == "devices":
        devices = context.get("devices", [])
        return {
            "title":          "确认检查设备",
            "description":    f"已按规则匹配 {len(devices)} 台设备，请确认：",
            "table_columns":  ["hostname", "ip", "section", "role", "vendor"],
        }
    if stage == "commands":
        return {
            "title":        "检查命令预览",
            "description":  "将按设备角色执行以下命令（basic + longer-match 同时跑）：",
            "grouped_by":   "role",
        }


# ═══════════════════════════════════════════════════════════════
# 7. 结果布局
# ═══════════════════════════════════════════════════════════════
RESULT_LAYOUT = {
    "summary": {
        "type":   "stat_cards",
        "fields": [
            {"label": "检查设备数", "key": "device_count",     "color": "blue"},
            {"label": "查询网段数", "key": "cidr_count",       "color": "blue"},
            {"label": "冲突路由数", "key": "conflict_count",   "color": "red"},
            {"label": "涉及设备数", "key": "conflict_devices", "color": "orange"},
        ],
    },
    "issues": {
        "type":    "table",
        "columns": [
            {"label": "EIP 网段",     "key": "eip_cidr",        "width": 140},
            {"label": "冲突设备",     "key": "hostname",        "width": 160},
            {"label": "设备 IP",      "key": "device_ip",       "width": 130},
            {"label": "角色",         "key": "role",            "width": 70},
            {"label": "分区",         "key": "section",         "width": 100},
            {"label": "命中路由",     "key": "route_entries"},
            {"label": "证据文件",     "key": "evidence"},
        ],
    },
    "evidence": {
        "type": "raw_files",
        "path": "raw/{device_ip}_{command_name}.txt",
    },
}


# ═══════════════════════════════════════════════════════════════
# 8. 分析逻辑
# ═══════════════════════════════════════════════════════════════

def _expand_eip_inputs(eip_input: str) -> list:
    """把用户输入展开为 ip_network 列表。"""
    cidrs = []
    for token in re.split(r"[,\s\n]+", eip_input or ""):
        token = token.strip()
        if not token:
            continue
        try:
            cidrs.append(ip_network(token, strict=False))
        except ValueError:
            continue
    return cidrs


def analyze(task_dir: Path, parsed_data: dict, params: dict) -> dict:
    """
    parsed_data 结构（runner 注入）:
    {
        "<device_ip>": {
            "hostname": ...,
            "section":  ...,
            "role":     ...,
            "results": {
                "<command_name>": [
                    {"dest", "mask", "nexthop", "interface", "raw"}, ...
                ],
                ...
            }
        },
        ...
    }
    """
    target_cidrs = _expand_eip_inputs(params.get("eip_input", ""))

    if not target_cidrs:
        return {
            "summary": {
                "device_count":     len(parsed_data),
                "cidr_count":       0,
                "conflict_count":   0,
                "conflict_devices": 0,
            },
            "issues": [],
            "error":  "未解析到有效的 EIP 输入",
        }

    issues = []
    devices_with_conflict = set()
    total_conflicts = 0

    for device_ip, dev_data in parsed_data.items():
        # 合并该设备所有命令的路由（去重：同一 (dest, mask) 只保留一条）
        all_routes = {}   # (dest, mask) -> route
        for cmd_name, routes in (dev_data.get("results") or {}).items():
            for r in routes:
                key = (r["dest"], r["mask"])
                if key not in all_routes:
                    all_routes[key] = dict(r, command=cmd_name)

        # 遍历每个目标 EIP 段
        for cidr in target_cidrs:
            hits = []
            for (dest, mask), route in all_routes.items():
                try:
                    dest_net = ip_network(f"{dest}/{mask}", strict=False)
                except ValueError:
                    continue
                # 命中条件（三选一）：
                #   1) dest_net == cidr                   精确匹配
                #   2) dest_net.subnet_of(cidr)            目标网段被更小子网占用（长匹配命中）
                #   3) cidr.subnet_of(dest_net)            目标网段被更大网段覆盖
                if dest_net == cidr or dest_net.subnet_of(cidr) or cidr.subnet_of(dest_net):
                    hits.append(route)

            if hits:
                total_conflicts += len(hits)
                devices_with_conflict.add(device_ip)
                issues.append({
                    "eip_cidr":      str(cidr),
                    "hostname":      dev_data.get("hostname", device_ip),
                    "device_ip":     device_ip,
                    "role":          dev_data.get("role", ""),
                    "section":       dev_data.get("section", ""),
                    "route_entries": [
                        f"{r['dest']}/{r['mask']} via {r['nexthop']} ({r['interface']})"
                        for r in hits
                    ],
                    "evidence":      f"raw/{device_ip}_{hits[0]['command']}.txt",
                })

    return {
        "summary": {
            "device_count":     len(parsed_data),
            "cidr_count":       len(target_cidrs),
            "conflict_count":   total_conflicts,
            "conflict_devices": len(devices_with_conflict),
        },
        "issues": issues,
    }
