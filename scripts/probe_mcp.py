"""Bounded protocol handshake; stores full schemas locally, prints compact summaries."""
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def probe(name, config, call):
    env = dict(os.environ)
    env.update(config.get("env", {}))
    params = StdioServerParameters(command=config["command"], args=config.get("args", []), env=env,
                                  cwd=config.get("cwd"))
    async with asyncio.timeout(90):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()
                tools = list(listed.tools)
                while listed.nextCursor:
                    listed = await session.list_tools(cursor=listed.nextCursor)
                    tools.extend(listed.tools)
                result = {"name": name, "checked_at": datetime.now(timezone.utc).isoformat(),
                          "server": initialized.serverInfo.model_dump(),
                          "tools": [tool.model_dump() for tool in tools]}
                if call:
                    response = await session.call_tool(call, {})
                    result["call"] = response.model_dump(mode="json")
                target = Path("runs/mcp")
                target.mkdir(parents=True, exist_ok=True)
                (target / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                summary = {"name": name, "tool_count": len(tools), "server": result["server"]}
                if call:
                    summary["call"] = result["call"]
                print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--call", help="Explicit tool call, empty arguments only")
    args = parser.parse_args()
    configuration = json.loads(Path("integrations/mcp.local.json").read_text(encoding="utf-8"))
    asyncio.run(probe(args.name, configuration["mcpServers"][args.name], args.call))
