"""Small, lazy-discovery MCP facade over independently configured CAD servers."""
import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from .backend import Backend, compact
from .config import home, inspect_environment, load, validate


class Gateway:
    def __init__(self, config, directory=None):
        validate(config)
        self.config = config
        self.directory = Path(directory or home() / "cache")
        self.backends = {name: Backend(name, backend, self.directory) for name, backend in config["backends"].items()}

    def backend(self, name):
        if name not in self.backends:
            raise ValueError(f"Backend {name} not configured; run multi-cad setup")
        if name == "solidworks" and inspect_environment(self.config)["solidworks"]["registration_matches"] is False:
            raise ValueError("Selected SolidWorks executable differs from the COM registered version; select the registered installation or repair registration before modeling")
        return self.backends[name]

    async def close(self):
        for backend in self.backends.values():
            await backend.close()

    async def status(self, live=False):
        status = inspect_environment(self.config)
        for name, backend in self.backends.items():
            status.setdefault(name, {})
            if live:
                try:
                    async with backend.operation_lock:
                        await backend.request("refresh")
                        query = "solidworks_list_documents" if name == "solidworks" else "get_scene_info"
                        result = await backend.invoke(query, {}, 30)
                    status[name].update(mcp_connected=backend.connected, cad_callable=result["ok"])
                except Exception as error:
                    status[name].update(mcp_connected=False, cad_callable=False, error=str(error))
            status[name].update(backend.summary())
            verified_path = self.directory / f"{name}-verified.json"
            if verified_path.exists():
                from .backend import fingerprint
                verified = json.loads(verified_path.read_text(encoding="utf-8"))
                verified['config_matches'] = verified.get("config_hash") == fingerprint(backend.config)
                status[name]['verification_history'] = verified
                if verified['config_matches']:
                    status[name]["capabilities_verified"] = verified
        return status

    async def search(self, backend_name, query="", limit=8):
        backend = self.backend(backend_name)
        async with backend.operation_lock:
            await backend.request("catalog")
        terms = query.lower().split()
        matches = []
        for tool in backend.tools.values():
            text = (tool["name"] + " " + (tool.get("description") or "")).lower()
            score = sum(term in text for term in terms)
            if not terms or score:
                matches.append((score, tool))
        matches.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        return [{"name": t["name"], "description": (t.get("description") or "")[:180]} for _, t in matches[:max(1, min(limit, 20))]]

    async def schema(self, backend_name, operation):
        backend = self.backend(backend_name)
        async with backend.operation_lock:
            await backend.request("catalog")
        if operation not in backend.tools:
            raise ValueError("Unknown operation; refresh capabilities or search first")
        return backend.tools[operation]

    async def execute(self, backend_name, calls):
        if not 1 <= len(calls) <= 25:
            raise ValueError("Batch size must be 1..25; dependent IDs require separate batches")
        backend = self.backend(backend_name)
        results = []
        async with backend.operation_lock:
            for call in calls:
                try:
                    result = await backend.invoke(call["operation"], call.get("arguments", {}))
                except Exception as error:
                    result = {"ok": False, "status": "request_rejected", "error": str(error)}
                results.append(compact(result))
                if not result["ok"]:
                    break
        return {"results": results, "skipped": len(calls)-len(results)}


def create_server(config_path=None):
    from mcp.server.fastmcp import FastMCP
    gateway = Gateway(load(config_path))

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield gateway
        finally:
            await gateway.close()

    mcp = FastMCP("Multi-CAD", lifespan=lifespan,
                  instructions="Discover only the relevant backend operations, fetch schema, then execute. Never equate connected with geometry verified. Keep user originals, report unknown assembly placement. Prefer plate_workflow for the validated plate recipe. Do not use direct upstream clients concurrently with this gateway.")

    @mcp.tool()
    async def environment_status(live: bool = False) -> dict:
        """Installation and connection summary. live performs read queries and may launch CAD."""
        return await gateway.status(live)

    @mcp.tool()
    async def capability_search(backend: str, query: str = "", limit: int = 8) -> list:
        """Find operations using short English keywords; returns summaries, not full schemas."""
        return await gateway.search(backend, query, limit)

    @mcp.tool()
    async def operation_schema(backend: str, operation: str) -> dict:
        """Get the authoritative parameter schema for exactly one operation."""
        return await gateway.schema(backend, operation)

    @mcp.tool()
    async def execute_operations(backend: str, calls: list[dict]) -> dict:
        """Execute ordered calls {operation, arguments}; stop on error. No automatic replay of writes."""
        return await gateway.execute(backend, calls)

    @mcp.tool()
    async def reconcile_write(backend: str, evidence: str) -> dict:
        """After inspecting actual CAD state, record reconciliation evidence to unblock writes. Does not replay anything."""
        if len(evidence.strip()) < 20:
            raise ValueError("Provide observed CAD state and the intended next action")
        item = gateway.backend(backend)
        async with item.operation_lock:
            from .project import write_json
            write_json(item.directory / f"{backend}-reconciliation.json", {"evidence": evidence})
            item.uncertain = False
            item.uncertain_path.unlink(missing_ok=True)
        return {"reconciled": True, "replayed": False}

    @mcp.tool()
    async def plate_workflow(project: str, action: str, hole_diameter: float = 6) -> dict:
        """Validated recipe: create 120x80x5 mm plate with four holes 10 mm from edges; edit hole diameter in a new version; or verify. Actions create/edit/verify. Does not touch unrelated documents."""
        from .plate import run_plate
        return await run_plate(gateway.backend("solidworks"), Path(project), action, hole_diameter)

    @mcp.tool()
    def project_create(project: str, goal: str, parameters: dict | None = None) -> dict:
        """Create a new project with a goal and parameter provenance, without starting CAD. Each parameter: {value, unit, source, protected}."""
        from .project import write_json
        parameters = parameters or {}
        for name, value in parameters.items():
            if not isinstance(value, dict) or not all(k in value for k in ("value", "unit", "source")):
                raise ValueError(f"Parameter {name} requires value/unit/source")
            if value["source"] not in ("user", "measured", "inferred", "default"):
                raise ValueError(f"Invalid source for parameter {name}")
        path = Path(project).resolve()
        path.mkdir(parents=True, exist_ok=False)
        for folder in ("inputs", "analysis", "output", "reports"):
            (path / folder).mkdir()
        state = {"schema_version": 2, "kind": "agent_project", "goal": goal, "parameters": parameters,
                 "versions": [], "status": "planned", "assembly_position": "unknown"}
        write_json(path / "project.json", state)
        return {"project": str(path), "status": "planned"}

    @mcp.tool()
    def project_state(project: str) -> dict:
        """Read durable project state and latest validation, without querying CAD."""
        path = Path(project)
        state = json.loads((path / "project.json").read_text(encoding="utf-8"))
        return state

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()
    create_server(args.config).run(transport="stdio")


if __name__ == "__main__":
    main()
