# Wall-contact diagnosis and remaining geometry checks

No physical motion has been executed during this diagnosis. The user's latest clarification resolves the naming: contact was with the **side wall beside the gripper**; the separate front wall was modeled on the wrong side and belongs about 40 cm from the base, on the right of the current 3D view (negative X). This supersedes the earlier ambiguous front-wall identification. The user requested moving the side-wall boundary 5 cm inward and previously requested a 5 cm buffer for both walls.

## Saved wall corrections

At 18:10:32 UTC, a fresh SDK readback verified exactly two frame changes and unchanged geometry dimensions, other frames, and joint positions:

| Obstacle | Previous center | Saved center | Saved inside planning boundary |
| --- | --- | --- | --- |
| Front wall | x=+740 mm | x=-400 mm | x=-350 mm |
| Side wall | y=-800 mm | y=-750 mm | y=-700 mm |

Both boxes remain 100 mm thick. For the front wall, the user's approximate physical inside face is x=-400 mm; the requested 50 mm inward margin gives a planning face at x=-350 mm, hence box center x=-400 mm. Without the margin, the box center would be x=-450 mm. The side wall was shifted exactly 50 mm toward the base. These are user-directed model corrections, not an independent survey of the physical walls.

The corrected scene flags the recorded incident sweep as entering the side buffer by 31.47 mm. The stopped gripper is 25.02 mm inside that buffer; front clearance is 292.20 mm. This does not establish a safe recovery move. The emergency stop remains pressed.

The offline checker previously hard-coded the front-wall direction. Two new regression tests reproduced the negative-X error and failure to reject a wall straddling the base; the checker now chooses the wall face toward the base. All nine diagnostic tests pass. No physical or camera configuration was altered beyond the two wall translations.

A plan-only Viam request at 18:11:26 UTC for a 50 mm retreat in positive Y, preserving tool orientation, returned two joint waypoints. It was not executed; joints stayed unchanged and `moving_after` was false. The returned plan is diagnostic evidence only, because the current pose starts inside the side-wall buffer. See `corrected-scene-plan-probe.json` and `retreat-plan-offline-check.json`.

## Evidence before the wall corrections

- Saved endpoint telemetry shows the approximately 20-degree tool-orientation command changed joint 2 by +36.92 degrees and joint 3 by -64.31 degrees. Holding flange XYZ does not limit the rest of the arm's sweep.
- The model places the `wall-front` inside face at world x=690 mm and `wall-side` at y=-750 mm. These placements were never measured against the actual workstation.
- The live model is the real arm's URDF, with official collision meshes from xArm module v1.1.36. The separate native simulated arm uses a different model representation. The earlier PyBullet fixtures were synthetic and did not reproduce the physical walls.
- `scene_sweep.py` reconstructs a linear joint interpolation between the saved pre/post tilt endpoints. At 0.1-degree joint sampling, the model has minimum front-plane clearance 341.18 mm and side-plane clearance 18.53 mm. This is not the recorded controller trajectory and does not identify the physical contact surface.
- Applying a 50 mm inward margin **offline** produces a side-plane intersection of 31.47 mm. The stopped pose itself is 25.02 mm inside that proposed buffered boundary. Therefore adding a buffer alone does not establish a collision-free recovery path.
- A fresh wrist RGB-D capture at 18:05:05.979 UTC has no blue marker. The left white tabletop region has 99.45% valid sampled depth and a strong plane fit (0.92 mm RMS). With the captured camera frame, that tabletop normal is tilted 29.27 degrees from world vertical and its sampled center maps to z=99.51 mm; the configured tabletop is z=-23 mm. This is a substantial scene/camera inconsistency, not a validated wall measurement.
- Only 7.64% of sampled pixels in the right textured-panel region have valid depth. No wall plane or robot-frame wall coordinate is accepted from that region.
- An offline experiment changing only camera yaw from -90 to +90 degrees reduced the tabletop-normal mismatch to about 2.15 degrees, but left a height discrepancy. This is a calibration hypothesis, not a sufficient calibration or an applied fix.
- A direct TCP probe to the arm controller on port 502 timed out. No manufacturer SDK controller connection, warning clear, reset, or motion command was attempted. Viam read-only access remained available.
- At 18:07:31 UTC, fresh telemetry again reported `moving: false`; both read-only controller queries returned `xArm: Emergency Stop Button Pushed In;`. This supersedes the earlier stopped-state/no-error snapshot. The emergency stop has not been released or cleared here.

## What explains the incident, and what remains unknown

The unsupported assumption was that a small tool-orientation change implied a small whole-arm motion. The recorded joints contradict that assumption. The preview's “Nothing intersecting” status was also insufficient: Viam documents that it does not check mesh geometry, self-collisions, or the full path, and previews omit timing and approximate driver interpolation.

