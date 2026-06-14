"""
Shared security constants and validation — 所有工具模块共享的单一真理源。

消除 builtin/base.py、tools/command.py、tools/file_ops.py 之间的安全常量重复。
"""

from __future__ import annotations

# ── 文件大小限制 ──
MAX_READ_SIZE = 2 * 1024 * 1024      # 2MB
MAX_WRITE_SIZE = 10 * 1024 * 1024    # 10MB
MAX_VERIFY_SIZE = 1 * 1024 * 1024    # 1MB

# ── 系统敏感路径黑名单 ──
SENSITIVE_PATHS = [
    "c:\\windows", "c:\\program files", "c:\\programdata",
    "/etc", "/usr", "/bin", "/sbin", "/boot", "/dev", "/proc", "/sys",
    "/var/log", "/root/.ssh", "/root/.gnupg",
]

# ── 用户敏感文件黑名单 ──
USER_SENSITIVE = [
    ".ssh", ".gnupg", ".aws", ".azure", ".config/gh",
    ".docker/config.json", "credentials", "id_rsa", "id_ed25519",
]

# ── 危险命令模式 ──
DANGEROUS_CMD_PATTERNS = [
    r"rm\s+(-[rfR]+\s+)?/", r"rm\s+(-[rfR]+\s+)?~",
    r"rmdir\s+/", r"del\s+/[sfq]\s+[a-zA-Z]:\\",
    r"del\s+/[sfq]\s+C:\\",
    r"\bformat\s+[a-zA-Z]:", r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b",
    r"curl.*\|\s*(?:bash|sh|python|node)",
    r"wget.*\|\s*(?:bash|sh|python|node)",
    r"Remove-Item\s+-[rR].*C:\\", r"Format-Volume",
    r"Clear-RecycleBin\s+-Force",
    r"\bchmod\s+777\b", r"\bchown\b.*root",
]

# ── 危险 Git 命令 ──
DANGEROUS_GIT_PATTERNS = [
    "push --force", "push -f", "reset --hard",
    "clean -fd", "clean -fXd", "checkout -- .",
    "branch -D", "reflog expire --all",
]

# ── 参数别名映射（LLM 常用 → 标准参数名）──
PARAM_ALIASES: dict[str, list[str]] = {
    "file_path":      ["path", "dir", "directory", "folder", "filepath", "file", "target"],
    "action":         ["command", "cmd", "shell", "exec", "run", "execute"],
    "content":        ["text", "data", "body", "value"],
    "search_pattern": ["query", "keyword", "term", "search"],
    "file_filter":    ["filter", "glob", "filetype", "ext", "extension"],
    "old_text":       ["old", "find", "search_text", "before", "original"],
    "new_text":       ["new", "replace", "replace_text", "after", "replacement"],
    "git_command":    ["subcommand", "git_cmd", "git_subcmd"],
    "url":            ["uri", "link", "href"],
    "symbol":         ["name", "func", "function_name", "class_name", "identifier"],
    "old_name":       ["from", "before_name"],
    "new_name":       ["to", "after_name"],
    "source":         ["from_path", "src"],
    "destination":    ["dest", "dst", "to_path", "target_path"],
    "repo":           ["repository", "repo_url", "github_url", "github_repo"],
    "github_action":  ["gh_action", "git_action"],
    "github_path":    ["gh_path", "file", "filepath"],
    "branch":         ["ref", "git_branch"],
    "city":           ["location", "place", "town", "municipality", "region"],
    "lang":           ["language", "locale"],
    "pattern":        ["glob_pattern", "glob"],
    "test_path":      ["path", "directory", "dir", "folder"],
    "filter_expr":    ["filter", "expr", "expression", "test_filter"],
    "command":        ["cmd", "shell", "exec", "run", "execute"],
}
