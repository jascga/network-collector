"""
cli/list_scenes.py — 列出已安装的场景插件

用法:
    python -m cli.list_scenes
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scene_registry import get_registry


def main():
    reg = get_registry()
    scenes = reg.list_scenes()
    if not scenes:
        print("[提示] 未发现任何场景插件")
        return
    print(f"已安装 {len(scenes)} 个场景插件:\n")
    for s in scenes:
        print(f"  {s.icon} {s.display_name}  ({s.name} v{s.version})")
        print(f"     {s.description[:80]}{'...' if len(s.description) > 80 else ''}")
        print(f"     设备规则: {len(s.device_rules)} 条")
        print(f"     命令: {sum(len(v) for v in s.command_mapping.values())} 条")
        print()


if __name__ == "__main__":
    main()
