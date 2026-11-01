**English** | [中文](README.zh-CN.md)

# AI Multi-CAD Agent v0.4.0

A local CAD tool system for an existing AI agent. The agent understands natural language; this project provides configuration, capability discovery, MCP dispatch, project versions, and verification. It needs no extra model API and does not embed a chat model.

## Current capabilities

- Independent user configuration and limited path discovery. Existing Blender and SolidWorks stdio MCP servers can be reused.
- One MCP entry point, with on-demand tool search and parameter schema reads. Connections stay open, calls run serially, and results are summarized in a local log.
- Known read-only operations are retried at most once. Write operations are not replayed. After a timeout or a process interruption, check the actual state and explicitly clear the block.
- Parametric creation, hole-diameter edits, version files, and reopen checks for one constrained base plate. This is not a general text-to-model algorithm.
- Selected-part 3MF editing: slicer roles/plates, explicit instance scope, Blender transforms and cylindrical cuts, bounded SW plate/washer reconstruction, immutable versions and reopen checks. See [part workflow](docs/parts-workflow.md).
- Version 0.4.0 ships selected-part editing; see the [acceptance record](docs/validation-v0.4.md) for coverage and limitations.

SolidWorks uses the existing [HarrierPigeon MCP](https://github.com/HarrierPigeon/Solidworks-MCP-Server). Blender uses [ahujasid MCP](https://github.com/ahujasid/mcp-for-blender). This project does not rewrite their modeling tools. An optional SolidWorks compatibility host adds exact acceptance queries, template-path configuration, and dimension-dialog handling. Upstream source stays unchanged.

## Install and configure

For the Windows release, download `MultiCAD-0.4.0-windows.zip` from [GitHub Releases](https://github.com/zyphlux/AI-Multi-CAD-Agent/releases). Choose the named ZIP asset, not GitHub's automatic source archive. Follow the [installation guide](docs/installation-quickstart.md). It includes an isolated installer, repair preview, shareable diagnostics and rollback; no source checkout is required. See the [release notes and limitations](docs/releases/v0.4.0.md). Real CAD acceptance on a second computer is pending.

For development from source:

Windows, Python 3.11+, and CAD software that is already installed and can start. From the source root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\python.exe -m multi_cad setup
.\.venv\Scripts\python.exe -m multi_cad doctor
```

Configuration is saved by default at `%LOCALAPPDATA%\MultiCAD\config.json`. `MULTI_CAD_HOME` overrides the data directory. `--config` overrides the configuration file location. A `cad.local.json` in the current directory is migrated automatically, and an older MCP configuration from this project or an existing Codex configuration can be imported. The setup asks only when nothing is found or more than one version exists. Non-interactive mode returns a `needs_input` list. An explicit path that no longer works is not silently replaced with another software version.

Reuse an existing MCP server from any directory:

```powershell
python -m multi_cad setup --import-mcp "D:\settings\mcp.json" --blender-server blender --solidworks-server sw
```

The input can be a generic `mcpServers` JSON file or Codex TOML. An existing local backend configuration is kept. Changing a backend requires an explicit edit of the local configuration or an install command. The MCP command, argument array, working directory, and environment variables are independent of the CAD executable path. Blender accepts only a local loopback connection, and the port is configurable.

When a backend is missing, explicitly install a pinned upstream version (network and Git required):

```powershell
python -m multi_cad install-backend blender
python -m multi_cad install-backend solidworks --wheel "dist\ai_multi_cad_agent-0.4.0-py3-none-any.whl"
```

Each install uses a new directory and keeps the previous environment and configuration backup. The source commit and the actual dependency list are stored in the install directory. Blender also needs the upstream add-on installed and enabled: run `mcp-for-blender.exe install-addon` from the new environment, then enable the add-on in the target Blender preferences. With several Blender versions, confirm the target with `addon-paths` first. An existing install is not reinstalled automatically.

## Connect an agent

Run these commands with the Python environment where this project is installed:

```powershell
python -m multi_cad export-config "D:\settings\mcp.json"
python -m multi_cad export-config ".codex\config.toml" --format codex
python -m multi_cad doctor --live
```

Export adds only the unified `multi_cad` service, preserves the rest of the configuration, and writes a backup. A same-named entry with different settings is reported as a conflict. Restart the agent client to load it. For daily use, enable only the unified entry. Leave the older direct CAD MCP servers for diagnosis, so two clients do not modify the same CAD session. `doctor --live` may start CAD. Without `--live`, no CAD application is started. A successful connection does not mean modeling has been verified.

For Codex, add `--disable-server OLD_SERVER_NAME` after the export command (the option can be repeated). It disables only the named direct server and keeps that server's original settings. Other servers are left unchanged.

Agent instructions: [Tool calls and project flow](docs/agent-workflow.md). The first release supports local Windows stdio and provides Codex TOML plus generic JSON configuration. It does not assume every client uses the same configuration layout.

## Parametric base-plate acceptance

The plate is 120 × 80 × 5 mm. The four hole centers are (10,10), (110,10), (110,70), and (10,70) mm. This high-level recipe supports only that shape. For every other task, the agent searches downstream tools and plans the work.

When an existing SolidWorks MCP source tree is available, enable the optional compatibility host (the current Python must already have the upstream dependencies):

```powershell
python -m multi_cad setup --use-sw-host "D:\MCP\Solidworks-MCP-Server" --part-template "D:\templates\Part.prtdot"
python -m multi_cad plate create "runs\plate" --hole-diameter 6
python -m multi_cad plate edit "runs\plate" --hole-diameter 8
python -m multi_cad plate verify "runs\plate"
```

Each command can run in a new process. An edit starts from a working copy of a verified file and checks the hash, the geometry, and the complete parameter map. An ambiguous map stops the command. A new version is registered only after verification succeeds. The previous version is not overwritten. A failed file is saved separately and marked failed. Other documents the user has open are left open. High-level acceptance requires the optional `multi_cad_inspect_part` capability. Other MCP servers can be called through the generic interface, but that does not count as passing this recipe.

## Original 3MF flow and limits

```powershell
python -m multi_cad analyse "source.3mf" --project "runs\mesh" --goal "保留独立对象"
python -m multi_cad blender "runs\mesh" --executable "D:\Blender\blender.exe"
```

A 3MF mesh resource is a candidate resource, not a confirmed product part. Slicer plate membership and declared part/negative roles are parsed; unknown roles are retained and block unsafe edits. Materials/textures, general reverse engineering and assembly inference remain unsupported. Print transforms are stored separately from real assembly positions. A screenshot does not replace dimensional verification.

## Tests

```powershell
python -m unittest discover -v
```

Tests need the `[mcp]` extra. Protocol tests use a fake MCP server and do not start CAD. On-machine acceptance is the base-plate flow above, run separately. Full schemas and logs stay in the local cache. Query results are truncated by default and include a file reference. Context-size reports use character and UTF-8 byte counts; they are not presented as actual model token usage.

On-machine acceptance and limits: [v0.2 validation record](docs/validation-v0.2.md). Release install guide: [Windows release installation guide](docs/installation-quickstart.md). Product requirements: [Requirements v2](docs/requirements-v2.md).
