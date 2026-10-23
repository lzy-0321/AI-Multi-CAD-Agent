"""Windows ZIP acceptance without CAD. Used locally and by the release workflow."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def run(command, cwd, env=None, expect_success=True):
    result = subprocess.run(command, cwd=cwd, env=env, text=True, encoding='utf-8', errors='replace',
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if (result.returncode == 0) != expect_success:
        raise RuntimeError(result.stdout)
    return result


def check(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    checksum = archive.with_suffix('.zip.sha256').read_text().split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == checksum
    extracted = destination / 'ZIP 解压'
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            target = (extracted / name).resolve()
            if not target.is_relative_to(extracted.resolve()):
                raise ValueError('Archive path escapes extraction directory')
        bundle.extractall(extracted)
    bundle_root = next(extracted.iterdir())
    installation = destination / '隔离 安装'
    arbitrary = destination / 'unrelated-working-directory'
    arbitrary.mkdir(exist_ok=True)
    installer = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                 str(bundle_root / 'install.ps1'), '-InstallDir', str(installation), '-Python', sys.executable]
    launcher = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(installation / 'launch.ps1')]
    print('Acceptance: clean ZIP install', flush=True)
    run(installer, arbitrary)
    active_path = installation / 'current.json'
    first = json.loads(active_path.read_text(encoding='utf-8'))
    package = run([first['python'], '-I', '-X', 'utf8', '-c', 'import multi_cad; print(multi_cad.__file__)'], arbitrary).stdout.strip()
    assert Path(package).is_relative_to(installation), package
    run(launcher + ['doctor', '--report', str(destination / 'diagnosis.json')], arbitrary)
    # A user's configuration, unrelated Agent service and model must survive upgrades.
    config_path = installation / 'config.json'
    config_path.write_text(json.dumps({'schema_version': 2, 'software': {}, 'backends': {}}), encoding='utf-8')
    config_before = config_path.read_bytes()
    project = destination / 'user-original.SLDPRT'
    project.write_bytes(b'acceptance fixture - do not change')
    agent = installation / 'agent.json'
    agent.write_text(json.dumps({'mcpServers': {'keep': {'command': 'untouched'}}}), encoding='utf-8')
    run(launcher + ['export-config', str(agent)], arbitrary)
    agent_before = agent.read_bytes()
    print('Acceptance: upgrade and stable Agent entry', flush=True)
    run(installer, arbitrary)
    upgraded = json.loads(active_path.read_text(encoding='utf-8'))
    assert upgraded['python'] != first['python']
    run(launcher + ['export-config', str(agent)], arbitrary)
    assert agent.read_bytes() == agent_before
    assert json.loads(agent_before)['mcpServers']['keep']['command'] == 'untouched'
    assert config_path.read_bytes() == config_before
    print('Acceptance: dependency failure retains current installation', flush=True)
    pointer_before = active_path.read_bytes()
    env = dict(os.environ, PIP_NO_INDEX='1', PIP_FIND_LINKS='')
    failure = run(installer, arbitrary, env, expect_success=False)
    (destination / 'expected-install-failure.log').write_text(failure.stdout, encoding='utf-8')
    assert active_path.read_bytes() == pointer_before
    assert config_path.read_bytes() == config_before
    config_path.write_text(json.dumps({'schema_version': 2, 'software': {'blender': {'executable': 'post-upgrade'}}, 'backends': {}}), encoding='utf-8')
    print('Acceptance: rollback restores prior program and configuration', flush=True)
    run(launcher + ['rollback'], arbitrary)
    assert json.loads(active_path.read_text(encoding='utf-8')) == first
    assert json.loads(config_path.read_bytes()) == json.loads(config_before)
    assert project.read_bytes() == b'acceptance fixture - do not change'
    run(launcher + ['doctor'], arbitrary)
    evidence = {'passed': True, 'archive_sha256': checksum, 'package_from_installed_environment': True,
                'clean_install': True, 'unicode_and_spaces': True, 'arbitrary_working_directory': True,
                'upgrade': True, 'stable_agent_entry': True, 'dependency_failure_preserves_active': True,
                'rollback': True, 'user_file_preserved': True, 'cad_started': False,
                'second_machine_cad_acceptance': 'pending'}
    (destination / 'installation-acceptance.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.destination:
        check(args.archive.resolve(), args.destination.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='multicad-') as temporary:
            check(args.archive.resolve(), Path(temporary))
