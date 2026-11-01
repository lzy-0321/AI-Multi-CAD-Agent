"""Durable part selection and bounded editing; large data stays in project files."""
import asyncio
import copy
import hashlib
import json
import math
import shutil
import uuid
from pathlib import Path

from .project import write_json
from .recognition import recognize
from .backend import ProcessLease


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Project reference escapes its directory')
    return path


def load_project(project):
    root = Path(project).resolve()
    state = read(root / 'project.json')
    source = root / 'inputs/source.3mf'
    if state.get('input_sha256') != digest(source):
        raise ValueError('Source file was changed; import a new project')
    manifest = read(root / 'analysis/source_manifest.json')
    if state.get('manifest_sha256') != digest(root / 'analysis/source_manifest.json'):
        raise ValueError('Manifest integrity is unknown or changed; upgrade legacy projects or reimport the original')
    if manifest.get('schema_version', 1) < 2:
        raise ValueError('Legacy project: run parts_upgrade before editing')
    return root, state, manifest


def select(manifest, selectors, scope):
    if scope not in ('instance', 'all_instances'):
        raise ValueError('Explicit scope required: instance or all_instances')
    if not selectors:
        raise ValueError('At least one target is required')
    selected = {}
    for selector in selectors:
        hits = [i for i in manifest['instances'] if i['id'] == selector or i['name'] == selector]
        if len(hits) != 1:
            raise ValueError('Ambiguous or missing target; select an exact ID: '+selector)
        target = hits[0]
        hits = [i for i in manifest['instances'] if i['resource_id'] == target['resource_id']] if scope == 'all_instances' else hits
        for item in hits:
            selected[item['id']] = item
    return list(selected.values())


def summary(instance):
    return {key: instance.get(key) for key in ('id', 'name', 'role', 'group_id', 'plate_ids', 'resource_id')}


def vector(value, length=3, positive=False):
    if not isinstance(value, list) or len(value) != length or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or (positive and v <= 0) for v in value):
        raise ValueError('Expected finite numeric vector'+(' with positive values' if positive else ''))
    return value


def validate_edit(edit):
    operation = edit.get('operation')
    if operation == 'translate':
        vector(edit.get('delta_mm'))
    elif operation == 'scale':
        vector(edit.get('factors'), positive=True)
        vector(edit.get('pivot_mm'))
    elif operation == 'cut_cylinder':
        vector(edit.get('center_mm'))
        vector(edit.get('axis'))
        if abs(sum(v*v for v in edit['axis'])-1) > 1e-6:
            raise ValueError('Cylinder axis must be normalized')
        vector([edit.get('diameter_mm'), edit.get('depth_mm')], 2, True)
    elif operation in ('resize_negative', 'set_parameters'):
        values = [edit[k] for k in ('diameter_mm', 'thickness_mm') if k in edit]
        if not values:
            raise ValueError('Provide a diameter or thickness in mm')
        vector(values, len(values), True)
    else:
        raise ValueError('Unsupported edit operation')


def plan(manifest, targets, edit, tolerance):
    validate_edit(edit)
    resources = {r['id']: r for r in manifest['resources']}
    result = []
    for target in targets:
        geometry = recognize(resources[target['resource_id']], tolerance)
        group = [i for i in manifest['instances'] if i['group_id'] == target['group_id']]
        negatives = [i for i in group if i['role'] == 'negative_part']
        unknown = [i for i in group if i['role'] not in ('normal_part', 'negative_part')]
        entry = {'target': target['id'], 'geometry': geometry, 'edit': copy.deepcopy(edit), 'status': 'ready', 'backend': 'blender'}
        if unknown or target['role'] not in ('normal_part', 'negative_part'):
            entry.update(status='unsupported', reason='Unknown source semantics; preserve source and clarify role')
        elif edit['operation'] == 'set_parameters':
            entry['backend'] = 'solidworks'
            if target['role'] != 'normal_part' or not geometry['supported'] or negatives:
                entry.update(status='unsupported', reason='Parametric editing requires a recognized plate/washer without unresolved source boolean volumes')
            matrix = target['print_transform_mm']
            if any(abs(sum(matrix[i][k]*matrix[j][k] for k in range(3))-(1 if i == j else 0)) > 1e-6 for i in range(3) for j in range(3)):
                entry.update(status='unsupported', reason='Scaled/sheared source placement must be baked and reanalysed before dimensional SW editing')
        elif edit['operation'] == 'resize_negative':
            if target['role'] != 'negative_part' or not geometry['supported'] or geometry['profile']['kind'] != 'washer' or geometry['holes']:
                entry.update(status='unsupported', reason='Source negative must be a recognized straight cylinder')
            else:
                vectors = [target['print_transform_mm'][axis][:3] for axis in geometry['plane_axes']]
                scales = [math.sqrt(sum(v*v for v in row)) for row in vectors]
                if min(scales) <= 0 or abs(scales[0]-scales[1]) > max(scales)*1e-6 or abs(sum(a*b for a, b in zip(*vectors))) > scales[0]*scales[1]*1e-6:
                    entry.update(status='unsupported', reason='Negative volume is elliptic or sheared in world space')
                else:
                    entry['edit'].update(plane_axes=geometry['plane_axes'], center=geometry['profile']['center'], old_radius=geometry['profile']['radius']*scales[0]*target.get('radius_factor', 1),
                        cylinder_axis=geometry['axis'], cylinder_base=geometry['base_mm'], cylinder_depth=geometry['thickness_mm'])
        elif edit['operation'] in ('translate', 'scale'):
            entry['notice'] = 'World-space transform affects every feature dimension on the selected axes; this is not a local feature edit.'
            if negatives and target['role'] == 'normal_part':
                if sum(i['role'] == 'normal_part' for i in group) == 1:
                    entry['dependencies'] = [i['id'] for i in negatives]
                    entry['notice'] += ' Associated source cutters follow this product transform.'
                else:
                    entry.update(status='unsupported', reason='Boolean group has multiple product parts; ownership is ambiguous')
        result.append(entry)
    return result


