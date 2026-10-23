**English** | [中文](zh/agent-workflow.md)

# Agent usage conventions

The user entry point is the existing MCP agent. Do not show underlying tool names to the user. When a critical dimension is missing, an environment choice is ambiguous, or the geometric intent is uncertain, ask for the necessary information together.

## Task flow

1. Read the project state. Make the goal, units, parameter sources, protected dimensions, and output location explicit.
2. Read the `environment_status` summary. Run a live check when needed. Do not treat a cache entry or a handshake as proof that CAD is usable.
3. Choose a backend per part. Search `capability_search` with short English keywords, then use `operation_schema` to read the parameters you are about to use.
4. Run `execute_operations` in order, at most 25 items per batch. An operation that depends on an ID returned by the previous item belongs in the next request. A batch is not a transaction. A later failure does not automatically roll back steps that already succeeded.
5. Check the result summary. Read the full log when needed. After saving the project, open it again and verify the user's dimensions and the protected geometry.

## Base plate and continued edits

`plate_workflow(project, action, hole_diameter)` supports create, edit, and verify. It applies only to the 120×80×5 mm plate whose four holes are 10 mm from the edges. Do not substitute this recipe for a different design.

`project_state` returns persistent parameters and versions. Projects use relative paths. A session entity ID is not a permanent identifier. Before an edit, reread dimension names, values, and geometry. Stop when the mapping is ambiguous.

## Failures

- Missing or incompatible tool: report the capability gap. Do not claim the task is complete.
- Write timeout: read the actual CAD state first, state the evidence, then call `reconcile_write`. It only clears the block. It does not replay the request.
- Unknown assembly position: keep it unknown, offer candidates or ask. Do not call a print layout an assembly.
- Documents already open: do not close all of them. The recipe closes only its own working copy and restores the previously active document.
- The generic interface has the upstream write capability. It is not a filesystem sandbox. The caller is responsible for user authorization and project scope. The serial lock cannot stop a person or another application from editing at the same time.

## Cache and cost

Each new connection refreshes schemas. Within a connection they expire after five minutes, and a live check refreshes them too. The cache includes version, configuration, and tool-list fingerprints. It does not mean the current connection is healthy. Each user holds one process lock per backend gateway.

Load only the unified entry point and the schemas for the current task. Large results are truncated. Read the full result from the artifact file when needed. Images are only a supplement to the geometry check.
