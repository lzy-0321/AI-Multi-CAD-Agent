import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from multi_cad.project import create_project, resume_analysis
from multi_cad.three_mf import analyse

NS = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
MESH = '''<mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>
<vertex x="0" y="2" z="0"/><vertex x="0" y="0" z="3"/></vertices><triangles>
<triangle v1="0" v2="2" v3="1"/><triangle v1="0" v2="1" v3="3"/>
<triangle v1="0" v2="3" v3="2"/><triangle v1="1" v2="2" v3="3"/></triangles></mesh>'''


def fixture(path, unit="millimeter", cyclic=False, external=False):
    child = '2' if cyclic else '1'
    reference = ' p:path="/3D/Objects/part.model"' if external else ''
    model = f'''<model xmlns="{NS}" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" unit="{unit}">
<resources><object id="1" name="Tetrahedron">{MESH}</object><object id="2"><components>
<component objectid="{child}"{reference} transform="1 0 0 0 1 0 0 0 1 10 0 0"/>
</components></object></resources><build>
<item objectid="2" transform="0 1 0 -1 0 0 0 0 1 0 5 0"/>
<item objectid="2"/></build></model>'''
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('_rels/.rels', '<Relationships><Relationship Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/3D/main.model"/></Relationships>')
        archive.writestr('3D/main.model', model)
        if external:
            archive.writestr('3D/Objects/part.model', f'<model xmlns="{NS}" unit="{unit}"><resources><object id="1">{MESH}</object></resources></model>')


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.3mf'

    def test_nested_rotation_translation_and_instances(self):
        fixture(self.source)
        result = analyse(self.source)
        self.assertEqual(len(result['resources']), 1)
        self.assertEqual(result['resources'][0]['instance_count'], 2)
        self.assertEqual(result['instances'][0]['bounds_mm'], {'min': [-2., 15., 0.], 'max': [0., 16., 3.], 'size': [2., 1., 3.]})
        self.assertIsNone(result['instances'][0]['assembly_transform_mm'])
        self.assertEqual(result['resources'][0]['quality']['volume_mm3'], 1.)

    def test_inch_units(self):
        fixture(self.source, unit='inch')
        result = analyse(self.source)
        self.assertAlmostEqual(result['instances'][0]['bounds_mm']['min'][1], 381.)
        self.assertAlmostEqual(result['resources'][0]['quality']['volume_mm3'], 25.4**3)

    def test_cross_file_resource(self):
        fixture(self.source, external=True)
        result = analyse(self.source)
        self.assertEqual(result['resources'][0]['source'], '3D/Objects/part.model#1')

    def test_cycle_rejected(self):
        fixture(self.source, cyclic=True)
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            analyse(self.source)

    def test_project_preserves_input_and_resume(self):
        fixture(self.source)
        original = self.source.read_bytes()
        project = create_project(self.source, self.root / 'project', '参数化安装孔')
        self.assertEqual((project / 'inputs/source.3mf').read_bytes(), original)
        before = (project / 'analysis/source_manifest.json').stat().st_mtime_ns
        resume_analysis(project)
        self.assertEqual((project / 'analysis/source_manifest.json').stat().st_mtime_ns, before)
        plan = json.loads((project / 'analysis/plan.json').read_text(encoding='utf-8'))
        self.assertEqual(plan['execution_status'], 'requires_reconstruction_plan')
        with self.assertRaises(FileExistsError):
            create_project(self.source, project, '')

    def test_failure_persisted(self):
        fixture(self.source, cyclic=True)
        with self.assertRaises(ValueError):
            create_project(self.source, self.root / 'failed', '')
        state = json.loads((self.root / 'failed/project.json').read_text())
        self.assertEqual(state['stages']['analysis'], 'failed')

    def test_bad_index_rejected(self):
        fixture(self.source)
        with zipfile.ZipFile(self.source) as archive:
            content = {n: archive.read(n) for n in archive.namelist()}
        with zipfile.ZipFile(self.source, 'w') as archive:
            for name, data in content.items():
                archive.writestr(name, data.replace(b'v1="0"', b'v1="99"'))
        with self.assertRaisesRegex(ValueError, 'index'):
            analyse(self.source)


if __name__ == '__main__':
    unittest.main()
