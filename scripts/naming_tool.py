#!/usr/bin/env python3
"""
命名模式库维护工具

用法:
  uv run python scripts/naming_tool.py test "标题"   # 测试标题命中哪条规则及提取结果
  uv run python scripts/naming_tool.py check         # 校验规则库（编译/重复名/命名组）
  uv run python scripts/naming_tool.py misses [-n N] # 查看最近 N 条识别失败样本
"""

import argparse
import json
import os
import sys
import tempfile

# 必须在导入项目模块前设置，避免初始化真实数据库
os.environ.setdefault("NEXUS_MEDIA_CONFIG", os.path.join(tempfile.gettempdir(), "nexus_media_tool_config.yaml"))
os.environ.setdefault("DATABASE__TYPE", "sqlite")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.media.parser.naming_patterns import _PATTERN_FIELDS, NamingPatternLibrary  # noqa: E402


def cmd_test(library: NamingPatternLibrary, title: str) -> int:
    hit = library.apply(title)
    if not hit:
        print(f"未命中任何规则: {title}")
        return 1
    print(f"命中规则: {hit['rule']}")
    for k in _PATTERN_FIELDS:
        if hit.get(k) is not None:
            print(f"  {k}: {hit[k]}")
    return 0


def cmd_check(library: NamingPatternLibrary) -> int:
    rules = library.rules
    if not rules:
        print("规则库为空或加载失败")
        return 1
    ok = True
    names = set()
    for rule in rules:
        if rule.name in names:
            print(f"[错误] 规则名重复: {rule.name}")
            ok = False
        names.add(rule.name)
        groups = set(rule.pattern.groupindex)
        unknown = groups - set(_PATTERN_FIELDS)
        if unknown:
            print(f"[警告] 规则 '{rule.name}' 含未支持的命名组: {unknown}")
        if not groups & {"cn_name", "en_name"}:
            print(f"[警告] 规则 '{rule.name}' 未提取任何名称（cn_name/en_name）")
    print(f"共 {len(rules)} 条规则，校验{'通过' if ok else '存在错误'}")
    return 0 if ok else 1


def cmd_misses(count: int) -> int:
    from app.core.settings import settings

    path = os.path.join(settings.data_path, "identify_misses.jsonl")
    if not os.path.exists(path):
        print(f"暂无失败样本: {path}")
        return 0
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-count:]
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        print(f"{rec.get('ts')} [{rec.get('reason')}] ({rec.get('site')}) {rec.get('title')}")
    print(f"共显示 {len(lines)} 条，文件: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="命名模式库维护工具")
    sub = parser.add_subparsers(dest="command", required=True)
    p_test = sub.add_parser("test", help="测试标题命中规则")
    p_test.add_argument("title")
    sub.add_parser("check", help="校验规则库")
    p_miss = sub.add_parser("misses", help="查看识别失败样本")
    p_miss.add_argument("-n", type=int, default=20)
    args = parser.parse_args()

    if args.command == "misses":
        return cmd_misses(args.n)
    library = NamingPatternLibrary()
    if args.command == "test":
        return cmd_test(library, args.title)
    return cmd_check(library)


if __name__ == "__main__":
    sys.exit(main())
