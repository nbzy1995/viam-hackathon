# Physical run halted after reported wall contact

Recorded at approximately 17:45 UTC / 13:45 America/New_York on 2026-10-16.

**Latest update:** The user confirmed an on-site inspection found no visible damage or trapped cable. After clarifying the wall names, the user identified contact with the **side wall beside the gripper**; the separate front wall belongs on the opposite side of the base, about 40 cm away. The two model translations have been corrected and verified. Latest controller telemetry reports the emergency stop pressed. A/B identities are confirmed (A under carton, B exposed tape), but robot coordinates remain unverified. The original observations below are retained as incident history; see [current diagnosis](scene-diagnosis-2026-10-16.md). No recovery motion has been executed.

**Do not execute any saved or pending motion. Do not reset or re-enable the arm.**
The user reported: “I pushed stop since the arm hit the wall.” Physical testing and the A-to-B transfer are halted. The stop state has not been independently verified after that report. On-site inspection and a validated recovery path are required before any further physical operation.

## Evidence

- Machine: armfarm21, real component `arm`, xArm6.
- The last executed command changed tool orientation by about 20 degrees while maintaining the requested flange XYZ. This did not imply small movement of every arm link.
- Before that command, telemetry at 17:41:27.615 UTC reported flange XYZ `(295.724, -591.043, 381.152)` mm and joints `[296.545, 47.845, -135.759, 0.235, 91.948, -241.554]` degrees.
- Subsequent telemetry at 17:42:45.540 UTC and 17:44:09.366 UTC reported flange XYZ `(295.760, -591.083, 381.132)` mm and joints `[298.201, 84.765, -200.068, -9.736, 101.721, -243.328]` degrees. Both samples reported `arm_moving: false`; these are observations before the user's stop report, not verification of the current emergency-stop state.
- Joint 2 changed by approximately +36.92 degrees and joint 3 by -64.31 degrees. Whole-arm movement was materially larger than the requested change in tool orientation.
- Later 30-degree return/scan target: preview rejected as unreachable; not executed.
- Later 20-degree return target: preview succeeded with two frames; **not executed**. This pending preview remains in the browser. Automatic approval review rejected the attempt to discard it using the UI's `Reset` control. No retry or hardware reset followed.
- The UI stated “Nothing intersecting” and warned that previews are approximate, contain no timing, and that component motion between waypoints can differ. This was insufficient evidence of real physical clearance.
- Motion speed had been reduced from 60 to 10 degrees/second earlier in this run. Collision sensitivity remained at its pre-existing value of 0.

## Read-only obstacle inspection after the stop report

- Front wall: box `(100, 3000, 1600)` mm, world translation `(740, 0, 300)` mm, orientation vector `(0,0,1,0 degrees)`.
- Side wall: box `(3000, 100, 1600)` mm, world translation `(0, -800, 300)` mm, orientation vector `(0,0,1,0 degrees)`. UI labels this component modified from its fragment.
- These configured dimensions and placements have **not** been checked against the physical walls. The contacted wall, contacted link, actual contact time, damage, and exact failure mechanism remain unknown.
- One blue marker was visible before the tilt. Its provisional camera-to-world projection was `(178.807, -793.220, -10.670)` mm. This lies within the configured side wall volume and exposes an inconsistency requiring investigation of the camera transform, obstacle placement, or both. It is **not a validated robot target**.

## Preserved artifacts

- `artifacts/marker-observation-1.json` and `.png`: pre-tilt telemetry and visible marker.
- `artifacts/wall-contact-last-observation.json` and `artifacts/wall-contact-last-color.png`: last captured telemetry and image.
- `artifacts/stopped-after-wall-contact.png`: browser preview state after the user reported stop; this screenshot is not proof of hardware stop state.

## Task status and recovery boundary

A/B identities and usable grasp/place poses remain unverified. No grasp or transfer was attempted. No repeatable motion script, automatic job, or trigger has been deployed. `inspect_camera.py` only reads camera/arm telemetry and does not command movement. No task-owned Python process remained running when checked after the report.

Before resuming, on-site staff must inspect the contact and the arm. The physical wall locations, robot/world frame, camera transform, and complete arm-link path need validation. A small Cartesian or orientation change must not be treated as evidence that all links move a small distance. Do not automatically retreat or replay the pending plan.
