[中文](../requirements-v2.md) | **English**

# AI Multi-CAD Agent
## An MCP-based system for intelligent 3D modeling, reverse reconstruction, and automatic assembly

**Requirements v2.0**

---

# 1. Project overview

## 1.1 Positioning

Build an intelligent 3D modeling system based on an AI agent and the Model Context Protocol (MCP).

The system accepts natural language, reference images, 3MF files, and other 3D models. It interprets the modeling request, analyzes geometry and the intended end use, and chooses SolidWorks, Blender, or both working together.

The AI has to do more than import and modify an existing model. It also needs to model from scratch, reverse-reconstruct a reference, design parametrically, assemble automatically, and keep iterating.

The primary output is a native, editable project file, not only a mesh exchange file such as STL or 3MF.

## 1.2 Five core goals

1. **Multimodal input:** accept natural language, images, 3MF, or other 3D model files, including combinations.
2. **Intelligent analysis:** analyze shape, structural complexity, part relationships, modeling difficulty, the user's edit intent, and the end use.
3. **Autonomous software choice:** decide whether to use SolidWorks, Blender, or both, and allow different parts to use different modeling approaches.
4. **Autonomous execution:** call the matching MCP servers to model from scratch, reverse-reconstruct, change parameters, edit meshes, assemble, check, and export.
5. **Closed-loop refinement:** check the finished model against the request. When it does not match, locate the problem, modify the model, and verify again.

## 1.3 Design principles

- **Intent First:** choose the workflow from the user's actual goal, not from the file format alone.
- **Editable First:** prefer a native project file that can still be edited.
- **Reconstruction First When Necessary:** when the original model cannot be edited effectively, choose to rebuild it.
- **Part-Level Routing:** choose the modeling application per part. A whole model does not have to stay in one application.
- **Non-destructive Workflow:** keep the original inputs and historical versions.
- **Verifiable Results:** modeling results need geometric, parametric, and assembly checks.
- **Human-in-the-Loop When Needed:** high-uncertainty geometry or assembly inferences should allow the user to confirm.

---

# 2. Input system

## 2.1 Natural language

The user can describe a model to create, or request a change to a model that already exists.

Typical tasks:

### A. Model from scratch

"Design a mounting bracket. The base plate is 120 mm long, 80 mm wide, and 5 mm thick, with a 6 mm mounting hole at each of the four corners."

The system should:

1. Analyze the geometry and the dimensions.
2. Choose parametric modeling in SolidWorks.
3. Create the sketch, constraints, and features.
4. Check the dimensions.
5. Save an SLDPRT, and export STEP or STL when requested.

### B. Modify an existing model

"Change this part's mounting-hole diameter from 5 mm to 8 mm, and leave the rest of the structure unchanged."

The system first decides whether the existing model can be edited directly.

When native features can be modified, change the parameters directly.

When the input is only a 3MF or STL mesh, or the original features cannot be changed reliably, analyze the geometry and rebuild the affected region or the whole part, then apply the change.

### C. Redesign from a reference

"Use this 3MF shape as a reference and redesign a similar enclosure, with a thicker base and four screw bosses."

The system treats the original model as a geometric reference. The original mesh does not have to become the final model.

It should identify the main shape, geometric features, and key dimensions, rebuild a new editable model, and add or change structure as requested.

### D. Multi-turn natural-language edits

"Thicken the base to 4 mm."

"Move the mounting holes inward by 3 mm."

"Leave a 0.3 mm gap between the cover and the base."

The system should keep editing the same project. The user should not have to restate the full request each time, and completed design changes should not be dropped without a reason.

## 2.2 Images

Supported inputs:

- Product photographs.
- Reference images from different angles.
- Hand sketches.
- Engineering drawings and dimensioned drawings.
- Model screenshots.
- Assembly illustrations.

The system needs to identify likely 3D shape, structural features, symmetry, part count, and dimensions from the images.

When an image has no dimensions, the AI may build a preliminary model, but unconfirmed dimensions must be marked as estimates. An estimate must not be treated as an exact engineering parameter.

Images can be combined with other inputs, for example:

"Assemble the parts in this 3MF the way the picture shows."

## 2.3 3D model input

Priority formats:

| Format | Primary use |
|---|---|
| 3MF | Slicer models and split-part projects |
| STL / OBJ | Mesh reference and reverse modeling |
| STEP / STP | CAD solid reference and edits |
| SLDPRT | SolidWorks native part |
| SLDASM | SolidWorks native assembly |
| BLEND | Blender native model |

