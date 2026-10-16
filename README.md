# Viam carton round trip

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
uv run pytest -q  # ten focused offline tests; never moves hardware
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
