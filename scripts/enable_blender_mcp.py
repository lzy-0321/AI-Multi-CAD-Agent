"""Run with the selected Blender executable after installing the upstream addon."""
import addon_utils
import bpy

addon_utils.enable("blender_mcp", default_set=True, persistent=True)
if "blender_mcp" not in bpy.context.preferences.addons:
    raise RuntimeError("Blender MCP addon did not enable")
bpy.ops.wm.save_userpref()
print("BLENDER_MCP_ADDON_ENABLED")
