"""Generate machine-local stdio configurations from this checkout, not fixed user paths."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
python = root / ".venv-mcp/Scripts/python.exe"
blender = root / ".venv-mcp/Scripts/mcp-for-blender.exe"
sw = root / "integrations/solidworks-mcp/server.py"
for path in (python, blender, sw):
    if not path.is_file():
        raise SystemExit(f"Missing installed dependency: {path}")
servers = {
    "multi_cad_blender": {"command": str(blender), "args": [], "env": {
        "BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": "9876", "BLENDER_MCP_DISABLE_TELEMETRY": "1"}},
    "multi_cad_solidworks": {"command": str(python), "args": [str(sw)]},
}
destination = root / "integrations/mcp.local.json"
if destination.exists():
    raise SystemExit("Configuration exists; preserve user choices and edit it explicitly")
destination.write_text(json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8")
lines = []
for name, server in servers.items():
    lines += [f"[mcp_servers.{name}]", f"command = {json.dumps(server['command'])}",
              f"args = {json.dumps(server['args'])}", "startup_timeout_sec = 60", "tool_timeout_sec = 120"]
    if server.get("env"):
        lines.append(f"[mcp_servers.{name}.env]")
        lines += [f"{key} = {json.dumps(value)}" for key, value in server["env"].items()]
    lines.append("")
(root / "integrations/codex.local.toml").write_text("\n".join(lines), encoding="utf-8")
print("Generated local MCP configurations")
