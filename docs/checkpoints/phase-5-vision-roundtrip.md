# Phase 5 checkpoint: vision-guided carton round trip

Captured October 16, 2026. This commit preserves the working script and evidence;
checkpointing itself commands no hardware.

`workshop_vision.py` detects an upright carton using Viam's built-in color detector
and the workshop's native detections-to-segments module. The carton substitution
requires selecting the cap surface from the native point cloud. It approaches
in the camera frame, descends in the gripper frame, and uses native motion planning
and grip checks throughout. Each leg ends with a fresh observation from home.

```sh
uv sync
uv run python workshop_vision.py            # read-only preview
uv run python workshop_vision.py --execute  # physical A -> B -> A
uv run pytest -q                           # ten offline tests; no hardware
```

See the root README for station configuration and credential requirements.
`config/vision-services.json` is the expected vision-resource recipe, not a full
machine configuration. The calibrated frame graph and saved pose baseline are
already tracked in `artifacts/roundtrip-checked-setup.json`.

## Demonstrated results

- `vision-cycle-20261016T200629Z.json`: automatic B -> A recovery followed by a
  complete A -> B -> A cycle. Final image/readback: `artifacts/vision-final.jpg`
  and `artifacts/vision-final.json`.
- `vision-cycle-20261016T203354Z.json`: all 16 motion stages of A -> B -> A passed,
  with the initial carton cap (440.1, -455.9, 149.9) mm, approximately 54.3 mm from
  designated A. The script re-detected at B, completed the return, verified A,
  and returned home. No operator intervention or higher-view search was needed.
- `overview-hardware-check.json`: an empty-gripper move to a higher observation
  pose, native carton detection there, and return home passed. Image:
  `artifacts/overview-view.jpg`.

All named run reports above are under `artifacts/diagnosis/`.

## Limits retained in the implementation

Pickup search accepts positions within 200 mm of either station. Actual routes
must pass native reachability, collision planning and sampled workspace geometry
checks. This is not a guaranteed 200 mm reachable disk. An earlier detected
position near (490.3, -486.2) mm failed its approach preview; that refusal is saved
in `vision-cycle-20261016T202557Z.json`. Only the 54.3 mm displaced start above has
been physically verified for this expansion.

Placement verification remains 45 mm from the requested destination. The two
200 mm search regions overlap, so search acceptance must not count as placement
success. The script does not continuously track or correct disturbances during
motion; keep the carton still once execution begins.

If home view cannot resolve an upright carton, execute mode makes one checked
empty-gripper search from flange (250, -200, 700.6) mm, 80 mm above home and nearer
the base, then returns home. Preview-only mode does not physically search.
Speed is 3 degrees/second. Failures stop without automatically retrying grasps,
releasing a held object, or resetting the controller. The local process lock only
coordinates scripts using that lock.

## Runtime geometry and tests

`scene_sweep.py` loads the included `live-state.json`, `arm-kinematics.model` and
collision STL files under `artifacts/diagnosis/meshes/`. The URDF was read from
this station's Viam arm API; meshes came from the official xArm module v1.1.36.
These are necessary runtime inputs, not a physics simulator. The live frame
configuration must continue matching the checked setup before execution.

Three geometry regression tests additionally use the included historical
`pre-wall-correction-state.json`, `tutorial-live-readback.json`, and
`camera-frame-basis-readback.json`. Five tests cover static-sequence failures;
two cover expanded search, overlapping station regions, and tape-versus-carton
selection. Full-area physical reliability and continuous disturbance recovery
remain unverified.

Sources: [official workshop](https://docs.viam.com/tutorials/pick-and-place/perception-guided-picking/),
[xArm module v1.1.36](https://github.com/viam-modules/viam-ufactory-xarm/tree/v1.1.36).

Checkpoint validation: all ten offline tests passed from a clean copy of the
staged files using the existing project Python environment. No local credentials
or untracked workspace files were available to those tests.
