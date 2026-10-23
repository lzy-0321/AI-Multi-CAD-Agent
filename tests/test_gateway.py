import asyncio
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multi_cad.backend import Backend, compact, response_data
from multi_cad.config import discover, export_client, import_servers, load, save, validate, disable_codex_servers
from multi_cad.plate import validate_plate


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_two_install_locations_and_ambiguity(self):
        first, second = self.root/'installation A/blender.exe', self.root/'other/version B/blender.exe'
        for path in (first, second):
            path.parent.mkdir(parents=True)
            path.touch()
        opts = {"registry": lambda: None, "path_lookup": lambda _: None, "common": [first, second]}
        self.assertEqual(discover('blender', **opts)['reason'], 'multiple_versions')
        self.assertEqual(discover('blender', explicit=str(second), saved=str(first), **opts)['candidates'], [str(second)])
        self.assertEqual(discover('blender', saved=str(first), **opts)['status'], 'selected')
        first.unlink()
        self.assertEqual(discover('blender', saved=str(first), **opts)['reason'], 'configured_path_missing')

    def test_save_backup_and_json_merge(self):
        path = self.root/'config.json'
        config = {"schema_version": 2, "software": {}, "backends": {}}
        save(config, path)
        config['software']['blender'] = {"executable": "X:/a.exe"}
        save(config, path)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)
        self.assertEqual(load(path), config)
        client = self.root/'client.json'
        client.write_text(json.dumps({"other": 1, "mcpServers": {"existing": {"command": "keep"}}}))
        export_client(client, path)
        export_client(client, path)
        data = json.loads(client.read_text())
        self.assertEqual(data['mcpServers']['existing']['command'], 'keep')
        self.assertEqual(data['other'], 1)

    def test_toml_preserves_comments_and_conflict(self):
        target = self.root/'config.toml'
        original = '# keep this comment\n[mcp_servers.other]\ncommand="keep"\n'
        target.write_text(original)
        export_client(target, self.root/'machine.json', 'codex')
        self.assertTrue(target.read_text().startswith(original))
        with self.assertRaises(ValueError):
            export_client(target, self.root/'different.json', 'codex')

    def test_import_preserves_existing_and_custom_args(self):
        target = self.root/'input.json'
        target.write_text(json.dumps({"mcpServers": {"my-sw": {"command": "custom python.exe", "args": ["some server.py"], "cwd": "work"}}}))
        config = {"backends": {"blender": {"command": "keep"}}}
        import_servers(config, target, {"solidworks": "my-sw"})
        self.assertEqual(config['backends']['solidworks']['args'], ['some server.py'])
        self.assertEqual(config['backends']['blender']['command'], 'keep')

    def test_loopback_only(self):
        with self.assertRaises(ValueError):
            validate({"backends": {"blender": {"command": "x", "env": {"BLENDER_HOST": "0.0.0.0"}}}})

    def test_ambiguous_mcp_names_require_selection(self):
        path = self.root/'many.json'
        path.write_text(json.dumps({'mcpServers': {'blender-old': {'command':'old'}, 'blender-new': {'command':'new'}}}))
        with self.assertRaisesRegex(ValueError, 'Multiple'):
            import_servers({'backends': {}}, path)

    def test_invalid_config_does_not_replace_previous(self):
        path = self.root/'config.json'
        original = {'schema_version':2, 'software':{}, 'backends':{}}
        save(original, path)
        with self.assertRaises(ValueError):
            save({'backends':{'bad':{'command':'python', 'args':'not an array'}}}, path)
        self.assertEqual(load(path), original)

    def test_disable_only_selected_codex_entry(self):
        import tomllib
        path = self.root/'settings.toml'
        path.write_text('[mcp_servers.direct]\ncommand="python"\nargs=["server.py"]\n[mcp_servers.other]\ncommand="keep"\n')
        disable_codex_servers(path, ['direct'])
        data = tomllib.loads(path.read_text())['mcp_servers']
        self.assertFalse(data['direct']['enabled'])
        self.assertEqual(data['direct']['args'], ['server.py'])
        self.assertEqual(data['other'], {'command':'keep'})


class ValidationTests(unittest.TestCase):
    def test_text_errors_and_nested_batch(self):
        for response in ({"content": [{"type": "text", "text": '❌ Failed to connect'}]},
                         {"content": [{"type": "text", "text": '{"calls":[{"ok":false}]}'}]},
                         {"isError": True, "content": []}):
            self.assertFalse(response_data(response)['ok'])
        self.assertTrue(response_data({"content": [{"type": "text", "text": 'Success'}]})['ok'])

    def test_truncated_results_keep_artifact(self):
        result = compact({"ok": True, "data": "a"*4000, "artifact": "log.json", "raw": {}})
        self.assertTrue(result['data']['truncated'])
        self.assertEqual(result['data']['full_result'], 'log.json')

    def test_geometric_acceptance_rejects_wrong_hole_or_constraints(self):
        data = {"solid_count": 1, "bounds": [{"min": [0,0,0], "max": [120,80,5]}],
                "volume_mm3": 48000-4*math.pi*9*5, "sketches": [{"constraint_status": 3}],
                "cylinders": [{"origin_mm": [x,y,0], "axis": [0,0,1], "radius_mm": 3} for x,y in [(10,10),(110,10),(110,70),(10,70)]]}
        self.assertTrue(validate_plate(data, 6)['passed'])
        data['cylinders'][0]['origin_mm'][0] = 11
        self.assertFalse(validate_plate(data, 6)['passed'])
        data['sketches'][0]['constraint_status'] = 2
        self.assertIn('Sketch is not fully constrained', validate_plate(data, 6)['failures'])


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {"command": sys.executable, "args": [str(Path(__file__).with_name('fake_mcp.py').resolve())]}
        self.backend = Backend('fixture', self.config, self.root)

    async def asyncTearDown(self):
        await self.backend.close()
        self.tmp.cleanup()

    async def test_handshake_catalog_error_and_missing_tool(self):
        summary = await self.backend.request('catalog')
        self.assertEqual(summary['tool_count'], 3)
        self.assertTrue((self.root/'fixture-capabilities.json').is_file())
        result = await self.backend.invoke('textual_failure', {})
        self.assertFalse(result['ok'])
        self.assertFalse(self.backend.uncertain)
        result = await self.backend.invoke('missing', {})
        self.assertEqual(result['status'], 'unavailable')

    async def test_write_timeout_persists_uncertainty_and_blocks_replay(self):
        result = await self.backend.invoke('delayed_write', {}, timeout=.05)
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertTrue(self.backend.uncertain_path.exists())
        result = await self.backend.invoke('delayed_write', {})
        self.assertEqual(result['status'], 'needs_reconciliation')
        another = Backend('fixture', self.config, self.root)
        self.assertTrue(another.uncertain)

    async def test_new_connection_refreshes_config_fingerprint(self):
        await self.backend.request('catalog')
        before = json.loads(self.backend.cache_path.read_text())['config_hash']
        await self.backend.close()
        self.backend = Backend('fixture', {**self.config, 'env': {'FIXTURE_VERSION': '2'}}, self.root)
        await self.backend.request('catalog')
        after = json.loads(self.backend.cache_path.read_text())['config_hash']
        self.assertNotEqual(before, after)
        result = await self.backend.invoke('solidworks_list_documents', {})
        self.assertTrue(result['ok'])


if __name__ == '__main__':
    unittest.main()
