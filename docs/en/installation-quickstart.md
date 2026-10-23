[中文](../installation-quickstart.md) | **English**

# Multi-CAD Windows candidate installation guide

Requires Windows and 64-bit Python 3.11+. Actual modeling also requires CAD that is available and licensed on this machine. Installation downloads Python dependencies over the network. It does not bundle CAD, a license, or a model API. End-to-end testing of this candidate on a second computer is not finished.

## Installer

Extract the ZIP and run this in its directory (administrator rights are not required):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
# Custom directory and Python:
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -InstallDir "D:\工具\Multi CAD" -Python "C:\Python314\python.exe"
```

The installer creates an isolated environment, installs dependencies over the network, and switches the active version only after the gateway MCP handshake succeeds. It does not start CAD and does not create a part. The default directory is `%LOCALAPPDATA%\MultiCAD`. Failure details are in `install.log` inside the new version directory. An existing entry stays active. If Python is missing, install 64-bit Python from https://www.python.org/downloads/windows/ and run the installer again.

## Configure CAD and an existing MCP server

Run the following commands in the installation directory. `launch.ps1` always uses the version that installed successfully. Call it by absolute path from any working directory.

```powershell
.\launch.ps1 setup
.\launch.ps1 doctor --report .\diagnosis.json
.\launch.ps1 export-config "D:\Agent settings\mcp.json"
# Codex configuration uses --format codex:
.\launch.ps1 export-config "D:\项目\.codex\config.toml" --format codex
```

The wizard prefers existing paths and MCP servers. It asks only when something is missing or more than one version is present. An existing MCP configuration can be imported:

```powershell
.\launch.ps1 setup --import-mcp "D:\settings\mcp.json" --solidworks-server my-sw --blender-server my-blender
```

If there is no MCP server, explicitly choose a pinned upstream version (Git and network required):

```powershell
.\launch.ps1 install-backend solidworks
.\launch.ps1 install-backend blender
```

The upstream source and pinned commit are recorded in the ZIP's `release.json`. Backend configuration is saved only after installation succeeds and the handshake tool check passes. SolidWorks uses the compatibility host shipped as a wheel, so a source directory is not required. Blender still needs the add-on installed and enabled in the selected version: run `venv\Scripts\mcp-for-blender.exe addon-paths` in the install result directory to see the target, then run that tool's `install-addon --help` and pass the upstream options for the target. Do not mark configuration complete only because the add-on is already installed in a different Blender version.

Export merges only the unified service and does not overwrite other services. A different `multi_cad` entry with the same name stops the export and reports a conflict. An older source-tree entry has to be removed by the user as that single entry before exporting again. Do not delete the whole agent configuration. Restart the agent after the new entry is loaded. For daily use, enable only the unified gateway.

## Repair and diagnosis

```powershell
.\launch.ps1 setup --repair
# Automation previews first, then add --apply after confirmation:
.\launch.ps1 setup --repair --non-interactive --solidworks "F:\solidworks\SOLIDWORKS\SLDWORKS.exe"
.\launch.ps1 setup --repair --non-interactive --solidworks "F:\solidworks\SOLIDWORKS\SLDWORKS.exe" --apply
.\launch.ps1 doctor --live --report .\diagnosis-live.json
```

Repair does not automatically choose another CAD version. Replacing an existing MCP server requires naming the imported entry. The command, argument array, and working directory can be configured separately. Repair shows a summary of field changes before saving, and it writes a backup. `.bak` files under the configuration directory can contain local environment details; review them before sharing.

`doctor` does not start CAD. `--live` calls CAD and may start the application. The report separates installation, COM registration, MCP connection, CAD callability, and historical business acceptance. History includes a timestamp and whether the configuration matches. It does not mean the current connection is healthy. The report omits environment-variable values, full command arguments, raw errors, and model content. Raw errors are in the local `cache\*-stderr.log` files; inspect them before sharing.

When Blender cannot be called, check that the add-on is enabled for the target version and that the localhost port matches. When SolidWorks registration does not match, choose a registered installation or use the application's own registration repair. After a write timeout, inspect the actual model state first. The agent then records evidence with `reconcile_write`. Do not replay the modeling operation directly.

## Explicit modeling acceptance

Configure a valid SolidWorks part template. With upstream source available:

```powershell
.\launch.ps1 setup --repair --use-sw-host "D:\MCP\Solidworks-MCP-Server" --part-template "D:\templates\Part.prtdot"
.\launch.ps1 plate create "D:\CAD projects\验收底板" --hole-diameter 6
.\launch.ps1 plate edit "D:\CAD projects\验收底板" --hole-diameter 8
.\launch.ps1 plate verify "D:\CAD projects\验收底板"
```

The agent's `plate_workflow` runs the same flow. Acceptance covers only the constrained plate: 120×80×5 mm, with four holes 10 mm from the edges. Do not start several clients that modify the same CAD session.

## Upgrade and rollback

Run `install.ps1` from a new ZIP against the same installation directory. The installer keeps the old environment, backs up the local configuration before activation, and the agent still points at the stable `launch.ps1`. Restart the agent after an upgrade.

```powershell
.\launch.ps1 rollback
```

Rollback restores the previous successful program version and the pre-upgrade configuration, and it backs up the configuration from before the rollback. If there is no older configuration snapshot, the current configuration is kept. CAD project files are not deleted or reverted. A first install has no version to roll back to. Old versions are not cleaned up automatically, so an environment still referenced by MCP is not removed.
