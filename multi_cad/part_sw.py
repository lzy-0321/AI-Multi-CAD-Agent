"""Bounded SW reconstruction using the existing upstream sketch/feature tools."""
import copy
import math
import shutil
import struct
from pathlib import Path

from .parts import digest, reference


def expected_volume(shape):
    p = shape['profile']
    area = ((p['max'][0]-p['min'][0])*(p['max'][1]-p['min'][1]) if p['kind'] == 'plate' else math.pi*p['radius']**2)
    return (area-sum(math.pi*h['radius']**2 for h in shape['holes']))*shape['thickness_mm']


def validate(inspection, shape):
    failures = []
    tolerance = shape['tolerance_mm']
    if inspection['solid_count'] != 1:
        failures.append('Expected one solid')
    if not inspection['sketches'] or any(s['constraint_status'] != 3 for s in inspection['sketches']):
        failures.append('Sketch is not fully defined')
    expected = expected_volume(shape)
    if expected <= 0 or abs(inspection['volume_mm3']-expected) > max(.01, expected*1e-5):
        failures.append('Analytic volume mismatch')
    profile = shape['profile']
    if profile['kind'] == 'plate':
        extent = [profile['max'][i]-profile['min'][i] for i in range(2)]+[shape['thickness_mm']]
        boxes = inspection.get('bounds', [])
        if len(boxes) != 1 or any(abs(a-b) > tolerance for a, b in zip(boxes[0]['min']+boxes[0]['max'], [0, 0, 0]+extent)):
            failures.append('Plate bounds changed')
    origin = profile.get('min', profile.get('center'))
    expected_cylinders = [(h['center'][0]-origin[0], h['center'][1]-origin[1], h['radius']) for h in shape['holes']]
    if profile['kind'] == 'washer':
        expected_cylinders.append((0, 0, profile['radius']))
    actual = list(inspection['cylinders'])
    for x, y, radius in expected_cylinders:
        match = next((c for c in actual if math.dist(c['origin_mm'][:2], (x, y)) <= tolerance and abs(c['radius_mm']-radius) <= tolerance and abs(abs(c['axis'][2])-1) < 1e-6), None)
        if match is None:
            failures.append('Cylinder position or radius mismatch')
        else:
            actual.remove(match)
    if actual:
        failures.append('Unexpected cylinders')
    if failures:
        raise ValueError('; '.join(failures))
    return {'passed': True, 'volume_mm3': inspection['volume_mm3'], 'checks': ['solid_count', 'fully_constrained', 'cylinders', 'volume', 'persistent_parameters']}


async def verify_part(backend, root, folder, record):
    """Reopen a private copy so user-open documents and originals remain untouched."""
    source = reference(root, record['file'])
    if digest(source) != record['sha256']:
        raise ValueError('Saved SW part changed')
    copy_path = folder / ('verify-'+source.name)
    shutil.copy2(source, copy_path)
    title, active = None, None
    async with backend.operation_lock:
        async def call(operation, **arguments):
            result = await backend.invoke(operation, arguments)
            if not result['ok']:
                raise RuntimeError('SW verification failed: '+operation)
            return result['data']
        try:
            active = (await call('solidworks_list_documents')).get('activeDocument')
            title = (await call('solidworks_open_document', path=str(copy_path)))['title']
            report = validate(await call('multi_cad_inspect_part'), record['geometry'])
            parameters = (await call('solidworks_list_parameters'))['parameters']
            for key, value in record['parameter_values'].items():
                matches = [p for p in parameters if p['parameter'] == key and abs(p.get('value', -999)-value) <= .001]
                if len(matches) != 1:
                    raise ValueError('SW parameter mapping changed: '+key)
            return report
        finally:
            if title and not backend.uncertain:
                await call('solidworks_close_document', name=title)
            if active and not backend.uncertain:
                await call('solidworks_activate_document', name=active)


