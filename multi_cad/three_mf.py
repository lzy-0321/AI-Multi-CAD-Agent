"""Read 3MF resource graphs without conflating mesh resources with physical parts.

Transforms use the 3MF row-vector convention; exported coordinates are millimetres.
Slicer metadata is retained, but unimplemented semantics are explicitly unknown.
"""
import hashlib
import math
import posixpath
import zipfile
from pathlib import Path
from collections import Counter
from urllib.parse import unquote
from xml.etree import ElementTree as ET

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NS = {"c": CORE}
UNITS = {"micron": .001, "millimeter": 1, "centimeter": 10,
         "inch": 25.4, "foot": 304.8, "meter": 1000}
IDENTITY = [1., 0., 0., 0., 1., 0., 0., 0., 1., 0., 0., 0.]


def matrix(value=None):
    values = list(map(float, value.split())) if value else IDENTITY.copy()
    if len(values) != 12 or not all(map(math.isfinite, values)):
        raise ValueError("Invalid 3MF transform")
    return [values[0:3] + [0], values[3:6] + [0],
            values[6:9] + [0], values[9:12] + [1]]


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4))
             for j in range(4)] for i in range(4)]


def transform(point, m):
    p = list(point) + [1]
    return [sum(p[k] * m[k][j] for k in range(4)) for j in range(3)]


def package_path(base, target):
    target = unquote(target).replace("\\", "/")
    path = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                             else posixpath.join(posixpath.dirname(base), target))
    if path == ".." or path.startswith("../") or ":" in path:
        raise ValueError("Invalid package reference")
    return path


def xml(data):
    # Reject declarations before parsing; accept ordinary XML declarations.
    normalized = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in normalized or b"<!ENTITY" in normalized:
        raise ValueError("DTD and entity declarations are unsupported")
    return ET.fromstring(data)


def bounds(vertices):
    if not vertices:
        raise ValueError("Empty mesh")
    low = [min(v[i] for v in vertices) for i in range(3)]
    high = [max(v[i] for v in vertices) for i in range(3)]
    return {"min": low, "max": high, "size": [b-a for a, b in zip(low, high)]}


def mesh_quality(vertices, triangles):
    edges = Counter()
    oriented = Counter()
    degenerate = 0
    volume6 = 0.
    for tri in triangles:
        a, b, c = [vertices[i] for i in tri]
        cross = [b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0]]
        volume6 += sum(a[i]*cross[i] for i in range(3))
        ab, ac = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        area = [ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0]]
        degenerate += sum(x*x for x in area) == 0
        for u, v in zip(tri, tri[1:] + tri[:1]):
            edges[tuple(sorted((u, v)))] += 1
            oriented[(u, v)] += 1
    closed = bool(triangles) and all(n == 2 for n in edges.values()) and not degenerate
    consistent = all(oriented[(u, v)] == oriented[(v, u)] for u, v in oriented)
    return {"edge_closed": closed, "consistent_winding": consistent,
            "degenerate_triangles": degenerate,
            "volume_mm3": abs(volume6)/6 if closed and consistent else None,
            "volume_note": "Signed-volume estimate; self-intersections not checked"}


