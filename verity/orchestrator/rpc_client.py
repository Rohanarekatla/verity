"""
verity/orchestrator/rpc_client.py
RPC client managing Node.js subprocess communication via stdio.
"""

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# asyncio's StreamReader defaults to a 64 KiB limit per line, and readline()
# raises ValueError once a line exceeds it. Every real page blows straight
# through that: a single runAxe frame for a page with ~67 violations is
# ~370 KB, and WebAIM measures the average homepage at 56 errors. Match the
# Node side's own framing cap (node-worker/rpc/framing.ts, maxLineBytes) so
# both ends agree on the largest frame the protocol allows.
STREAM_LIMIT_BYTES = 64 * 1024 * 1024


class RPCClient:
    """
    Manages an asyncio subprocess running Node.js and handles
    line-delimited JSON-RPC 2.0 communication over stdio.
    """

    def __init__(self, command: list[str], default_timeout: float = 30.0):
        self.command = command
        self.default_timeout = default_timeout
        self.process: Optional[asyncio.subprocess.Process] = None
        self._next_id = 1
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Spawns the background subprocess and starts listening on stdout."""
        if self.process is not None and self.process.returncode is None:
            return

        logger.info(f"Launching RPC worker process: {' '.join(self.command)}")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT_BYTES,
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Failed to launch command '{self.command[0]}'. "
                "Ensure Node.js is installed and accessible in your PATH."
            )

        # Start background task to listen for stdout JSON responses
        self._read_task = asyncio.create_task(self._read_loop())

    async def send_request(
        self, method: str, params: dict[str, Any], timeout: Optional[float] = None
    ) -> Any:
        """
        Sends a JSON-RPC request over stdin and awaits the response.
        """
        if self.process is None or self.process.stdin is None or self.process.returncode is not None:
            raise RuntimeError("RPC worker process is not running. Call start() first.")

        request_id = self._next_id
        self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        future = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        # Send JSON line to worker over stdin
        line = json.dumps(payload) + "\n"
        try:
            self.process.stdin.write(line.encode("utf-8"))
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError(f"Failed to write to stdin: Worker pipe closed ({e}).")

        effective_timeout = timeout if timeout is not None else self.default_timeout

        try:
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(
                f"RPC request '{method}' (id={request_id}) timed out after {effective_timeout}s."
            )

    def _fail_all_pending(self, exc: BaseException) -> None:
        """
        Settle every in-flight request with `exc`.

        If the reader stops for any reason, nothing else will ever resolve
        these futures and each caller blocks until its own timeout — hiding
        the real cause behind a misleading "timed out" message. Failing them
        loudly, immediately, with the actual error is the same principle the
        Node dispatcher follows: a hang is worse than a failure.
        """
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(exc)
        self._pending_requests.clear()

    async def _read_loop(self) -> None:
        """Background loop reading line-delimited JSON messages from stdout."""
        if self.process is None or self.process.stdout is None:
            return

        while True:
            try:
                line = await self.process.stdout.readline()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Most likely a frame larger than the stream limit. Without
                # this, the task dies here and every caller waits out its
                # timeout for a response that can never arrive.
                logger.error(f"Reader stopped: {type(exc).__name__}: {exc}")
                self._fail_all_pending(
                    RuntimeError(f"RPC reader failed: {type(exc).__name__}: {exc}")
                )
                return

            if not line:
                # EOF: the worker exited. Anything still pending never will be.
                self._fail_all_pending(
                    RuntimeError("Worker closed stdout before responding.")
                )
                break

            decoded = line.decode("utf-8").strip()
            if not decoded:
                continue

            try:
                msg = json.loads(decoded)
            except json.JSONDecodeError:
                # Log debug outputs from Developer A's worker instead of crashing
                logger.debug(f"[Worker Output]: {decoded}")
                continue

            # Route response to waiting request using ID
            if isinstance(msg, dict) and "id" in msg:
                req_id = msg.get("id")
                if req_id in self._pending_requests:
                    future = self._pending_requests.pop(req_id)
                    if not future.done():
                        # Handle errors returned directly from Developer A's worker
                        if "error" in msg and msg["error"] is not None:
                            err = msg["error"]
                            err_msg = err.get("message", "Unknown error from worker")
                            err_code = err.get("code", -32603)
                            future.set_exception(
                                RuntimeError(f"[Worker Error {err_code}]: {err_msg}")
                            )
                        else:
                            future.set_result(msg.get("result"))

    async def stop(self) -> None:
        """Gracefully shuts down the worker process."""
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None

        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                if self.process and self.process.returncode is None:
                    self.process.kill()
            finally:
                self.process = None

        for req_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(RuntimeError("RPC client stopped before response received."))
        self._pending_requests.clear()