import copy
import json
import math
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

from multi_cad.parts import plan, select, validate_edit
from multi_cad.recognition import recognize
from multi_cad.three_mf import analyse, bounds, mesh_quality
from tests.test_core import fixture


def washer(outer=20, inner=5, height=3, segments=128):
    vertices = [[radius*math.cos(i*2*math.pi/segments), radius*math.sin(i*2*math.pi/segments), z]
                for z in (0, height) for radius in (outer, inner) for i in range(segments)]
    triangles = []
    def quad(a, b, c, d):
        triangles.extend([[a, b, c], [a, c, d]])
    n = segments
    for i in range(n):
        j = (i+1)%n
        quad(i, j, 2*n+j, 2*n+i)
        quad(n+j, n+i, 3*n+i, 3*n+j)
        quad(j, i, n+i, n+j)
        quad(2*n+i, 2*n+j, 3*n+j, 3*n+i)
    return {'id': 'ring', 'vertices_mm': vertices, 'triangles': triangles,
            'bounds_mm': bounds(vertices), 'quality': mesh_quality(vertices, triangles)}


def write_washer(path):
    r = washer()
    verts = ''.join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in r['vertices_mm'])
    tris = ''.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in r['triangles'])
    model = f'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter"><resources><object id="1" name="Test washer"><mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh></object></resources><build><item objectid="1"/><item objectid="1" transform="1 0 0 0 1 0 0 0 1 60 0 0"/></build></model>'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('_rels/.rels', '<Relationships><Relationship Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/3D/main.model"/></Relationships>')
        z.writestr('3D/main.model', model)


