# Milestone 2: scene-aware text control

Latest iteration: [expanded evaluation and latency results](text-evaluation-v2.md).
It adds a separate development/holdout split, validates stacking support IDs, and
keeps explanations brief. The saved paired timings cover inference only.

The program keeps one Viam SDK connection open and turns natural-language
requests into a short sequence of pick-and-place commands. It uses the installed
Codex login, live images, native depth observations, and verified execution
history. No phrase parser, generated Python execution, or additional server.

## Run and edit

```sh
uv run python workshop_text.py             # preview console
uv run python workshop_text.py --execute   # physical console
uv run python evaluate_text.py             # language evaluation; no robot calls
uv run python evaluate_text.py --heldout   # independent, frozen language cases
```

Use `/stop` to cancel a request and stop the arm; `/quit` closes the connection.
Busy requests are rejected rather than queued. The existing control lock is
shared with the round-trip script. Start at the checked home pose with an empty
gripper. Existing collision checks and the 3 degrees/second speed remain active.

The durable working directory is [`robot_workspace`](../robot_workspace/):

- [`INSTRUCTIONS.md`](../robot_workspace/INSTRUCTIONS.md): editable behavior;
  reread on every request, with no process restart required.
- `scene.json`, `wrist.jpg`, optional `overview.jpg`: latest fresh observation.
- `input.json`, `decision.json`: exact latest model input and proposed commands.
- `history.json`: only visually verified physical moves; survives restarts.

Runtime state/images are Git-ignored. Each model call receives the current scene
and persisted history explicitly; the SDK connection remains open between calls.
Jerry can use `TextController(robot, execute=True, notify=callback)` and
`await controller.run(text)` while holding `workshop_static.control_lock()`.

## Behavior

The default left/right reference is the calibrated wrist-camera view. Its
world-frame direction is computed from camera geometry, not a manually assigned
axis. “Slightly” and unspecified “closer” mean 20 mm, stated in the response.
Normal typos such as “cartoon” resolve to the uniquely observed carton.

A command can translate a named object, restore its last verified position, or
place it on another observed object. There is no fixed translation-distance,
sequence-length, or object-name allowlist. The executor checks the full
sequence before the first transfer, rechecks the object before execution,
previews motion with Viam, grasps, lifts, places, returns home, and verifies.
A preview or failed move cannot become an undo destination. Restore concerns
position only; it does not restore arbitrary orientation or arrangement.

`tabletop_transfer.py` derives a downward grasp, object footprint, and support
height from native point clouds. It uses the official approach, descend, grab,
lift, carry, place, release, retreat flow. Observed neighbors and the carried
object are included in native collision checks. A blocked grasp angle triggers
alternative jaw angles that fit the observed footprint. Missing geometry,
insufficient jaw clearance, unreachable poses, and collisions remain concrete
execution failures. The planner does not certify grasp friction or stacking
stability. Restart a running console after Python/schema changes.

If a target/reference cannot be observed, the model requests a higher look.
Physical mode plans both legs of the checked empty-gripper observation move,
captures a new scene, returns home, and interprets the request again. There is at
most one such search per request. Preview mode reports that observation is
needed without moving. A failed camera/RPC is not treated as an empty table.

Native Viam services supply the scene: the existing carton detector/segmenter,
the official color detectors plus `red-segment` and `yellow-segment`.
The existing shape detector intermittently missed the red block, so the text
controller uses color for both new objects. Added services are recorded in
[`config/text-vision-services.json`](../config/text-vision-services.json).
Live depth observations resolve the carton, red rectangle, and yellow cylinder.
The external Brio camera is optional visual context, not a metric coordinate
source. It was no longer enumerated by macOS during the final checks; the wrist
camera successfully captured all three objects.

## Verification and limits

On October 16, 2026, the previously rejected request:

> move the cartoon 3 cm to the left of current location.

was correctly interpreted using a fresh wrist image and passed all seven native
motion previews in **10.36 seconds**. No object was moved by this regression run.
Evidence: `artifacts/diagnosis/text-task-20261016T214134900709Z.json`.
A separate live status request identified all three objects with measured world
positions in **7.50 seconds**:
`artifacts/diagnosis/text-task-20261016T214316842587Z.json`.

The automatic higher-view path also passed on hardware: a missing-object request
triggered a previewed observation move, captured a fresh image and native scene,
returned home, and correctly reported no visible green block. It did not grasp
or relocate an object. Total time including both model calls and arm travel was
44.27 seconds: `artifacts/diagnosis/text-task-20261016T214401814550Z.json`.

