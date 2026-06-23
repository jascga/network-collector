"""
cli/create_task.py — 创建任务（CLI 版）

用法:
    python -m cli.create_task <plugin_name> --name <task_name> --region <region> \\
                                --eip <eip_input> [--db <path>]
示例:
    python -m cli.create_task eip_conflict_check \\
        --name "测试任务" --region wuhu202 --eip "1.2.3.0/24, 5.6.7.8"
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import Database
from core.scene_registry import get_registry


def main():
    parser = argparse.ArgumentParser(description="创建 EIP 冲突检查任务")
    parser.add_argument("plugin_name", help="场景插件名（如 eip_conflict_check）")
    parser.add_argument("--name", required=True, help="任务名称")
    parser.add_argument("--region", required=True, help="检查区域")
    parser.add_argument("--eip", required=True, help="EIP 输入")
    parser.add_argument("--db", default="network_collector.db", help="数据库路径")
    args = parser.parse_args()

    scene = get_registry().get(args.plugin_name)
    if not scene:
        print(f"[错误] 插件不存在: {args.plugin_name}")
        print("可用插件:", [s.name for s in get_registry().list_scenes()])
        sys.exit(1)

    db = Database(os.path.abspath(args.db))
    db.open()

    params = {
        "region":   args.region,
        "eip_input": args.eip,
    }

    # 写入数据库
    cur = db.conn.execute("""
        INSERT INTO tasks
            (name, plugin_name, plugin_version, plugin_params, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (
        args.name,
        scene.name,
        scene.version,
        json.dumps(params, ensure_ascii=False),
        __import__("datetime").datetime.now().isoformat(),
    ))
    db.conn.commit()
    task_id = cur.lastrowid
    print(f"[成功] 任务已创建: #{task_id}")
    print(f"       名称: {args.name}")
    print(f"       插件: {scene.name} v{scene.version}")
    print(f"       参数: {params}")
    print(f"\n接下来执行: python -m cli.run_task {task_id}")


if __name__ == "__main__":
    main()
