"""
cli/run_task.py — CLI 任务执行入口

用法:
    python -m cli.run_task <task_id> [--db <path>] [--output <dir>]

示例:
    python -m cli.run_task 42
    python -m cli.run_task 42 --db network_collector.db
    python -m cli.run_task 42 --output /tmp/nc_out
"""
import argparse
import json
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import Database
from core.crypto import init_master, load_cipher
from core.runner import TaskRunner


def main():
    parser = argparse.ArgumentParser(description="Network Collector - CLI 任务执行器")
    parser.add_argument("task_id", type=int, help="要执行的任务 ID")
    parser.add_argument("--db", default="network_collector.db", help="数据库路径")
    parser.add_argument("--output", help="任务输出目录（默认读数据库配置）")
    parser.add_argument("--no-master-pwd", action="store_true",
                        help="跳过主密码（SSH 私钥密码无法解密，仅用于测试无加密场景）")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    db = Database(db_path)
    db.open()

    cipher = None
    if not args.no_master_pwd:
        db_dir = os.path.dirname(db_path) or "."
        from core.crypto import SALT_FILE
        salt_path = os.path.join(db_dir, SALT_FILE)
        if os.path.exists(salt_path):
            pwd = input("请输入主密码: ")
            try:
                cipher = load_cipher(db_dir, pwd)
            except Exception as e:
                print(f"[错误] 主密码验证失败: {e}")
                sys.exit(1)
        else:
            print(f"[提示] 未发现 salt 文件 ({salt_path})，跳过密码解密")

    # 校验任务存在
    task = db.get_task(args.task_id)
    if not task:
        print(f"[错误] 任务 #{args.task_id} 不存在")
        sys.exit(1)
    if not task.get("plugin_name"):
        print(f"[错误] 任务 #{args.task_id} 没有 plugin_name 字段（老格式任务）")
        sys.exit(1)

    print(f"[任务] #{args.task_id}: {task.get('name', '')}")
    print(f"       插件: {task['plugin_name']} v{task.get('plugin_version', '?')}")
    params_raw = task.get("plugin_params")
    if isinstance(params_raw, str):
        try:
            params_raw = json.loads(params_raw)
        except Exception:
            params_raw = {}
    print(f"       参数: {params_raw}")

    runner = TaskRunner(db, args.task_id,
                        output_base=args.output,
                        cipher=cipher)
    try:
        result = runner.run()
    except Exception as e:
        print(f"[失败] {e}")
        import traceback
        traceback.print_exc()
        db.update_task_status(args.task_id, "failed")
        sys.exit(1)

    print("\n========== 任务完成 ==========")
    summary = result.get("summary", {})
    for k, v in summary.items():
        print(f"  {k}: {v}")
    if result.get("error"):
        print(f"  error: {result['error']}")
    print(f"\n详细结果: {runner.task_dir / 'result.json'}")


if __name__ == "__main__":
    main()
