"""
parser_loader.py — 解析器加载器

按解析器名加载 parsers/ 下的模块，约定入口函数：
    parse(raw_output: str, params: dict = None) -> list[dict]
"""
import importlib
from typing import Optional, Callable


def load_parser(parser_name: str) -> Optional[Callable]:
    """根据解析器名加载 parse 函数。

    返回 None 表示加载失败（调用方需自行降级）。
    """
    if not parser_name:
        return None
    try:
        mod = importlib.import_module(f"parsers.{parser_name}")
        fn = getattr(mod, "parse", None)
        if fn is None:
            print(f"[ParserLoader] 解析器 {parser_name} 缺少 parse() 函数")
        return fn
    except Exception as e:
        print(f"[ParserLoader] 加载解析器失败 {parser_name}: {e}")
        return None
