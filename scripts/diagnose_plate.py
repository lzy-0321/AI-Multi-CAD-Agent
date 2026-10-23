"""Inspect an explicitly selected failure artifact through MCP, without editing it."""
import asyncio
import json
import sys
from pathlib import Path
from multi_cad.gateway import Gateway
from multi_cad.config import load

async def main():
    gateway = Gateway(load(sys.argv[1]))
    backend = gateway.backend("solidworks")
    title = None
    try:
        result = await backend.invoke("solidworks_open_document", {"path": str(Path(sys.argv[2]).resolve())})
        print(json.dumps(result.get("data"), ensure_ascii=False))
        title = result.get("data", {}).get("title")
        print(json.dumps(await backend.invoke("multi_cad_inspect_part", {}), ensure_ascii=False))
    finally:
        if title:
            await backend.invoke("solidworks_close_document", {"name": title})
        await gateway.close()

asyncio.run(main())
