**English** | [中文](zh/validation-v0.3.md)

# v0.3.0rc1 acceptance record

Date: 2026-10-23 (Australia/Sydney). **Local isolated testing passed; real CAD acceptance on a second computer is pending.**

## Installation and recovery

- 34 automated tests passed, including configuration preservation, protocol errors, write uncertainty, rollback failure recovery, report redaction and bilingual documentation links.
- The actual ZIP was extracted and installed into Chinese/space paths. The Python package loaded from the isolated environment's `site-packages`, not the source checkout. The launcher worked from an unrelated working directory.
- Reinstallation created a new version directory while keeping the same Agent entry and other services. A dependency failure with package indexes disabled left the active pointer and configuration unchanged. Rollback restored the prior program and configuration and preserved a user-file fixture.
- Installation through a temporary R: drive mapping also passed; this is drive-letter testing, not a second physical disk or computer. The mapping was removed afterward.
- Both pinned upstream MCPs were downloaded into separate environments and passed handshake/tool checks. SolidWorks compatibility code was installed from the supplied wheel. Blender add-on installation on a fresh machine is still a manual, version-specific step.

## CAD and context

- Three independent installed gateway processes created the 120×80×5 mm plate with four 6 mm holes, changed the holes to 8 mm, then reopened and verified the file. The first version's hash stayed unchanged. Geometry, volume, fully defined sketch and persistent parameter mapping passed.
- Volumes: 47434.513322353836 mm³ (6 mm holes), 46994.690350851255 mm³ (8 mm holes).
- Open-document lists and active-document state matched before and after each action. No unrelated documents were open in this live run; preservation of a separate document is also covered by lifecycle simulation tests.
- Eight gateway tool schemas plus one requested operation used 5385 JSON characters, compared with 80325 for the complete 96-tool upstream catalogue: 93.3% smaller. This is not a tokenizer-specific token or billing measurement.
- Local runtime: Python 3.14, MCP SDK 1.30.0, SolidWorks COM revision 33.0.0. Fixed upstream commits are recorded in the release manifest.

Private local evidence is under `runs/release-acceptance/`: `installation-acceptance.json` in the final installer check directory, installed gateway `accept-create.json`, `accept-edit.json`, `accept-verify.json`, versioned SLDPRT files and `gateway-measurement.json`. These files and machine configuration are excluded from source releases.

## Release gates

The GitHub workflow independently runs tests on Windows with Python 3.11 and 3.14, builds the ZIP, exercises installation/recovery without CAD, and only then publishes a pre-release. Its attached `installation-acceptance.json` describes installer verification, not a second-machine CAD test. General reverse engineering and automatic assembly remain outside this candidate.
