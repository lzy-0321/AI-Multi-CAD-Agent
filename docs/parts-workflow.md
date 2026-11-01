**English** | [中文](zh/parts-workflow.md)

# Selected-part editing (0.4.0)

Use an existing Agent with the unified gateway. Search capabilities with `backend="project"` and query `parts`, then fetch only the schema of the operation being used. The gateway still exposes eight MCP tools. These local project operations do not require a new model API.

## Workflow

1. `parts_import`: supply a source 3MF, a new project directory and the user's goal. The source is copied and hashed. Slicer names, plate membership, source roles and resource instances are preserved. A mesh is not automatically a physical product part.
2. `parts_list`: page/search concise object records. `parts_detail` returns original-source dimensions, mesh quality and shape analysis; `parts_preview` produces a local PNG. Detail explicitly describes the source, not the dimensions of a later edited version.
3. Select exact IDs. Duplicate names require disambiguation. Set `scope` to `instance` or `all_instances`; the latter means references to the same source resource, not every geometrically similar mesh. Do not guess whether the user meant one or all copies.
4. `parts_plan`: provide an edit. Read the route, geometric evidence, limits and any dependent cutters. Missing dimensions or ambiguous targets should be asked together.
5. `parts_edit`: execute the selected targets. A multi-target edit is one project transaction, but a list of separate gateway calls is not a transaction. The same edit applies to each selected target. Different edits use separate versions.
6. `parts_verify`: reopen Blender and any SW native files in isolated copies, compare saved geometry, placement, dimensions and mappings. `parts_export` exports selected resolved product solids as STL in millimetres. Print placement remains separate from unknown assembly placement.

## Supported edits and routing

| Operation | Parameters | Execution |
|---|---|---|
| `translate` | `delta_mm` vector | Blender world-space translation |
| `scale` | positive `factors`, `pivot_mm` | Blender world-space scaling; all feature dimensions on those axes change |
| `cut_cylinder` | `center_mm`, normalized `axis`, `diameter_mm`, `depth_mm` | Editable Blender boolean; cut geometry and closedness checked |
| `resize_negative` | `diameter_mm` | Recognized cylindrical source negative; world-space diameter, dependent product checked |
| `set_parameters` | `thickness_mm` and/or `diameter_mm` | SW plate/washer reconstruction or persistent native parameter edit |

Mechanical parameter edits require a closed, consistently oriented, axis-aligned plate or washer with two matching planar caps. Circle-fit and chord errors must meet the project's tolerance (default 0.05 mm). Diameter edits currently require one identified hole. Multiple straight holes can be reconstructed while changing thickness. Arbitrarily oriented, stepped, curved, ribbed or unresolved boolean-source solids are refused for SW reconstruction. This is not general reverse engineering.

Complex meshes use Blender for the explicitly supported operations. A request for parametric output never silently falls back to mesh output. Source negatives are retained as editable cutters, not exported as product solids. A product transform carries its unambiguously owned source cutters; the plan lists these dependencies. Unknown roles and ambiguous multi-product boolean groups block edits/exports. Non-manifold outputs are rejected. Blender 5.2's manifold solver is selected when available and applicable; otherwise the exact solver is used and its result still must pass validation.

SW remains the master representation of reconstructed parts. Its STL is a derived scene preview, with units and canonical bounds checked. Editing that preview through the high-level Blender route is refused. A part already changed in Blender also requires fresh geometry analysis before SW reconstruction; automatic reanalysis of arbitrary edited meshes is not included in this version.

## Execution, files and recovery

The configured Blender MCP launches a separate background Blender worker. It never opens project files into the user's live scene. This requires the upstream `execute_blender_code` capability to permit subprocess execution. A safe-mode rejection is reported; this project does not disable safe mode or bypass it. Keep Blender and its selected MCP add-on running before editing.

SW uses the existing compatibility host, a configured part template, and upstream sketch/feature tools. Only owned working documents are closed; the previous active document is restored. Small sketches are fitted to view before upstream coordinate selection.

Project state records relative artifacts, source/manifest/file hashes, selected IDs, dependent IDs, measured geometry, user edits, native parameter mappings, verification and immutable versions. Large meshes, reports and complete logs remain local. Each new edit works on a copy and registers a version only after reopening it. Failed batches leave the last successful project state unchanged and write a local failure report. Inspect a timed-out write before reconciliation; no write is automatically replayed.

`parts_upgrade` backs up a legacy mesh project's state and manifest before reanalysis. It does not pretend old object IDs were verified. Already-versioned projects are not silently migrated.

For CLI automation, put the operation arguments in a UTF-8 JSON file, then run:

```powershell
python -m multi_cad parts parts_import --arguments import.json
python -m multi_cad parts parts_list --arguments list.json
python -m multi_cad parts parts_plan --arguments edit.json
python -m multi_cad parts parts_edit --arguments edit.json
python -m multi_cad parts parts_verify --arguments selection.json
python -m multi_cad parts parts_export --arguments selection.json
```

Example `edit.json` after choosing the actual ID:

```json
{"project":"D:/CAD/my-project","targets":["part-ID-from-parts_list"],"scope":"instance","edit":{"operation":"set_parameters","diameter_mm":12}}
```

Outputs are `.blend`, selected `.SLDPRT` files and optional STL. Slicer settings are not written back into 3MF. Automatic assembly, arbitrary sculpting, picture reconstruction and second-machine validation remain outside this delivery.
