"""Machine configuration and bounded discovery; no CAD process is started here."""
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .project import write_json


def home():
    return Path(os.environ.get("MULTI_CAD_HOME", Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "MultiCAD"))


def load(path=None):
    path = Path(path or home() / "config.json")
    if not path.exists():
        return {"schema_version": 2, "software": {}, "backends": {}}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("schema_version") != 2:
        raise ValueError("Unsupported machine configuration version")
    return value


def save(value, path=None):
    path = Path(path or home() / "config.json")
    validate(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + f".{time.time_ns()}.bak"))
    write_json(path, value)
    return path


def validate(value):
    for name, backend in value.get("backends", {}).items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ValueError("Invalid backend name")
        if backend.get("transport", "stdio") != "stdio":
            raise ValueError("v0.2 supports local stdio only")
        if not isinstance(backend.get("command"), str) or not backend["command"]:
            raise ValueError(f"Missing command for {name}")
        if not isinstance(backend.get("args", []), list) or not all(isinstance(x, str) for x in backend.get("args", [])):
            raise ValueError("MCP args must be a string array")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in backend.get("env", {}).items()):
            raise ValueError("MCP env must contain string values")
        env = backend.get("env", {})
        if name == "blender":
            if env.get("BLENDER_HOST", "localhost") not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("v0.2 requires a loopback Blender connection")
            if not 1024 <= int(env.get("BLENDER_PORT", 9876)) <= 65535:
                raise ValueError("Invalid Blender port")


def registered_solidworks():
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID") as key:
            clsid = winreg.QueryValueEx(key, "")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32") as key:
            raw = winreg.QueryValueEx(key, "")[0]
        match = re.match(r'^\s*"([^"]+)"|^\s*(.+?\.exe)(?:\s|$)', raw, re.I)
        return (match.group(1) or match.group(2)) if match else None
    except OSError:
        return None


def discover(name, explicit=None, saved=None, registry=None, path_lookup=None, common=None):
    """An invalid explicit/saved choice must not silently fall back to another version."""
    for source, candidate in (("explicit", explicit), ("saved", saved)):
        if candidate:
            path = Path(os.path.expandvars(candidate)).expanduser()
            return {"status": "selected" if path.is_file() else "needs_input", "source": source,
                    "candidates": [str(path)], "reason": None if path.is_file() else "configured_path_missing"}
    candidates = []
    registered = registry() if registry else (registered_solidworks() if name == "solidworks" else None)
    if registered:
        candidates.append(registered)
    command = "SLDWORKS.exe" if name == "solidworks" else "blender"
    found = (path_lookup or shutil.which)(command)
    if found:
        candidates.append(found)
    if common is None:
        program = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        common = list((program / "Blender Foundation").glob("Blender */blender.exe")) if name == "blender" else list(program.glob("SOLIDWORKS*/SOLIDWORKS/SLDWORKS.exe"))
    candidates.extend(map(str, common))
    unique = {os.path.normcase(str(Path(p).resolve())): str(Path(p).resolve()) for p in candidates if Path(p).is_file()}
    paths = list(unique.values())
    return {"status": "selected" if len(paths) == 1 else "needs_input", "source": "discovery",
            "candidates": paths, "reason": "multiple_versions" if len(paths) > 1 else ("not_found" if not paths else None)}


def import_servers(config, path, mapping=None):
    """Import explicitly chosen JSON MCP entries, preserving other local backends."""
    if Path(path).suffix == ".toml":
        import tomllib
        servers = tomllib.loads(Path(path).read_text(encoding="utf-8-sig")).get("mcp_servers", {})
    else:
        servers = json.loads(Path(path).read_text(encoding="utf-8-sig")).get("mcpServers", {})
    if mapping is None:
        mapping = {}
        for backend in ("blender", "solidworks"):
            if backend in config["backends"]:
                continue
            candidates = [name for name, server in servers.items() if backend in name.lower() and server.get("command") and server.get("enabled", True)]
            if len(candidates) > 1:
                raise ValueError(f"Multiple {backend} MCP entries {candidates}; select --{backend}-server")
            if candidates:
                mapping[backend] = candidates[0]
    for backend, entry in mapping.items():
        if entry in servers and backend not in config["backends"]:
            source = servers[entry]
            if source.get("url"):
                raise ValueError("Only local stdio MCP imports are supported")
            config["backends"][backend] = {k: v for k, v in source.items() if k in ("command", "args", "cwd", "env")}
            config["backends"][backend]["transport"] = "stdio"
    validate(config)