def analyse(path):
    resources, models, instances = {}, {}, []
    warnings = ["Assembly placement unknown; build transforms represent printing placement.",
                "Mesh resources are candidates, not confirmed physical product parts.",
                "Slicer plates, modifiers, material and support semantics are not yet interpreted."]
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > 256 * 1024**2:
            raise ValueError("Package exceeds prototype size limit (256 MiB / 10000 entries)")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate package entries")
        relations = xml(archive.read("_rels/.rels"))
        starts = [r for r in relations if r.get("Type", "").endswith("/3dmodel")]
        if len(starts) != 1 or starts[0].get("TargetMode") == "External":
            raise ValueError("Expected one internal 3MF start relationship")
        root_path = package_path("", starts[0].attrib["Target"])

        def load(model_path):
            if model_path in models:
                return models[model_path]
            root = xml(archive.read(model_path))
            if root.tag != f"{{{CORE}}}model":
                raise ValueError("Unsupported model namespace")
            unit = root.get("unit", "millimeter")
            if unit not in UNITS:
                raise ValueError(f"Unknown model unit: {unit}")
            objects = {o.attrib["id"]: o for o in root.findall("c:resources/c:object", NS)}
            if len(objects) != len(root.findall("c:resources/c:object", NS)):
                raise ValueError("Duplicate object IDs")
            models[model_path] = (root, objects, UNITS[unit])
            return models[model_path]

        root, _, root_scale = load(root_path)
        world = matrix()
        for i in range(3):
            world[i][i] = root_scale

        def visit(model_path, object_id, placement, trail, active, printable):
            key = f"{model_path}#{object_id}"
            if key in active or len(active) > 64:
                raise ValueError("Cyclic or too deep component graph")
            _, objects, scale = load(model_path)
            if object_id not in objects:
                raise ValueError(f"Missing object: {key}")
            obj = objects[object_id]
            mesh = obj.find("c:mesh", NS)
            components = obj.findall("c:components/c:component", NS)
            if mesh is not None and components:
                raise ValueError("Object contains both mesh and components")
            if mesh is not None:
                rid = hashlib.sha256(key.encode()).hexdigest()[:16]
                if rid not in resources:
                    vertices = [[float(v.attrib[a]) for a in ("x", "y", "z")]
                                for v in mesh.findall("c:vertices/c:vertex", NS)]
                    if not all(math.isfinite(x) for v in vertices for x in v):
                        raise ValueError("Non-finite vertex")
                    triangles = [[int(t.attrib[a]) for a in ("v1", "v2", "v3")]
                                 for t in mesh.findall("c:triangles/c:triangle", NS)]
                    if any(i < 0 or i >= len(vertices) for t in triangles for i in t):
                        raise ValueError("Triangle vertex index out of range")
                    mm = [[x*scale for x in v] for v in vertices]
                    resources[rid] = {"id": rid, "source": key, "name": obj.get("name", f"Object {object_id}"),
                                      "type": obj.get("type", "model"), "classification": "unconfirmed",
                                      "vertices_mm": mm, "triangles": triangles, "bounds_mm": bounds(mm),
                                      "quality": mesh_quality(mm, triangles), "source_unit_scale": scale}
                resource = resources[rid]
                normalize = matrix()
                for i in range(3):
                    normalize[i][i] = 1/scale
                mm_placement = multiply(normalize, placement)
                instances.append({"id": f"instance-{len(instances)+1:05d}", "resource_id": rid,
                                  "hierarchy": trail + [key], "printable": printable,
                                  "print_transform_mm": mm_placement, "assembly_transform_mm": None,
                                  "bounds_mm": bounds([transform(v, mm_placement) for v in resource["vertices_mm"]])})
                if len(instances) > 10000:
                    raise ValueError("Instance expansion limit exceeded")
            elif not components:
                warnings.append(f"Object without geometry: {key}")
            for index, component in enumerate(components):
                ref = component.get(f"{{{PROD}}}path")
                child_path = package_path(model_path, ref) if ref else model_path
                _, _, child_scale = load(child_path)
                if child_scale != scale:
                    raise ValueError("Mixed-unit component references require explicit support")
                visit(child_path, component.attrib["objectid"],
                      multiply(matrix(component.get("transform")), placement),
                      trail + [f"{key}/component-{index}"], active | {key}, printable)

        for index, item in enumerate(root.findall("c:build/c:item", NS)):
            ref = item.get(f"{{{PROD}}}path")
            model_path = package_path(root_path, ref) if ref else root_path
            if load(model_path)[2] != root_scale:
                raise ValueError("Mixed-unit build references require explicit support")
            visit(model_path, item.attrib["objectid"], multiply(matrix(item.get("transform")), world),
                  [f"build-{index}"], set(), item.get("printable", "true") not in ("0", "false"))
        counts = Counter(i["resource_id"] for i in instances)
        for rid, resource in resources.items():
            resource["instance_count"] = counts[rid]
        metadata = {m.get("name", ""): m.text for m in root.findall("c:metadata", NS)}
        result = {"schema_version": 1, "unit": "mm", "root_model": root_path,
                "metadata": metadata, "package_entries": names, "plates": None,
                "resources": list(resources.values()), "instances": instances, "warnings": warnings}
        from .slicer import enrich
        settings = xml(archive.read('Metadata/model_settings.config')) if 'Metadata/model_settings.config' in names else None
        return enrich(result, settings, hashlib.sha256(Path(path).read_bytes()).hexdigest())