Other formats can be added as backend software supports them.

### Special handling for slicer 3MF files

Focus on Bambu Studio, OrcaSlicer, and similar applications.

Extract:

- Build plates and the models on them.
- Model objects, separate parts, and repeated instances.
- Part names, dimensions, units, and mesh data.
- Relative transforms and hierarchy.
- Possible assembly structure.
- Supports and print helpers that are not product geometry.

Parts on a build plate may already have been rearranged. Their current positions are not the final assembly positions by default.

---

# 3. Task understanding and planning

## F01 — Automatic intent recognition

After receiving input, the system decides what the user actually wants done.

At least these working modes:

| Mode | Description |
|---|---|
| Create | Model from scratch from text or images |
| Edit | Modify an existing native model |
| Reconstruct | Rebuild from a mesh, images, or reference geometry |
| Reconstruct & Modify | Reverse-reconstruct first, then apply the requested structural and parametric changes |
| Assemble | Organize multiple parts into an assembly |
| Analyse | Inspect structure, dimensions, or editability |
| Convert | Convert formats while preserving geometry and structure as far as possible |
| Hybrid | Combine the tasks above as needed |

These modes can be combined. They are not mutually exclusive.

For example, one user task can include Reconstruct, Modify, Assemble, and Export together.

## F02 — Automatic task plan

The AI builds an internal execution plan before choosing MCP servers.

The plan needs to include:

- The user's final goal.
- Input files and reference material.
- The target model form.
- Parts to create or modify.
- The modeling method for each part.
- Geometric features that must stay unchanged.
- Key parameters, constraints, and dimensions.
- Assembly relationships.
- Verification criteria.
- Output formats and save locations.

The plan can be updated while the work runs.

Uncertain parameters should record their source and confidence.

---

# 4. Choosing the modeling application

## F03 — Automatic SolidWorks / Blender routing

The system chooses the application from the model type, the intended use, and how editable the user needs the result to be.

### Prefer SolidWorks when

- The work is a mechanical part, bracket, or mounting structure.
- Exact dimensions, hole diameters, or tolerances matter.
- The work is an enclosure, cover, or mechanical joint.
- The result should be parametrically editable.
- Parts need assembly and mechanical constraints.
- The result is a drawing or CAD geometry for manufacturing.

### Prefer Blender when

- The work is an organic surface, a sculpture, or a character.
- The work is a game asset or a scene model.
- The mesh edits are complex.
- The work needs retopology, UVs, textures, or materials.
- The work needs animation, rendering, or visual presentation.
- The shape is freeform and does not fit traditional parametric CAD.

### Mixed collaboration

For example, a product with a mechanical base and a complex shaped enclosure:

1. SolidWorks rebuilds the mechanical base.
2. Blender handles the complex enclosure.
3. The two sides collaborate through explicit coordinates, units, and a geometry exchange format.
4. The primary project file follows the end use.

Mixed modeling does not mean a Blender mesh can become a SolidWorks parametric solid without loss. The system must recognize cross-application conversion limits.

## F04 — Intelligent choice per part

Inside one assembly, different parts can use different modeling approaches.

At part level, the AI should record:

- Modeling application.
- Modeling method.
- Recommended model representation.
- Expected reconstruction difficulty.
- Editing capability that can actually be delivered.
- Conversion risk.

For example, rebuild the enclosure as a Blender mesh, and rebuild screw bosses, brackets, and connectors as parametric SolidWorks parts.

---

# 5. Automatic modeling and reverse reconstruction

## F05 — Automatic modeling from scratch

The AI should be able to create a new model from text, images, or both.

The SolidWorks route should prefer real CAD features:

- Reference planes.
- Sketches.
- Dimensions and geometric constraints.
- Extrude, revolve, and cut.
- Hole features.
- Fillets, chamfers, and patterns.
- Assembly-related features when needed.

The Blender route should support:

- Mesh creation.
- Multi-object structure.
- Modifiers.
- Boolean operations.
- Surface modeling.
- Materials and textures.
- Automatic renders and previews.

## F06 — 3MF / STL reverse reconstruction

This is one of the core capabilities.

**A triangle mesh in a 3MF can usually be edited as a mesh. It does not contain SolidWorks dimensions, sketches, or feature history.**

The system therefore has to decide when to keep the mesh and when to rebuild.

### Reverse-reconstruction flow

