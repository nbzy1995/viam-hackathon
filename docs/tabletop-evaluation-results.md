# Tabletop evaluation and latency results

The earlier 42/42 result tested language interpretation only. The new evaluation
runs the real model and production text controller through native Viam planning,
local simulated arm/gripper calls, object-state updates, placement verification,
and persistent move history. It makes no physical actuator calls.

## Coverage

The suite contains 28 scenarios: 20 development runs and eight independently
authored holdout cases. Seventeen are positive tasks (14 manipulation and three
observation/status cases); eleven exercise rejection or failure handling.

| Dimension | Cases |
|---|---|
| Directions and quantities | Slight shifts, centimeters/millimeters/meters, rotated camera directions |
| Object relationships | Closer/farther, alternate source/reference objects |
| Placement | Stack, unstack onto the table, correct support height |
| Task state | Multiple objects, outward/return, stack/restore, verified prior positions |
| Observation | Table summary, higher view, hidden object found, still missing after looking |
| Ambiguity and faults | Ambiguous source, camera unavailable, empty grasp, release error, misplaced or unobservable release |
| Planning and scene changes | Unreachable goal, obstacle collision, complete-sequence preflight, source moved before execution |

These cover common pick/place operations using the existing carton, block, and
cylinder. They do not establish manipulation of arbitrary office items such as
paper, cables, keyboards, or filled cups. The fixture author did not read the
production instructions or previous evaluation cases before authoring the suite.

The scorer measures the independently updated world, preserves non-targets,
checks intermediate releases and verified history, and requires faults to
actually fire. Status prose receives separate review. Expected destinations are
not used to update simulated objects. See the
[evaluation contract](office-e2e-evaluation-contract.md) for exact predicates.

## Results and repairs

Final regression results are recorded in the linked evidence below after the
complete run and prose review finish.

Earlier failures remain preserved:

- First development run: 14/20. It exposed an unusable approach joint branch,
  insufficient grasp orientations, redundant observation for ambiguous intent,
  and a simulator observation-boundary error.
- Corrected development run: 19/20; one active-operation block prevented a fault
  from firing. That case passed on a same-code retry and was recorded separately.
- First untouched holdout: 7/8. One model request timed out before robot commands.
  Cleanup took 128.9 seconds despite a 60-second deadline because the CLI's child
  retained output pipes. Process-group cleanup is now bounded and regression
  tested. The task passed on replay in 12.5 seconds. Replays are labeled
  regressions, not new held-out evidence.

The two original user failures and the additional general repairs are documented
in the [failure investigation](text-failure-investigation.md). No case-specific
coordinates, joint angles, or prompt-match shortcuts were added to production.

## Latency after correctness

Removed one duplicate seven-stage planning pass per executed object. Whole-task
preflight, the fresh per-object preview, collision checks, scene/joint guards,
placement verification, and stop-on-execution-failure remain.

Four alternating-order baseline/candidate pairs all completed correctly:

| Task | Native plan calls, before → after | Time after interpretation, before → after |
|---|---:|---:|
| Small shift | 21 → 14 | 4.73 → 3.43 s |
| Carton with rotated view | 29 → 22 | 5.60 → 2.94 s |
| Unstack | 71 → 64 | 12.83 → 10.84 s |
| Two objects | 42 → 28 | 7.13 → 5.76 s |

Median paired reduction: **1.68 seconds after interpretation; 1.93 seconds
overall**. One pair was slower overall because its model response took longer.
This small comparison measures software/planning latency, not physical cycle
time. It does not demonstrate faster model inference. Full timings and retained
baseline hashes are in the
[paired benchmark](../artifacts/diagnosis/office-e2e-latency-pairs.json).

## Reproduce and limits

Run serially against the existing station's native planning service:

```sh
uv run pytest -q
uv run python evaluate_tabletop.py --run-id development-new
uv run python evaluate_tabletop.py --suite config/office-e2e-holdout.json \
  --replay-of artifacts/diagnosis/office-e2e-holdout-1.json --run-id regression-new
```

Reports refuse to overwrite an existing run ID. They record fixtures, code,
instructions, robot-model and dependency fingerprints, model outputs, native
plans, simulated actions, world state, faults, and per-predicate failures.

The simulator uses synthetic perception and geometric grasp/release behavior.
It applies native preview trajectories locally; it does not exercise the real
Motion.Move RPC's replanning or motor timing. It cannot validate detector
accuracy, friction, grip force, release dynamics, or physical stack stability.
Those require a separate physical run with the current code.

Python changes require restarting the persistent text console. Instruction-only
edits continue to reload on the next request. Do not start a second physical
controller alongside an existing one.
