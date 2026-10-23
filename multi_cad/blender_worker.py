"""Executed inside Blender; build and reopen validation run in separate processes."""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


project = Path(sys.argv[sys.argv.index("--") + 1])
mode = sys.argv[-1]
manifest = json.loads((project / "analysis/source_manifest.json").read_text(encoding="utf-8"))
output = project / "output/blender/Project.blend"

if mode == "build":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = .001
    meshes = {}
    for resource in manifest["resources"]:
        mesh = bpy.data.meshes.new(resource["id"])
        mesh.from_pydata(resource["vertices_mm"], [], resource["triangles"])
        mesh.update()
        meshes[resource["id"]] = mesh
    collections = {}
    for instance in manifest["instances"]:
        parent = bpy.context.scene.collection
        for depth in range(1, len(instance["hierarchy"])):
            key = "/".join(instance["hierarchy"][:depth])
            if key not in collections:
                collection = bpy.data.collections.new(instance["hierarchy"][depth-1])
                parent.children.link(collection)
                collections[key] = collection
            parent = collections[key]
        obj = bpy.data.objects.new(instance["id"], meshes[instance["resource_id"]])
        parent.objects.link(obj)
        obj.matrix_world = Matrix(instance["print_transform_mm"]).transposed()
        obj["source_resource_id"] = instance["resource_id"]
        obj["assembly_status"] = "unknown"
        obj["coordinate_space"] = "printing"
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
elif mode == "verify":
    bpy.ops.wm.open_mainfile(filepath=str(output))
    failures = []
    objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if len(objects) != len(manifest["instances"]):
        failures.append("Object count mismatch")
    resources = {r["id"]: r for r in manifest["resources"]}
    for instance in manifest["instances"]:
        obj = bpy.data.objects.get(instance["id"])
        if obj is None:
            failures.append("Missing " + instance["id"])
            continue
        resource = resources[instance["resource_id"]]
        if len(obj.data.vertices) != len(resource["vertices_mm"]) or len(obj.data.polygons) != len(resource["triangles"]):
            failures.append("Mesh count mismatch " + instance["id"])
        points = [obj.matrix_world @ v.co for v in obj.data.vertices]
        for axis in range(3):
            for field, actual in (("min", min(p[axis] for p in points)), ("max", max(p[axis] for p in points))):
                expected = instance["bounds_mm"][field][axis]
                if abs(actual-expected) > max(.0001, abs(expected)*1e-6):
                    failures.append("Bounds mismatch " + instance["id"])
    result = {"passed": not failures, "checks": ["reopen", "object_count", "mesh_counts", "world_bounds"],
              "failures": failures, "assembly_verified": False}
    (project / "reports/blender_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if failures:
        raise RuntimeError(str(failures))
else:
    raise ValueError("Unknown worker mode")
