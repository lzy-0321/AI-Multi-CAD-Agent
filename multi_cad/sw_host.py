"""Compatibility host for the pinned HarrierPigeon server; upstream files stay unchanged.

Adds precise read-only inspection, configurable templates and scoped dimension-dialog
suppression. The host remains an MCP server; the gateway uses no out-of-band COM.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--part-template")
    parser.add_argument("--assembly-template")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    sys.path.insert(0, str(source))
    from solidworks.connection import SolidWorksConnection
    from solidworks.sketching import SketchingTools
    from solidworks.geometry_query import GeometryQueryTools
    from solidworks.com_utils import com_prop
    from mcp.types import Tool

    original_init = SolidWorksConnection.__init__

    def initialize(self):
        original_init(self)
        for field, path in (("template_path", args.part_template), ("assembly_template_path", args.assembly_template)):
            if path:
                if not Path(path).is_file():
                    raise ValueError(f"Missing template: {path}")
                setattr(self, field, str(Path(path).resolve()))
    SolidWorksConnection.__init__ = initialize

    original_dimension = SketchingTools.sketch_dimension

    def dimension(self, values):
        app = self.connection.app
        previous = app.GetUserPreferenceToggle(10)  # swInputDimValOnCreate, local swconst typelib
        app.SetUserPreferenceToggle(10, False)
        try:
            # Upstream selects by coordinate using the current view's pick
            # tolerance. Fit small profiles before selecting their segments.
            doc = self.connection.get_active_doc()
            if doc:
                doc.ViewZoomtofit2()
            return original_dimension(self, values)
        finally:
            app.SetUserPreferenceToggle(10, previous)
    SketchingTools.sketch_dimension = dimension

    original_definitions = GeometryQueryTools.get_tool_definitions
    original_execute = GeometryQueryTools.execute

    def definitions(self):
        return original_definitions(self) + [Tool(name="multi_cad_inspect_part", description="Read exact solid count, bounds, cylindrical axes, sketch constraints and dimensions from the active part. Survives MCP restarts.",
            inputSchema={"type": "object", "properties": {}})]

    def execute(self, name, values):
        if name != "multi_cad_inspect_part":
            return original_execute(self, name, values)
        self.connection.ensure_connection()
        doc = self.connection.get_active_doc()
        if not doc or int(com_prop(doc, "GetType")) != 1:
            raise ValueError("Active document is not a part")
        bodies = doc.GetBodies2(0, False) or []
        cylinders, sketches, bounds = [], [], []
        for body in bodies:
            # Extreme points are exact, unlike the approximate GetBodyBox API.
            # Late-bound COM out arguments differ across versions; vertex extents
            # are sufficient for this planar plate, while cylinders are separate.
            pts = [list(com_prop(v, "GetPoint")) for v in (body.GetVertices() or [])]
            if pts:
                bounds.append({"min": [min(p[i] for p in pts)*1000 for i in range(3)],
                               "max": [max(p[i] for p in pts)*1000 for i in range(3)]})
            for face in body.GetFaces() or []:
                surface = com_prop(face, "GetSurface")
                if int(com_prop(surface, "Identity")) == 4002:
                    params = com_prop(surface, "CylinderParams")
                    cylinders.append({"origin_mm": [v*1000 for v in params[:3]], "axis": list(params[3:6]),
                                      "radius_mm": params[6]*1000})
        for feature in doc.FeatureManager.GetFeatures(False) or []:
            if com_prop(feature, "GetTypeName2") in ("ProfileFeature", "3DProfileFeature"):
                sketch = com_prop(feature, "GetSpecificFeature2")
                segments = []
                for segment in com_prop(sketch, "GetSketchSegments") or []:
                    kind = int(com_prop(segment, "GetType"))
                    item = {"type": kind}
                    for label, prop in (("start", "GetStartPoint2"), ("end", "GetEndPoint2"), ("center", "GetCenterPoint2")):
                        try:
                            point = com_prop(segment, prop)
                            item[label] = [com_prop(point, axis)*1000 for axis in ("X", "Y", "Z")]
                        except Exception:
                            pass
                    if kind == 1:
                        item["radius_mm"] = com_prop(segment, "GetRadius")*1000
                    segments.append(item)
                sketches.append({"name": feature.Name, "constraint_status": int(com_prop(sketch, "GetConstrainedStatus")), "segments": segments})
        mass = com_prop(doc.Extension, "CreateMassProperty") if bodies else None
        return json.dumps({"solid_count": len(bodies), "bounds": bounds, "cylinders": cylinders,
                           "sketches": sketches, "volume_mm3": mass.Volume*1e9 if mass else None,
                           "path": com_prop(doc, "GetPathName"), "title": com_prop(doc, "GetTitle")})
    GeometryQueryTools.get_tool_definitions = definitions
    GeometryQueryTools.execute = execute
    spec = importlib.util.spec_from_file_location("multi_cad_sw_upstream", source / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.run()


if __name__ == "__main__":
    main()
