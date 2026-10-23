"""A real stdio fixture for transport, failure and cache tests; never touches CAD."""
import asyncio
import os
from mcp.server.fastmcp import FastMCP

server = FastMCP("fixture")

if os.environ.get('BLENDER_PORT_FAILURE'):
    @server.tool()
    def get_scene_info() -> dict:
        return {'error': 'Connection refused: fixture Blender port is unavailable'}

@server.tool()
def solidworks_list_documents() -> dict:
    return {"documents": [], "version_marker": os.environ.get("FIXTURE_VERSION", "1")}

@server.tool()
def textual_failure() -> str:
    return "❌ Failed to create feature"

@server.tool()
async def delayed_write() -> str:
    await asyncio.sleep(5)
    return "done"

if __name__ == "__main__":
    server.run()
