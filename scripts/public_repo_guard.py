from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TOP_LEVEL = {
    ".env", "artifacts", ".staging", ".sidecars", ".venv", "logs",
    "workspace", "handoff", "_installed", "_authoritative",
}
FORBIDDEN_NAME_PATTERNS = [
    re.compile(r"^cookies(?:-journal)?$", re.I),
    re.compile(r"^trust tokens(?:-journal)?$", re.I),
    re.compile(r"^device bound sessions(?:-journal)?$", re.I),
    re.compile(r"^vpn tokens(?:-journal)?$", re.I),
    re.compile(r"^session_", re.I),
    re.compile(r"\.(?:pem|pfx|key)$", re.I),
]
CONTENT_RULES = [
    ("ABSOLUTE_WINDOWS_USER_PATH", re.compile(r"[A-Za-z]:\\Users\\[^\\\r\n]+\\")),
    ("ABSOLUTE_LOCAL_RUNTIME_PATH", re.compile(r"AppData\\Local\\UniversalRuntime", re.I)),
    ("WEBCODEX_SESSION_ID", re.compile(r"wc_sess_[A-Za-z0-9_]+")),
    ("WEBCODEX_CLIENT_ID", re.compile(r"desktop-[A-Za-z0-9_-]{8,}")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("OPENAI_STYLE_SECRET", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("BEARER_LITERAL", re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}")),
]
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".md", ".json", ".yaml", ".yml", ".toml",
    ".ps1", ".txt", ".csv", ".html", ".css", ".sh", ".patch",
}

findings: list[str] = []
for name in FORBIDDEN_TOP_LEVEL:
    if (ROOT / name).exists():
        findings.append(f"FORBIDDEN_TOP_LEVEL:{name}")

for path in ROOT.rglob("*"):
    if ".git" in path.parts or path.is_dir():
        continue
    rel = path.relative_to(ROOT).as_posix()
    if path.stat().st_size > 5 * 1024 * 1024:
        findings.append(f"LARGE_FILE:{rel}")
    if any(rx.search(path.name) for rx in FORBIDDEN_NAME_PATTERNS):
        findings.append(f"SENSITIVE_NAME:{rel}")
    if path.suffix.lower() not in TEXT_SUFFIXES:
        continue
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        findings.append(f"NON_UTF8_TEXT:{rel}")
        continue
    for label, rx in CONTENT_RULES:
        if rx.search(content):
            findings.append(f"{label}:{rel}")

if findings:
    for item in sorted(set(findings)):
        print(item)
    raise SystemExit(1)

count = sum(1 for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts)
print(f"PUBLIC_REPO_GUARD=PASS files={count}")
