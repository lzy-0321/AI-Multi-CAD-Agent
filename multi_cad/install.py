"""Explicit pinned installs, kept separate from environment discovery."""
import subprocess
import sys
import time
import os
import asyncio
from pathlib import Path
from .config import home, load, save

SOURCES = {
    "blender": {"url": "https://github.com/ahujasid/mcp-for-blender.git", "commit": "25e1fe008fc523b1a947c6f3d28510a362a0f06e"},
    "solidworks": {"url": "https://github.com/HarrierPigeon/Solidworks-MCP-Server.git", "commit": "60c11fe45b6cfc60c4e2da8ad41fc725a48bf8ea"},
}


def use_sw_host(config, source, python=None):
    source = Path(source).resolve()
    if not (source / "server.py").is_file():
        raise ValueError("Selected SolidWorks MCP source lacks server.py")
    args = ["-m", "multi_cad.sw_host", "--source", str(source)]
    software = config["software"].get("solidworks", {})
    for key, option in (("part_template", "--part-template"), ("assembly_template", "--assembly-template")):
        if software.get(key):
            args.extend([option, software[key]])
    config["backends"]["solidworks"] = {"transport": "stdio", "command": str(Path(python or sys.executable).resolve()), "args": args}


async def check_backend(name, entry, directory):
    from .backend import Backend
    backend = Backend(name, entry, directory)
    try:
        await backend.request('catalog')
        required = 'solidworks_list_documents' if name == 'solidworks' else 'get_scene_info'
        if required not in backend.tools:
            raise ValueError(f'Backend handshake missing required tool: {required}')
    finally:
        await backend.close()


def project_wheel(explicit=None):
    from .release import managed_root
    import json
    candidate = explicit or os.environ.get('MULTI_CAD_WHEEL')
    root = managed_root()
    if not candidate and root:
        candidate = json.loads((root / 'current.json').read_text(encoding='utf-8'))['wheel']
    if not candidate or not Path(candidate).is_file() or not Path(candidate).name.startswith('ai_multi_cad_agent-'):
        raise ValueError('Supply --wheel from the release ZIP, or use the installed launch.ps1 entry')
    return Path(candidate).resolve()


def install_backend(name, config_path=None, wheel=None):
    # Resolve the artifact before downloading anything. A source checkout is never required.
    artifact = project_wheel(wheel) if name == 'solidworks' else None
    source = SOURCES[name]
    root = home() / "backends" / name / (source["commit"][:12] + "-" + str(time.time_ns()))
    root.mkdir(parents=True, exist_ok=False)
    repo, env = root / "source", root / "venv"
    def run(args):
        subprocess.run(args, check=True)
    run(["git", "clone", source["url"], str(repo)])
    run(["git", "-C", str(repo), "checkout", "--detach", source["commit"]])
    actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if actual != source["commit"]:
        raise ValueError("Upstream revision mismatch")
    run([sys.executable, "-m", "venv", str(env)])
    python = env / "Scripts/python.exe"
    constraints = root / "constraints.txt"
    constraints.write_text("mcp>=1.26,<2\n", encoding="utf-8")
    if name == "blender":
        run([str(python), "-m", "pip", "install", "-c", str(constraints), str(repo)])
    else:
        run([str(python), "-m", "pip", "install", "-c", str(constraints), "-r", str(repo / "requirements.txt")])
        run([str(python), "-m", "pip", "install", str(artifact)])
    config = load(config_path)
    if name == "blender":
        config["backends"][name] = {"command": str(env / "Scripts/mcp-for-blender.exe"), "args": [],
            "env": {"BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": "9876", "BLENDER_MCP_DISABLE_TELEMETRY": "1"}}
    else:
        use_sw_host(config, repo, python)
    config["backends"][name]["provenance"] = {**source, "installed_at": time.time()}
    (root / "requirements.lock.txt").write_text(subprocess.check_output([str(python), "-m", "pip", "freeze"], text=True), encoding="utf-8")
    asyncio.run(check_backend(name, config['backends'][name], root / 'handshake'))
    save(config, config_path)
    return {"installed": name, "location": str(root), "addon_action_required": name == "blender"}