1. Analyze the original mesh.
2. Extract separate parts.
3. Identify base shapes and geometric features.
4. Identify likely symmetry, hole positions, repeated structure, and mating faces.
5. Estimate and record key dimensions.
6. Choose an appropriate modeling application.
7. Build a new editable model.
8. Compare the original model with the reconstruction.
9. Correct geometric deviations that can be identified.
10. Save a native project file.

### Reconstruction levels

**Level 1 — Editable Mesh**

Keep the original triangle mesh and edit objects, vertices, faces, deformations, and modifiers in Blender or similar software.

**Level 2 — Editable Geometry**

Rebuild a mesh structure, surfaces, or CAD solids that are easier to modify, and support geometric edits within a defined range.

**Level 3 — Parametric Reconstruction**

Identify design features as far as possible and rebuild sketches, features, dimensional constraints, and parameter relationships in SolidWorks.

The user can change the model by editing key dimensions.

The system must not assume that every complex mesh can be recovered as a parametric model.

## F07 — Reconstruct, then modify

This is a separate task mode and should be supported early.

When the user supplies a 3MF and asks to change a structure that cannot be edited parametrically, the agent should not simply report an error and stop.

For example:

"Rebuild an editable model from this 3MF, set the enclosure wall thickness to 3 mm, and change the mounting-hole diameter to 5 mm."

The correct flow:

1. Read the 3MF.
2. Identify the parts that need to change.
3. Analyze the original structure.
4. Decide whether a local rebuild or a full rebuild is more appropriate.
5. Rebuild an editable model that contains the target features.
6. Apply the new wall thickness, hole diameter, and other parameters.
7. Check whether the change affects other structure.
8. Regenerate the assembly when needed.
9. Save a new native project file.

**The reconstruction has to serve the final edit. It should not mechanically copy the original model and then reprocess every original structure.**

If a hole diameter is about to change, the AI can use the target diameter directly while rebuilding the sketch.

## F08 — Parameter management and continued editing

The system keeps one parameter record, for example:

- Enclosure length.
- Enclosure width.
- Wall thickness.
- Hole diameter.
- Hole spacing.
- Boss height.
- Fit clearance.
- Pattern count.

Distinguish:

- Parameters the user stated explicitly.
- Parameters measured from the original model.
- Parameters inferred from images.
- Default parameters the AI is using for now.

A parameter change should update the affected parts and trigger the necessary re-verification.

For SolidWorks, prefer editing an existing dimension or feature. For Blender, prefer editing an existing parametric modifier or regenerating the related mesh.

---

# 6. Part identification and assembly reconstruction

## F09 — Automatic part identification

For a multi-part 3MF:

- Keep the part grouping from the source file.
- Identify repeated parts and instances.
- Decide whether a mesh is only part of a part.
- Separate print-helper geometry from the actual product.
- Assign each part a unique internal ID.
- Record the correspondence between source parts and rebuilt parts.

## F10 — Recover assembly intent

When the original 3MF only contains parts laid out on a build plate, the system should try to infer the real assembly positions.

Evidence can include:

- Geometric matching.
- Contact-face analysis.
- Hole axes and slot relationships.
- Symmetry.
- Product photos supplied by the user.
- Assembly diagrams.
- Natural-language assembly instructions.

Produce assembly relationships and a confidence level.

When several assembly arrangements are reasonable, generate candidates. Do not force one unverified arrangement.

## F11 — Create a SolidWorks assembly

The system should support:

1. Creating separate SLDPRT files.
2. Creating an SLDASM.
3. Inserting every component.
4. Placing parts in space.
5. Adding assembly constraints that can be determined reliably.
6. Checking interference.
7. Checking unconstrained degrees of freedom.
8. Saving the assembly and its dependent part files.

For a complex mesh, it is acceptable to output an assembly that preserves the correct positions first, then add more complete mechanical mates step by step.

## F12 — Assembly relationships and parameter coupling

When the user changes a part parameter, check whether assembly relationships are affected.

For example:

"Change the shaft diameter from 6 mm to 8 mm."

The system needs to identify the affected shaft holes, bearings, or connectors, decide from the user's intent whether coupled edits are required, and check that the new mechanical fit is valid.

Do not change a dimension the user explicitly asked to keep unchanged, unless the user authorizes that change.

---

# 7. Automatic MCP execution

## F13 — Unified MCP dispatch

The AI agent manages multiple MCP servers together:

- 3MF analysis MCP or parsing service.
- Blender MCP.
- SolidWorks MCP.
- Geometry verification service.
- File management and conversion tools.

The user does not choose, switch, or call MCP servers by hand.

