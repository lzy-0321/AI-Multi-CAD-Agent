"""Exercise persistence and ownership independently of a SolidWorks installation."""
import asyncio
import json
import math
import tempfile
import unittest
from pathlib import Path
from multi_cad.plate import run_plate, digest


class SimulatedBackend:
    def __init__(self, root):
        self.operation_lock = asyncio.Lock()
        self.tools = {'multi_cad_inspect_part': {}}
        self.directory = root
        self.config = {'command':'fixture'}
        self.uncertain = False
        self.calls = []
        self.diameter = 6
        self.parameters = {'D1@PlateThickness':5, 'D1@PlateProfile':120, 'D2@PlateProfile':80,
                           **{f'D{i}@PlateProfile':6 for i in (3,6,9,12)}}
        self.ambiguous = False

    async def request(self, *args):
        return {}

    async def invoke(self, tool, args):
        self.calls.append((tool, args))
        data = {}
        if tool == 'solidworks_list_documents':
            data = {'activeDocument':'UserUnsavedPart', 'documents':[{'title':'UserUnsavedPart'}]}
        elif tool == 'solidworks_open_document':
            data = {'title':Path(args['path']).name}
        elif tool == 'solidworks_list_parameters':
            data = {'parameters':[{'parameter':key, 'value':value} for key,value in self.parameters.items()]}
            if self.ambiguous:
                data['parameters'].append(data['parameters'][0])
        elif tool == 'solidworks_set_parameter':
            self.parameters[args['parameter']] = args['value']
            self.diameter = args['value']
        elif tool == 'solidworks_save_document':
            path = Path(args['path'])
            path.write_text(json.dumps(self.parameters))
            data = {'title':path.name}
        elif tool == 'multi_cad_inspect_part':
            data = {'solid_count':1, 'bounds':[{'min':[0,0,0], 'max':[120,80,5]}],
                    'sketches':[{'constraint_status':3}], 'volume_mm3':48000-4*math.pi*(self.diameter/2)**2*5,
                    'cylinders':[{'origin_mm':[x,y,0], 'axis':[0,0,1], 'radius_mm':self.diameter/2}
                                 for x,y in [(10,10),(110,10),(110,70),(10,70)]]}
        return {'ok':True, 'data':data}


class PlateLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)/'project'
        for folder in ('output','reports'):
            (self.project/folder).mkdir(parents=True)
        self.backend = SimulatedBackend(Path(self.tmp.name))
        source = self.project/'output/v1.SLDPRT'
        source.write_bytes(b'original')
        self.state = {'kind':'parametric_plate', 'parameters':{'hole_diameter':{'value':6}},
                      'versions':[{'file':'output/v1.SLDPRT', 'hole_diameter':6, 'sha256':digest(source)}],
                      'parameter_values':dict(self.backend.parameters),
                      'hole_parameters':[f'D{i}@PlateProfile' for i in (3,6,9,12)]}
        (self.project/'project.json').write_text(json.dumps(self.state))

    async def test_edit_preserves_original_and_other_document(self):
        result = await run_plate(self.backend, self.project, 'edit', 8)
        self.assertTrue(result['version']['reopened'])
        self.assertEqual((self.project/'output/v1.SLDPRT').read_bytes(), b'original')
        self.assertEqual(len(json.loads((self.project/'project.json').read_text())['versions']), 2)
        self.assertFalse(any(t=='solidworks_close_document' and a['name']=='UserUnsavedPart' for t,a in self.backend.calls))
        self.assertEqual(self.backend.calls[-1], ('solidworks_activate_document', {'name':'UserUnsavedPart'}))

    async def test_ambiguous_mapping_stops_before_parameter_edit(self):
        self.backend.ambiguous = True
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            await run_plate(self.backend, self.project, 'edit', 8)
        self.assertFalse(any(t=='solidworks_set_parameter' for t,_ in self.backend.calls))
        self.assertEqual((self.project/'output/v1.SLDPRT').read_bytes(), b'original')