async def blender_job(gateway, root, request, goal):
    backend = gateway.backend('blender')
    job = root / 'workspace' / ('job-'+uuid.uuid4().hex)
    job.mkdir(parents=True)
    request['report'] = str(job / 'result.json')
    request_path = job / 'request.json'
    write_json(request_path, request)
    worker = Path(__file__).with_name('part_worker.py')
    # Launch an isolated Blender through the configured MCP. Never load a project
    # into the user's live scene. Safe-mode rejections are surfaced, not bypassed.
    code = ('import bpy, subprocess\n'
            f'args = [bpy.app.binary_path, "--background", "--factory-startup", "--python-exit-code", "1", "--python", {str(worker)!r}, "--", {str(request_path)!r}]\n'
            f'log = open({str(job / "blender.log")!r}, "w", encoding="utf-8")\n'
            'try:\n'
            '    result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=150, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))\n'
            '    print("job_exit", result.returncode)\n'
            'finally:\n'
            '    log.close()\n')
    async with backend.operation_lock:
        response = await backend.invoke('execute_blender_code', {'code': code, 'user_prompt': goal}, 175)
    if not response['ok'] or not Path(request['report']).exists():
        raise RuntimeError('Blender job failed or was rejected; inspect '+str(job))
    report = read(request['report'])
    if not report.get('passed'):
        raise ValueError('Blender validation failed: '+report.get('error', 'unknown'))
    return report


