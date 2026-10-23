import argparse
import json
import shutil
import subprocess
import asyncio
from pathlib import Path

from .project import create_project, resume_analysis, write_json
from .environment import solidworks_status
from . import config


def blender_path(explicit=None, config_path=None):
    settings = config.load(config_path)
    choice = config.discover("blender", explicit, settings["software"].get("blender", {}).get("executable"))
    if choice["status"] != "selected":
        raise ValueError(f"Select Blender with setup or --executable: {choice}")
    return choice["candidates"][0]


def export_blender(project, executable):
    project = Path(project).resolve()
    state = json.loads((project / "project.json").read_text(encoding="utf-8"))
    if state["stages"]["analysis"] != "complete":
        raise ValueError("Complete analysis before exporting")
    output = project / "output/blender/Project.blend"
    if output.exists():
        raise ValueError("Output already exists; create a new project to preserve this version")
    if not executable:
        raise ValueError("Blender not found; supply --executable")
    worker = Path(__file__).with_name("blender_worker.py")
    state["stages"]["blender"] = "running"
    write_json(project / "project.json", state)
    try:
        for mode in ("build", "verify"):
            with (project / f"reports/blender_{mode}.log").open("w", encoding="utf-8") as log:
                subprocess.run([executable, "--background", "--factory-startup", "--python-exit-code", "1",
                                "--python", str(worker), "--", str(project), mode],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        if not output.is_file():
            raise ValueError("Blender did not save the output")
        state["stages"]["blender"] = "complete"
        state.pop("error", None)
    except Exception as error:
        state["stages"]["blender"] = "failed"
        state["error"] = str(error)
        raise
    finally:
        write_json(project / "project.json", state)


def main():
    parser = argparse.ArgumentParser(description="AI Multi-CAD foundation CLI")
    parser.add_argument("--config", help="Machine config override (default: user-local MultiCAD/config.json)")
    commands = parser.add_subparsers(dest="command", required=True)
    analyse = commands.add_parser("analyse")
    analyse.add_argument("source")
    analyse.add_argument("--project", required=True)
    analyse.add_argument("--goal", default="保留独立网格并分析")
    resume = commands.add_parser("resume")
    resume.add_argument("project")
    blender = commands.add_parser("blender")
    blender.add_argument("project")
    blender.add_argument("--executable")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--live", action="store_true", help="Query MCP and CAD; may launch CAD")
    doctor.add_argument('--report', help='Write a shareable, allowlisted diagnosis JSON')
    setup = commands.add_parser("setup")
    setup.add_argument("--non-interactive", action="store_true")
    setup.add_argument('--repair', action='store_true')
    setup.add_argument('--apply', action='store_true', help='Apply explicit noninteractive repairs; default is preview')
    setup.add_argument('--export-to', help='Explicit Agent configuration destination')
    setup.add_argument('--format', choices=['json', 'codex'], default='json')
    setup.add_argument("--blender")
    setup.add_argument("--solidworks")
    setup.add_argument("--import-mcp")
    setup.add_argument("--blender-server", help="Name of an existing entry in the imported MCP config")
    setup.add_argument("--solidworks-server", help="Name of an existing entry in the imported MCP config")
    setup.add_argument("--use-sw-host", help="Path to the pinned SW MCP source")
    setup.add_argument("--part-template")
    setup.add_argument("--assembly-template")
    export = commands.add_parser("export-config")
    export.add_argument("destination")
    export.add_argument("--format", choices=["json", "codex"], default="json")
    export.add_argument("--disable-server", action="append", default=[], help="Explicitly disable a named direct server in Codex TOML, preserving its settings")
    install = commands.add_parser("install-backend")
    install.add_argument("backend", choices=["blender", "solidworks"])
    install.add_argument('--wheel', help='Release project wheel, needed for SW outside a managed installation')
    rollback = commands.add_parser('rollback')
    rollback.add_argument('--root', help='Installation directory; defaults to this managed installation')
    plate = commands.add_parser("plate")
    plate.add_argument("action", choices=["create", "edit", "verify"])
    plate.add_argument("project")
    plate.add_argument("--hole-diameter", type=float, default=6)
    args = parser.parse_args()
    try:
        if args.command == "analyse":
            print(create_project(args.source, args.project, args.goal))
        elif args.command == "resume":
            resume_analysis(args.project)
        elif args.command == "blender":
            export_blender(args.project, blender_path(args.executable, args.config))
            print("Saved and reopened Blender project successfully")
        elif args.command == "setup":
            for value in (args.part_template, args.assembly_template):
                if value and not Path(value).is_file():
                    raise ValueError(f'Template does not exist: {value}')
            mapping = {name: getattr(args, name + "_server") for name in ("blender", "solidworks") if getattr(args, name + "_server")}
            if args.repair:
                result = config.repair(args.config, {'blender': args.blender, 'solidworks': args.solidworks},
                    args.import_mcp, mapping or None, not args.non_interactive, args.apply,
                    {'part_template': args.part_template, 'assembly_template': args.assembly_template}, args.use_sw_host)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return
            result = config.setup(args.config, {"blender": args.blender, "solidworks": args.solidworks}, args.import_mcp, not args.non_interactive, mapping or None)
            if args.use_sw_host or args.part_template or args.assembly_template:
                from .install import use_sw_host
                settings = config.load(args.config)
                for key in ("part_template", "assembly_template"):
                    if getattr(args, key):
                        settings["software"].setdefault("solidworks", {})[key] = getattr(args, key)
                if args.use_sw_host:
                    use_sw_host(settings, args.use_sw_host)
                else:
                    entry = settings['backends'].get('solidworks', {})
                    host_args = entry.get('args', [])
                    if 'multi_cad.sw_host' in host_args:
                        for key, option in (('part_template', '--part-template'), ('assembly_template', '--assembly-template')):
                            if getattr(args, key):
                                if option in host_args:
                                    host_args[host_args.index(option) + 1] = getattr(args, key)
                                else:
                                    host_args.extend([option, getattr(args, key)])
                config.save(settings, args.config)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            destination = args.export_to
            if not destination and not args.non_interactive:
                destination = input('Agent configuration file to merge (empty = export later): ').strip().strip('"')
                if destination and Path(destination).suffix.lower() == '.toml':
                    args.format = 'codex'
            if destination:
                config.export_client(destination, args.config, args.format)
        elif args.command == "export-config":
            if args.disable_server and args.format != "codex":
                raise ValueError("Disabling entries is only supported for Codex TOML")
            config.export_client(args.destination, args.config, args.format)
            if args.disable_server:
                config.disable_codex_servers(args.destination, args.disable_server)
            print("Gateway entry merged; restart the selected Agent client to load it")
        elif args.command == "install-backend":
            from .install import install_backend
            print(json.dumps(install_backend(args.backend, args.config, args.wheel), ensure_ascii=False))
        elif args.command == 'rollback':
            from .release import rollback
            print(json.dumps(rollback(args.root), ensure_ascii=False, indent=2))
        elif args.command == "doctor" and not args.live:
            from .gateway import Gateway
            status = asyncio.run(Gateway(config.load(args.config)).status(False))
            from .diagnostics import report, save_report
            print(json.dumps(save_report(args.report, status) if args.report else report(status), ensure_ascii=False, indent=2))
        else:
            from .gateway import Gateway
            async def run():
                gateway = Gateway(config.load(args.config))
                try:
                    if args.command == "doctor":
                        return await gateway.status(True)
                    from .plate import run_plate
                    return await run_plate(gateway.backend("solidworks"), Path(args.project), args.action, args.hole_diameter)
                finally:
                    await gateway.close()
            result = asyncio.run(run())
            if args.command == 'doctor':
                from .diagnostics import report, save_report
                result = save_report(args.report, result) if args.report else report(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Error: {error}\n")
