import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from multi_cad import config, release
from multi_cad.diagnostics import report
from multi_cad.install import install_backend, project_wheel
from multi_cad.gateway import Gateway


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / '中文 with spaces'
        self.root.mkdir()
        self.wheel = self.root / 'ai_multi_cad_agent-0.3.0rc1-py3-none-any.whl'
        self.wheel.write_bytes(b'fixture')
        self.launcher = self.root / 'launch-source.ps1'
        self.launcher.write_text('stable launcher')
        self.target = self.root / 'installation'

    def runner(self, command, log, env=None):
        if command[1:3] == ['-m', 'venv']:
            executable = Path(command[3]) / 'Scripts/python.exe'
            executable.parent.mkdir(parents=True)
            executable.touch()

    def test_install_failure_does_not_activate_or_change_config(self):
        release.install(self.wheel, self.target, self.launcher, runner=self.runner)
        previous = (self.target/'current.json').read_bytes()
        settings = {'schema_version': 2, 'software': {}, 'backends': {}}
        config.save(settings, self.target/'config.json')
        for stage in ('venv', 'pip', 'smoke'):
            def failing(command, log, env=None):
                if stage in command:
                    raise subprocess.CalledProcessError(1, command)
                self.runner(command, log, env)
            with self.assertRaisesRegex(RuntimeError, 'previous entry is unchanged'):
                release.install(self.wheel, self.target, self.launcher, runner=failing)
            self.assertEqual((self.target/'current.json').read_bytes(), previous)
            self.assertEqual(config.load(self.target/'config.json'), settings)

    def test_upgrade_rollback_restores_snapshot_and_leaves_projects(self):
        release.install(self.wheel, self.target, self.launcher, runner=self.runner)
        previous = json.loads((self.target/'current.json').read_text())
        settings = {'schema_version': 2, 'software': {}, 'backends': {}}
        config.save(settings, self.target/'config.json')
        project = self.target/'user.SLDPRT'
        project.write_bytes(b'user-original')
        release.install(self.wheel, self.target, self.launcher, runner=self.runner)
        config.save({**settings, 'software': {'blender': {'executable': 'new'}}}, self.target/'config.json')
        release.rollback(self.target)
        self.assertEqual(json.loads((self.target/'current.json').read_text()), previous)
        self.assertEqual(config.load(self.target/'config.json'), settings)
        self.assertEqual(project.read_bytes(), b'user-original')
        self.assertTrue(list(self.target.glob('config.pre-rollback-*.bak')))

    def test_managed_export_uses_stable_launcher(self):
        target = self.root/'agent.json'
        with patch('multi_cad.release.managed_root', return_value=self.target):
            config.export_client(target)
        entry = json.loads(target.read_text())['mcpServers']['multi_cad']
        self.assertIn(str(self.target/'launch.ps1'), entry['args'])
        self.assertNotIn('venv', entry['command'])

    def test_first_install_cannot_rollback(self):
        release.install(self.wheel, self.target, self.launcher, runner=self.runner)
        before = (self.target/'current.json').read_bytes()
        with self.assertRaises(ValueError):
            release.rollback(self.target)
        self.assertEqual(before, (self.target/'current.json').read_bytes())

    def test_failed_rollback_pointer_write_restores_current_config(self):
        release.install(self.wheel, self.target, self.launcher, runner=self.runner)
        settings = {'schema_version': 2, 'software': {}, 'backends': {}}
        config.save(settings, self.target/'config.json')
        release.install(self.wheel, self.target, self.launcher, runner=self.runner)
        newer = {**settings, 'software': {'blender': {'executable': 'new'}}}
        config.save(newer, self.target/'config.json')
        original_write = release.write_json
        def fail_pointer(path, value):
            if Path(path).name == 'current.json':
                raise OSError('fixture disk failure')
            original_write(path, value)
        with patch('multi_cad.release.write_json', side_effect=fail_pointer), self.assertRaises(OSError):
            release.rollback(self.target)
        self.assertEqual(config.load(self.target/'config.json'), newer)

    def test_backend_failures_preserve_existing_config(self):
        path = self.root/'config.json'
        original = {'schema_version': 2, 'software': {}, 'backends': {'solidworks': {'command': 'existing'}}}
        config.save(original, path)
        from multi_cad.install import SOURCES
        for failure in ('git', 'pip', 'handshake'):
            def runner(command, **kwargs):
                if failure == command[0] or (failure == 'pip' and 'pip' in command):
                    raise subprocess.CalledProcessError(1, command)
            def output(command, **kwargs):
                return SOURCES['solidworks']['commit'] if command[0] == 'git' else 'dependencies'
            with patch('multi_cad.install.home', return_value=self.root/failure), \
                 patch('multi_cad.install.subprocess.run', side_effect=runner), \
                 patch('multi_cad.install.subprocess.check_output', side_effect=output), \
                 patch('multi_cad.install.use_sw_host', side_effect=lambda settings, *args: settings['backends'].update({'solidworks': {'command': 'candidate'}})), \
                 patch('multi_cad.install.check_backend', new=AsyncMock(side_effect=RuntimeError('handshake') if failure == 'handshake' else None)):
                with self.assertRaises((subprocess.CalledProcessError, RuntimeError)):
                    install_backend('solidworks', path, self.wheel)
            self.assertEqual(config.load(path), original)