async def execute(gateway, operation, arguments):
    project = arguments['project']
    if operation == 'parts_import':
        from .project import create_project
        root = create_project(arguments['source'], project, arguments.get('goal', 'Edit selected parts'))
        state = read(root / 'project.json')
        state.update(kind='part_project', schema_version=3, versions=[])
        write_json(root / 'project.json', state)
        return {'project': str(root), 'status': 'imported', 'next': 'parts_list'}
    if operation == 'parts_upgrade':
        from .three_mf import analyse
        root = Path(project).resolve()
        with_project = ProcessLease(root / '.parts.lock')
        try:
            state = read(root / 'project.json')
            if state.get('input_sha256') != digest(root / 'inputs/source.3mf'):
                raise ValueError('Original input changed')
            if state.get('versions'):
                raise ValueError('Already versioned; automatic migration refused')
            backup = root / ('migration-'+uuid.uuid4().hex)
            backup.mkdir()
            shutil.copy2(root / 'project.json', backup / 'project.json')
            shutil.copy2(root / 'analysis/source_manifest.json', backup / 'source_manifest.json')
            manifest = analyse(root / 'inputs/source.3mf')
            write_json(root / 'analysis/source_manifest.json', manifest)
            state['manifest_sha256'] = digest(root / 'analysis/source_manifest.json')
            state.update(kind='part_project', schema_version=3, versions=[])
            write_json(root / 'project.json', state)
            return {'migrated': True}
        finally:
            with_project.close()
    root, state, manifest = load_project(project)
    if operation == 'parts_list':
        query = arguments.get('query', '').casefold()
        items = [summary(i) for i in manifest['instances'] if query in (i['name']+' '+i['role']).casefold()]
        offset, limit = arguments.get('offset', 0), arguments.get('limit', 20)
        plates = None if manifest['plates'] is None else [{'id': p['id'], 'name': p['name'], 'instance_count': len(p['instances'])} for p in manifest['plates']]
        return {'total': len(items), 'items': items[offset:offset+min(limit, 50)], 'plates': plates}
    targets = select(manifest, arguments.get('targets', []), arguments.get('scope'))
    if operation == 'parts_detail':
        resources = {r['id']: r for r in manifest['resources']}
        return {'items': [dict(summary(t), bounds_mm=t['bounds_mm'], print_transform_mm=t['print_transform_mm'],
            quality=resources[t['resource_id']]['quality'], instance_count=resources[t['resource_id']]['instance_count'],
            geometry=recognize(resources[t['resource_id']], arguments.get('tolerance_mm', .05)),
            geometry_basis='original_source', assembly_position='unknown') for t in targets]}
    planned_version = state.get('versions', [])[-1]['id'] if state.get('versions') else None
    if operation in ('parts_plan', 'parts_edit'):
        planning_targets = [dict(t) for t in targets]
        if state.get('versions'):
            latest = state['versions'][-1]
            snapshots = read(reference(root, latest['report']))['snapshot']
            for target in planning_targets:
                if target['id'] not in snapshots:
                    raise ValueError('Saved target mapping is missing')
                matrix = snapshots[target['id']]['matrix']
                target['print_transform_mm'] = [list(row) for row in zip(*matrix)]
                target['radius_factor'] = math.prod(p['edit']['diameter_mm']/(2*p['edit']['old_radius'])
                    for version in state['versions'] for p in version['plans']
                    if p['target'] == target['id'] and p['edit']['operation'] == 'resize_negative')
        plans = plan(manifest, planning_targets, arguments['edit'], arguments.get('tolerance_mm', .05))
        for p in plans:
            history = [item for version in state.get('versions', []) for item in version.get('plans', []) if item['target'] == p['target']]
            if history and history[-1]['backend'] == 'solidworks' and p['backend'] != 'solidworks':
                p.update(status='unsupported', reason='This part is owned by its SW native file; editing its preview would lose native synchronization')
            if history and p['backend'] == 'solidworks' and any(item['backend'] == 'blender' for item in history):
                p.update(status='unsupported', reason='Source geometry changed in Blender; current geometry must be reanalysed before SW reconstruction')
        if operation == 'parts_plan':
            return {'plans': plans, 'unselected': 'preserve geometry, transform and identity', 'assembly': 'unknown'}
        if any(p['status'] != 'ready' for p in plans):
            return {'ok': False, 'status': 'unsupported', 'plans': plans}
    lease = ProcessLease(root / '.parts.lock')
    try:
        # Reload after acquiring the cross-process project lease.
        root, state, manifest = load_project(project)
        if state.get('kind') != 'part_project':
            raise ValueError('Upgrade legacy project before editing')
        current = state['versions'][-1] if state['versions'] else None
        if operation == 'parts_edit' and (current['id'] if current else None) != planned_version:
            raise ValueError('Project advanced while planning; read and plan again')
        if current:
            for file, checksum in current['files'].items():
                if digest(reference(root, file)) != checksum:
                    raise ValueError('Saved artifact changed; reconcile before editing')
        folder = root / 'output' / ('version-'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        baseline = read(reference(root, current['report']))['snapshot'] if current else None
        blend_input = str(reference(root, current['blend'])) if current else None
        if operation == 'parts_preview':
            image = folder / 'selection.png'
            report = await blender_job(gateway, root, {'mode': 'preview', 'input': blend_input,
                'manifest': str(root / 'analysis/source_manifest.json'), 'preview': str(image),
                'preview_targets': [t['id'] for t in targets]}, state['goal'])
            return {'image': str(image), 'targets': [summary(t) for t in targets], 'assembly_position': 'unknown'}
        if operation == 'parts_verify':
            if not current:
                raise ValueError('No saved version')
            report = await blender_job(gateway, root, {'mode': 'verify', 'input': blend_input, 'baseline': baseline}, state['goal'])
            sw_reports = {}
            from .part_sw import verify_part
            for target, record in current.get('solidworks', {}).items():
                sw_reports[target] = await verify_part(gateway.backend('solidworks'), root, folder, record)
            return {'passed': report['passed'], 'version': current['id'], 'solidworks': sw_reports}
        if operation == 'parts_export':
            if not current:
                raise ValueError('Edit and save a version first')
            exports = {t['id']: str(folder / (t['id']+'.stl')) for t in targets}
            await blender_job(gateway, root, {'mode': 'export', 'input': blend_input, 'baseline': baseline, 'exports': exports}, state['goal'])
            return {'files': list(exports.values()), 'unit': 'mm'}
        if operation != 'parts_edit':
            raise ValueError('Unknown part operation')
        if not current:
            initial = folder / 'baseline.blend'
            report = await blender_job(gateway, root, {'mode': 'build', 'manifest': str(root / 'analysis/source_manifest.json'), 'output': str(initial)}, state['goal'])
            baseline, blend_input = report['snapshot'], str(initial)
        affected = {t['id'] for t in targets}
        for target in targets:
            if target['role'] == 'negative_part':
                affected.update(i['id'] for i in manifest['instances'] if i['group_id'] == target['group_id'] and i['role'] == 'normal_part')
        edits = [dict(p['edit'], target=p['target']) for p in plans if p['backend'] == 'blender']
        dependency_ids = {key for p in plans for key in p.get('dependencies', [])}
        if dependency_ids & {t['id'] for t in targets}:
            raise ValueError('Select the product alone; its source cutters already follow the transform')
        for p in plans:
            for key in p.get('dependencies', []):
                edits.append(dict(p['edit'], target=key))
        affected.update(dependency_ids)
        sw_records = copy.deepcopy(current.get('solidworks', {}) if current else {})
        replacements = []
        for p in plans:
            if p['backend'] == 'solidworks':
                from .part_sw import edit_part
                record = await edit_part(gateway.backend('solidworks'), root, folder, p, sw_records.get(p['target']))
                sw_records[p['target']] = record
                replacements.append({'target': p['target'], 'stl': str(reference(root, record['preview'])), 'geometry': p['geometry']})
        output = folder / 'Project.blend'
        report = await blender_job(gateway, root, {'mode': 'edit', 'input': blend_input, 'output': str(output),
            'edits': edits, 'replacements': replacements, 'affected': sorted(affected), 'baseline': baseline}, state['goal'])
        reopened = await blender_job(gateway, root, {'mode': 'verify', 'input': str(output), 'baseline': report['snapshot']}, state['goal'])
        reopened['edit_checks'] = report['checks']
        reopened['reopened'] = True
        report_path = folder / 'validation.json'
        write_json(report_path, reopened)
        files = {str(path.relative_to(root)): digest(path) for path in folder.iterdir() if path.suffix in ('.blend', '.SLDPRT', '.stl', '.json')}
        for record in sw_records.values():
            for field in ('file', 'preview'):
                files[record[field]] = digest(reference(root, record[field]))
        version = {'id': folder.name, 'blend': str(output.relative_to(root)), 'report': str(report_path.relative_to(root)),
            'files': files, 'targets': sorted(affected), 'plans': plans, 'solidworks': sw_records, 'reopened': True}
        state['versions'].append(version)
        state.update(status='verified', assembly_position='unknown')
        write_json(root / 'project.json', state)
        return {'passed': True, 'version': version['id'], 'blend': str(output), 'targets': sorted(affected)}
    except Exception as error:
        # Failed artifacts remain inspectable, while the last successful state is unchanged.
        write_json(root / 'reports' / ('failure-'+uuid.uuid4().hex+'.json'), {'error': str(error)})
        raise
    finally:
        lease.close()


def definitions():
    common = {'project': {'type': 'string'}}
    selection = {'targets': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 20}, 'scope': {'enum': ['instance', 'all_instances']}}
    edit = {'type': 'object', 'properties': {'operation': {'enum': ['translate', 'scale', 'cut_cylinder', 'resize_negative', 'set_parameters']},
        **{k: {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3} for k in ('delta_mm', 'factors', 'pivot_mm', 'center_mm', 'axis')},
        **{k: {'type': 'number', 'exclusiveMinimum': 0} for k in ('diameter_mm', 'depth_mm', 'thickness_mm')}}, 'required': ['operation'], 'additionalProperties': False}
    specs = {
        'parts_import': ('Import 3MF source without changing it; parse slicer parts and roles.', {'source': {'type': 'string'}, 'goal': {'type': 'string'}}, ['source']),
        'parts_upgrade': ('Back up and upgrade a legacy mesh project without guessing old mappings.', {}, []),
        'parts_list': ('Search concise part names, stable IDs, roles and plate membership.', {'query': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, []),
        'parts_plan': ('Analyze selected geometry and route a bounded edit; no CAD writes.', dict(selection, edit=edit, tolerance_mm={'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1}), ['targets', 'scope', 'edit']),
        'parts_detail': ('Read selected source dimensions, quality and geometry fit; large meshes remain local.', dict(selection, tolerance_mm={'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1}), ['targets', 'scope']),
        'parts_preview': ('Render selected objects into a local PNG; printing placement is not assembly placement.', selection, ['targets', 'scope']),
        'parts_edit': ('Edit only selected parts; atomic project version after reopen verification. Scale is world-space whole-object scaling. set_parameters uses SW; other edits use Blender.', dict(selection, edit=edit, tolerance_mm={'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1}), ['targets', 'scope', 'edit']),
        'parts_verify': ('Reopen the saved project and compare geometry and placement.', selection, ['targets', 'scope']),
        'parts_export': ('Export only selected resolved product solids to STL in mm.', selection, ['targets', 'scope'])}
    return {name: {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': dict(common, **properties), 'required': ['project']+required, 'additionalProperties': False}} for name, (description, properties, required) in specs.items()}