The orchestrator decides which capabilities to use from the task plan.

## F14 — Tool capability detection

The system cannot assume that every MCP version supports the same operations.

Before execution, determine:

- Whether the current application is already running.
- Whether the MCP connection succeeded.
- Whether the required tool is available.
- Whether the current file can be imported.
- Whether the target output format is supported.
- Whether an operation needs user confirmation.

When a tool cannot do the job, choose another execution path or report the limit explicitly.

## F15 — Process management and failure recovery

Support:

- Step-by-step execution.
- Saving intermediate results.
- Adjusting the plan from tool results.
- Capturing import, modeling, and assembly errors.
- A limited number of retries for recoverable errors.
- Keeping completed model work after a failure, as far as possible.
- Continuing to edit in a later task.

Overwrite, delete, and bulk-edit operations that can be irreversible should ask for an appropriate confirmation.

---

# 8. Automatic checking and iterative refinement

## F16 — Geometric verification

Check against the user's request:

- Dimensions.
- Units.
- Volume.
- Part count.
- Hole diameter, hole spacing, and wall thickness.
- Mesh integrity.
- CAD solid validity.
- Surface deviation from the reference model.
- Unexpected geometric changes.

Dimensions the user stated explicitly are the primary acceptance criteria.

For reverse reconstruction from a reference, the geometric-similarity tolerance should be configurable per project.

## F17 — Visual check

The AI generates screenshots or renders:

- Front.
- Side.
- Top.
- A perspective view.
- Sections when needed.
- The assembly and an exploded view.

Judge the model from the geometric check and the visual check together.

Visual similarity does not replace engineering dimension checks.

## F18 — Autonomous correction loop

The basic loop:

**Model → check → find a problem → analyze the cause → modify → check again**

The system should be able to repeat that loop until:

- The acceptance criteria are met.
- The configured retry limit is reached.
- A problem cannot be solved automatically.
- The user needs to supply information or confirm design intent.

Avoid an infinite loop and an uncontrolled large-scale rebuild.

## F19 — User feedback and multi-turn iteration

The user can request a change at any stage:

"The enclosure is too thick."

"There should be an opening here."

"The screw boss should connect to the base."

"I want this part to become a parametric model."

The AI should understand the current project state and decide whether to edit an existing feature, edit the mesh, rebuild locally, or recreate the part.

Prefer changing only the affected region, and keep other results that have already passed verification.

---

# 9. System architecture

Suggested modules:

### Layer 1 — User Interface

Handles:

- Natural-language interaction.
- File and image input.
- Model preview.
- Part list.
- Parameter editing.
- Assembly preview.
- Execution progress and the result report.

### Layer 2 — AI CAD Orchestrator

Responsible for:

- Understanding the request.
- Model-analysis decisions.
- Task-type recognition.
- The work plan.
- SolidWorks / Blender routing.
- MCP dispatch.
- Error recovery.
- Automatic verification and retry.

### Layer 3 — Geometry & Reconstruction Engine

Responsible for:

- 3MF / STL parsing.
- Part separation.
- Geometric feature recognition.
- Mesh processing.
- The parametric reconstruction plan.
- Assembly-relationship inference.
- Geometric comparison.

### Layer 4 — CAD Execution

Controls, through MCP:

- SolidWorks.
- Blender.
- Related conversion and geometry tools.

This layer creates, modifies, and saves the actual models.

### Layer 5 — Validation & Project Management

Responsible for:

- Dimension and shape verification.
- Assembly checks.
- Result screenshots.
- Retention of original files.
- Project version management.
- Parameter and part mapping.
- Execution logs.
- Result reports.

---

# 10. Representative end-to-end workflows

## Workflow A — Text-only automatic modeling

Input:

"Create a parametric motor-mount bracket."

Flow:

Parse the request → route to SolidWorks → parametric sketch → model → verify dimensions → SLDPRT.

## Workflow B — Modeling from image references

Input:

"Use these pictures as a reference and make a similar model."

Flow:

Visual analysis → geometric inference → choose software → preliminary model → multi-view check → iterative correction → native project file.

## Workflow C — Reverse-reconstruct a 3MF and modify it

Input:

"Rebuild from this 3MF, set the enclosure wall thickness to 3 mm, and add four mounting bosses."

Flow:

Parse the 3MF → identify parts → analyze geometry → judge parametric feasibility → rebuild in SolidWorks or Blender → modify the target structure → verify → export.

## Workflow D — Automatic assembly from a split 3MF

Input:

