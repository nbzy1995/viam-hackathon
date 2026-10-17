# Viam carton round trip

[Voice demo](voice-ui/README.md): realtime ElevenLabs speech around the local
robot harness, with saved readiness and five-degree motion checks.

[Milestone 2: scene-aware text control](docs/milestone-2-text-control.md).
`uv run python workshop_text.py` opens the persistent preview console;
`--execute` enables physical execution. Edit
[`robot_workspace/INSTRUCTIONS.md`](robot_workspace/INSTRUCTIONS.md) to iterate
behavior without restarting. The program supplies live images, native 3D object
positions, and persisted verified move history to Codex. Left/right defaults to
the calibrated wrist view; “slightly” means 20 mm. It can request one checked
higher observation, translate objects, restore their previous positions, or
place one observed object on another. There is no 5 cm move cap or carton-only
allowlist. Native depth supplies grasp/support geometry; Viam previews the path
and tries alternative grasp angles when needed. This general adapter has preview
verification; physical results below belong to the earlier carton adapter.
Restart the console after Python/schema updates; instruction-only edits reload
on the next request.

[Tabletop end-to-end evaluation and latency results](docs/tabletop-evaluation-results.md)
cover the production controller with real model calls and native Viam planning,
plus stateful simulated arm/gripper execution. Camera and contact are synthetic;
this is software integration evidence, separate from physical transfer results.

The original failed “cartoon 3 cm to the left” request now passes interpretation
and all native motion previews in 10.36 seconds. Eight known development regressions passed;
run `uv run python evaluate_text.py`. These do not establish generalization or
physical transfer reliability. The separate frozen set runs with
`uv run python evaluate_text.py --heldout`.
[Generalization audit](docs/text-generalization-check.md): 16/16 first-pass
held-out command cases; one unsupported status claim found by manual review,
then corrected and checked with four fresh factual-status cases. Future reruns
of these now-known cases are regressions.
A two-command “3 cm right, then put it back” request passed on hardware without
intervention: 3.34 mm outward error, 2.26 mm return error, 138.97 seconds total.
The higher-view observation and return also passed on hardware. [MCP comparison](docs/mcp-comparison.md)
now confirms OAuth and machine discovery. Live MCP reads are blocked by the
child CLI's approval gate, so no transport-speed comparison is available yet.

One trigger uses native Viam vision and motion to move the carton A → B → A,
then return home. It re-observes after placement to accommodate a shifted carton.
If the carton starts at B, it first returns it to A.

```sh
uv run python workshop_vision.py            # native preview of the next transfer
uv run python workshop_vision.py --execute  # physical recovery, if needed, and round trip
```

Two physical vision-guided A → B → A cycles passed without intervention on
2026-10-16. The latest started 5.4 cm from A; an earlier run first recovered the
carton from B. Longer-run repeatability has not yet been established.

The implementation follows the [official workshop](https://docs.viam.com/tutorials/pick-and-place/perception-guided-picking/):
observe from home, detect and segment with Viam vision services, approach in the
camera frame, descend in the gripper frame, then grasp and place through Viam.
The built-in color detector replaces the shape detector for the approved carton
substitution. A small grasp calculation uses the cap surface in the native
point cloud and retains the checked downward orientation.

Start with the arm at its saved home, the carton upright within 20 cm of A or B,
and the workspace clear. The radius is a pickup-search allowance; it does not
extend mechanical reach or relax collision checks. If home view cannot resolve
the carton, execution makes one previewed empty-gripper move to a higher view
(80 mm above home, closer to the base), observes, and returns home before picking.
Preview-only mode previews that search but does not move the arm. Placement
verification remains within 45 mm of the requested destination, separately from
the expanded search radius. A = (451.3, -509) mm; B = (391, -349) mm in world coordinates.
The script checks the station configuration, previews each transfer, checks
holding during carry, and stops on failure without automatic retry or release.
Speed is 3 degrees/second. A process lock prevents simultaneous workshop runs;
it cannot block controls in the Viam browser or on another computer.

`workshop_static.py` is the Phase 4 saved-pose reference. It completed two script
runs, but a third missed the fixed re-grasp at B after the carton shifted.
Use the vision sequence for continued validation of repeatable operation.

Credentials are loaded from ignored `.env.viam.json`. Reports are saved under
`artifacts/diagnosis/`. See [checkpoint evidence](docs/checkpoints/phase-5-vision-roundtrip.md).

```sh
uv run pytest -q  # focused offline tests; never moves hardware
```

The 20 cm expansion has not been verified by physical pickups throughout that
area. Some points near A are outside the straight-down pickup reach; the native
planner rejects those before any carrying move.

The higher-view motion, native carton detection there, and return home were
verified on hardware. See `artifacts/diagnosis/overview-hardware-check.json`.

The existing machine must retain the calibrated arm/camera/gripper frames and
saved poses in `artifacts/roundtrip-checked-setup.json`. The vision resource
recipe is `config/vision-services.json`; merge it into the existing machine
configuration rather than replacing the entire configuration. Supply local
`.env.viam.json` with `address`, `api_key_id`, and `api_key`.
