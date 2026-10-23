import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .three_mf import analyse


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def create_project(source, destination, goal):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or source.suffix.lower() != ".3mf":
        raise ValueError("This prototype accepts an existing .3mf input")
    destination.mkdir(parents=True, exist_ok=False)
    for folder in ("inputs", "analysis", "workspace/extracted_meshes", "output/blender", "reports"):
        (destination / folder).mkdir(parents=True)
    copied = destination / "inputs" / "source.3mf"
    shutil.copy2(source, copied)
    state = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
             "goal": goal, "original_source": str(source),
             "input_sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
             "stages": {"analysis": "pending", "blender": "not_started"}}
    write_json(destination / "project.json", state)
    resume_analysis(destination)
    return destination


def resume_analysis(destination):
    destination = Path(destination).resolve()
    state = json.loads((destination / "project.json").read_text(encoding="utf-8"))
    if state["stages"]["analysis"] == "complete":
        return
    try:
        source = destination / "inputs/source.3mf"
        if hashlib.sha256(source.read_bytes()).hexdigest() != state["input_sha256"]:
            raise ValueError("Original input checksum changed")
        manifest = analyse(source)
        for resource in manifest["resources"]:
            # Preserve source resources, including unknown auxiliary objects; do not guess exclusions.
            obj = destination / "workspace/extracted_meshes" / (resource["id"] + ".obj")
            with obj.open("w", encoding="utf-8") as stream:
                stream.write("# Coordinates in millimetres; source resource, not confirmed product part\n")
                for v in resource["vertices_mm"]:
                    stream.write("v " + " ".join(map(str, v)) + "\n")
                for t in resource["triangles"]:
                    stream.write("f " + " ".join(str(i+1) for i in t) + "\n")
        write_json(destination / "analysis/source_manifest.json", manifest)
        mechanical = any(word in state["goal"].lower() for word in ("参数", "孔", "公差", "机械", "solidworks", "parametric"))
        plan = {"kind": "rule_based_baseline", "goal": state["goal"],
                "requested_backend": "solidworks" if mechanical else "blender",
                "execution_status": "requires_reconstruction_plan" if mechanical else "ready_for_mesh_export",
                "reason": "Goal keywords indicate CAD intent" if mechanical else "Mesh preservation baseline",
                "requires_geometry_based_ai_routing": True,
                "parts": [{"resource_id": r["id"], "representation": "editable_mesh",
                           "assembly_status": "unknown"} for r in manifest["resources"]]}
        write_json(destination / "analysis/plan.json", plan)
        report = ["# Analysis report", "", f"Mesh resources: {len(manifest['resources'])}",
                  f"Build leaf instances: {len(manifest['instances'])}", "",
                  "These counts are not verified product-part counts.", "", "## Limitations", ""]
        report.extend("- " + warning for warning in manifest["warnings"])
        (destination / "reports/final_report.md").write_text("\n".join(report), encoding="utf-8")
        state["stages"]["analysis"] = "complete"
        state.pop("error", None)
    except Exception as error:
        state["stages"]["analysis"] = "failed"
        state["error"] = str(error)
        raise
    finally:
        write_json(destination / "project.json", state)
