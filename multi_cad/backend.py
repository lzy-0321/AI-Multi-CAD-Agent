"""Persistent MCP actor. All stream contexts enter/exit in the same asyncio task."""
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from .project import write_json

# Only these known queries can be retried. Unknown tools are treated as mutations.
READ_ONLY = {"get_addon_status", "get_scene_info", "solidworks_list_documents", "solidworks_list_parameters",
             "solidworks_list_features", "solidworks_get_body_info", "solidworks_get_faces", "solidworks_get_edges",
             "solidworks_get_vertices", "solidworks_get_mass_properties", "solidworks_get_feature_tree",
             "solidworks_get_state", "solidworks_list_components", "solidworks_list_mates", "multi_cad_inspect_part"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def response_data(result):
    """Normalize both protocol errors and the pinned SW server's textual failures."""
    data = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "\n".join(texts)
    payload = data.get("structuredContent")
    if payload is None:
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            payload = {"text": text}
    failed = bool(data.get("isError")) or bool(re.search(r"(?im)^\s*(?:❌|error\b|failed\b|failure\b)", text))
    if isinstance(payload, dict):
        failed |= bool(payload.get("error")) or payload.get("success") is False
        failed |= payload.get("status") in ("error", "failed")
        failed |= str(payload.get("result", "")).lstrip().startswith(("❌", "Error", "Failed"))
        failed |= any(c.get("ok") is False for c in payload.get("calls", []) if isinstance(c, dict))
    return {"ok": not failed, "data": payload, "raw": data}


class ProcessLease:
    """Prevent two gateway processes from driving the same local backend concurrently."""
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another gateway owns this CAD session")

    def close(self):
        self.file.close()


class Backend:
    def __init__(self, name, config, directory):
        self.name, self.config, self.directory = name, config, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.queue = asyncio.Queue()
        self.task = None
        self.operation_lock = asyncio.Lock()
        self.tools = {}
        self.connected = False
        self.last_error = None
        self.last_refresh = 0
        self.uncertain_path = self.directory / f"{name}-uncertain.json"
        self.uncertain = self.uncertain_path.exists()
        self.cache_path = self.directory / f"{name}-capabilities.json"

    async def request(self, kind, *args):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._worker())
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((kind, args, future))
        return await future

    async def _worker(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        lease = None
        pending = None
        try:
            # SW has one local COM session; Blender can have distinct port sessions.
            identity = self.name + (self.config.get("env", {}).get("BLENDER_PORT", "9876") if self.name == "blender" else "")
            lease = ProcessLease(self.directory / (identity + ".lock"))
            env = dict(os.environ)
            env.update(self.config.get("env", {}))
            env["PYTHONUTF8"] = "1"
            params = StdioServerParameters(command=self.config["command"], args=self.config.get("args", []),
                                          cwd=self.config.get("cwd"), env=env)
            with (self.directory / f"{self.name}-stderr.log").open("a", encoding="utf-8") as log:
                async with stdio_client(params, errlog=log) as streams:
                    async with ClientSession(*streams) as session:
                        async with asyncio.timeout(60):
                            info = await session.initialize()
                            await self._refresh(session, info.serverInfo.model_dump())
                        self.connected = True
                        self.last_error = None
                        while True:
                            pending = await self.queue.get()
                            kind, args, future = pending
                            if kind == "stop":
                                if not future.done():
                                    future.set_result(None)
                                break
                            try:
                                if kind == "refresh":
                                    async with asyncio.timeout(30):
                                        await self._refresh(session, info.serverInfo.model_dump())
                                    result = self.summary()
                                elif kind == "catalog":
                                    if time.monotonic() - self.last_refresh > 300:
                                        async with asyncio.timeout(30):
                                            await self._refresh(session, info.serverInfo.model_dump())
                                    result = self.summary()
                                else:
                                    tool, arguments, timeout = args
                                    if tool not in self.tools:
                                        raise ValueError(f"Tool unavailable: {tool}")
                                    from jsonschema import validate
                                    validate(arguments, self.tools[tool]["inputSchema"])
                                    async with asyncio.timeout(timeout):
                                        result = response_data(await session.call_tool(tool, arguments))
                                if not future.done():
                                    future.set_result(result)
                            except (TimeoutError, ConnectionError, OSError) as error:
                                if not future.done():
                                    future.set_exception(error)
                                raise
                            except Exception as error:
                                if not future.done():
                                    future.set_exception(error)
                                raise
                            pending = None
        except BaseException as error:
            self.last_error = str(error)
            if pending and not pending[2].done():
                pending[2].set_exception(RuntimeError(str(error)))
            while not self.queue.empty():
                _, _, future = self.queue.get_nowait()
                if not future.done():
                    future.set_exception(RuntimeError(str(error)))
        finally:
            self.connected = False
            if lease:
                lease.close()

    async def _refresh(self, session, server):
        tools, cursor = [], None
        while True:
            result = await session.list_tools(cursor=cursor)
            tools.extend(t.model_dump(mode="json") for t in result.tools)
            cursor = result.nextCursor
            if not cursor:
                break
        self.tools = {t["name"]: t for t in tools}
        self.last_refresh = time.monotonic()
        # Always refresh on a new connection; never treat disk cache as liveness evidence.
        write_json(self.cache_path, {"config_hash": fingerprint(self.config), "server": server,
                                    "tools_hash": fingerprint(tools), "checked_at": time.time(), "tools": tools})

    def summary(self):
        return {"backend": self.name, "connected": self.connected, "tool_count": len(self.tools),
                "uncertain_write": self.uncertain, "last_error": self.last_error}

    async def close(self):
        if self.task and not self.task.done():
            try:
                await self.request("stop")
            finally:
                await self.task

    async def invoke(self, tool, arguments, timeout=120):
        """Caller owns operation_lock, allowing an entire workflow to hold it."""
        read_only = tool in READ_ONLY
        if self.uncertain and not read_only:
            return {"ok": False, "status": "needs_reconciliation", "error": "Previous write outcome unknown; inspect CAD and acknowledge before another write"}
        # Validate before marking anything as potentially applied.
        await self.request("catalog")
        if tool not in self.tools:
            return {"ok": False, "status": "unavailable", "error": f"Tool unavailable: {tool}"}
        from jsonschema import validate as validate_arguments
        validate_arguments(arguments, self.tools[tool]["inputSchema"])
        attempts = 2 if read_only else 1
        if not read_only:
            write_json(self.uncertain_path, {"tool": tool, "arguments": arguments, "status": "in_flight"})
        for attempt in range(attempts):
            try:
                result = await self.request("call", tool, arguments, timeout)
                if not read_only:
                    self.uncertain_path.unlink(missing_ok=True)
                break
            except Exception as error:
                result = {"ok": False, "status": "failed" if read_only else "outcome_unknown", "error": str(error)}
                if not read_only:
                    self.uncertain = True
                    write_json(self.uncertain_path, {"tool": tool, "arguments": arguments, "error": str(error)})
                if self.task:
                    await self.task
                    self.task = None
                if attempt + 1 < attempts:
                    await asyncio.sleep(.2)
        log_id = uuid.uuid4().hex
        write_json(self.directory / f"{log_id}.json", {"tool": tool, "arguments": arguments, "result": result})
        result["artifact"] = str(self.directory / f"{log_id}.json")
        if result.get("status") == "outcome_unknown":
            query = "solidworks_list_documents" if self.name == "solidworks" else "get_scene_info"
            if self.task and not self.task.done():
                await self.task
            try:
                result["state_after_failure"] = await self.request("call", query, {}, 20)
            except Exception as error:
                result["state_after_failure"] = {"error": str(error)}
                if self.task:
                    await self.task
        return result


def compact(result, limit=1800):
    value = {k: v for k, v in result.items() if k != "raw"}
    text = json.dumps(value.get("data", value.get("error", "")), ensure_ascii=False)
    if len(text) > limit:
        value["data"] = {"preview": text[:limit], "truncated": True, "full_result": value.get("artifact")}
    return value
