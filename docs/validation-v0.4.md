**English** | [中文](zh/validation-v0.4.md)

# v0.4 local acceptance — 2026-10-27

Environment: Windows, Python 3.14, Blender 5.2.2 LTS and SolidWorks 2025. The existing pinned Blender and SolidWorks MCPs were used through new stdio gateway processes. Live Blender uses a dedicated test session; each modeling job runs in a separate background Blender. Private source models, installation paths, native outputs and detailed logs are excluded from Git.

## Measured results

| Scenario | Evidence |
|---|---|
| Real clock source | 12 plate records; 27 normal and 8 negative part instances. This is a source-role inventory, not a claim that 35 product parts exist. |
| Real drawer source | 13 plate records; 29 normal part instances. No geometry qualified for the bounded SW recognizer. |
| Clock single-part move | One selected part moved 1 mm; all other recorded raw/evaluated geometry, group identities and transforms matched after saving and reopening. |
| Clock negative volume | A recognized cylindrical source cutter changed to 6 mm; its product solid was checked for closedness, cylindrical wall and absence of material inside the cut. Product scaling with its cutter and subsequent 7 mm edit also passed in new processes. |
| Drawer multi-part move | Two selected parts moved 1 mm; the other 27 instances remained unchanged. Saved BLEND reopened successfully. |
| Real-source SW reconstruction | A small rectangular clock part was rebuilt with a fully defined profile and thickness 0.3 mm; the source object was replaced only by its derived scene preview. Other objects remained unchanged. |
| Synthetic SW washer | One of two instances reconstructed with a 12 mm hole; another process changed hole to 14 mm and thickness to 4 mm. A third process reopened the SW file and checked geometry and every persistent parameter. The other instance was preserved. |
| Mixed scene / Blender continuation | The remaining mesh washer received an off-center 4 mm cylindrical cut, then a 1.1 Z scale in another process; its cutter followed. SW artifacts and the other instance stayed unchanged. Selected STL export passed closedness and millimetre checks. |
| Preview | Selected clock product rendered to local PNG; image inspected. This is supplementary evidence, not dimensional acceptance. |

SW reconstruction checks one solid, fully defined sketches, persistent dimensions, analytic volume and cylinder position/radius; rectangular profiles additionally check exact vertex bounds. Source fitting checks matching planar caps, loop geometry, circle residuals/chord error and volume. This is a bounded analytic check, not general Hausdorff comparison or a self-intersection proof for arbitrary meshes.

## Regression and installation

The automated suite covers source preservation, instance ambiguity, declared slicer roles, synthetic Orca-style plate metadata, unknown auxiliary types, incomplete geometry, parameter validation, manifest tampering, write failure without replay, failed multi-target commit, eight-tool compatibility, existing plate lifecycle and installer recovery. Synthetic Orca metadata does not establish compatibility with every Orca version.

The Windows ZIP acceptance separately checks clean installation into a Chinese/space-containing directory, execution outside the checkout, installed package location, upgrade, dependency-failure protection, other Agent settings, original-file preservation and rollback. The installer does not start CAD. The local `installation-acceptance.json` is tied to the archive checksum.

Using compact JSON character counts: 96 SW schemas = 76,062 characters; eight gateway schemas = 3,799; gateway plus one part-edit schema = 5,088. The last comparison is approximately 93.3% fewer characters. These are not actual model token measurements.

## Limits retained

- No second-machine CAD acceptance, at the user's request; no fresh Python 3.11 CAD run in this local session.
- SW support is axis-aligned simple profiles in source geometry and rigid source placements. Scaled/sheared placements, unresolved source booleans and complex drawer bodies are rejected.
- Native-file changes by users are detected by hashes; ambiguous mappings stop editing. Arbitrary external SLDPRT recognition is not implemented.
- General assembly, arbitrary sculpting, picture-based modeling, slicer settings write-back and automatic Blender-to-SW reanalysis remain unimplemented.
- Actual acceptance used owned documents. Unrelated-open-document cleanup behavior is covered by lifecycle tests; it is not claimed as an additional live multi-user test.
- This record describes local CAD acceptance for v0.4.0. GitHub CI independently validates the published installer; the older v0.3.1 release is preserved.