def setup(path=None, explicit=None, import_path=None, interactive=True, mapping=None):
    config = load(path)
    explicit = explicit or {}
    legacy = Path("cad.local.json")
    if legacy.exists():
        old = json.loads(legacy.read_text(encoding="utf-8"))
        for name in ("solidworks", "blender"):
            if old.get(name + "_executable"):
                config["software"].setdefault(name, {"executable": old[name + "_executable"]})
    if import_path:
        import_servers(config, import_path, mapping)
    elif not config["backends"] and Path("integrations/mcp.local.json").is_file():
        import_servers(config, "integrations/mcp.local.json")
    elif not config["backends"] and (Path.home() / ".codex/config.toml").is_file():
        import_servers(config, Path.home() / ".codex/config.toml", mapping)
    questions = []
    for name in ("blender", "solidworks"):
        selected = discover(name, explicit.get(name) or os.environ.get(name.upper() + "_EXECUTABLE"),
                            config["software"].get(name, {}).get("executable"))
        if selected["status"] == "needs_input" and interactive:
            print(f"{name}: {selected['reason']} {selected['candidates']}")
            answer = input("Executable path (empty = configure later): ").strip().strip('"')
            if answer:
                selected = discover(name, explicit=answer)
        if selected["status"] == "selected":
            config["software"].setdefault(name, {})["executable"] = selected["candidates"][0]
        else:
            questions.append({"software": name, **selected})
        if name not in config["backends"]:
            if interactive:
                command = input(f"{name} MCP executable (empty = install later): ").strip().strip('"')
                if command:
                    args = json.loads(input('MCP arguments as JSON array ([]): ').strip() or "[]")
                    cwd = input("MCP working directory (empty = default): ").strip()
                    entry = {"transport": "stdio", "command": command, "args": args}
                    if cwd:
                        entry["cwd"] = cwd
                    if name == "blender":
                        entry["env"] = {"BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": input("Blender port (9876): ").strip() or "9876",
                                        "BLENDER_MCP_DISABLE_TELEMETRY": "1"}
                    config["backends"][name] = entry
            if name not in config["backends"]:
                questions.append({"backend": name, "reason": "mcp_not_configured"})
    target = save(config, path)
    return {"config": str(target), "needs_input": questions}


def export_client(destination, config_path=None, format="json"):
    """Merge only the gateway entry; never rewrite unrelated client settings."""
    destination = Path(destination)
    command = str(Path(sys.executable).resolve())
    args = ["-m", "multi_cad.gateway", "--config", str(Path(config_path or home() / "config.json").resolve())]
    from .release import managed_root
    root = managed_root()
    if root:
        command = shutil.which('powershell.exe') or 'powershell.exe'
        args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'launch.ps1'),
                '-Gateway', '-ConfigPath', str(Path(config_path or root / 'config.json').resolve())]
    if format == "json":
        data = json.loads(destination.read_text(encoding="utf-8-sig")) if destination.exists() else {}
        entries = data.setdefault("mcpServers", {})
        entry = {"command": command, "args": args}
        if entries.get("multi_cad") == entry:
            return
        if "multi_cad" in entries:
            raise ValueError("A different multi_cad entry exists; resolve explicitly")
        entries["multi_cad"] = entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.copy2(destination, destination.with_name(destination.name + f".{time.time_ns()}.bak"))
        write_json(destination, data)
    else:
        import tomllib
        text = destination.read_text(encoding="utf-8") if destination.exists() else ""
        entries = tomllib.loads(text).get("mcp_servers", {})
        if "multi_cad" in entries:
            if entries["multi_cad"].get("command") == command and entries["multi_cad"].get("args") == args:
                return
            raise ValueError("A different multi_cad entry exists; resolve explicitly")
        text += "\n[mcp_servers.multi_cad]\ncommand = " + json.dumps(command) + "\nargs = " + json.dumps(args) + "\nstartup_timeout_sec = 60\ntool_timeout_sec = 300\n"
        tomllib.loads(text)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.copy2(destination, destination.with_name(destination.name + f".{time.time_ns()}.bak"))
        destination.write_text(text, encoding="utf-8")


def inspect_environment(config):
    result = {}
    registered = registered_solidworks()
    for name in ("blender", "solidworks"):
        executable = config.get("software", {}).get(name, {}).get("executable")
        backend = config.get("backends", {}).get(name)
        result[name] = {"installed": bool(executable and Path(executable).is_file()),
                        "registered": bool(registered) if name == "solidworks" else None,
                        "registration_matches": (os.path.normcase(registered) == os.path.normcase(executable)) if registered and executable and name == "solidworks" else None,
                        "mcp_configured": bool(backend), "mcp_connected": "not_checked",
                        "cad_callable": "not_checked", "capabilities_verified": []}
    return result


