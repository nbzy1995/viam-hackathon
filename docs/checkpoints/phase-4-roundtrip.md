# Phase 4 checkpoint: native A–B–A round trip

Checkpoint captured on October 16, 2026. This records the main thread's existing
work and execution evidence; checkpointing itself sends no robot commands.

## Implemented behavior

`workshop_static.py` uses native Viam saved-pose switches and the gripper API to
pick up the carton at A, place and release at B, re-grasp at B, return and release
at A, and return the arm home. The return leg and tabletop placement adapt the
[official Phase 4 tutorial](https://docs.viam.com/tutorials/pick-and-place/control-the-robot-from-python/).

```sh
uv sync
uv run python workshop_static.py            # readiness check; no robot motion
uv run python workshop_static.py --execute  # physical A -> B -> A round trip
```

The station must have the six saved controls configured, with matching frames
and poses in `artifacts/roundtrip-checked-setup.json`. Begin at the checked home
pose with an empty gripper and the carton upright at the checked A position and
orientation. The script does not detect a displaced carton. Configuration
changes require a fresh route preview; the stored setup is a historical baseline,
not proof that the current station is ready.

Credentials are supplied locally in ignored `.env.viam.json`, with `address`,
`api_key_id`, and `api_key`. No credentials are included in this checkpoint.

The script sets runtime speed to 3 degrees/second and acceleration to 6
degrees/second squared. It checks arm status, controller errors, saved setup,
Cartesian endpoint positions, and grip retention. A failure requests an arm
stop; it does not automatically retry, release the object, or reset the controller.
The local control lock coordinates workshop scripts that honor that same lock.

## Recorded physical evidence

| Run start (UTC) | Recorded outcome |
| --- | --- |
| 19:49:17 | A -> B -> A completed; both releases and return home recorded |
| 19:54:14 | A -> B -> A completed; both releases and return home recorded |
| 19:58:03 | Stopped after release at B when re-grasp returned false; no return carry |

The first successful run took approximately 119 seconds. The saved final image
supports the main thread's observation that the carton was upright back at A.
`roundtrip-result.json` distinguishes one visually verified physical round trip
from two successful script reports. Three-cycle repeatability is not established.

Included evidence:

- `artifacts/roundtrip-result.json`
- `artifacts/roundtrip-final-color.png`
- `artifacts/roundtrip-checked-setup.json`
- `artifacts/diagnosis/roundtrip-native-preview.json`
- The three timestamped run reports listed above

## Offline validation and remaining work

```sh
uv run pytest tests/test_workshop_static.py qa-console/test_persistent_sim.py -q
```

Five static-script tests cover failed initial grasp, starting with an object
already held, motion failure, lost grip, and failed re-grasp at B. Three console
tests cover persistent connection reuse and simulator-only command routing.
These tests use fakes and never connect to the robot.

This checkpoint preserves the successful adapted Phase 4 execution and its known
repeatability failure. Phase 5 perception-guided physical picking and reliable
repetition remain separate work. No claim is made that every tutorial checkpoint
has been completed.
