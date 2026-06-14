"""
Execution tools — command, git
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import BaseTool

logger = logging.getLogger(__name__)


class CommandTool(BaseTool):
    name = "command"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        cmd = self.resolve(self._extra.get("action", ""), context)
        if not cmd:
            return {"action_type": "command", "success": False, "error": "需要 action 参数（命令文本）"}

        self._validate_command(cmd)

        if sys.platform == "win32":
            shell_exec = ["powershell", "-Command", cmd]
        else:
            shell_exec = ["/bin/bash", "-c", cmd]

        try:
            proc = subprocess.run(
                shell_exec, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self.timeout, cwd=self.cwd,
            )
            result = {
                "action_type": "command", "command": cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr,
                "success": proc.returncode == 0,
            }
            self._write_output(context, proc.stdout.strip())
            return result
        except subprocess.TimeoutExpired:
            return {"action_type": "command", "success": False, "error": f"命令超时 ({self.timeout}s): {cmd}"}
        except FileNotFoundError:
            return {"action_type": "command", "success": False, "error": f"Shell 不可用"}


class GitTool(BaseTool):
    name = "git"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        git_cmd = self.resolve(self._extra.get("git_command", "status"), context).strip()
        extra_args = self.resolve(self._extra.get("action", ""), context).strip()

        self._validate_git_command(git_cmd)

        git_commands = {
            "status": ["git", "status", "--short"],
            "diff": ["git", "diff", "--stat"],
            "diff_full": ["git", "diff"],
            "log": ["git", "log", "--oneline", "-10"],
            "branch": ["git", "branch", "-a"],
            "add": ["git", "add", "."],
            "stash": ["git", "stash"],
        }

        if git_cmd in git_commands:
            cmd = git_commands[git_cmd]
        elif git_cmd.startswith("commit"):
            msg = git_cmd.replace("commit", "").strip() or extra_args or "auto commit"
            cmd = ["git", "commit", "-m", msg]
        elif git_cmd.startswith("add"):
            target = git_cmd.replace("add", "").strip() or extra_args or "."
            cmd = ["git", "add", target]
        else:
            cmd = ["git"] + git_cmd.split() + (extra_args.split() if extra_args else [])

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout, cwd=self.cwd or ".",
            )
            output = proc.stdout.strip() or proc.stderr.strip()
            result = {
                "action_type": "git", "command": " ".join(cmd),
                "returncode": proc.returncode, "output": output,
                "success": proc.returncode == 0,
            }
            self._write_output(context, output)
            return result
        except subprocess.TimeoutExpired:
            return {"action_type": "git", "success": False, "error": "Git 命令超时"}
        except FileNotFoundError:
            return {"action_type": "git", "success": False, "error": "Git 未安装"}