def normalize_stl(path, shape):
    """Normalize explicit SW STL unit variants by verifying canonical expected bounds."""
    data = Path(path).read_bytes()
    if len(data) >= 84 and len(data) == 84+50*struct.unpack_from('<I', data, 80)[0]:
        rows = [list(struct.unpack_from('<12fH', data, 84+i*50)) for i in range(struct.unpack_from('<I', data, 80)[0])]
    else:
        vertices = [list(map(float, line.split()[1:])) for line in data.decode('ascii').splitlines() if line.strip().startswith('vertex ')]
        if not vertices or len(vertices)%3:
            raise ValueError('Unrecognized STL export')
        rows = [[0., 0., 0.]+sum(vertices[i:i+3], [])+[0] for i in range(0, len(vertices), 3)]
    points = [row[k:k+3] for row in rows for k in (3, 6, 9)]
    p = shape['profile']
    if p['kind'] == 'plate':
        expected_min = [0, 0, 0]
        expected_max = [p['max'][i]-p['min'][i] for i in range(2)]+[shape['thickness_mm']]
    else:
        expected_min = [-p['radius'], -p['radius'], 0]
        expected_max = [p['radius'], p['radius'], shape['thickness_mm']]
    raw_min = [min(v[i] for v in points) for i in range(3)]
    raw_max = [max(v[i] for v in points) for i in range(3)]
    candidates = [factor for factor in (1., 1000., 25.4) if max(abs((raw_max[i]-raw_min[i])*factor-(expected_max[i]-expected_min[i])) for i in range(3)) <= shape['tolerance_mm']]
    if len(candidates) != 1:
        raise ValueError('STL units or bounds do not match the verified part')
    scale = candidates[0]
    # SW can translate STL to positive octant. Restore the already verified
    # canonical profile frame, not printing/assembly placement.
    shift = [(expected_min[i]+expected_max[i]-(raw_min[i]+raw_max[i])*scale)/2 for i in range(3)]
    with Path(path).open('wb') as stream:
        stream.write(b'MultiCAD verified millimetres'.ljust(80, b'\0'))
        stream.write(struct.pack('<I', len(rows)))
        for row in rows:
            stream.write(struct.pack('<12fH', *row[:3], *(v*scale+shift[i%3] for i, v in enumerate(row[3:12])), 0))


