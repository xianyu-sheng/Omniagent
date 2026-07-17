"""
MCP Transport — JSON-RPC 2.0 传输层。

支持两种传输方式：
- stdio: 通过子进程的标准输入/输出通信
- SSE: 通过 HTTP Server-Sent Events 通信
"""

from __future__ import annotations

import json
import logging
import select
import subprocess
import sys
import threading
import time
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
        # stdout 行缓冲：跨多次 _readline_with_timeout 调用保留未消费字节，
        # 避免与 BufferedReader 内部缓冲冲突。
        self._read_buf = bytearray()
        # F7/§8.1.4：stderr 由后台守护线程持续 drain 到有界缓冲，防子进程 stderr
        # 大量输出写满管道缓冲（~64KB）后阻塞 -> stdout 不再响应 -> 死锁/超时。
        self._stderr_buf: list[str] = []
        self._stderr_lock = threading.Lock()
        self._stderr_thread: threading.Thread | None = None
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
            # F7/§8.1.4：起后台守护线程持续 drain stderr
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, name="mcp-stderr-drain", daemon=True
            )
            self._stderr_thread.start()
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

    def receive(self, timeout: float = 30.0) -> dict[str, Any]:
        """接收 JSON-RPC 消息（带墙钟超时，避免 readline 无限阻塞）。"""
        if not self._proc or self._proc.poll() is not None:
            raise RuntimeError("MCP 子进程未运行")

        with self._lock:
            deadline = time.monotonic() + timeout
            line = self._readline_with_timeout(deadline)
            if line is None:
                raise RuntimeError(f"MCP 接收超时：{timeout}s 内无输出")
            if line == "":
                stderr = self._read_stderr_safely()
                raise RuntimeError(f"MCP 子进程无输出（EOF）。stderr: {stderr[:500]}")
            try:
                return json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"MCP 响应解析失败: {e}")

    def _readline_with_timeout(self, deadline: float) -> str | None:
        """从 stdout 读取一行，带整体 deadline 墙钟超时。

        使用 select 等待数据可读，避免 ``readline()`` 在子进程挂起时无限阻塞
        （B11）。返回值约定：
          - 行字符串（含 ``\\n``，已 utf-8 解码）：读到完整一行；
          - ``""``：遇到 EOF 且缓冲区无残留；
          - ``None``：deadline 超时，未读到完整行。
        """
        stream = self._proc.stdout
        try:
            fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            return None
        while True:
            nl = self._read_buf.find(b"\n")
            if nl >= 0:
                line = bytes(self._read_buf[:nl + 1])
                del self._read_buf[:nl + 1]
                return line.decode("utf-8", errors="replace")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                ready, _, _ = select.select([fd], [], [], remaining)
            except (OSError, ValueError):
                return None
            if not ready:
                return None
            try:
                chunk = stream.buffer.read1(8192)
            except Exception:
                return None
            if not chunk:
                # EOF：返回缓冲区残留（无换行）或空串
                if self._read_buf:
                    line = bytes(self._read_buf)
                    self._read_buf.clear()
                    return line.decode("utf-8", errors="replace")
                return ""
            self._read_buf += chunk

    def _drain_stderr(self) -> None:
        """后台持续读取子进程 stderr 到有界缓冲（防管道写满死锁 + 保留近期诊断）。

        drain 线程**独占** stderr 的读取与关闭：子进程退出/关闭 stderr 时
        ``readline`` 返回 ``""``，循环结束后在 finally 中关闭 stderr。
        这样主线程的 ``close()`` 不再直接关闭 stderr，避免与 drain 线程争抢
        stderr 内部锁导致 ``close()`` 死锁（§8.1.4/F7）。
        """
        if not self._proc or not self._proc.stderr:
            return
        stream = self._proc.stderr
        try:
            for line in iter(stream.readline, ""):
                with self._stderr_lock:
                    self._stderr_buf.append(line)
                    # 上限保护：仅保留最近 200 行，防无界增长
                    if len(self._stderr_buf) > 200:
                        del self._stderr_buf[: len(self._stderr_buf) - 200]
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _read_stderr_safely(self) -> str:
        """返回近期 stderr 缓冲内容（由后台 drain 线程持续填充，仅用于错误诊断）。"""
        with self._stderr_lock:
            if not self._stderr_buf:
                return ""
            return "".join(self._stderr_buf[-50:])  # 最近 50 行

    def request(self, method: str, params: dict[str, Any] | None = None,
                max_lines: int = 50, timeout: float = 30.0) -> dict[str, Any]:
        """发送请求并等待响应（原子操作，带墙钟超时）。

        - ``max_lines``：最多读取的行数上限（防止被无关通知/日志行无限消耗）。
        - ``timeout``：整体墙钟超时（秒）；超时抛 ``RuntimeError``。
          （B11：替代原先 ``max_retries`` 仅限行数、单行 readline 仍可无限阻塞的缺陷。）
        """
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

            # 等待响应（匹配 id），带墙钟 deadline 与行数上限
            deadline = time.monotonic() + timeout
            for _ in range(max_lines):
                line = self._readline_with_timeout(deadline)
                if line is None:
                    raise RuntimeError(
                        f"MCP 请求超时：{timeout}s 内未收到 id={request_id} 的响应")
                if line == "":
                    stderr = self._read_stderr_safely()
                    raise RuntimeError(
                        f"MCP 子进程无输出（EOF）。stderr: {stderr[:500]}")
                try:
                    response = json.loads(line)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"MCP 响应解析失败: {e}")

                if response.get("id") == request_id:
                    return response
                if "id" not in response:
                    logger.debug(f"MCP 通知: {response.get('method', 'unknown')}")
                    continue

            raise RuntimeError(
                f"MCP 请求超时：读取 {max_lines} 行后仍未收到 id={request_id} 的响应")

    def close(self) -> None:
        """关闭子进程。

        顺序很关键：先关 stdin + terminate 让子进程退出；子进程退出 -> stderr EOF ->
        drain 线程的 readline 返回并自行关闭 stderr。主线程随后 join drain 线程、关 stdout。
        **不直接关 stderr**，避免与 drain 线程争抢 stderr 内部锁导致死锁（§8.1.4/F7）。
        """
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
            # 子进程已终止 -> stderr EOF -> drain 线程退出（已自行关闭 stderr）
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=2.0)
                self._stderr_thread = None
            try:
                self._proc.stdout.close()
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

    def __del__(self) -> None:
        # §8.1.5：与 StdioTransport 一致，GC 丢弃时释放 httpx 连接池，防资源泄漏
        try:
            self.close()
        except Exception:
            pass
