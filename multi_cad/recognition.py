"""Conservative recognition of axis-aligned extruded plates and washers in mm.

No inferred geometry is accepted unless both cap topology and volume agree.
Arbitrary orientation and multi-level solids deliberately return unsupported.
"""
import math
from collections import Counter, defaultdict


def circle(points, tolerance):
    if len(points) < 8:
        return None
    a = points[0]
    b = max(points, key=lambda p: math.dist(a, p))
    c = max(points, key=lambda p: abs((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])))
    d = 2*(a[0]*(b[1]-c[1])+b[0]*(c[1]-a[1])+c[0]*(a[1]-b[1]))
    if abs(d) < 1e-12:
        return None
    aa, bb, cc = (sum(x*x for x in p) for p in (a, b, c))
    center = [(aa*(b[1]-c[1])+bb*(c[1]-a[1])+cc*(a[1]-b[1]))/d,
              (aa*(c[0]-b[0])+bb*(a[0]-c[0])+cc*(b[0]-a[0]))/d]
    radii = [math.dist(p, center) for p in points]
    radius = sum(radii)/len(radii)
    residual = max(abs(r-radius) for r in radii)
    # Include chord sagitta, not just vertex agreement, in surface error.
    chord = max(math.dist(points[i], points[(i+1) % len(points)]) for i in range(len(points)))
    sagitta = radius-math.sqrt(max(0, radius*radius-chord*chord/4))
    if max(residual, sagitta) > tolerance:
        return None
    return {'center': center, 'radius': radius, 'residual_mm': max(residual, sagitta)}


def recognize(resource, tolerance=.05):
    if not math.isfinite(tolerance) or tolerance <= 0 or tolerance > 1:
        raise ValueError('Tolerance must be > 0 and <= 1 mm')
    quality = resource['quality']
    failure = {'supported': False, 'reason': 'Not a validated axis-aligned plate/washer extrusion', 'tolerance_mm': tolerance}
    if not quality['edge_closed'] or not quality['consistent_winding']:
        return dict(failure, reason='Closed consistently oriented mesh required')
    vertices, triangles = resource['vertices_mm'], resource['triangles']
    for axis in sorted(range(3), key=lambda a: resource['bounds_mm']['size'][a]):
        low, high = resource['bounds_mm']['min'][axis], resource['bounds_mm']['max'][axis]
        thickness = high-low
        if thickness <= 2*tolerance or any(min(abs(p[axis]-low), abs(p[axis]-high)) > tolerance for p in vertices):
            continue
        axes = [a for a in range(3) if a != axis]
        lower = {tuple(round(p[a]/tolerance, 3) for a in axes) for p in vertices if abs(p[axis]-low) <= tolerance}
        upper = {tuple(round(p[a]/tolerance, 3) for a in axes) for p in vertices if abs(p[axis]-high) <= tolerance}
        if lower != upper:
            continue
        edges = Counter()
        for tri in triangles:
            if all(abs(vertices[i][axis]-low) <= tolerance for i in tri):
                for u, v in zip(tri, tri[1:]+tri[:1]):
                    edges[tuple(sorted((u, v)))] += 1
        adjacency = defaultdict(list)
        for (a, b), count in edges.items():
            if count == 1:
                adjacency[a].append(b)
                adjacency[b].append(a)
        if not adjacency or any(len(v) != 2 for v in adjacency.values()):
            continue
        remaining, loops = set(adjacency), []
        while remaining:
            start = min(remaining)
            current, previous, loop = start, None, []
            while current in remaining:
                remaining.remove(current)
                loop.append([vertices[current][a] for a in axes])
                nxt = next(n for n in adjacency[current] if n != previous)
                previous, current = current, nxt
            if current != start:
                loops = []
                break
            loops.append(loop)
        if not loops:
            continue
        area = lambda p: abs(sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p)))/2)
        loops.sort(key=area, reverse=True)
        outer, holes = loops[0], [circle(p, tolerance) for p in loops[1:]]
        if any(h is None for h in holes):
            continue
        lo = [min(p[a] for p in outer) for a in range(2)]
        hi = [max(p[a] for p in outer) for a in range(2)]
        rectangle = all(min(abs(p[0]-lo[0]), abs(p[0]-hi[0]), abs(p[1]-lo[1]), abs(p[1]-hi[1])) <= tolerance for p in outer)
        rectangle = rectangle and abs(area(outer)-(hi[0]-lo[0])*(hi[1]-lo[1])) <= tolerance*2*sum(hi[a]-lo[a] for a in range(2))
        ring = circle(outer, tolerance)
        if rectangle:
            profile = {'kind': 'plate', 'min': lo, 'max': hi}
            outer_area = (hi[0]-lo[0])*(hi[1]-lo[1])
        elif ring and len(holes) <= 1 and (not holes or math.dist(ring['center'], holes[0]['center']) <= tolerance):
            profile = dict(kind='washer', **ring)
            outer_area = math.pi*ring['radius']**2
        else:
            continue
        expected = (outer_area-sum(math.pi*h['radius']**2 for h in holes))*thickness
        measured = quality['volume_mm3']
        # A conservative cap-area/volume check rejects hidden cavities and stray geometry.
        volume_tolerance = max(tolerance*outer_area*2, expected*.002)
        if expected <= 0 or abs(expected-measured) > volume_tolerance:
            continue
        return {'supported': True, 'profile': profile, 'holes': holes, 'axis': axis, 'plane_axes': axes,
                'base_mm': low, 'thickness_mm': thickness, 'tolerance_mm': tolerance,
                'source': 'measured', 'volume_mm3': measured, 'analytic_volume_mm3': expected,
                'volume_error_mm3': abs(expected-measured), 'surface_error_mm': max([h['residual_mm'] for h in holes]+[ring['residual_mm'] if ring else 0]),
                'method': 'two planar caps, boundary loops, circle fit, chord error, closed mesh and volume'}
    return failure