"These parts came from OrcaSlicer. Restore the original assembly and generate a SolidWorks assembly."

Flow:

Parse the build plate → extract parts → analyze mating geometry → infer assembly positions → create separate parts → create an SLDASM → check the assembly → export.

## Workflow E — Multi-application collaboration

Input:

"Keep this model's complex surface shape, rebuild the base mounting structure as parametric parts, and generate a complete assembly."

Flow:

Analyze the model → choose software per part → Blender handles the complex surfaces → SolidWorks rebuilds the mechanical structure → exchange and align geometry → verify the assembly → write several native project files.

## Workflow F — Edit an existing project

Input:

"Raise the enclosure of the assembly we built earlier by 10 mm, and leave the other parts unchanged."

Flow:

Read project state → identify the enclosure → change parameters or rebuild locally → update the assembly → verify the related parts → save a new version.

---

# 11. Files and state

Recommended project directory:

```text
CAD-Project/
├── inputs/
│   ├── source.3mf
│   ├── reference_01.png
│   └── requirements.md
│
├── analysis/
│   ├── source_manifest.json
│   ├── geometry_analysis.json
│   └── assembly_candidates.json
│
├── workspace/
│   ├── extracted_meshes/
│   ├── reconstruction/
│   └── previews/
│
├── output/
│   ├── solidworks/
│   │   ├── Assembly.SLDASM
│   │   └── Parts/
│   ├── blender/
│   │   └── Project.blend
│   └── exports/
│
└── reports/
    ├── validation.json
    └── final_report.md
```

Project state should be stored persistently.

At a minimum, record:

- Input file sources.
- Part IDs and the corresponding project files.
- Original dimensions and the parameters after edits.
- The current primary editing format.
- The modeling tool used for each part.
- How complete the reverse reconstruction is.
- Assembly positions and constraints.
- Verification results.
- Questions that are uncertain or still open.

---

# 12. Priority and development phases

| Phase | Goal | Main capabilities |
|---|---|---|
| Phase 1 — Core Agent | Basic modeling automation | Natural-language input, software choice, Blender/SW MCP dispatch, modeling from scratch, edits, save |
| Phase 2 — Reconstruction | Editable model reconstruction | 3MF parsing, part splitting, geometry recognition, mesh rebuild, simple parametric reverse engineering, edit after rebuild |
| Phase 3 — Assembly | Automatic assembly | Assembly-position inference, separate parts, SLDASM, mates, assembly verification |
| Phase 4 — Hybrid CAD | Cross-application collaboration | Per-part routing, mixed Blender/SW workflow, geometry exchange |
| Phase 5 — Autonomous Refinement | Autonomous refinement | Automatic verification, local correction, version restore, multi-turn interaction, full project management |

Phase 1 and Phase 2 are the most valuable foundation.

## 13. Final acceptance criteria

The system should at least complete these representative tasks:

1. **Text-only modeling:** generate a genuinely parametric SolidWorks part from a dimension description.
2. **Image modeling:** build a 3D model from reference images and explicitly report dimensions that cannot be confirmed.
3. **3MF reading:** correctly identify the separate product parts in a slicer project.
4. **Reverse reconstruction:** rebuild a simple mechanical mesh as a SolidWorks part with editable features.
5. **Edit after reconstruction:** produce the modified rebuilt model directly from the user's request.
6. **Blender routing:** choose Blender automatically for a complex mesh and save a project file that can still be edited.
7. **Automatic assembly:** generate an SLDASM with separate components and record component positions that can be confirmed.
8. **Mixed workflow:** use SolidWorks and Blender in the same project for the parts each one fits.
9. **Automatic verification:** correct or report dimensional, geometric, or assembly errors when they are found.
10. **Continued iteration:** the user can modify an existing project with later natural-language requests, without repeating the entire modeling sequence.

---

# 14. Product experience

In the ideal case, the user only needs to:

**Upload text, images, or a model → describe the desired result → the AI interprets the task → analyze the existing geometry → decide whether to edit directly or rebuild → choose SolidWorks or Blender → execute → verify and correct → return an editable project file.**

For a 3MF exported from a slicer, the system should use it as a reference, redesign editable parts, and assemble them when needed. It should not stop at importing the file.

When there is no input model, the system should create a new model directly from natural language or images.

When a project already exists, the system should keep understanding and modifying that design.

**The end goal is a general AI 3D modeling agent that can plan on its own, collaborate across CAD applications, reconstruct geometry, change parameters, infer assemblies, and check its own results.**
