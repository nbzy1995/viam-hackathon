# Official workshop checkpoints

Scope: [Viam pick-and-place workshop](https://docs.viam.com/tutorials/pick-and-place/),
core phases 1–5. The approved substitutions are a carton for the block and a
marked tabletop destination for the bin. Phase 6 deployment is optional.

| Phase | Evidence | Status |
| --- | --- | --- |
| 1: platform and configuration | Live arm, gripper, RGB-D camera, frames and native motion service inspected | Passed |
| 2: manual control | Real carton grasp, carry, tabletop release, withdrawal and home return | Passed |
| 3: saved poses | Six native pose controls executed on hardware; straight legs use Cartesian goals with linear constraints | Passed |
| 4: Python sequence | Two successful script reports for A → B → A; first independently confirmed by camera and telemetry | Passed once with visual verification; repeatability failed on a later run |
| 5: perception | Native color detector and segmenter locate the carton and table markers; vision-guided transfer previews pass | Passed: vision-guided B → A recovery and A → B → A cycle, without intervention |

## Current approach

`workshop_vision.py` uses Viam's built-in `color_detector`, the tutorial's
`viam:vision:detections-to-segments` service and `builtin` motion service.
The tutorial's shape detector returned no detections for this carton. The color
model is the explicit carton substitution; no custom detector or ML model is used.

The native segmenter's point cloud supplies the cap's highest surface. The
script selects that surface to aim the gripper, preserving the proven downward
orientation. This is carton-specific grasp geometry, rather than the tutorial's
block-center offset. It observes from home, approaches in the camera frame,
and descends in the gripper frame. It observes again after every placement so
that a shifted carton does not require an operator reset.

A = (451.3, -509) mm and B = (391, -349) mm in world coordinates. The script
accepts a small measured shift near either station. A carton initially at B is
returned to A before the A → B → A cycle. These are the reachable stations chosen
after the original distant pickup was rejected by the planner.

## Physical evidence and failure

- Manual A → B: `artifacts/manual-transfer-result.json`.
- First scripted round trip: `artifacts/diagnosis/roundtrip-20261016T194917Z.json`;
  final image: `artifacts/roundtrip-final-color.png`. Approximately 119 seconds.
- Second successful script report: `artifacts/diagnosis/roundtrip-20261016T195414Z.json`.
- Third run: `artifacts/diagnosis/roundtrip-20261016T195803Z.json`. Released at B,
  then Grab returned false. The script stopped without attempting the return carry.
- Recovery: `artifacts/diagnosis/recover-from-failed-regrasp.json`. Empty gripper
  opened, withdrew from B, then returned home; native previews and telemetry passed.
- Fresh depth at B placed the cap near (358, -349, 146) mm: about 33 mm from the
  saved B grasp center. This explains why replaying that fixed grasp can miss;
  the exact physical cause of the shift was not recorded.

## Checks and limits

Native plans retain collision checks and are additionally checked against the
configured workspace geometry. These are geometric checks, not a physics
simulation or a guarantee against an unmodeled obstacle. Carrying paths retain
the previously checked carton envelope. Speed remains 3 degrees/second.

Ten focused offline tests cover grasp/motion failure handling and geometry
regressions. The workshop scripts also share a process lock. That lock does not
prevent commands from the Viam browser or another computer.

Obsolete simulator scripts, the PyBullet dependency, custom motion executors
and their tests were removed. The historical fixed-pose script remains as the
Phase 4 reference; its repeated fixed re-grasp is not the reliable demo path.

## Vision-guided hardware result, 20:12 UTC

`artifacts/diagnosis/vision-cycle-20261016T200629Z.json` records all 24 motion
stages of the recovery B → A and the subsequent A → B → A cycle, with successful
grasps, holding checks, releases, home returns and destination detections. The
re-detected cap at B was (391.6, -336.6, 146.5) mm; the return pickup used that
measurement instead of the fixed B center. No operator reset was needed.

This demonstrates the adapted Phase 5 checkpoint and one complete vision-guided
round trip. It does not establish long-run reliability. The full run, including
the preliminary recovery transfer, took about six minutes at 3 degrees/second.

Final readback at 20:14 UTC confirmed stationary home and empty/open gripper
(position 840). `artifacts/vision-final.jpg` shows the carton back at A;
`artifacts/vision-final.json` records the verification. No control process remains
running.

## Expanded pickup search

Pickup acceptance is now 200 mm from either station. This remains subject to
native reachability and collision planning; it is not a guaranteed reachable
disk. Placement verification stays at 45 mm, so overlapping search regions do
not hide a wrong destination. Native carton candidates are checked in size order
so a large blue tape detection does not suppress a smaller carton.

If no upright carton is resolved from home, one higher observation is attempted
only in execute mode, with an empty gripper. Both outgoing and return routes are
previewed. The higher flange target is (250, -200, 700.6) mm, 80 mm above home;
straight vertical lifts of 50 and 100 mm at home XY were rejected as unreachable.
The native segment is transformed using the actual stationary camera pose at
that view, then the arm returns home before the pickup sequence.

The current carton cap near (490.3, -486.2, 149.8) mm was detected and accepted
by the expanded search, but its approach preview was rejected as unreachable.
No pickup was attempted. Full 20 cm physical pickup coverage is unverified.

The higher-view hardware check passed at 16:28 EDT: native vision resolved the
carton from the raised pose, and the arm returned to stationary home. Evidence:
`artifacts/diagnosis/overview-hardware-check.json` and
`artifacts/overview-view.jpg`. Ten focused offline tests passed. This was an
empty-gripper camera check, not a 20 cm displaced pickup trial.

## Displaced-start physical cycle, 16:37 EDT

`artifacts/diagnosis/vision-cycle-20261016T203354Z.json` passed the full
A → B → A sequence without intervention. The initial cap was approximately
(440.1, -455.9, 149.9) mm, 54.3 mm from A. All 16 motion stages completed,
including re-detection and a corrected pickup at B; final vision confirmed
placement at A and stationary home. The higher-view fallback was not needed.
This validates a 5.4 cm displaced start, not the entire 20 cm search area.
