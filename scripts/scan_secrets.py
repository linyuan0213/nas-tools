"""提交前密钥扫描：命中 token/apikey/密钥模式即拦截（需人工确认后绕过）"""

import re
import sys
from pathlib import Path

# 强特征：sk- 开头密钥、显式 key/password/secret 赋值、32 位 hex 密钥、JWT
_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"(?:api[_-]?key|api_secret|access[_-]?key|secret[_-]?key|client[_-]?secret|password|passwd|token|jwt[_-]?secret)\s*[=:]\s*[\"'][^\"'\s]{8,}[\"']", re.I),
    re.compile(r"\b[a-f0-9]{32}\b"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]

# 允许占位符/示例值（非真实密钥）
_ALLOWED = {
    "test_tmdb_key", "your-api-key", "example", "changeme", "your_password",
    "xxxx", "password", "admin", "secret", "123456", "token", "api_key",
}


def _is_placeholder(name: str, value: str) -> bool:
    low = value.lower()
    if any(a in low for a in _ALLOWED) or low in {"", "''", '""', "null", "none"}:
        return True
    # 值与字段名相同（如 TMDB_API_KEY = "TMDB_API_KEY"）视为占位符
    if name and value and name.lower().strip("_") == low.strip().strip("'\""):
        return True
    return False


def scan_file(path: Path) -> list[str]:
    hits = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return hits
    for i, line in enumerate(lines, 1):
        for pat in _PATTERNS:
            for m in pat.finditer(line):
                # 提取字段名与值（尽力而为）
                before = line[: m.start()]
                name = before.split("=")[-1].split(":")[-1].strip().strip('"').strip("'")
                value = m.group(0)
                if _is_placeholder(name, value):
                    continue
                hits.append(f"{path}:{i}: {line.strip()[:120]}")
    return hits


def main() -> int:
    staged = sys.argv[1:]
    if not staged:
        return 0
    problems: list[str] = []
    for f in staged:
        p = Path(f)
        if not p.exists():
            continue
        problems.extend(scan_file(p))
    if problems:
        print("=" * 60)
        print("⚠ 提交内容疑似包含真实密钥/令牌，已拦截：")
        for p in problems:
            print(f"  - {p}")
        print("=" * 60)
        print("如确认为占位符/示例，请忽略；如为真实密钥请先在源文件中替换为占位符，")
        print("或联系用户确认后再用 git commit --no-verify 强制提交。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
