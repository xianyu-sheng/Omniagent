"""
OmniAgent 库管理器 — MCP 和 Skill 的浏览、搜索、安装。

内置库随包发布，可选从 GitHub 拉取最新版本。
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── 库文件路径 ──────────────────────────────────────────

_PKG_DATA = Path(__file__).resolve().parent.parent / "data"
_BUILTIN_MCP_LIB = _PKG_DATA / "mcp_library.yaml"
_BUILTIN_SKILL_LIB = _PKG_DATA / "skill_library.yaml"

# 远程库 URL（GitHub raw）
_REMOTE_MCP_LIB_URL = (
    "https://raw.githubusercontent.com/xianyu-sheng/Omniagent/main/"
    "omniagent/data/mcp_library.yaml"
)
_REMOTE_SKILL_LIB_URL = (
    "https://raw.githubusercontent.com/xianyu-sheng/Omniagent/main/"
    "omniagent/data/skill_library.yaml"
)

# 本地缓存（用户安装的远程版本）
_USER_DATA = Path.home() / ".omniagent"
_CACHED_MCP_LIB = _USER_DATA / "mcp_library.yaml"
_CACHED_SKILL_LIB = _USER_DATA / "skill_library.yaml"


# ── 数据模型 ────────────────────────────────────────────

@dataclass
class MCPServerEntry:
    """MCP 库中的一个条目。"""
    name: str
    description: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    category: str = ""
    homepage: str = ""
    note: str = ""


@dataclass
class SkillEntry:
    """Skill 库中的一个条目。"""
    name: str
    description: str
    category: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    params: list[dict[str, str]] = field(default_factory=list)
    system_prompt: str = ""


# ── 加载 / 解析 ─────────────────────────────────────────

def _load_yaml(path: Path) -> dict[str, Any]:
    """安全加载 YAML 文件。"""
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning(f"加载 YAML 失败 ({path}): {e}")
        return {}


def _parse_mcp_entry(raw: dict) -> MCPServerEntry | None:
    """解析单个 MCP 条目。"""
    name = raw.get("name", "")
    if not name:
        return None
    return MCPServerEntry(
        name=name,
        description=raw.get("description", ""),
        command=raw.get("command", ""),
        args=raw.get("args", []),
        env=raw.get("env", {}),
        category=raw.get("category", ""),
        homepage=raw.get("homepage", ""),
        note=raw.get("note", ""),
    )


def _parse_skill_entry(raw: dict) -> SkillEntry | None:
    """解析单个 Skill 条目。"""
    name = raw.get("name", "")
    if not name:
        return None
    return SkillEntry(
        name=name,
        description=raw.get("description", ""),
        category=raw.get("category", ""),
        steps=raw.get("steps", []),
        params=raw.get("params", []),
        system_prompt=raw.get("system_prompt", ""),
    )


# ── MCP 库 ──────────────────────────────────────────────

class MCPLibrary:
    """MCP 服务器库管理器。"""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerEntry] = {}
        self._load()

    def _load(self) -> None:
        """优先级: 本地缓存 > 内置库。"""
        self._servers.clear()

        # 先加载内置库
        for raw in _load_yaml(_BUILTIN_MCP_LIB).get("servers", []):
            entry = _parse_mcp_entry(raw)
            if entry:
                self._servers[entry.name] = entry

        # 本地缓存覆盖
        for raw in _load_yaml(_CACHED_MCP_LIB).get("servers", []):
            entry = _parse_mcp_entry(raw)
            if entry:
                self._servers[entry.name] = entry

    def discover(self, keyword: str = "") -> list[MCPServerEntry]:
        """浏览或搜索 MCP 服务器。

        keyword 为空时返回全部，否则按名称/描述/分类模糊匹配。
        """
        if not keyword:
            return sorted(self._servers.values(), key=lambda s: s.name)

        keyword_lower = keyword.lower()
        results: list[MCPServerEntry] = []
        for s in self._servers.values():
            if (keyword_lower in s.name.lower()
                    or keyword_lower in s.description.lower()
                    or keyword_lower in s.category.lower()):
                results.append(s)
        return sorted(results, key=lambda s: s.name)

    def get(self, name: str) -> MCPServerEntry | None:
        """获取一个 MCP 条目。支持模糊匹配。"""
        if name in self._servers:
            return self._servers[name]
        # 模糊匹配
        name_lower = name.lower()
        for s in self._servers.values():
            if s.name.lower() == name_lower:
                return s
        # 前缀匹配
        for s in self._servers.values():
            if s.name.lower().startswith(name_lower):
                return s
        return None

    def update_from_remote(self) -> tuple[bool, str]:
        """从 GitHub 拉取最新 MCP 库。"""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(_REMOTE_MCP_LIB_URL)
            req.add_header("User-Agent", "OmniAgent-CLI")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode("utf-8")

            # 验证 YAML
            parsed = yaml.safe_load(data)
            if not parsed or "servers" not in parsed:
                return False, "远程库格式无效"

            _USER_DATA.mkdir(parents=True, exist_ok=True)
            _CACHED_MCP_LIB.write_text(data, encoding="utf-8")
            self._load()
            count = len(parsed.get("servers", []))
            return True, f"已更新 MCP 库（{count} 个服务器）"

        except urllib.error.HTTPError as e:
            return False, f"网络错误: HTTP {e.code}"
        except urllib.error.URLError as e:
            return False, f"网络错误: {e.reason}"
        except Exception as e:
            return False, f"更新失败: {e}"


# ── Skill 库 ────────────────────────────────────────────

class SkillLibrary:
    """Skill 库管理器。"""

    def __init__(self) -> None:
        self._skills: dict[str, SkillEntry] = {}
        self._load()

    def _load(self) -> None:
        """优先级: 本地缓存 > 内置库。"""
        self._skills.clear()

        for raw in _load_yaml(_BUILTIN_SKILL_LIB).get("skills", []):
            entry = _parse_skill_entry(raw)
            if entry:
                self._skills[entry.name] = entry

        for raw in _load_yaml(_CACHED_SKILL_LIB).get("skills", []):
            entry = _parse_skill_entry(raw)
            if entry:
                self._skills[entry.name] = entry

    def discover(self, keyword: str = "") -> list[SkillEntry]:
        """浏览或搜索 Skill。"""
        if not keyword:
            return sorted(self._skills.values(), key=lambda s: s.name)

        keyword_lower = keyword.lower()
        results: list[SkillEntry] = []
        for s in self._skills.values():
            if (keyword_lower in s.name.lower()
                    or keyword_lower in s.description.lower()
                    or keyword_lower in s.category.lower()):
                results.append(s)
        return sorted(results, key=lambda s: s.name)

    def get(self, name: str) -> SkillEntry | None:
        """获取一个 Skill 条目。"""
        if name in self._skills:
            return self._skills[name]
        name_lower = name.lower()
        for s in self._skills.values():
            if s.name.lower() == name_lower:
                return s
        for s in self._skills.values():
            if s.name.lower().startswith(name_lower):
                return s
        return None

    def install(self, name: str) -> tuple[bool, str]:
        """将 Skill 安装到 ~/.omniagent/skills/。"""
        entry = self.get(name)
        if not entry:
            return False, f"未找到 Skill '{name}'。输入 /skill discover 浏览可用 Skill"

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

    def update_from_remote(self) -> tuple[bool, str]:
        """从 GitHub 拉取最新 Skill 库。"""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(_REMOTE_SKILL_LIB_URL)
            req.add_header("User-Agent", "OmniAgent-CLI")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode("utf-8")

            parsed = yaml.safe_load(data)
            if not parsed or "skills" not in parsed:
                return False, "远程库格式无效"

            _USER_DATA.mkdir(parents=True, exist_ok=True)
            _CACHED_SKILL_LIB.write_text(data, encoding="utf-8")
            self._load()
            count = len(parsed.get("skills", []))
            return True, f"已更新 Skill 库（{count} 个 Skill）"

        except urllib.error.HTTPError as e:
            return False, f"网络错误: HTTP {e.code}"
        except urllib.error.URLError as e:
            return False, f"网络错误: {e.reason}"
        except Exception as e:
            return False, f"更新失败: {e}"


# ── 全局单例 ────────────────────────────────────────────

_mcp_library: MCPLibrary | None = None
_skill_library: SkillLibrary | None = None


def get_mcp_library() -> MCPLibrary:
    """获取 MCP 库单例。"""
    global _mcp_library
    if _mcp_library is None:
        _mcp_library = MCPLibrary()
    return _mcp_library


def get_skill_library() -> SkillLibrary:
    """获取 Skill 库单例。"""
    global _skill_library
    if _skill_library is None:
        _skill_library = SkillLibrary()
    return _skill_library
