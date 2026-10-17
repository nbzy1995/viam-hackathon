# Tabletop end-to-end evaluation contract

This evaluates the supported workflow: a text request, fresh calibrated scene,
model interpretation, the production controller, native xArm motion planning,
SDK motion/gripper calls, independent scene updates, verification, and durable
history. Language-only scoring and successful motion previews are separate
metrics. Neither is a completed transfer.

Scope is simple rigid tabletop objects visible to configured perception, with a
downward parallel-gripper grasp and width below 75 mm. The fixtures represent the
red block, yellow cylinder, and carton already supported by this demo. They do
not establish that the robot can manipulate arbitrary office items such as
paper, cables, filled cups, keyboards, or deformable objects.

The execution model is **stateful kinematic integration**. Native Viam planning
uses the checked xArm model, frames, walls and collision geometry. Camera and
gripper effects are simulated explicitly. This is end to end across the software
workflow; it is not contact-physics validation or proof of reliable physical
grasping, friction, release, depth perception, or stacking stability.

## Inputs and ownership

- Development: [`office-e2e-development.json`](../config/office-e2e-development.json),
  18 scenarios and 20 runs after expanding fault variants.
- Independent holdout: `config/office-e2e-holdout.json`, eight scenarios.
  The implementer must not inspect its cases before freezing the implementation,
  production instructions, evaluator, and development results by SHA256.
- The suite author read only the command schema, interpreter API, and capability
  documentation. Existing evaluation cases/results and production instructions
  were excluded. These are independently authored probes, not a statistically
  representative benchmark of all office tasks.

Each case starts from a new fixture and empty history unless its fixture states
otherwise. Turns within a case share world state and verified history. No case
may use the preceding case's state. Parent-owned preflight must establish that
the positive fixture is valid for the checked robot. If a positive native plan
fails, record the failure; do not silently relabel it an expected rejection or
change a held-out arrangement after seeing its result.

## Machine-readable format

```json
{
  "version": 1,
  "split": "development",
  "execution_model": "stateful_kinematic_sdk_integration",
  "coordinate_units": "mm",
  "defaults": {},
  "fixtures": {
    "standard": {
      "table_z_mm": 7.94052666147,
      "objects": [{
        "id": "red-1", "label": "red block",
        "center_xy_mm": [430, -360], "bottom_z_mm": 7.94052666147,
        "size_xyz_mm": [50, 24, 20], "yaw_deg": 0
      }],
      "image_right_xy": [0, -1], "image_up_xy": [1, 0],
      "obstacles": "checked_setup", "verified_history": []
    }
  },
  "cases": [{
    "id": "example", "fixture": "standard",
    "turns": [{
      "request": "Move the red block 2 cm right.",
      "expect": {
        "outcome": "completed",
        "final_positions": [{
          "object_id": "red-1", "xy_mm": [430, -380],
          "bottom_z_mm": 7.94052666147,
          "tolerance_mm": 5, "z_tolerance_mm": 3
        }],
        "relations": [], "preserved_ids": [],
        "actuator_policy": "run", "history_policy": "verified_success_only",
        "arm_home": true, "gripper_empty": true
      }
    }]
  }]
}
```

`visible_ids_before` and `visible_ids_after_overview` change perception only;
hidden objects remain in the world. `extra_obstacles` adds fixture-specific
geometry to the checked walls. `fault` injects one named failure. A turn with
`variants` expands into independent copies of that case, each using one variant
fault. Fixtures use box extents for the object envelope; a label such as cylinder
does not require a contact-physics engine.

Outcomes normalize production output to `completed`, `status`, `reject`, or
`error`. A clarification response counts as reject if it performs no object
action. This normalization must not treat an exception as success or allow a
rejection to pass a positive case.

## Development coverage

| Case | Behavior under test | Required outcome |
|---|---|---|
| D01 | Describe the observed table | Correct observed objects; no actuation/history change |
| D02 | Explicit higher-view request | One successful overview, fresh summary, return home |
| D03 | Small default shift | Red object moves 20 mm in camera-right direction |
| D04 | Rotated view | Carton moves 50 mm in recalibrated camera-left direction |
| D05 | Millimeters and meters across two turns | 30 mm outward, then return; persistent state |
| D06 | Relative object reference | Red moves 20 mm toward yellow; reference stays fixed |
| D07 | Stack | Red ends centered on yellow, with correct support height |
| D08 | Unstack | Red leaves support, translates, and rests on table |
| D09 | Verified restore | Carton returns to its own last verified position |
| D10 | Two objects in one request | Both requested final positions; carton unchanged |
| D11 | Initially hidden object | One overview finds carton; requested move then completes |
| D12 | Still-missing object | One overview, then rejection; no grasp/transfer |
| D13 | Ambiguous source | No arbitrary selection or object actuation |
| D14 | Camera unavailable | Failure, no blind observation motion or object action |
| D15 | Unreachable destination | Native planning blocks before any transfer |
| D16 | Obstructed destination | Native collision checking blocks before any transfer |
| D17 | Empty grasp | Stop after failure; no carry or successful history entry |
| D18 | Release/verification faults | Release RPC failure, wrong position, and missing final observation each fail without success history |

