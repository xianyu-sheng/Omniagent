"""
OmniAgent 库管理器 — MCP / Skill 云端库。

核心策略: 每次 /mcp discover 从 GitHub 拉取最新库 YAML，
缓存到 ~/.omniagent/ 用于离线兜底。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import time

import yaml

logger = logging.getLogger(__name__)

# ── 云端库 URL ──────────────────────────────────────────

_MCP_LIB_URL = (
    "https://raw.githubusercontent.com/xianyu-sheng/Omniagent/main/"
    "library/mcp_library.yaml"
)
_SKILL_LIB_URL = (
    "https://raw.githubusercontent.com/xianyu-sheng/Omniagent/main/"
    "library/skill_library.yaml"
)

# ── 本地缓存（~/.omniagent/）─────────────────────────────

_USER_DATA = Path.home() / ".omniagent"
_CACHE_MCP = _USER_DATA / "mcp_library.cache.yaml"
_CACHE_SKILL = _USER_DATA / "skill_library.cache.yaml"
_CACHE_TTL = 3600  # 缓存有效期（秒），1 小时内不重复请求


# ── 数据模型 ────────────────────────────────────────────

@dataclass
class MCPServerEntry:
    name: str
    description: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    category: str = ""
    homepage: str = ""
    note: str = ""


@dataclass
class SkillEntry:
    name: str
    description: str
    category: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    params: list[dict[str, str]] = field(default_factory=list)
    system_prompt: str = ""


# ── HTTP 拉取 ───────────────────────────────────────────

def _http_fetch(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """从 URL 拉取文本内容。返回 (成功, 内容或错误信息)。"""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "OmniAgent-CLI")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"网络不可达: {e.reason}"
    except Exception as e:
        return False, str(e)


def _cache_valid(cache_path: Path) -> bool:
    """缓存是否存在且未过期。"""
    try:
        if not cache_path.exists():
            return False
        age = time.time() - cache_path.stat().st_mtime
        return age < _CACHE_TTL
    except Exception:
        return False


# ── 解析 ────────────────────────────────────────────────

def _parse_mcp_entries(raw_yaml: str) -> list[MCPServerEntry]:
    """解析 MCP 库 YAML 为条目列表。"""
    try:
        data = yaml.safe_load(raw_yaml) or {}
    except Exception as e:
        logger.warning(f"解析 MCP 库 YAML 失败: {e}")
        return []
    entries: list[MCPServerEntry] = []
    for raw in data.get("servers", []):
        name = raw.get("name", "")
        if not name:
            continue
        entries.append(MCPServerEntry(
            name=name,
            description=raw.get("description", ""),
            command=raw.get("command", ""),
            args=raw.get("args", []),
            url=raw.get("url", ""),
            env=raw.get("env", {}),
            category=raw.get("category", ""),
            homepage=raw.get("homepage", ""),
            note=raw.get("note", ""),
        ))
    return entries


def _parse_skill_entries(raw_yaml: str) -> list[SkillEntry]:
    """解析 Skill 库 YAML 为条目列表。"""
    try:
        data = yaml.safe_load(raw_yaml) or {}
    except Exception as e:
        logger.warning(f"解析 Skill 库 YAML 失败: {e}")
        return []
    entries: list[SkillEntry] = []
    for raw in data.get("skills", []):
        name = raw.get("name", "")
        if not name:
            continue
        entries.append(SkillEntry(
            name=name,
            description=raw.get("description", ""),
            category=raw.get("category", ""),
            steps=raw.get("steps", []),
            params=raw.get("params", []),
            system_prompt=raw.get("system_prompt", ""),
        ))
    return entries


# ── 库加载策略（云端 → 缓存 → 内置兜底）────────────────

class _LibraryBase:
    """基类: 云端拉取 + 本地缓存 + 内置兜底。"""

    cloud_url: str
    cache_path: Path
    # 内置兜底（出错时给用户最起码的东西）
    fallback_yaml: str = ""

    def __init__(self) -> None:
        self._entries: list[Any] = []
        self._by_name: dict[str, Any] = {}
        self._source: str = "未加载"  # "cloud" / "cache" / "fallback"
        self._error: str = ""

    def load(self) -> None:
        """按优先级加载: 云端 → 缓存 → 内置兜底。"""
        self._entries.clear()
        self._by_name.clear()
        self._error = ""

        # 1. 尝试云端拉取
        ok, content = _http_fetch(self.cloud_url, timeout=8.0)
        if ok:
            self._entries = self._parse_entries(content)
            self._source = "cloud"
            # 写入缓存
            try:
                _USER_DATA.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.debug(f"写入缓存失败: {e}")
            self._build_index()
            return
        self._error = content  # 保存错误信息

        # 2. 云端失败，尝试本地缓存
        if self.cache_path.exists():
            try:
                cached = self.cache_path.read_text(encoding="utf-8")
                self._entries = self._parse_entries(cached)
                self._source = "cache"
                self._build_index()
                return
            except Exception as e:
                logger.debug(f"读取缓存失败: {e}")

        # 3. 内置兜底
        if self.fallback_yaml:
            self._entries = self._parse_entries(self.fallback_yaml)
            self._source = "fallback"
            self._build_index()

    def _build_index(self) -> None:
        for e in self._entries:
            self._by_name[e.name] = e

    def _parse_entries(self, raw: str) -> list[Any]:
        raise NotImplementedError

    @property
    def source_label(self) -> str:
        if self._source == "cloud":
            return "☁️ 云端"
        elif self._source == "cache":
            age = int(time.time() - self.cache_path.stat().st_mtime) if self.cache_path.exists() else 0
            return f"💾 缓存（{age // 60} 分钟前）" if age > 0 else "💾 缓存"
        else:
            return "📦 内置（离线）"

    def discover(self, keyword: str = "") -> list[Any]:
        """浏览或模糊搜索。"""
        if keyword:
            kw = keyword.lower()
            return sorted(
                [e for e in self._entries
                 if kw in e.name.lower()
                 or kw in e.description.lower()
                 or kw in (getattr(e, 'category', '') or '').lower()],
                key=lambda e: e.name,
            )
        return sorted(self._entries, key=lambda e: e.name)

    def get(self, name: str) -> Any | None:
        """精确或模糊获取单个条目。"""
        if name in self._by_name:
            return self._by_name[name]
        nl = name.lower()
        for e in self._entries:
            if e.name.lower() == nl:
                return e
        for e in self._entries:
            if e.name.lower().startswith(nl):
                return e
        return None


class MCPLibrary(_LibraryBase):
    """MCP 云端库。"""

    cloud_url = _MCP_LIB_URL
    cache_path = _CACHE_MCP
    fallback_yaml = """\
