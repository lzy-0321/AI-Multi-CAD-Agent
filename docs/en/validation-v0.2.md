[中文](../validation-v0.2.md) | **English**

# v0.2 validation record

Acceptance date: 2026-10-22 (Australia/Sydney). The evidence below is from the current machine. It does not mean every SolidWorks or Blender version passed.

## Verified

- All 23 automated tests passed. They cover configuration migration and merging, the MCP protocol, no replay after a timeout, parameter mapping, and file-version protection. Reopening the base plate again under the default user configuration passed.
- Sketch, dimension, extrude, rename, save, open, and parameter-edit tools came from the upstream SolidWorks MCP.
- Created a 120×80×5 mm plate. The four hole centers are (10,10), (110,10), (110,70), and (10,70) mm, with a diameter of 6 mm. The sketch is fully defined, there is one solid, the volume is 47434.513322353836 mm³, and save plus reopen passed.
- A second, independent MCP process changed the four holes to 8 mm from a working copy, protected the other parameters, and produced a new-version volume of 46994.690350851255 mm³. The difference from the analytic value is less than 0.01 mm³.
- A third process reopened the file and checked dimensions, hole positions, hole diameter, solid count, constraint status, and the parameter map. The original version's SHA-256 is unchanged.
- The gateway passed a real stdio `initialize`, `tools/list`, tool search, and single-item schema query. Both Blender and SolidWorks passed an actual read-only call.

Local evidence on this machine: `runs/plate-validated/project.json`, `runs/plate-validated/reports/`, and `runs/gateway-measurement.json`. The project files are `runs/plate-validated/output/plate-v001.SLDPRT` and `plate-v002.SLDPRT`. Those files are not committed to the source repository.

## Context size

The unified gateway exposes 8 tools. During the test, the SolidWorks host provided 96 tools (95 upstream tools plus 1 exact acceptance query). The full upstream schema is 80325 JSON characters. The gateway schema plus the schema for one required operation is 5385 characters, about 93.3% smaller. Those counts use the same serialization. They are not actual model token usage. An agent's own tool-discovery mechanism changes the savings.

## Upstream versions

- Blender: `ahujasid/mcp-for-blender`, commit `25e1fe008fc523b1a947c6f3d28510a362a0f06e`.
- SolidWorks: `HarrierPigeon/Solidworks-MCP-Server`, commit `60c11fe45b6cfc60c4e2da8ad41fc725a48bf8ea`.
- Local environment: Blender 5.2.2 LTS, SolidWorks COM revision 33.0.0, Python 3.14, MCP SDK 1.30.0.

## Issues found and fixed

- A two-point smart dimension can create a diagonal distance and move a hole center. The recipe now dimensions from the hole center to a horizontal or vertical edge, still through the upstream dimension tool.
- A workflow wrapper parameter name collided with the tool's `name` parameter. The wrapper name was corrected and a document-lifecycle regression test was added.
- An MCP child process does not inherit every environment variable by default. The test client passes the data-directory environment explicitly.
- After a write timeout, later writes are blocked before the connection is handled. The old session is allowed to finish cleanup before reconnecting, so an exception during cleanup cannot skip the explicit pending-check state.

## Limits

The base plate is a constrained recipe. It does not replace general parametric reverse engineering or an arbitrary assembly. A new machine still needs a local live check of the actual software version, license, template, and permissions. Multi-path configuration tests use temporary directories. They are not a test on two physical computers.

The installed upstream source was not modified. The optional compatibility host supplies exact read-back, the template path, and dimension-dialog compatibility at runtime. An ordinary backend can connect to the gateway directly. High-level plate acceptance needs that exact read-back capability. A clean machine using the bundled installer has not yet been verified end to end on a second computer.
