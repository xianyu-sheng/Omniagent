"""
Web tools — web_fetch, github_fetch, weather
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import BaseTool

logger = logging.getLogger(__name__)

# ── GitHub 凭证加载 ──────────────────────────────────────────


def _load_github_token() -> str | None:
    """从 ~/.omniagent/credentials.yaml 或环境变量加载 GitHub token。

    优先级: GITHUB_TOKEN 环境变量 > credentials.yaml 中的 github.api_key
    """
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if env_token:
        return env_token.strip()

    creds_path = Path.home() / ".omniagent" / "credentials.yaml"
    if creds_path.exists():
        try:
            with open(creds_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                github_cfg = data.get("github", {})
                if isinstance(github_cfg, dict):
                    token = github_cfg.get("api_key") or github_cfg.get("token")
                    if token and str(token).strip():
                        return str(token).strip()
                elif isinstance(github_cfg, str):
                    return github_cfg.strip()
        except Exception:
            pass
    return None


def _build_github_headers() -> dict:
    """构建 GitHub API 请求头，包含 token（如果可用）。"""
    headers = {"User-Agent": "OmniAgent-CLI/0.3"}
    token = _load_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        logger.debug("github_fetch/web_fetch: 使用 GitHub token 认证")
    else:
        logger.debug("github_fetch/web_fetch: 无 GitHub token，使用未认证请求（60次/小时限制）")
    return headers


class WebFetchTool(BaseTool):
    name = "web_fetch"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        url = self.resolve(self._extra.get("url", "") or self._extra.get("action", ""), context)
        if not url:
            return {"action_type": "web_fetch", "success": False, "error": "需要 url 参数"}

        # P0-4 修复: 清理 URL 中的换行符和空白字符
        import re as _re
        url = _re.sub(r'[\r\n]+', '', url).strip()
        url_lower = url.lower()
        if url_lower.startswith("file://"):
            return {"action_type": "web_fetch", "url": url, "content": "", "success": False, "error": "禁止访问 file:// 协议"}
        # HTTP → HTTPS 自动升级（现代服务通常要求 HTTPS）
        if url_lower.startswith("http://"):
            upgraded = "https://" + url[7:]
            logger.debug(f"web_fetch HTTP→HTTPS 升级: {url[:60]} → {upgraded[:60]}")
            url = upgraded
            url_lower = url.lower()
        if any(url_lower.startswith(p) for p in ["https://169.254", "https://10.", "https://172.1", "https://192.168", "https://localhost", "https://127."]):
            return {"action_type": "web_fetch", "url": url, "content": "", "success": False, "error": "禁止访问内网地址"}

        try:
            import httpx

            # P0-8: 对 GitHub API 请求使用 token 认证
            headers = _build_github_headers() if "api.github.com" in url_lower or "raw.githubusercontent.com" in url_lower else {"User-Agent": "OmniAgent-CLI/0.3"}

            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)

                # P0-8: 403 限流检测 — 给出清晰的错误信息
                if resp.status_code == 403 and "rate limit" in (resp.text or "").lower():
                    return {
                        "action_type": "web_fetch", "url": url, "content": "",
                        "success": False,
                        "error": (
                            "GitHub API 限流 (403 rate limit exceeded)。"
                            "未认证请求限制 60次/小时。\n"
                            "解决方案: 在 ~/.omniagent/credentials.yaml 中添加:\n"
                            "  github:\n"
                            "    api_key: ghp_xxxxxxxxxxxx\n"
                            "或设置环境变量 GITHUB_TOKEN。"
                        ),
                    }

                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type:
                    text = _html_to_text(resp.text)
                else:
                    text = resp.text

                if len(text) > 50000:
                    text = text[:50000] + "\n\n... (已截断)"

                result = {
                    "action_type": "web_fetch", "url": url,
                    "status_code": resp.status_code, "content": text,
                    "content_length": len(text), "success": True,
                }
                self._write_output(context, text[:5000])
                return result
        except ImportError:
            return {"action_type": "web_fetch", "success": False, "error": "需要 httpx 库"}
        except Exception as e:
            return {"action_type": "web_fetch", "url": url, "content": "", "success": False, "error": str(e)}


def _html_to_text(html: str) -> str:
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.I)
    text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.I)
    text = re.sub(r'</(p|div|h[1-6]|li|tr)>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class GitHubFetchTool(BaseTool):
    name = "github_fetch"

    @staticmethod
    def _detect_default_branch(client, repo: str, headers: dict) -> str | None:
        """通过 GitHub API 查询仓库的默认分支。

        优先使用此方法获取真正的默认分支名，避免盲目猜测 main/master。
        """
        try:
            repo_url = f"https://api.github.com/repos/{repo}"
            resp = client.get(repo_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                default_branch = data.get("default_branch", "")
                if default_branch:
                    logger.info(f"github_fetch: 检测到默认分支 '{default_branch}' for {repo}")
                    return default_branch
        except Exception as e:
            logger.debug(f"github_fetch: 获取默认分支失败: {e}")
        return None

    @staticmethod
    def _resolve_branch(client, repo: str, preferred_branch: str, headers: dict) -> str:
        """智能解析分支名：用户指定 > API 默认分支 > main > master。

        Returns:
            解析后的分支名
        """
        # 如果用户提供了非空分支名，优先使用
        if preferred_branch and preferred_branch.strip():
            return preferred_branch.strip()

        # 查询 API 获取默认分支
        default = GitHubFetchTool._detect_default_branch(client, repo, headers)
        if default:
            return default

        return "main"

    @staticmethod
    def _try_fetch_url(client, url: str, headers: dict) -> tuple:
        """尝试获取 URL，404 时返回 None 而非抛异常。"""
        resp = client.get(url, headers=headers)
        if resp.status_code == 404:
            return None, 404
        resp.raise_for_status()
        return resp, resp.status_code

    @staticmethod
    def _try_branches(client, repo: str, path_fn, headers: dict, preferred_branch: str) -> tuple:
        """按优先级尝试多个分支名来获取资源。

        Args:
            path_fn: callable(branch) -> url
            preferred_branch: 用户指定的分支名（可能为空）

        Returns:
            (response, branch_used) 或 raises 最后一个异常
        """
        # 构建候选分支列表
        candidates = []
        seen = set()

        if preferred_branch and preferred_branch.strip():
            candidates.append(preferred_branch.strip())
            seen.add(preferred_branch.strip())

        # 查询默认分支
        default = GitHubFetchTool._detect_default_branch(client, repo, headers)
        if default and default not in seen:
            candidates.append(default)
            seen.add(default)

        for fallback in ("main", "master"):
            if fallback not in seen:
                candidates.append(fallback)
                seen.add(fallback)

        last_error = None
        for branch in candidates:
            url = path_fn(branch)
            try:
                resp = client.get(url, headers=headers)
                if resp.status_code == 404:
                    logger.debug(f"github_fetch: 分支 '{branch}' 返回 404 for {url}")
                    continue
                resp.raise_for_status()
                logger.info(f"github_fetch: 成功使用分支 '{branch}'")
                return resp, branch
            except Exception as e:
                last_error = e
                logger.debug(f"github_fetch: 分支 '{branch}' 失败: {e}")

        raise last_error or Exception(f"所有分支尝试均失败: {candidates}")

    def execute(self, context: AgentContext) -> dict[str, Any]:
        repo = self.resolve(self._extra.get("repo", ""), context)
        if not repo:
            return {"action_type": "github_fetch", "success": False, "error": "需要 repo 参数 (格式: owner/repo)"}

        repo = repo.strip().rstrip("/")
        if "github.com" in repo:
            m = re.search(r"github\.com/([^/]+/[^/]+)", repo)
            if m:
                repo = m.group(1)

        action = self.resolve(self._extra.get("github_action", ""), context) or "list_files"
        branch = self.resolve(self._extra.get("branch", ""), context) or ""
        gh_path = self.resolve(self._extra.get("github_path", ""), context) or ""

        try:
            import httpx
        except ImportError:
            return {"action_type": "github_fetch", "success": False, "error": "需要 httpx 库"}

        # P0-8: 使用 GitHub token 认证（如果可用）
        headers = _build_github_headers()

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                if action == "list_files":
                    def _list_url(b): return f"https://api.github.com/repos/{repo}/git/trees/{b}?recursive=1"
                    resp, used_branch = self._try_branches(client, repo, _list_url, headers, branch)
                    tree = resp.json().get("tree", [])
                    files = [item["path"] for item in tree if item.get("type") == "blob" and not item["path"].startswith(".git/")]
                    text = f"仓库 {repo} (分支: {used_branch}) 共 {len(files)} 个文件:\n" + "\n".join(files)
                    if len(text) > 10000:
                        text = text[:10000] + "\n\n... (共 {len(files)} 个文件，已截断)"
                    self._write_output(context, text[:5000])
                    return {"action_type": "github_fetch", "repo": repo, "branch": used_branch, "files": files, "file_count": len(files), "content": text, "success": True}

                if action == "fetch_file":
                    if not gh_path:
                        return {"action_type": "github_fetch", "success": False, "error": "需要 github_path 参数"}
                    def _file_url(b): return f"https://raw.githubusercontent.com/{repo}/{b}/{gh_path}"
                    resp, used_branch = self._try_branches(client, repo, _file_url, headers, branch)
                    text = resp.text
                    if len(text) > 50000:
                        text = text[:50000] + "\n\n... (已截断)"
                    self._write_output(context, text[:5000])
                    return {"action_type": "github_fetch", "repo": repo, "branch": used_branch, "path": gh_path, "content": text, "content_length": len(text), "success": True}

                if action == "fetch_readme":
                    for name in ["README.md", "readme.md", "README.rst", "README"]:
                        try:
                            def _readme_url(b): return f"https://raw.githubusercontent.com/{repo}/{b}/{name}"
                            resp, used_branch = self._try_branches(client, repo, _readme_url, headers, branch)
                            text = resp.text[:20000]
                            self._write_output(context, text[:5000])
                            return {"action_type": "github_fetch", "repo": repo, "branch": used_branch, "path": name, "content": text, "success": True}
                        except Exception:
                            continue
                    return {"action_type": "github_fetch", "success": False, "error": "未找到 README 文件（已尝试所有分支和常见文件名）"}

                return {"action_type": "github_fetch", "success": False, "error": f"不支持的操作: {action}"}

        except Exception as e:
            error_str = str(e)
            # P0-8: 403 限流检测
            if "403" in error_str and ("rate limit" in error_str.lower() or "rate limit" in error_str):
                return {
                    "action_type": "github_fetch", "repo": repo, "success": False,
                    "error": (
                        "GitHub API 限流 (403 rate limit exceeded)。\n"
                        "建议:\n"
                        "1. 在 ~/.omniagent/credentials.yaml 中配置 github.api_key\n"
                        "2. 设置环境变量 GITHUB_TOKEN\n"
                        "3. 使用 git clone 将仓库克隆到本地后用 list_files + read_file 分析\n"
                        "4. 使用 web_fetch 访问 raw.githubusercontent.com 获取文件（无速率限制）"
                    ),
                }
            return {"action_type": "github_fetch", "repo": repo, "success": False, "error": str(e)}


class WeatherTool(BaseTool):
    name = "weather"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        city = self.resolve(self._extra.get("city", ""), context)
        if not city:
            return {"action_type": "weather", "success": False, "content": "", "error": "需要 city 参数"}
        lang = self.resolve(self._extra.get("lang", ""), context) or "zh"

        try:
            from omniagent.utils.weather import format_weather_report, get_weather
            info = get_weather(city, lang)
            report = format_weather_report(info)
            result = {"action_type": "weather", "city": city, "success": "error" not in info, "weather_info": info, "content": report}
            self._write_output(context, report[:5000])
            return result
        except ImportError:
            return {"action_type": "weather", "success": False, "error": "需要 httpx 库"}
        except Exception as e:
            return {"action_type": "weather", "city": city, "success": False, "error": str(e)}