class PartsTests(unittest.TestCase):
    def test_measured_washer_and_chord_error(self):
        r = recognize(washer())
        self.assertTrue(r['supported'])
        self.assertEqual(r['profile']['kind'], 'washer')
        self.assertAlmostEqual(r['holes'][0]['radius'], 5)
        self.assertGreater(r['surface_error_mm'], 0)
        self.assertFalse(recognize(washer(segments=8))['supported'])

    def test_open_mesh_and_multi_level_refused(self):
        r = washer()
        r['quality']['edge_closed'] = False
        self.assertFalse(recognize(r)['supported'])
        r = washer()
        r['vertices_mm'][0][2] = 1
        self.assertFalse(recognize(r)['supported'])

    def test_slicer_roles_and_plate_instance_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'test.3mf'
            fixture(p)
            settings = '<config><object id="2"><metadata key="name" value="Group"/><part id="1" subtype="negative_part"><metadata key="name" value="Cutter"/></part></object><plate><metadata key="plater_id" value="7"/><model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="1"/></model_instance></plate></config>'
            with zipfile.ZipFile(p, 'a') as z:
                z.writestr('Metadata/model_settings.config', settings)
            m = analyse(p)
            self.assertEqual([i['role'] for i in m['instances']], ['negative_part']*2)
            self.assertEqual([i['plate_ids'] for i in m['instances']], [[], ['7']])
            self.assertEqual(m['instances'], analyse(p)['instances'])
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                select(m, ['Cutter'], 'instance')
            self.assertEqual(len(select(m, [m['instances'][0]['id']], 'instance')), 1)
            self.assertEqual(len(select(m, [m['instances'][0]['id']], 'all_instances')), 2)

    def test_route_uses_geometry_and_goal(self):
        from multi_cad.three_mf import matrix
        target = {'id': 'one', 'role': 'normal_part', 'group_id': 'a', 'resource_id': 'ring', 'print_transform_mm': matrix()}
        manifest = {'resources': [washer()], 'instances': [target]}
        self.assertEqual(plan(manifest, [target], {'operation': 'set_parameters', 'diameter_mm': 12}, .05)[0]['backend'], 'solidworks')
        manifest['resources'][0]['quality']['edge_closed'] = False
        self.assertEqual(plan(manifest, [target], {'operation': 'set_parameters', 'diameter_mm': 12}, .05)[0]['status'], 'unsupported')
        self.assertEqual(plan(manifest, [target], {'operation': 'translate', 'delta_mm': [1, 0, 0]}, .05)[0]['backend'], 'blender')

    def test_invalid_edit_rejected_before_cad(self):
        for edit in ({'operation': 'scale', 'factors': [1, -1, 1], 'pivot_mm': [0]*3},
                     {'operation': 'translate', 'delta_mm': [float('nan'), 0, 0]},
                     {'operation': 'cut_cylinder', 'axis': [0, 0, 2], 'center_mm': [0]*3, 'diameter_mm': 2, 'depth_mm': 5}):
            with self.assertRaises(ValueError):
                validate_edit(edit)

    def test_gateway_still_has_eight_tools_and_local_discovery(self):
        import asyncio
        from multi_cad.gateway import Gateway, create_server
        async def check():
            with tempfile.TemporaryDirectory() as tmp:
                config = {'schema_version': 2, 'software': {}, 'backends': {}}
                gateway = Gateway(config, Path(tmp)/'cache')
                try:
                    found = await gateway.search('project', 'parts')
                    self.assertGreater(len(found), 0)
                    schema = await gateway.schema('project', 'parts_edit')
                    self.assertIn('scope', schema['inputSchema']['required'])
                    with patch('multi_cad.gateway.load', return_value=config), patch('multi_cad.gateway.home', return_value=Path(tmp)):
                        self.assertEqual(len(await create_server().list_tools()), 8)
                finally:
                    await gateway.close()
        asyncio.run(check())

    def test_batch_failure_does_not_commit_and_does_not_replay(self):
        import asyncio
        from multi_cad.parts import execute, read
        from multi_cad.project import create_project, write_json
        async def check():
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                source = base/'source.3mf'
                write_washer(source)
                project = create_project(source, base/'project', 'change selected parts')
                state = read(project/'project.json')
                state.update(kind='part_project', versions=[])
                write_json(project/'project.json', state)
                original = (project/'project.json').read_bytes()
                manifest = read(project/'analysis/source_manifest.json')
                calls = []
                async def job(gateway, root, request, goal):
                    calls.append(request)
                    if len(calls) == 1:
                        Path(request['output']).write_bytes(b'baseline')
                        return {'passed': True, 'snapshot': {}}
                    raise TimeoutError('write timeout; inspect actual state')
                args = {'project': str(project), 'targets': [manifest['instances'][0]['id']], 'scope': 'all_instances', 'edit': {'operation': 'translate', 'delta_mm': [1, 0, 0]}}
                with patch('multi_cad.parts.blender_job', side_effect=job):
                    with self.assertRaises(TimeoutError):
                        await execute(None, 'parts_edit', args)
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(calls[1]['edits']), 2)
                self.assertEqual((project/'project.json').read_bytes(), original)
                self.assertEqual(read(project/'project.json')['versions'], [])
                self.assertEqual(source.read_bytes(), (project/'inputs/source.3mf').read_bytes())
        asyncio.run(check())

    def test_unknown_slicer_roles_not_promoted_to_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'unknown.3mf'
            fixture(path)
            with zipfile.ZipFile(path, 'a') as z:
                z.writestr('Metadata/model_settings.config', '<config><object id="2"><part id="1" subtype="future_modifier"/></object></config>')
            manifest = analyse(path)
            target = manifest['instances'][0]
            self.assertEqual(target['role'], 'future_modifier')
            self.assertEqual(plan(manifest, [target], {'operation': 'translate', 'delta_mm': [1, 0, 0]}, .05)[0]['status'], 'unsupported')

    def test_forged_selection_and_bad_unit_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            select({'instances': []}, ['missing'], 'instance')
        with self.assertRaises(ValueError):
            recognize(washer(), float('inf'))

    def test_protocol_safe_mode_failure_is_not_success(self):
        from multi_cad.backend import response_data
        self.assertFalse(response_data({'content': [{'type': 'text', 'text': 'Rejected by safe mode - subprocess is forbidden'}]})['ok'])

    def test_orca_style_multi_plate_and_auxiliary_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'orca.3mf'
            fixture(path)
            with zipfile.ZipFile(path, 'a') as z:
                z.writestr('Metadata/project_settings.config', '{"compatible_printers":[],"printer_settings_id":"Synthetic Orca fixture"}')
                z.writestr('Metadata/model_settings.config', '<config><object id="2"><part id="1" subtype="modifier_part"><metadata key="name" value="辅助对象"/></part></object>'
                    '<plate><metadata key="plater_id" value="1"/><model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="0"/></model_instance></plate>'
                    '<plate><metadata key="plater_id" value="2"/><model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="1"/></model_instance></plate></config>')
            m = analyse(path)
            self.assertEqual([i['plate_ids'] for i in m['instances']], [['1'], ['2']])
            self.assertTrue(all(i['role'] == 'modifier_part' for i in m['instances']))

    def test_modified_manifest_cannot_drive_cad(self):
        from multi_cad.project import create_project
        from multi_cad.parts import load_project
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base/'source.3mf'
            write_washer(source)
            project = create_project(source, base/'project', 'test')
            manifest = project/'analysis/source_manifest.json'
            manifest.write_text(manifest.read_text(encoding='utf-8')+' ', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Manifest integrity'):
                load_project(project)