The user has now identified the side wall as the contact surface. The original side model allowed only 18.53 mm clearance along the reconstructed sweep; that clearance was not verified physically. The corrected model excludes that sweep. The exact time/contact point and real-versus-model offset remain unmeasured. Camera calibration also fails the tabletop consistency check. Do not claim independent physical calibration from these model changes.

## Minimal recovery route

1. Wall identity and requested model changes are now resolved. Verify physical clearance locally and validate camera mounting/frame values against physical references before using camera-derived targets.
2. Do not add the 50 mm margin again: it is already included in the saved wall translations. The current arm envelope intersects the side margin and needs an explicitly reviewed recovery path.
3. Preview a short recovery path from fresh joints, inspect all links and tool attachments along it, and reject large unexpected joint changes. Keep the operator at the stop control. Do not replay the old pending preview.
4. Follow Viam's static-position teaching workflow for A/B. Verify manual transfer before creating the repeatable execution script, as requested. A remains under the carton; B is the exposed tape. Neither robot pose is known yet.

## Reproducible checks

```
uv run pytest tests/test_scene_diagnostics.py -q
uv run diagnose_depth.py
```

Nine diagnostic tests passed, including negative-X wall placement and rejection of a wall straddling the base. Incident regression tests use the preserved `pre-wall-correction-state.json`, so live edits cannot silently change their baseline. Agreement with Viam telemetry uses the same kinematic model and is not independent physical calibration. These tests certify diagnostic behavior only; they do not certify physical clearance or Milestone 1 completion. `scene_sweep.py` adds an optional comparative 50 mm margin in its report; running it against the new live snapshot represents an **additional** margin, not the saved scene itself. Use `wall-correction-qa.json` for the saved-scene results.

Artifacts: `artifacts/diagnosis/recorded-sweep.json`, `depth-consistency.json`, `live-state.json`, saved official model/meshes, and `artifacts/current-color.png`, `current-depth.npy`, `current-observation.json`.

Correction evidence: `artifacts/diagnosis/pre-wall-correction-state.json`, `wall-correction-qa.json`, `corrected-walls-3d.png`, `corrected-scene-plan-probe.json`, and `retreat-plan-offline-check.json`.

## Official sources

