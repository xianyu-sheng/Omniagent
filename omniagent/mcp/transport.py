"""
MCP Transport — JSON-RPC 2.0 传输层。

支持两种传输方式：
- stdio: 通过子进程的标准输入/输出通信
- SSE: 通过 HTTP Server-Sent Events 通信
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from typing import Any

import httpx

from omniagent.utils.llm_client import _create_http_client

logger = logging.getLogger(__name__)


class MCPTransport:
    """MCP 传输基类。"""

    def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    def receive(self) -> dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class StdioTransport(MCPTransport):
    """通过子进程 stdio 通信。"""

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._start()

    def _start(self) -> None:
        """启动子进程。"""
        cmd = [self.command] + self.args
        import os
        child_env = dict(os.environ)
        if self.env:
            child_env.update(self.env)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                text=True,
            )
            logger.info(f"MCP 子进程启动: {' '.join(cmd)} (PID: {self._proc.pid})")
        except FileNotFoundError:
            raise RuntimeError(f"MCP 命令不存在: {self.command}")
        except Exception as e:
            raise RuntimeError(f"MCP 子进程启动失败: {e}")

    def send(self, message: dict[str, Any]) -> None:
        """发送 JSON-RPC 消息。"""
        if not self._proc or self._proc.poll() is not None:
            raise RuntimeError("MCP 子进程未运行")

        data = json.dumps(message) + "\n"
        with self._lock:
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except Exception as e:
                raise RuntimeError(f"MCP 发送失败: {e}")

    def receive(self) -> dict[str, Any]:
        """接收 JSON-RPC 消息。"""
        if not self._proc or self._proc.poll() is not None:
            raise RuntimeError("MCP 子进程未运行")

        with self._lock:
            try:
                line = self._proc.stdout.readline()
                if not line:
                    stderr = self._proc.stderr.read() if self._proc.stderr else ""
                    raise RuntimeError(f"MCP 子进程无输出。stderr: {stderr[:500]}")
                return json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"MCP 响应解析失败: {e}")

    def request(self, method: str, params: dict[str, Any] | None = None, max_retries: int = 50) -> dict[str, Any]:
        """发送请求并等待响应（原子操作）。"""
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                raise RuntimeError("MCP 子进程未运行")

            self._request_id += 1
            request_id = self._request_id
            message = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params:
                message["params"] = params

            data = json.dumps(message) + "\n"
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except Exception as e:
                raise RuntimeError(f"MCP 发送失败: {e}")

            # 等待响应（匹配 id），带重试上限
            for _ in range(max_retries):
                try:
                    line = self._proc.stdout.readline()
                    if not line:
                        raise RuntimeError("MCP 子进程无输出")
                    response = json.loads(line)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"MCP 响应解析失败: {e}")

                if response.get("id") == request_id:
                    return response
                if "id" not in response:
                    logger.debug(f"MCP 通知: {response.get('method', 'unknown')}")
                    continue

            raise RuntimeError(f"MCP 请求超时：未在 {max_retries} 次重试内收到响应")

    def close(self) -> None:
        """关闭子进程。"""
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.stdout.close()
            except Exception:
                pass
            try:
                self._proc.stderr.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def __del__(self) -> None:
        self.close()


class SSETransport(MCPTransport):
    """通过 HTTP SSE 通信。"""

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.headers = headers or {}
        self._client = _create_http_client(timeout=30.0)
        self._request_id = 0

    def send(self, message: dict[str, Any]) -> None:
        """通过 HTTP POST 发送消息。"""
        try:
            resp = self._client.post(
                self.url,
                json=message,
                headers={**self.headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"MCP SSE 发送失败: {e}")

    def receive(self) -> dict[str, Any]:
        """通过 SSE 接收消息。"""
        try:
            with self._client.stream("GET", self.url, headers=self.headers) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data:
                            return json.loads(data)
            raise RuntimeError("SSE 连接关闭")
        except Exception as e:
            raise RuntimeError(f"MCP SSE 接收失败: {e}")

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送请求。SSE 模式下直接用 POST 请求-响应。"""
        self._request_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params:
            message["params"] = params

        try:
            resp = self._client.post(
                self.url,
                json=message,
                headers={**self.headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"MCP SSE 请求失败: {e}")

    def close(self) -> None:
        self._client.close()
