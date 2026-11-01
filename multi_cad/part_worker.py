"""Isolated Blender job. Invoked by the existing Blender MCP, never in a user's scene."""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def boolean_solver(modifier, target, cutter):
    import bmesh
    def manifold(obj):
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            return bool(bm.faces) and all(e.is_manifold for e in bm.edges)
        finally:
            bm.free()
    supported = {item.identifier for item in modifier.bl_rna.properties['solver'].enum_items}
    modifier.solver = 'MANIFOLD' if 'MANIFOLD' in supported and manifold(target) and manifold(cutter) else 'EXACT'


def signature(obj):
    mesh = obj.to_mesh(preserve_all_data_layers=False, depsgraph=bpy.context.evaluated_depsgraph_get())
    try:
        mesh.calc_loop_triangles()
        return hashlib.sha256(json.dumps([
            [[float(v) for v in p.co] for p in mesh.vertices],
            [list(t.vertices) for t in mesh.loop_triangles]], separators=(',', ':')).encode()).hexdigest()
    finally:
        obj.to_mesh_clear()


def snapshot():
    deps = bpy.context.evaluated_depsgraph_get()
    result = {}
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or not obj.get('part_id'):
            continue
        evaluated = obj.evaluated_get(deps)
        points = [obj.matrix_world @ v.co for v in evaluated.data.vertices]
        result[obj['part_id']] = {
            'raw': signature(obj), 'evaluated': signature(evaluated),
            'matrix': [list(row) for row in obj.matrix_world],
            'group': obj.get('source_group'), 'role': obj.get('role'),
            'bounds': {'min': [min(p[a] for p in points) for a in range(3)],
                       'max': [max(p[a] for p in points) for a in range(3)]} if points else None}
    return result