def repair(path=None, explicit=None, import_path=None, mapping=None, interactive=True,
           apply=False, templates=None, sw_host=None):
    """Prepare repairs in memory; noninteractive defaults to preview, never silent replacement."""
    import copy
    original = load(path)
    proposed = copy.deepcopy(original)
    explicit = explicit or {}
    needs = []
    choices = []
    for name in ('blender', 'solidworks'):
        saved = original['software'].get(name, {}).get('executable')
        selected = discover(name, explicit=explicit.get(name), saved=saved)
        if selected['status'] != 'selected':
            found = discover(name)
            choices.append({'software': name, 'old': saved, 'candidates': found['candidates']})
            if interactive:
                print(f"{name}: configured path {saved!r}; candidates: {found['candidates']}")
                answer = input('Choose executable path (empty = keep unresolved): ').strip().strip('"')
                if answer:
                    selected = discover(name, explicit=answer)
        if selected['status'] == 'selected':
            proposed['software'].setdefault(name, {})['executable'] = selected['candidates'][0]
        else:
            needs.append({'software': name, 'reason': selected['reason']})
    if import_path:
        if not mapping:
            raise ValueError('Repair imports require explicit --blender-server / --solidworks-server to choose replacements')
        imported = {'backends': {}}
        import_servers(imported, import_path, mapping)
        if set(imported['backends']) != set(mapping):
            raise ValueError('Selected MCP entry missing from import; nothing saved')
        proposed['backends'].update(imported['backends'])
    for name in ('blender', 'solidworks'):
        backend = proposed['backends'].get(name, {})
        command = backend.get('command', '')
        valid_command = bool(command and (Path(command).is_file() or shutil.which(command)))
        valid_cwd = not backend.get('cwd') or Path(backend['cwd']).is_dir()
        if not valid_command or not valid_cwd:
            if interactive:
                print(f'{name}: MCP command or working directory is unavailable. Existing arguments and environment will be retained.')
                answer = input('MCP executable path (empty = keep unresolved): ').strip().strip('"')
                if answer:
                    backend = copy.deepcopy(backend)
                    backend['command'] = answer
                    raw = input('Arguments as JSON array (empty = keep existing): ').strip()
                    if raw:
                        backend['args'] = json.loads(raw)
                    cwd = input('Working directory (empty = inherit): ').strip().strip('"')
                    backend.pop('cwd', None)
                    if cwd:
                        backend['cwd'] = cwd
                    proposed['backends'][name] = backend
                    valid_command = Path(answer).is_file() or bool(shutil.which(answer))
                    valid_cwd = not cwd or Path(cwd).is_dir()
            if not valid_command or not valid_cwd:
                needs.append({'backend': name, 'reason': 'mcp_command_or_cwd_missing'})
    sw = proposed['software'].setdefault('solidworks', {})
    for key, value in (templates or {}).items():
        if value:
            if not Path(value).is_file():
                raise ValueError(f'Template does not exist: {value}')
            sw[key] = str(Path(value).resolve())
    host_args = proposed['backends'].get('solidworks', {}).get('args', [])
    if sw_host or 'multi_cad.sw_host' in host_args:
        template = sw.get('part_template')
        if not template or not Path(template).is_file():
            if interactive:
                answer = input('SolidWorks Part.PRTDOT path (empty = resolve later): ').strip().strip('"')
                if answer and Path(answer).is_file():
                    sw['part_template'] = str(Path(answer).resolve())
            if not sw.get('part_template') or not Path(sw['part_template']).is_file():
                needs.append({'software': 'solidworks', 'reason': 'part_template_unresolved'})
        if sw_host:
            from .install import use_sw_host
            use_sw_host(proposed, sw_host)
        else:
            for key, option in (('part_template', '--part-template'), ('assembly_template', '--assembly-template')):
                if sw.get(key):
                    if option in host_args:
                        host_args[host_args.index(option) + 1] = sw[key]
                    else:
                        host_args.extend([option, sw[key]])
    validate(proposed)
    changes = []
    for group in ('software', 'backends'):
        for name, value in proposed[group].items():
            if original[group].get(name) != value:
                changes.append({'section': group, 'name': name, 'changed_fields': sorted(
                    k for k in set(value) | set(original[group].get(name, {})) if value.get(k) != original[group].get(name, {}).get(k))})
    result = {'changes': changes, 'candidates': choices, 'needs_input': needs, 'saved': False}
    if interactive:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        apply = bool(changes) and input('Save these changes with a backup? [y/N]: ').strip().lower() == 'y'
    if apply and changes:
        save(proposed, path)
        result['saved'] = True
    return result


def disable_codex_servers(path, names):
    """Explicitly disable only named direct servers, retaining their diagnostic configuration."""
    import tomllib
    path = Path(path)
    original = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(original)
    updated = original
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name == "multi_cad":
            raise ValueError("Choose a valid direct server name, not the gateway")
        entry = parsed.get("mcp_servers", {}).get(name)
        if entry is None:
            raise ValueError(f"Server not found: {name}")
        if entry.get("enabled") is False:
            continue
        pattern = rf"(?ms)(^\[mcp_servers\.{re.escape(name)}\][ \t]*\r?\n)(.*?)(?=^\[|\Z)"
        match = re.search(pattern, updated)
        if not match:
            raise ValueError("Cannot safely edit this TOML table layout; edit enabled explicitly")
        body = re.sub(r"(?m)^enabled\s*=.*\n?", "", match.group(2))
        updated = updated[:match.start()] + match.group(1) + "enabled = false\n" + body + updated[match.end():]
    tomllib.loads(updated)
    if updated != original:
        shutil.copy2(path, path.with_name(path.name + f".{time.time_ns()}.bak"))
        path.write_text(updated, encoding="utf-8")