servers:
  - name: filesystem
    description: "安全的文件系统读写（内置离线兜底）"
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    category: 系统
  - name: fetch
    description: "HTTP 网页抓取（内置离线兜底）"
    command: npx
    args: ["-y", "@modelcontextprotocol/server-fetch"]
    category: 网络
  - name: brave-search
    description: "Brave 搜索（内置离线兜底）"
    command: npx
    args: ["-y", "@modelcontextprotocol/server-brave-search"]
    env:
      BRAVE_API_KEY: "<你的 Brave API Key>"
    category: 搜索
"""

    def _parse_entries(self, raw: str) -> list[MCPServerEntry]:
        return _parse_mcp_entries(raw)


class SkillLibrary(_LibraryBase):
    """Skill 云端库。"""

    cloud_url = _SKILL_LIB_URL
    cache_path = _CACHE_SKILL
    fallback_yaml = """\
skills:
  - name: git-commit
    description: "AI 生成 commit message（内置离线兜底）"
    category: 开发
    steps:
      - type: command
        action: git diff --cached
        output_var: diff
      - type: llm
        prompt: "根据以下 git diff 生成一条规范的 commit message（中文 50 字以内）：\\n{diff}"
"""

    def _parse_entries(self, raw: str) -> list[SkillEntry]:
        return _parse_skill_entries(raw)

    def install(self, name: str) -> tuple[bool, str]:
        """将 Skill 安装到 ~/.omniagent/skills/。"""
        entry = self.get(name)
        if not entry:
            return False, f"未找到 Skill '{name}'"

        from omniagent.repl.skill_manager import SkillManager

        mgr = SkillManager()
        try:
            mgr.create(
                name=entry.name,
                description=entry.description,
                steps=entry.steps,
                system_prompt=entry.system_prompt,
                params=entry.params,
            )
            return True, f"✅ Skill '{entry.name}' 已安装（{len(entry.steps)} 个步骤）"
        except Exception as e:
            return False, f"安装失败: {e}"

    def refresh_repl_skills(self) -> None:
        """安装后刷新 REPL 的 Skill 缓存。"""
        try:
            from omniagent.repl.skill_manager import SkillManager
            mgr = SkillManager()
            mgr.load()
        except Exception as e:
            logger.debug(f"刷新 Skill 失败: {e}")


# ── 全局单例（每次命令行新进程，单例即可）───────────────

_mcp_lib: MCPLibrary | None = None


def get_mcp_library(force_refresh: bool = False) -> MCPLibrary:
    """获取 MCP 库单例。force_refresh=True 跳过缓存强行拉取。"""
    global _mcp_lib
    if _mcp_lib is None or force_refresh:
        _mcp_lib = MCPLibrary()
        _mcp_lib.load()
    return _mcp_lib


_skill_lib: SkillLibrary | None = None


def get_skill_library(force_refresh: bool = False) -> SkillLibrary:
    """获取 Skill 库单例。"""
    global _skill_lib
    if _skill_lib is None or force_refresh:
        _skill_lib = SkillLibrary()
        _skill_lib.load()
    return _skill_lib
