"""插件包审计器 — 安装前多级静态门禁（SAST 骨架）

输入：插件 zip 字节 + 期望 sha256。
执行：大小/类型 → 解压安全（路径穿越/符号链接）→ 文件白名单 → 代码禁 API 扫描 → 密钥模式扫描。
输出统一扫描报告：passed + findings[{severity, rule, file}]，block 级命中即不通过。
"""

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# 单包大小与解压限制
MAX_PACKAGE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_FILES = 1000
MAX_TOTAL_BYTES = 300 * 1024 * 1024

# 解压后允许的文件扩展名（前端/后端/配置/资源）
_ALLOWED_EXTENSIONS = {
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".vue",
    ".ts",
    ".json",
    ".css",
    ".html",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".ttf",
    ".woff",
    ".woff2",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".xml",
    ".zip",
}

# 禁 API / 危险行为（按行扫描，命中即 block）
_BANNED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("eval/exec/compile", re.compile(r"\b(eval|exec|compile)\s*\(")),
    ("dynamic_import", re.compile(r"(__import__|importlib\.import_module)\s*\(")),
    ("unsafe_pickle", re.compile(r"pickle\.loads?\s*\(")),
    ("shell_exec", re.compile(r"\b(subprocess|os\.system|os\.popen|commands\.getoutput)\b")),
    ("raw_socket", re.compile(r"\b(import\s+socket|from\s+socket\s+import)")),
    ("file_wipe", re.compile(r"shutil\.rmtree\s*\(|os\.remove\s*\(|os\.unlink\s*\(")),
    ("base64_decode_run", re.compile(r"base64\.b64decode\s*\([^)]*\)\s*\.\s*(decode|run|exec)")),
]

# 密钥 / 令牌模式（文本级，命中即 block，复用 scan_secrets 同源思路）
_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_.\-]{16,}"),
    re.compile(r"(api[_-]?key|access[_-]?key|client[_-]?secret|password|passwd)\s*[:=]\s*[\"'][^\"']{12,}[\"']", re.I),
    re.compile(r"(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|-----BEGIN.*PRIVATE KEY-----)"),
]


@dataclass
class Finding:
    severity: str  # block | warn
    rule: str
    file: str = ""
    detail: str = ""


@dataclass
class AuditReport:
    passed: bool = False
    findings: list[Finding] = field(default_factory=list)
    sha256_ok: bool = False
    package_size: int = 0
    file_count: int = 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "sha256_ok": self.sha256_ok,
            "package_size": self.package_size,
            "file_count": self.file_count,
            "findings": [
                {"severity": f.severity, "rule": f.rule, "file": f.file, "detail": f.detail} for f in self.findings
            ],
        }


class PluginPackageAuditor:
    """插件包静态审计器"""

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def audit_bytes(self, data: bytes, expected_sha256: str | None = None) -> AuditReport:
        report = AuditReport(
            package_size=len(data),
            sha256_ok=not expected_sha256 or self.sha256(data) == expected_sha256,
        )
        if expected_sha256 and not report.sha256_ok:
            report.findings.append(Finding("block", "sha256_mismatch", "", "包哈希与索引声明不一致"))
        if len(data) > MAX_PACKAGE_SIZE:
            report.findings.append(Finding("block", "package_too_large", "", "包超过 50MB 限制"))
            report.passed = not any(f.severity == "block" for f in report.findings)
            return report
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                self._scan_archive(zf, report)
        except zipfile.BadZipFile as e:
            report.findings.append(Finding("block", "bad_zip", "", str(e)))
        report.passed = not any(f.severity == "block" for f in report.findings)
        return report

    def _scan_archive(self, zf: zipfile.ZipFile, report: AuditReport) -> None:
        infos = zf.infolist()
        if len(infos) > MAX_FILES:
            report.findings.append(Finding("block", "too_many_files", "", f"文件数超限（{len(infos)}>{MAX_FILES}）"))
            return
        total = 0
        for info in infos:
            total += info.file_size
        if total > MAX_TOTAL_BYTES:
            report.findings.append(Finding("block", "unpacked_too_large", "", "解压后体积超限"))
            return
        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            if name.startswith("/") or ".." in pure.parts or pure.is_absolute():
                report.findings.append(Finding("block", "path_traversal", name, "非法路径"))
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:  # symlink
                report.findings.append(Finding("block", "symlink", name, "不允许符号链接"))
                continue
            ext = Path(name).suffix.lower()
            if info.is_dir() or not ext:
                continue
            if ext not in _ALLOWED_EXTENSIONS:
                report.findings.append(Finding("block", "disallowed_file_type", name, f"不允许的文件类型: {ext}"))
                continue
            try:
                content = zf.read(info)
            except Exception as e:  # noqa: BLE001
                report.findings.append(Finding("block", "unreadable", name, str(e)))
                continue
            report.file_count += 1
            for finding in self._scan_content(name, content):
                report.findings.append(finding)

    def _scan_content(self, file_name: str, content: bytes) -> list[Finding]:
        findings: list[Finding] = []
        text = content.decode("utf-8", errors="ignore")
        if file_name.endswith((".py", ".pyi")):
            for rule, pattern in _BANNED_PATTERNS:
                if pattern.search(text):
                    findings.append(Finding("block", rule, file_name, "命中禁用 API 模式"))
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(Finding("block", "secret_leak", file_name, "检测到疑似密钥/令牌文本"))
        # JSON 必须是合法对象
        if file_name.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as e:
                findings.append(Finding("block", "invalid_json", file_name, str(e)))
        return findings
