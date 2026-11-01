"""Slicer semantics supplement the 3MF graph; metadata never supplies executable code."""
import hashlib
import json
from collections import Counter


def metadata(element):
    return {m.get('key'): m.get('value') for m in element.findall('metadata') if m.get('key')}


def enrich(manifest, settings, source_hash):
    objects = {}
    plates = []
    membership = {}
    if settings is not None:
        for obj in settings.findall('object'):
            oid = obj.get('id')
            if oid in objects:
                raise ValueError('Duplicate slicer object identity')
            part_ids = [part.get('id') for part in obj.findall('part')]
            if len(part_ids) != len(set(part_ids)):
                raise ValueError('Duplicate slicer part identity')
            objects[oid] = {'metadata': metadata(obj), 'parts': {
                p.get('id'): {'name': metadata(p).get('name'), 'role': p.get('subtype', 'unknown')}
                for p in obj.findall('part')}}
        for number, plate in enumerate(settings.findall('plate')):
            meta = metadata(plate)
            entry = {'id': meta.get('plater_id', str(number + 1)), 'name': meta.get('plater_name'), 'instances': []}
            for instance in plate.findall('model_instance'):
                value = metadata(instance)
                key = (value.get('object_id'), value.get('instance_id'))
                membership.setdefault(key, []).append(entry['id'])
                entry['instances'].append({'object_id': key[0], 'instance_id': key[1]})
            plates.append(entry)
    resources = {r['id']: r for r in manifest['resources']}
    occurrence = Counter()
    groups = {}
    for instance in manifest['instances']:
        trail = instance['hierarchy']
        build = trail[0]
        top = trail[1].split('/component-')[0] if len(trail) > 2 else trail[-1]
        top_id = top.rsplit('#', 1)[-1]
        if build not in groups:
            occurrence_index = occurrence[top]
            occurrence[top] += 1
            groups[build] = (top_id, occurrence_index)
        top_id, occurrence_index = groups[build]
        record = objects.get(top_id, {})
        leaf_id = trail[-1].rsplit('#', 1)[-1]
        part = record.get('parts', {}).get(leaf_id, {})
        resource = resources[instance['resource_id']]
        role = part.get('role', 'normal_part' if settings is None and resource['type'] == 'model' else 'unknown')
        instance.update(source_instance_id=instance['id'],
            id='part-' + hashlib.sha256((source_hash + '/' + '/'.join(trail)).encode()).hexdigest()[:20],
            object_id=top_id, group_id=build, occurrence=occurrence_index,
            name=part.get('name') or record.get('metadata', {}).get('name') or resource['name'],
            role=role, plate_ids=membership.get((top_id, str(occurrence_index)), []),
            source_part_id=leaf_id)
        if 'geometry_sha256' not in resource:
            resource['geometry_sha256'] = hashlib.sha256(json.dumps(
                [resource['vertices_mm'], resource['triangles']], separators=(',', ':')).encode()).hexdigest()
    manifest.update(schema_version=2, source_sha256=source_hash, plates=plates if settings is not None else None)
    manifest['warnings'] = [w for w in manifest['warnings'] if not w.startswith('Slicer plates,')]
    manifest['warnings'].append('Slicer roles are source declarations; unknown roles are retained, never treated as product solids.')
    return manifest
