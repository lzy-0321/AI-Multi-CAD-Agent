"""A deliberately bounded parametric recipe, with immutable validated versions."""
import hashlib
import json
import math
import shutil
import uuid
import time
from pathlib import Path

from .project import write_json

CENTERS = [(10., 10.), (110., 10.), (110., 70.), (10., 70.)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_plate(inspection, diameter):
    failures = []
    if inspection.get("solid_count") != 1:
        failures.append("Expected one solid")
    bounds = inspection.get("bounds", [])
    if len(bounds) != 1 or any(abs(v-e) > .001 for v, e in zip(bounds[0]["min"] + bounds[0]["max"], [0, 0, 0, 120, 80, 5])):
        failures.append("Protected plate bounds changed")
    expected = 120*80*5 - 4*math.pi*(diameter/2)**2*5
    if abs(inspection.get("volume_mm3", 0)-expected) > .01:
        failures.append("Volume mismatch")
    cylinders = inspection.get("cylinders", [])
    if len(cylinders) != 4:
        failures.append("Expected exactly four cylindrical hole faces")
    unmatched = list(CENTERS)
    for cylinder in cylinders:
        center = cylinder["origin_mm"][:2]
        match = next((p for p in unmatched if math.dist(p, center) < .001), None)
        if match is None or abs(cylinder["radius_mm"]*2-diameter) > .001 or abs(abs(cylinder["axis"][2])-1) > 1e-6:
            failures.append("Hole center, diameter or axis mismatch")
        elif match:
            unmatched.remove(match)
    sketches = inspection.get("sketches", [])
    if not sketches or any(s["constraint_status"] != 3 for s in sketches):
        failures.append("Sketch is not fully constrained")
    return {"passed": not failures, "failures": failures, "expected_volume_mm3": expected,
            "actual_volume_mm3": inspection.get("volume_mm3"), "checks": ["one_solid", "bounds", "hole_centers", "diameter", "volume", "fully_defined_sketch"]}


async def run_plate(backend, project, action, diameter=6):
    if action not in ("create", "edit", "verify"):
        raise ValueError("Action must be create, edit or verify")
    if not math.isfinite(diameter) or not 0 < diameter < 20:
        raise ValueError("Hole diameter must be between 0 and 20 mm")
    project = project.resolve()
    async with backend.operation_lock:
        await backend.request("catalog")
        if "multi_cad_inspect_part" not in backend.tools:
            raise ValueError("Plate recipe requires the pinned SW compatibility host; configure with multi-cad install-backend solidworks or --use-sw-host")
        if action == "create":
            project.mkdir(parents=True, exist_ok=False)
            (project / "output").mkdir()
            (project / "reports").mkdir()
            state = {"schema_version": 2, "kind": "parametric_plate", "main_format": "SLDPRT",
                     "required_capabilities": ["solidworks", "multi_cad_inspect_part"], "versions": [],
                     "parameters": {k: {"value": v, "unit": "mm", "source": "user", "protected": k != "hole_diameter"}
                                    for k, v in {"length": 120, "width": 80, "thickness": 5, "edge_offset": 10, "hole_diameter": diameter}.items()},
                     "assembly_position": "not_applicable"}
        else:
            state = json.loads((project / "project.json").read_text(encoding="utf-8"))
            if state.get("kind") != "parametric_plate" or not state["versions"]:
                raise ValueError("Not a validated plate project")
        state["status"] = "running"
        write_json(project / "project.json", state)
        owned_title, previous_title = None, None

        async def call(operation, **arguments):
            result = await backend.invoke(operation, arguments)
            if not result["ok"]:
                raise RuntimeError(f"{operation}: {result.get('error', result.get('data'))}; log={result.get('artifact')}")
            return result["data"]

        try:
            documents = await call("solidworks_list_documents")
            previous_title = documents.get("activeDocument")
            current = state["versions"][-1] if state["versions"] else None
            # Never attach to a user's already-open project copy, which may have unsaved edits.
            if current:
                original = (project / current["file"]).resolve()
                if not original.is_relative_to(project):
                    raise ValueError("Project file reference escapes project directory")
                if digest(original) != current["sha256"]:
                    raise ValueError("Saved version was externally changed; reconcile before editing")
                working = project / "output" / ("working-" + uuid.uuid4().hex + ".SLDPRT")
                shutil.copy2(original, working)
                opened = await call("solidworks_open_document", path=str(working))
                owned_title = opened["title"]
                old_diameter = current["hole_diameter"]
                baseline = validate_plate(await call("multi_cad_inspect_part"), old_diameter)
                if not baseline["passed"]:
                    raise ValueError(f"Baseline failed: {baseline['failures']}")
                params = (await call("solidworks_list_parameters"))["parameters"]
                for parameter, expected in state["parameter_values"].items():
                    matches = [p for p in params if p["parameter"] == parameter]
                    if len(matches) != 1 or abs(matches[0].get("value", -999)-expected) > .001:
                        raise ValueError(f"Ambiguous or changed parameter mapping: {parameter}")
                if action == "verify":
                    state["status"] = "verified"
                    state["last_validation"] = baseline
                    from .backend import fingerprint
                    write_json(backend.directory / "solidworks-verified.json", {"config_hash": fingerprint(backend.config),
                        "verified_at": time.time(), "historical": True,
                        "capabilities": ["reopen", "geometry_validation", "parameter_mapping"],
                        "evidence": str(project / "project.json")})
                    return baseline
                for parameter in state["hole_parameters"]:
                    await call("solidworks_set_parameter", parameter=parameter, value=diameter, unit="mm")
            else:
                await call("solidworks_new_part")
                owned_title = (await call("solidworks_list_documents"))["activeDocument"]
                sketch = await call("solidworks_create_sketch", plane="Front")
                await call("solidworks_sketch_rectangle", x1=0, y1=0, x2=120, y2=80)
                await call("solidworks_sketch_dimension", entityPoints=[{"x": 60, "y": 0}], dimX=60, dimY=-10, value=120)
                await call("solidworks_sketch_dimension", entityPoints=[{"x": 120, "y": 40}], dimX=130, dimY=40, value=80)
                hole_parameters = []
                for x, y in CENTERS:
                    await call("solidworks_sketch_circle", radius=diameter/2, centerX=x, centerY=y)
                    value = await call("solidworks_sketch_dimension", entityPoints=[{"x": x+diameter/2, "y": y}], dimX=x+8, dimY=y+8, value=diameter)
                    if not value.get("parameter"):
                        raise ValueError("No persistent diameter parameter returned")
                    hole_parameters.append(value["parameter"])
                    # Point-to-line dimensions force perpendicular X/Y distances.
                    # Point-to-point AddDimension2 may produce an aligned distance
                    # regardless of label position, moving holes diagonally.
                    types = ["SKETCHPOINT", "SKETCHSEGMENT"]
                    await call("solidworks_sketch_dimension", entityPoints=[{"x": x, "y": y}, {"x": 0, "y": 40}], entityTypes=types, dimX=x/2, dimY=y-4, value=x)
                    await call("solidworks_sketch_dimension", entityPoints=[{"x": x, "y": y}, {"x": 60, "y": 0}], entityTypes=types, dimX=x-4, dimY=y/2, value=y)
                sketch_state = await call("solidworks_get_state", detail="full")
                write_json(project / "reports/pre_extrusion.json", sketch_state)
                feature = await call("solidworks_create_extrusion", depth=5)
                await call("solidworks_rename_feature", name=feature["id"], newName="PlateThickness")
                # Read-back sketch name, not guessed Sketch1/localized 草图1.
                sketch_name = hole_parameters[0].split("@", 1)[1]
                await call("solidworks_rename_feature", name=sketch_name, newName="PlateProfile")
                state["hole_parameters"] = [p.split("@", 1)[0] + "@PlateProfile" for p in hole_parameters]
            inspection = await call("multi_cad_inspect_part")
            validation = validate_plate(inspection, diameter)
            if not validation["passed"]:
                raise ValueError(f"Geometry validation failed: {validation['failures']}")
            filename = f"plate-v{len(state['versions'])+1:03d}.SLDPRT"
            output = project / "output" / filename
            if output.exists():
                raise ValueError("Version output exists; refusing overwrite")
            saved = await call("solidworks_save_document", path=str(output))
            owned_title = saved.get("title", filename)
            await call("solidworks_close_document", name=owned_title)
            owned_title = None
            opened = await call("solidworks_open_document", path=str(output))
            owned_title = opened["title"]
            reopened = await call("multi_cad_inspect_part")
            validation = validate_plate(reopened, diameter)
            if not validation["passed"]:
                raise ValueError("Reopen verification failed")
            parameters = (await call("solidworks_list_parameters"))["parameters"]
            values = {p["parameter"]: p["value"] for p in parameters if "value" in p}
            if current:
                for key, old_value in state["parameter_values"].items():
                    if key not in state["hole_parameters"] and (key not in values or abs(values[key]-old_value) > .001):
                        raise ValueError(f"Protected parameter changed: {key}")
            for key in state["hole_parameters"]:
                if key not in values or abs(values[key]-diameter) > .001:
                    raise ValueError(f"Diameter parameter not persistent: {key}")
            state["parameter_values"] = values
            version = {"file": str(output.relative_to(project)), "sha256": digest(output), "hole_diameter": diameter,
                       "validation": validation, "reopened": True}
            state["versions"].append(version)
            state["parameters"]["hole_diameter"]["value"] = diameter
            state["last_validation"] = validation
            state["status"] = "verified"
            state.pop("error", None)
            write_json(project / "reports" / (filename + ".json"), {"inspection": reopened, "parameters": parameters, "validation": validation})
            from .backend import fingerprint
            write_json(backend.directory / "solidworks-verified.json", {"config_hash": fingerprint(backend.config),
                "verified_at": time.time(), "historical": True, "capabilities": ["parametric_plate", "reopen", "geometry_validation"] + (["edit_diameter"] if current else []),
                "evidence": str(project / "reports" / (filename + ".json"))})
            return {"project": str(project), "version": version}
        except Exception as error:
            state["status"] = "failed"
            state["error"] = str(error)
            if owned_title and not backend.uncertain:
                try:
                    failed_path = project / "output" / ("failed-" + uuid.uuid4().hex + ".SLDPRT")
                    saved = await call("solidworks_save_document", path=str(failed_path))
                    owned_title = saved["title"]
                    state["failed_artifact"] = str(failed_path.relative_to(project))
                except Exception as save_error:
                    state["failed_artifact_error"] = str(save_error)
            raise
        finally:
            # Only explicitly owned documents are closed. Never close all documents.
            if owned_title and not backend.uncertain:
                try:
                    await call("solidworks_close_document", name=owned_title)
                except Exception as error:
                    state["cleanup_error"] = str(error)
            if previous_title and not backend.uncertain:
                try:
                    await call("solidworks_activate_document", name=previous_title)
                except Exception as error:
                    state["restore_active_error"] = str(error)
            write_json(project / "project.json", state)