Eight known development regressions passed on explicit synthetic geometry: slight
right, left 5 cm, previous position, closer to another object, the original typo,
negation, missing-object observation, and missing-history rejection. These check
the requested example behavior, not generalization or physical grasping. Results and per-case latency are saved in
`artifacts/diagnosis/text-evaluation.json`; rerun with `evaluate_text.py`.

The separate [generalization audit](text-generalization-check.md) preserves a
frozen first pass, an unsupported status claim missed by command-only scoring,
the general correction, and fresh factual-status checks. Replays of known cases
must not be presented as new held-out evidence.

Before the general adapter, two model checks used the captured real scene: “red block slightly
right” and “yellow bin closer to red bin.” Both selected the correct measured
objects and displacement directions. The executor correctly blocked both because
their grasps are unvalidated. Evidence: `artifacts/diagnosis/text-live-evaluation.json`.

**Only the earlier carton adapter has physical validation.** The new general
adapter attempts native planning for red/yellow objects and stacking; it has not
yet completed a physical red/yellow transfer. Depth surfaces remain estimates.

The reported `move the red bin on top of yellow bar` failure was caused by the
old horizontal-only schema and 50 mm limit. It now resolves to `place_on(red-1,
yellow-1)`. Against the captured live scene, the initial grasp collided with
the neighboring yellow object. A 15 degree alternate jaw angle passed all seven
native previews without changing the desired object orientation or disabling
collision checks. Evidence: `artifacts/diagnosis/stack-native-preview.json`.
A fresh-camera end-to-end retry also passed in 11.326 seconds:
`artifacts/diagnosis/text-task-20261016T221240607967Z.json` (scene 1.705 s,
interpretation 7.071 s, remaining native previews 2.550 s). A separate 12 cm
yellow-object language regression correctly produced the calibrated displacement:
`artifacts/diagnosis/text-long-move-regression.json`.
A carton 3 cm move also passed all native previews through the new adapter:
`artifacts/diagnosis/carton-generic-preview.json`. The focused local suite has
21 passing tests, including noisy depth, jaw-angle search, and no execution
after failed previews.
This is preview evidence, not physical stacking evidence. The previous frozen
language audit also predates this expanded action schema; its score is historical.

The fixed table surface was measured twice from native camera point clouds,
with 0.091 mm spread. `config/tabletop-surface.json` binds that measurement to
the checked frame configuration. Routine requests reuse it and freshly observe
objects, avoiding large full-camera clouds that repeatedly disrupted the SDK
connection. Object top estimation uses a dense depth plane rather than the
highest noisy tail, which had intermittently shrunk a support to one corner.

A two-command physical request, “Move the carton 3 cm to the right, then put it
back in its previous position,” completed without intervention: 3.34 mm outward
placement error, 2.26 mm return error, 138.97 seconds total. Both verified moves
were saved to durable history; the arm finished home. Evidence:
`artifacts/diagnosis/text-task-20261016T214515662831Z.json`.
A new process then loaded both saved moves and correctly reported them alongside
a fresh three-object scene: `artifacts/diagnosis/text-task-20261016T214816482195Z.json`.

The earlier single carton move toward B is also retained:
`artifacts/diagnosis/text-task-20261016T211940273856Z.json` (4.65 mm final error,
71.42 seconds at conservative speed). Do not interpret language tests as new
hardware-transfer evidence.

The [MCP comparison](mcp-comparison.md) now confirms OAuth and authenticated
machine discovery. Live reads are blocked by the child CLI's approval policy;
their local rejection timings are not robot latency. Compare SDK and MCP with
the same model, instructions, images, and observations once live reads work.

Sources: [Viam agent guide](https://docs.viam.com/build-apps/use-viam-from-an-agent/),
[official perception workshop](https://docs.viam.com/tutorials/pick-and-place/perception-guided-picking/),
[native picking](https://docs.viam.com/motion-planning/move-an-arm/pick-an-object/),
[native placement](https://docs.viam.com/motion-planning/move-an-arm/place-an-object/),
[carried geometry](https://docs.viam.com/motion-planning/obstacles/attach-detach-geometries/),
[official color detection](https://docs.viam.com/vision/object-detection/detect-by-color/),
[Codex structured output](https://developers.openai.com/codex/noninteractive).
