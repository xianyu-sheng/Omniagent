"""
Web tools — web_fetch, github_fetch, weather
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import BaseTool

logger = logging.getLogger(__name__)


class WebFetchTool(BaseTool):
    name = "web_fetch"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        url = self.resolve(self._extra.get("url", "") or self._extra.get("action", ""), context)
        if not url:
            return {"action_type": "web_fetch", "success": False, "error": "需要 url 参数"}

        url = url.strip()
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
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": "OmniAgent-CLI/0.3"})
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
        branch = self.resolve(self._extra.get("branch", ""), context) or "main"
        gh_path = self.resolve(self._extra.get("github_path", ""), context) or ""

        try:
            import httpx
        except ImportError:
            return {"action_type": "github_fetch", "success": False, "error": "需要 httpx 库"}

        headers = {"User-Agent": "OmniAgent-CLI/0.2"}

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                if action == "list_files":
                    api_url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
                    resp = client.get(api_url, headers=headers)
                    if resp.status_code == 404:
                        resp = client.get(f"https://api.github.com/repos/{repo}/git/trees/master?recursive=1", headers=headers)
                    resp.raise_for_status()
                    tree = resp.json().get("tree", [])
                    files = [item["path"] for item in tree if item.get("type") == "blob" and not item["path"].startswith(".git/")]
                    text = f"仓库 {repo} 共 {len(files)} 个文件:\n" + "\n".join(files)
                    if len(text) > 10000:
                        text = text[:10000] + "\n\n... (已截断)"
                    self._write_output(context, text[:5000])
                    return {"action_type": "github_fetch", "repo": repo, "files": files, "file_count": len(files), "content": text, "success": True}

                if action == "fetch_file":
                    if not gh_path:
                        return {"action_type": "github_fetch", "success": False, "error": "需要 github_path 参数"}
                    raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{gh_path}"
                    resp = client.get(raw_url, headers=headers)
                    if resp.status_code == 404:
                        resp = client.get(f"https://raw.githubusercontent.com/{repo}/master/{gh_path}", headers=headers)
                    resp.raise_for_status()
                    text = resp.text
                    if len(text) > 50000:
                        text = text[:50000] + "\n\n... (已截断)"
                    self._write_output(context, text[:5000])
                    return {"action_type": "github_fetch", "repo": repo, "path": gh_path, "content": text, "content_length": len(text), "success": True}

                if action == "fetch_readme":
                    for name in ["README.md", "readme.md", "README.rst", "README"]:
                        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{name}"
                        resp = client.get(raw_url, headers=headers)
                        if resp.status_code == 200:
                            text = resp.text[:20000]
                            self._write_output(context, text[:5000])
                            return {"action_type": "github_fetch", "repo": repo, "path": name, "content": text, "success": True}
                    return {"action_type": "github_fetch", "success": False, "error": "未找到 README"}

                return {"action_type": "github_fetch", "success": False, "error": f"不支持的操作: {action}"}

        except Exception as e:
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