def solid_mesh(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    edges, oriented = {}, {}
    volume = 0.
    for tri in mesh.loop_triangles:
        ids = list(tri.vertices)
        a, b, c = [mesh.vertices[i].co for i in ids]
        area2 = (b-a).cross(c-a).length
        if not math.isfinite(area2) or area2 == 0:
            evaluated.to_mesh_clear()
            raise ValueError('Degenerate output triangle')
        volume += a.dot(b.cross(c))/6
        for u, v in zip(ids, ids[1:]+ids[:1]):
            key = tuple(sorted((u, v)))
            edges[key] = edges.get(key, 0)+1
            oriented[(u, v)] = oriented.get((u, v), 0)+1
    if not edges or any(v != 2 for v in edges.values()) or any(n != oriented.get((v, u), 0) for (u, v), n in oriented.items()) or abs(volume) < 1e-8:
        evaluated.to_mesh_clear()
        raise ValueError('Output is not a closed consistently oriented solid')
    return evaluated, mesh, abs(volume)*abs(obj.matrix_world.determinant())


def stl(obj, path):
    evaluated, mesh, volume = solid_mesh(obj)
    try:
        with Path(path).open('xb') as stream:
            stream.write(b'MultiCAD millimetres'.ljust(80, b'\0'))
            stream.write(struct.pack('<I', len(mesh.loop_triangles)))
            for tri in mesh.loop_triangles:
                points = [obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices]
                normal = (points[1]-points[0]).cross(points[2]-points[0]).normalized()
                stream.write(struct.pack('<12fH', *normal, *(v for p in points for v in p), 0))
    finally:
        evaluated.to_mesh_clear()
    return volume


def verify_cut(objects, center, axis, radius, depth, tolerance=.05):
    center, axis = Vector(center), Vector(axis).normalized()
    wall_points = 0
    for obj in objects:
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for vertex in evaluated.data.vertices:
            p = obj.matrix_world @ vertex.co-center
            axial = p.dot(axis)
            radial = (p-axis*axial).length
            if abs(axial) < depth/2-tolerance and radial < radius-tolerance:
                raise ValueError('Material remains inside requested cylindrical cut')
            if abs(axial) <= depth/2+tolerance and abs(radial-radius) <= tolerance:
                wall_points += 1
    if wall_points < 6:
        raise ValueError('Requested cylindrical wall could not be verified')


def execute(request):
    mode = request['mode']
    if request.get('input'):
        bpy.ops.wm.open_mainfile(filepath=request['input'])
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.unit_settings.system = 'METRIC'
        bpy.context.scene.unit_settings.scale_length = .001
        manifest = json.loads(Path(request['manifest']).read_text(encoding='utf-8'))
        resources = {r['id']: r for r in manifest['resources']}
        groups = {}
        for instance in manifest['instances']:
            resource = resources[instance['resource_id']]
            mesh = bpy.data.meshes.new(instance['id'])
            mesh.from_pydata(resource['vertices_mm'], [], resource['triangles'])
            mesh.update()
            obj = bpy.data.objects.new(instance['id'], mesh)
            bpy.context.scene.collection.objects.link(obj)
            obj.matrix_world = Matrix(instance['print_transform_mm']).transposed()
            obj['part_id'], obj['role'] = instance['id'], instance['role']
            obj['source_group'], obj['source_name'] = instance['group_id'], instance['name']
            obj['assembly_status'] = 'unknown'
            groups.setdefault(instance['group_id'], []).append(obj)
        for members in groups.values():
            negatives = [o for o in members if o['role'] == 'negative_part']
            normals = [o for o in members if o['role'] == 'normal_part']
            unknown = [o for o in members if o['role'] not in ('negative_part', 'normal_part')]
            for obj in members:
                obj['export_blocked'] = bool(unknown or (negatives and len(normals) != 1))
                if obj['role'] != 'normal_part':
                    obj.hide_render = True
                    obj.display_type = 'WIRE'
            if len(normals) == 1 and not unknown:
                for cutter in negatives:
                    modifier = normals[0].modifiers.new('Source negative: '+cutter['part_id'], 'BOOLEAN')
                    modifier.operation, modifier.solver, modifier.object = 'DIFFERENCE', 'EXACT', cutter
    bpy.context.view_layer.update()
    before = snapshot()
    objects = {o['part_id']: o for o in bpy.context.scene.objects if o.get('part_id')}
    allowed = set(request.get('affected', []))
    for replacement in request.get('replacements', []):
        obj = objects[replacement['target']]
        if obj['part_id'] not in allowed:
            raise ValueError('Unauthorized replacement')
        existing = set(bpy.data.objects)
        bpy.ops.wm.stl_import(filepath=replacement['stl'], global_scale=1.0, use_scene_unit=False)
        imported = [o for o in bpy.data.objects if o not in existing and o.type == 'MESH']
        if len(imported) != 1:
            raise ValueError('Expected one SW preview mesh')
        preview = imported[0]
        geometry = replacement['geometry']
        origin = geometry['profile'].get('min', geometry['profile'].get('center'))
        for vertex in preview.data.vertices:
            coordinates = list(vertex.co)
            local = [0., 0., 0.]
            for index, axis in enumerate(geometry['plane_axes']):
                local[axis] = coordinates[index]+origin[index]
            local[geometry['axis']] = coordinates[2]+geometry['base_mm']
            vertex.co = local
        obj.data = preview.data.copy()
        bpy.data.objects.remove(preview, do_unlink=True)
        obj.modifiers.clear()
        obj['main_format'] = 'SLDPRT'
        obj['representation'] = 'derived_preview'
    for edit in request.get('edits', []):
        obj = objects[edit['target']]
        if obj['part_id'] not in allowed or obj.get('export_blocked'):
            raise ValueError('Target is not authorized or has unresolved source semantics')
        operation = edit['operation']
        if operation == 'translate':
            obj.matrix_world.translation += Vector(edit['delta_mm'])
        elif operation == 'scale':
            pivot = Vector(edit['pivot_mm'])
            scaling = Matrix.Diagonal(Vector(edit['factors']+[1]))
            obj.matrix_world = Matrix.Translation(pivot) @ scaling @ Matrix.Translation(-pivot) @ obj.matrix_world
        elif operation == 'resize_negative':
            if obj['role'] != 'negative_part':
                raise ValueError('Expected a source negative volume')
            axes = edit['plane_axes']
            center = edit['center']
            factor = edit['diameter_mm'] / (2*edit['old_radius'])
            for vertex in obj.data.vertices:
                for index, axis in enumerate(axes):
                    vertex.co[axis] = center[index]+(vertex.co[axis]-center[index])*factor
            obj.data.update()
            for product in objects.values():
                for modifier in product.modifiers:
                    if modifier.type == 'BOOLEAN' and modifier.object == obj:
                        boolean_solver(modifier, product, obj)
        elif operation == 'cut_cylinder':
            if obj['role'] != 'normal_part':
                raise ValueError('Cylinder cut requires a normal product part')
            bpy.ops.mesh.primitive_cylinder_add(vertices=256, radius=edit['diameter_mm']/2,
                depth=edit['depth_mm'], location=edit['center_mm'])
            cutter = bpy.context.object
            cutter.name = 'Edit cutter '+obj['part_id']
            cutter.rotation_mode = 'QUATERNION'
            cutter.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(Vector(edit['axis']))
            bpy.context.view_layer.update()
            placement = cutter.matrix_world.copy()
            cutter.parent = obj
            cutter.matrix_world = placement
            cutter['owner_part'] = obj['part_id']
            cutter.hide_render, cutter.display_type = True, 'WIRE'
            modifier = obj.modifiers.new('Editable cylindrical cut', 'BOOLEAN')
            modifier.operation, modifier.solver, modifier.object = 'DIFFERENCE', 'EXACT', cutter
            boolean_solver(modifier, obj, cutter)
        else:
            raise ValueError('Unsupported edit operation')
        bpy.context.view_layer.update()
    after = snapshot()
    if request.get('preview'):
        selected = [objects[key] for key in request['preview_targets']]
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH':
                obj.hide_render = obj not in selected or obj.get('role') == 'negative_part'
        points = [obj.matrix_world @ Vector(corner) for obj in selected for corner in obj.bound_box]
        if not points:
            raise ValueError('No preview geometry')
        low = Vector([min(p[a] for p in points) for a in range(3)])
        high = Vector([max(p[a] for p in points) for a in range(3)])
        center, size = (low+high)/2, max((high-low).length, 1)
        bpy.ops.object.camera_add(location=center+Vector((1, -1, 1))*size)
        camera = bpy.context.object
        camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type, camera.data.ortho_scale = 'ORTHO', size*1.2
        bpy.context.scene.camera = camera
        scene = bpy.context.scene
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.display.shading.light = 'STUDIO'
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 900, 700, 100
        scene.render.filepath = request['preview']
        bpy.ops.render.render(write_still=True)
    baseline = request.get('baseline', before)
    if set(after) != set(baseline):
        raise ValueError('Object identity set changed')
    for key in baseline:
        if key not in allowed and after[key] != baseline[key]:
            raise ValueError('Unselected object changed: '+key)
    checks = {}
    for target in allowed:
        obj = objects[target]
        if obj['role'] == 'normal_part':
            evaluated, mesh, volume = solid_mesh(obj)
            evaluated.to_mesh_clear()
            checks[target] = {'closed': True, 'volume_mm3': volume}
    for edit in request.get('edits', []):
        if edit['operation'] == 'cut_cylinder' and before[edit['target']]['evaluated'] == after[edit['target']]['evaluated']:
            raise ValueError('Cylinder did not alter target geometry')
        if edit['operation'] == 'resize_negative':
            dependents = [key for key in allowed if key != edit['target'] and objects[key]['role'] == 'normal_part']
            if not dependents or all(before[key]['evaluated'] == after[key]['evaluated'] for key in dependents):
                raise ValueError('Negative volume did not change any resolved product solid')
            cutter = objects[edit['target']]
            center = Vector((0, 0, 0))
            for index, axis in enumerate(edit['plane_axes']):
                center[axis] = edit['center'][index]
            center[edit['cylinder_axis']] = edit['cylinder_base']+edit['cylinder_depth']/2
            direction = cutter.matrix_world.to_3x3().col[edit['cylinder_axis']]
            verify_cut([objects[key] for key in dependents], cutter.matrix_world @ center,
                direction, edit['diameter_mm']/2, edit['cylinder_depth']*direction.length)
        if edit['operation'] == 'cut_cylinder':
            verify_cut([objects[edit['target']]], edit['center_mm'], edit['axis'], edit['diameter_mm']/2, edit['depth_mm'])
        if edit['operation'] in ('translate', 'scale'):
            old = Matrix(before[edit['target']]['matrix'])
            if edit['operation'] == 'translate':
                old.translation += Vector(edit['delta_mm'])
            else:
                pivot = Vector(edit['pivot_mm'])
                old = Matrix.Translation(pivot) @ Matrix.Diagonal(Vector(edit['factors']+[1])) @ Matrix.Translation(-pivot) @ old
            actual = objects[edit['target']].matrix_world
            if max(abs(actual[i][j]-old[i][j]) for i in range(4) for j in range(4)) > .0001:
                raise ValueError('Requested transform was not applied')
    exported = []
    for target, path in request.get('exports', {}).items():
        obj = objects[target]
        if obj['role'] != 'normal_part' or obj.get('export_blocked'):
            raise ValueError('Only resolved product solids can be exported')
        stl(obj, path)
        exported.append(path)
    if request.get('output'):
        if Path(request['output']).exists():
            raise ValueError('Refusing to overwrite a saved version')
        bpy.ops.wm.save_as_mainfile(filepath=request['output'])
    return {'passed': True, 'snapshot': after, 'checks': checks, 'exports': exported, 'unit': 'mm'}


if __name__ == '__main__':
    request_path = Path(sys.argv[sys.argv.index('--')+1])
    request = json.loads(request_path.read_text(encoding='utf-8'))
    try:
        result = execute(request)
    except Exception as error:
        result = {'passed': False, 'error': str(error)}
        raise
    finally:
        Path(request['report']).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