async def edit_part(backend, root, folder, plan, previous):
    shape = copy.deepcopy(previous['geometry'] if previous else plan['geometry'])
    edit = plan['edit']
    if 'diameter_mm' in edit:
        if len(shape['holes']) != 1:
            raise ValueError('Diameter edit requires exactly one identified hole; multi-hole selection is not implemented')
        shape['holes'][0]['radius'] = edit['diameter_mm']/2
    if 'thickness_mm' in edit:
        shape['thickness_mm'] = edit['thickness_mm']
    if expected_volume(shape) <= 0:
        raise ValueError('Hole consumes entire part')
    output = folder / (plan['target']+'.SLDPRT')
    preview = folder / (plan['target']+'.stl')
    title, active = None, None
    async with backend.operation_lock:
        async def call(operation, **values):
            result = await backend.invoke(operation, values)
            if not result['ok']:
                raise RuntimeError(operation+': '+str(result.get('error', result.get('data'))))
            return result['data']
        try:
            active = (await call('solidworks_list_documents')).get('activeDocument')
            if previous:
                source = reference(root, previous['file'])
                if digest(source) != previous['sha256']:
                    raise ValueError('Saved SW part changed')
                work = folder / 'working.SLDPRT'
                shutil.copy2(source, work)
                title = (await call('solidworks_open_document', path=str(work)))['title']
                validate(await call('multi_cad_inspect_part'), previous['geometry'])
                params = (await call('solidworks_list_parameters'))['parameters']
                for key, value in previous['parameter_values'].items():
                    hits = [p for p in params if p['parameter'] == key and abs(p.get('value', -999)-value) < .001]
                    if len(hits) != 1:
                        raise ValueError('Ambiguous persistent parameter '+key)
                mapping = previous['mapping']
                for name, key in mapping.items():
                    if name in edit:
                        await call('solidworks_set_parameter', parameter=key, value=edit[name], unit='mm')
            else:
                await call('solidworks_new_part')
                title = (await call('solidworks_list_documents'))['activeDocument']
                await call('solidworks_create_sketch', plane='Front')
                profile = shape['profile']
                origin = profile.get('min', profile.get('center'))
                mapping = {}
                if profile['kind'] == 'plate':
                    width, height = [profile['max'][i]-profile['min'][i] for i in range(2)]
                    await call('solidworks_sketch_rectangle', x1=0, y1=0, x2=width, y2=height)
                    await call('solidworks_sketch_dimension', entityPoints=[{'x': width/2, 'y': 0}], dimX=width/2, dimY=-5, value=width)
                    await call('solidworks_sketch_dimension', entityPoints=[{'x': width, 'y': height/2}], dimX=width+5, dimY=height/2, value=height)
                else:
                    radius = profile['radius']
                    await call('solidworks_sketch_circle', radius=radius, centerX=0, centerY=0)
                    await call('solidworks_sketch_dimension', entityPoints=[{'x': radius, 'y': 0}], dimX=radius+5, dimY=5, value=radius*2)
                for hole in shape['holes']:
                    x, y = [hole['center'][i]-origin[i] for i in range(2)]
                    radius = hole['radius']
                    await call('solidworks_sketch_circle', radius=radius, centerX=x, centerY=y)
                    parameter = await call('solidworks_sketch_dimension', entityPoints=[{'x': x+radius, 'y': y}], dimX=x+radius+3, dimY=y+3, value=radius*2)
                    if len(shape['holes']) == 1:
                        mapping['diameter_mm'] = parameter['parameter']
                    if profile['kind'] == 'plate':
                        types = ['SKETCHPOINT', 'SKETCHSEGMENT']
                        await call('solidworks_sketch_dimension', entityPoints=[{'x': x, 'y': y}, {'x': 0, 'y': height/2}], entityTypes=types, dimX=x/2, dimY=y-3, value=x)
                        await call('solidworks_sketch_dimension', entityPoints=[{'x': x, 'y': y}, {'x': width/2, 'y': 0}], entityTypes=types, dimX=x-3, dimY=y/2, value=y)
                feature = await call('solidworks_create_extrusion', depth=shape['thickness_mm'])
                await call('solidworks_rename_feature', name=feature['id'], newName='PartThickness')
                params = (await call('solidworks_list_parameters'))['parameters']
                matches = [p['parameter'] for p in params if p['parameter'].endswith('@PartThickness') and abs(p.get('value', -999)-shape['thickness_mm']) < .001]
                if len(matches) != 1:
                    raise ValueError('Cannot uniquely map thickness')
                mapping['thickness_mm'] = matches[0]
            validation = validate(await call('multi_cad_inspect_part'), shape)
            title = (await call('solidworks_save_document', path=str(output))).get('title', output.name)
            await call('solidworks_close_document', name=title)
            title = None
            title = (await call('solidworks_open_document', path=str(output)))['title']
            validation = validate(await call('multi_cad_inspect_part'), shape)
            params = (await call('solidworks_list_parameters'))['parameters']
            values = {p['parameter']: p['value'] for p in params if 'value' in p}
            if previous:
                changed = {mapping[k] for k in edit if k in mapping}
                for key, old in previous['parameter_values'].items():
                    if key not in changed and (key not in values or abs(values[key]-old) > .001):
                        raise ValueError('Protected SW dimension changed')
            for name, key in mapping.items():
                expected = shape['thickness_mm'] if name == 'thickness_mm' else shape['holes'][0]['radius']*2
                if key not in values or abs(values[key]-expected) > .001:
                    raise ValueError('Parameter mapping did not survive reopen')
            await call('solidworks_save_document', path=str(preview))
            normalize_stl(preview, shape)
            return {'file': str(output.relative_to(root)), 'preview': str(preview.relative_to(root)), 'sha256': digest(output),
                    'geometry': shape, 'mapping': mapping, 'parameter_values': values, 'validation': validation, 'main_format': 'SLDPRT'}
        finally:
            if title and not backend.uncertain:
                await call('solidworks_close_document', name=title)
            if active and not backend.uncertain:
                await call('solidworks_activate_document', name=active)