- [Static positions and obstacles](https://docs.viam.com/tutorials/pick-and-place/static-positions/): measured obstacle geometry and manually taught poses.
- [Move mode](https://docs.viam.com/visualization/3d-scene/move-mode/): preview and collision-display limitations.
- [RealSense module](https://github.com/viam-modules/viam-camera-realsense): optical coordinate convention and aligned depth/color behavior.
- [xArm module v1.1.36](https://github.com/viam-modules/viam-ufactory-xarm/tree/v1.1.36): actual hardware model and driver implementation.

## On-site contact confirmed during recovery check

At the next real-arm attempt, fresh readback still reported the emergency-stop
button pressed. The user explicitly confirmed: **“Still touching or pressing
against the wall.”** No physical movement, reset, or re-enable was issued.
A 5 mm positive-Y plan-only probe was prepared, but its connection timed out
before any planning RPC was sent. No new plan was obtained. Modeled clearance does not establish the direction or force of actual
contact. Keep the emergency stop engaged and have the on-site robot technician
assess and clear the contact using the manufacturer's recovery procedure before
remote powered motion resumes. Do not replay any saved recovery plan.


## Recovery attempt failed physical validation

The user subsequently confirmed contact cleared, an operator ready, and the
emergency stop released. Fresh telemetry showed no controller errors. A fresh
5 mm positive-Y plan was checked against the saved model: maximum joint change
about 2 degrees, maximum modeled vertex displacement 5.932 mm, monotonically
increasing modeled side-wall clearance. Executed once at 3 deg/s and 6 deg/s².
Readback reached the target within 0.0046 mm and reported not moving.

**The user then reported “No—wrong direction or contact.”** This physical
validation fails regardless of numerical endpoint success. A stop was requested,
the user was instructed to press the emergency stop if contact remained, and the
one-shot recovery helper was disabled. Do not infer the next motion direction
from the current scene; resolve the physical contact and frame correspondence
with an on-site operator before any powered move. No A-to-B transfer occurred.
Evidence: `recovery-5mm-result.json`, `recovery-stop.json` in artifacts/diagnosis.


### Clarification after the recovery stop

The user clarified that there does not seem to be contact, then answered
“not sure” when asked whether the move went closer to the wall or was too small
to judge. Thus neither contact nor wrong-direction travel is confirmed. The
physical clearance check is **unresolved**, not a confirmed new collision.
Fresh telemetry at 18:24:11 UTC: stationary, state [0, 2], error/warning [0, 0, 0].
No further motion was issued. On-site identification of retreat direction or
a locally supervised move to an open pose is needed before remote execution.


## Requested 3D retreat preview (no execution)

Previewed +50 mm world Y from the stopped pose, preserving X/Z/orientation.
Target flange: (300.1085, -535.6022, 371.1267) mm. Viam returned two waypoints
and displayed 13 interpolated frames. Preview overlap warning for gripper claws
and wall-side persisted at frames 1–6, clearing at frames 7–13. The separate
“Currently touching” warning describes the unchanged live start, not the preview
endpoint. Ceiling, simulated arm, and point cloud were hidden visually only;
obstacle configuration was not changed.

A separately generated plan-only request for the same target was sampled with
the saved real-arm collision meshes and tool boxes: side clearance increased
monotonically from -20.008 mm (inside added margin) to +29.993 mm. Minimum other
boundary clearance: front 292.045 mm, table 173.579 mm, ceiling 495.108 mm.
Maximum joint change 16.562 degrees; maximum modeled point displacement 55.031 mm.
This checks sampled boundary geometry, not physical calibration, dynamics, cables,
or independent self-collision detection. It supports a model-space retreat but
is not a collision-free path from the initial overlapping pose. No execution,
reset, or enable command was sent. Joints were unchanged; arm reported stationary.

Evidence: `artifacts/diagnosis/retreat-preview-frames.json`,
`retreat-50mm-preview.png`, and `recovery-50mm-plan.json` in the same directory.
The browser preview remains available for inspection and must not be executed
without a fresh start/scene check and resolved physical recovery conditions.

## Restored view: both markers recorded, calibration still unresolved

After the user's manual repositioning, read-only wrist captures at
18:35:20.797 and 18:38:47.413 UTC show the same stationary joint positions.
Both tape markers are now visible, with A partly covered by the carton.
`artifacts/table-markers.json` records visible-tape centroids in the preserved
18:35 capture: A=(840.96,258.69) px, B=(630.42,398.73) px. The carton graphics
are separate blue regions and are not counted as markers. World positions and
verified grasp/place poses remain null. The external Brio capture at 18:38:50
also shows the carton, exposed B, part of the arm/base, and wall; it crops the
wrist and cannot independently verify gripper alignment.

`uv run python check_restored_view.py` reproduces an offline tabletop check:
90.34% of sampled white-table points fit within 10 mm, with 4.50 mm RMS residual.
The configured camera transform gives a 27.14-degree table tilt. Changing only
camera roll about its optical axis from -90 to +90 degrees offline reduces the
tilt to 1.66 degrees, but leaves the sampled tabletop at z=17.42 mm against the
configured z=-23 mm: a 40.42 mm discrepancy. A second fresh capture reproduces
the qualitative discrepancy. This supports a camera orientation mismatch;
it does not establish the full camera extrinsic transform, the true table
height, or a safe pick target. No configuration change was applied.

A table plane does not resolve translation along the plane or heading about
its normal. The cropped base/axis marking is insufficient to identify an exact
robot-frame point. Viam's official [frame calibration worksheet](https://github.com/viam-devrel/pick-and-place/blob/main/setup/frame-calibration-worksheet.md)
requires checking a detected object against a known measured world position.
Its [mount configuration guide](https://docs.viam.com/tutorials/pick-and-place/configure-resources/)
explicitly limits the example offsets to the matching workshop hardware.
Do not apply the apparent 180-degree correction as a complete calibration.

The user asked not to be interrupted for routine steps. Read-only vision and
offline checks proceeded autonomously. No arm/gripper movement or manual
transfer occurred in this continuation. The simplest remaining physical route
is taught grasp/approach/place poses using the station controls; the alternative
is physically measuring and validating camera/gripper frames and a known point.
The repeatable physical cycle remains pending the first verified manual transfer.


## Native workshop continuation at 19:14 UTC

See tutorial-checkpoints.md for current workflow and evidence. The earlier
calibration uncertainty was reduced by wrist-pose observations and a held-out
check, and the resulting camera extrinsic was applied and independently read
back through Viam TransformPose. A simulator arm remaining in the shared scene
was observed to move in a preview along with the real arm; that preview was
not executed, and the simulator resource is now disabled. This is a separate
planning defect, not proof of the cause of the earlier wall incident.

The current carton location is unreachable for a straight-down tutorial pickup.
The operator has been asked to move carton and A marker 15 cm toward the base.
No physical arm commands are issued during this pending workspace adjustment.