class RepairTests(unittest.TestCase):
    def test_repair_preview_apply_and_custom_backend_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            moved = root/'移动 blender.exe'
            moved.touch()
            settings = {'schema_version': 2, 'software': {'blender': {'executable': 'missing'}},
                        'backends': {'blender': {'command': sys.executable, 'args': ['custom.py', '--port', '9999'], 'env': {'SECRET': 'retain'}}}}
            path = root/'config.json'
            config.save(settings, path)
            result = config.repair(path, {'blender': str(moved)}, interactive=False)
            self.assertFalse(result['saved'])
            self.assertEqual(config.load(path), settings)
            result = config.repair(path, {'blender': str(moved)}, interactive=False, apply=True)
            self.assertTrue(result['saved'])
            self.assertEqual(config.load(path)['backends'], settings['backends'])
            self.assertTrue(list(root.glob('*.bak')))

    def test_missing_saved_path_requires_choice_even_one_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config.json'
            settings = {'schema_version': 2, 'software': {'blender': {'executable': 'missing'}}, 'backends': {}}
            config.save(settings, path)
            with patch('multi_cad.config.discover', side_effect=lambda name, explicit=None, saved=None: {
                'status': 'needs_input' if saved else 'selected', 'reason': 'configured_path_missing', 'candidates': ['new.exe']}):
                result = config.repair(path, interactive=False)
            self.assertEqual(config.load(path), settings)
            self.assertTrue(result['needs_input'])

    def test_diagnosis_cannot_include_secrets_or_model_payload(self):
        status = {'solidworks': {'installed': True, 'error': 'SECRET', 'args': ['SECRET'], 'env': {'TOKEN': 'SECRET'},
            'verification_history': {'config_matches': False, 'verified_at': 123, 'capabilities': ['reopen', 'SECRET'], 'evidence': 'SECRET'}}}
        result = report(status)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertFalse(result['backends']['solidworks']['business_verification']['config_matches'])


class DiagnosticProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_connected_mcp_with_unavailable_blender_port_is_not_cad_success(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway({'software': {}, 'backends': {'blender': {
                'command': sys.executable, 'args': [str(Path(__file__).with_name('fake_mcp.py').resolve())],
                'env': {'BLENDER_PORT_FAILURE': '1'}}}}, directory)
            try:
                status = await gateway.status(True)
                self.assertTrue(status['blender']['mcp_connected'])
                self.assertFalse(status['blender']['cad_callable'])
                self.assertTrue(report(status)['backends']['blender']['next_actions'])
            finally:
                await gateway.close()


if __name__ == '__main__':
    unittest.main()
