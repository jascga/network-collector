"""
parsers 包 — 命令解析器集合

每个解析器对应一条命令（1对1 绑定，通过 commands.parser 字段查找）。
解析器入口固定为 parse(raw_output, params=None) -> list[dict]。
"""