This coverage follows interaction, geometry, state, and failure-stage dimensions.
It is not an enumeration of paraphrases for the user's examples. The independent
holdout changes wording, geometry, view, sequence composition, and state/failure
combinations. Once opened and used for changes, it becomes regression coverage;
it cannot supply a fresh held-out score again.

## Outcome oracle

The expected predicates are read only by the scorer. They must never initialize
the post-command world, supply perception results, or update object locations.
The simulated world updates objects from actual SDK trajectory endpoints and
grasp/release events, with grasp-frame offsets and explicit support behavior.
Copying a planned target or expected coordinate into the world is circular and
invalidates the result.

- `final_positions`: independent final object center in XY and bottom height,
  within stated tolerances. Passing the goal to a planner does not satisfy it.
- `relations`: independently compute center-distance change or support/contact.
  A supported object must overlap its support footprint and have a bottom within
  the stated contact gap. This is a geometric predicate, not a stability claim.
- `preserved_ids`: every listed non-target's position, height and orientation
  remains unchanged within 2 mm and a small stated angular tolerance. Compare
  against the turn's initial world, not its latest perception.
- `min_source_motion_mm`: prevents a no-op from passing a short-distance task.
- `milestones`: optional independent world predicates after numbered release
  events, so an outward-and-return sequence cannot pass by doing nothing.
- `visible_claim_ids`: all required visible objects must appear in the status
  response; invented objects or claims of successful movement are failures.
  Use explicit structured evidence where available, with human review for prose
  claims. Do not hide ungraded prose behind an overall pass.
- `arm_home` / `gripper_empty`: true or false is a required terminal condition;
  null means no such requirement after a fault. Fault termination still requires
  a stop and no subsequent unsafe movement.

`actuator_policy` is `none`, `overview_only`, `run`, or `stop_after_fault`.
`none` forbids motion/open/grab calls; an emergency stop RPC is allowed and logged.
`overview_only` permits the checked empty-gripper observation round trip, not a
grasp or transfer. Once the controller decides reject, no subsequent motion,
open or grab call is allowed. A prior observe decision may have legitimately
performed the single overview. `stop_after_fault` allows steps before the fault,
requires stopping afterward, and forbids automatic continuation.

`history_policy=unchanged` requires exact history equality. For
`verified_success_only`, every recorded success must correspond to independently
verified world evidence. Failures, previews, model predictions and unobserved
placements cannot become restore destinations. `verified_move_count`, where
present, checks completed moves rather than an exact internal command trace.

## Fault injection contract

| Stage/kind | Simulator behavior |
|---|---|
| `camera/unavailable` | Observation RPC fails; do not synthesize an empty table |
| `grasp/empty_grasp` | Grasp reports no object and world remains unattached |
| `release/rpc_error` | Release raises and leaves attachment state explicit |
| `verification/offset_released_object` | After release, displace the actual world object by the specified offset before observing |
| `verification/hide_released_object` | Keep actual released world position but hide it from final perception |
| `before_execution_observation/offset_source_object` | Move the actual source between full preflight and the execution guard; the old plan must not run |

Faults are deterministic, one-shot at the named stage/occurrence, and recorded in
the result. The engine must assert that the fault actually fired. A case that
never reaches its injection point is a failure or blocked run, not a pass of the
fault response. Natural collision/unreachable failures must come from the native
planner; they are not mocked planner exceptions.

## Run order and report

1. Freeze fixture inputs and run development through the real interpreter and
   production controller, with the kinematic SDK environment and native planner.
2. Preserve per-turn initial/final worlds, observation lifecycle, model outputs,
   native plan diagnostics, actuator events, history deltas, injected faults and
   predicate results. Identify unavailable infrastructure as blocked.
3. Fix general causes, then rerun affected development cases and the full small
   development set. Keep first failures and changed-code hashes.
4. Freeze code, instructions, scorer and fixtures; run all eight holdout cases
   once and retain their first-pass results before any inspection-driven changes.
5. Report positive task completion, negative-case containment, observation/state
   coverage, and blocked cases separately. Do not merge them into an apparently
   impressive single success percentage.
6. Only after correctness coverage is satisfactory, compare latency on the same
   frozen cases/worlds/model/settings. Retain end-to-end and stage timings,
   including observation and native planning. A faster rejected request is not
   a successful latency improvement.

Physical validation remains a separate next stage. The simulator's successful
kinematic transfer cannot certify friction, grasp acquisition, or recovery from
real contact. Known hardware failures should also be retained as reproducible
development cases; these independent cases supplement them.

## Running again

```sh
uv run python evaluate_tabletop.py --run-id development-new
uv run python evaluate_tabletop.py --suite config/office-e2e-holdout.json \
  --replay-of artifacts/diagnosis/office-e2e-holdout-1.json --run-id regression-new
```

`--replay-of` requires an already completed run of the exact same suite and
labels the new result `regression_replay`. It permits focused `--case` debugging
without presenting a consumed holdout as new independent evidence. The original
held-out result is retained. Positive-task completion and negative-case
containment must be reported separately, alongside blocked infrastructure.

The scorer checks history prefix, source/release positions and support heights;
overview claims require a higher camera pose from independent forward kinematics.
Prose status claims require an explicit review artifact before a full pass.
The native preview connection is shared with the station: run these evaluations
serially. An active-operation guard failure is blocked evidence, not a successful
test of a later injected fault.
