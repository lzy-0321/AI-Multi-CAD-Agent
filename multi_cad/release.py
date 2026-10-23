"""Versioned per-user installation. Activation is the last, atomic step."""
import json
import os
import shutil
import subprocess
import sys
import time
import hashlib
from pathlib import Path

from .config import home, load, validate
from .project import write_json
from .backend import ProcessLease


def managed_root():
    root = Path(sys.prefix).parent.parent.parent
    return root if (root / 'current.json').is_file() and Path(sys.prefix).parent.parent.name == 'versions' else None


def run(command, log, env=None):
    with Path(log).open('a', encoding='utf-8') as stream:
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT, env=env, cwd=Path(log).parent)


def install(wheel, root, launcher, python=sys.executable, runner=run):
    wheel, root = Path(wheel).resolve(), Path(root).resolve()
    if not wheel.is_file() or not wheel.name.startswith('ai_multi_cad_agent-') or wheel.suffix != '.whl':
        raise ValueError('Select the ai_multi_cad_agent wheel supplied in the release bundle')
    root.mkdir(parents=True, exist_ok=True)
    lease = ProcessLease(root / 'installation.lock')
    try:
        current = root / 'current.json'
        previous = json.loads(current.read_text(encoding='utf-8')) if current.exists() else None
        config_path = root / 'config.json'
        settings = load(config_path)
        validate(settings)
        stamp = str(time.time_ns())
        version = wheel.name.split('-')[1]
        target = root / 'versions' / (version + '-' + stamp)
        target.mkdir(parents=True)
        log = target / 'install.log'
        bundled = target / wheel.name
        shutil.copy2(wheel, bundled)
        interpreter = target / 'venv' / 'Scripts' / 'python.exe'
        try:
            print('Creating isolated Python environment...', flush=True)
            runner([str(python), '-m', 'venv', str(target / 'venv')], log)
            print('Installing wheel and dependencies; details in ' + str(log), flush=True)
            runner([str(interpreter), '-m', 'pip', 'install', str(bundled) + '[mcp]'], log)
            # A real stdio handshake checks the gateway without launching any CAD.
            env = dict(os.environ, MULTI_CAD_HOME=str(root))
            print('Checking gateway handshake (CAD will not start)...', flush=True)
            runner([str(interpreter), '-I', '-m', 'multi_cad.release', 'smoke'], log, env=env)
        except Exception as error:
            write_json(target / 'failed.json', {'stage': 'install_or_handshake', 'error_type': type(error).__name__})
            raise RuntimeError(f'Installation failed; previous entry is unchanged. Inspect local log: {log}') from error
        backup = target / 'config-before.json'
        if config_path.exists():
            shutil.copy2(config_path, backup)
        # The launcher protocol is stable across releases. Never overwrite a modified launcher.
        launch_target = root / 'launch.ps1'
        launcher_bytes = Path(launcher).read_bytes()
        if launch_target.exists() and launch_target.read_bytes() != launcher_bytes:
            raise ValueError('Existing launch.ps1 differs; keep the current installation and resolve explicitly')
        if not launch_target.exists():
            launch_target.write_bytes(launcher_bytes)
        record = {'schema_version': 1, 'version': version, 'python': str(interpreter),
                  'wheel': str(bundled), 'sha256': hashlib.sha256(bundled.read_bytes()).hexdigest(),
                  'activated_at': time.time(), 'previous': previous,
                  'config_before': str(backup) if backup.exists() else None}
        write_json(target / 'installation.json', record)
        write_json(current, record)
        return {'installed': version, 'root': str(root), 'launcher': str(launch_target),
                'cad_verified': False, 'next': 'Run launch.ps1 setup, then export-config to your Agent'}
    finally:
        lease.close()


def rollback(root=None):
    root = Path(root or managed_root() or home()).resolve()
    lease = ProcessLease(root / 'installation.lock')
    try:
        current = root / 'current.json'
        record = json.loads(current.read_text(encoding='utf-8'))
        previous = record.get('previous')
        if not previous or not Path(previous['python']).is_file():
            raise ValueError('No available previous installation; nothing changed')
        config_path = root / 'config.json'
        snapshot = record.get('config_before')
        # Validate all restoration inputs before touching current state.
        if snapshot:
            restored = load(snapshot)
            if not Path(snapshot).is_file():
                raise ValueError('Configuration snapshot missing; nothing changed')
            validate(restored)
        if config_path.exists():
            shutil.copy2(config_path, root / f'config.pre-rollback-{time.time_ns()}.bak')
        before = config_path.read_bytes() if config_path.exists() else None
        try:
            if snapshot:
                write_json(config_path, restored)
            # No old configuration means preserve a subsequently created user configuration.
            write_json(current, previous)
        except Exception:
            if snapshot:
                if before is None:
                    config_path.unlink(missing_ok=True)
                else:
                    temporary = config_path.with_suffix('.restore.tmp')
                    temporary.write_bytes(before)
                    os.replace(temporary, config_path)
            raise
        return {'rolled_back_to': previous['version'], 'restart_agent': True, 'projects_changed': False}
    finally:
        lease.close()


async def smoke():
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async with asyncio.timeout(60):
        async with stdio_client(StdioServerParameters(command=sys.executable,
                args=['-I', '-m', 'multi_cad.gateway'], env=dict(os.environ))) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                tools = await client.list_tools()
                expected = {'environment_status', 'capability_search', 'operation_schema', 'execute_operations',
                            'reconcile_write', 'plate_workflow', 'project_create', 'project_state'}
                if {tool.name for tool in tools.tools} != expected:
                    raise RuntimeError('Gateway tool contract mismatch')
    return {'gateway_handshake': True, 'tools': 8, 'cad_started': False}


if __name__ == '__main__':
    import asyncio
    if sys.argv[1:] != ['smoke']:
        raise SystemExit('Usage: python -m multi_cad.release smoke')
    print(json.dumps(asyncio.run(smoke())))
