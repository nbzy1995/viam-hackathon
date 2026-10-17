# Two failed requests, October 16, 2026

## Findings

`move higher, and see again` completed its higher observation and return home.
The wrist camera supplied fresh evidence of three objects. The second model call
received the original request without an explicit completed-operation record and
requested another observation. The one-observation guard then raised a misleading
camera-unavailable error. The optional external camera's missing `ffmpeg` was
separate: the wrist camera was working.

`ok. move the red bin to the right 5 cm.` was interpreted correctly as a 50 mm
translation along calibrated image-right. No transfer began. The executor chose
a 247.31 mm TCP travel height from the tallest object anywhere in the scene.
The native planner rejected the carry endpoint at that height as unreachable.
Three grasp angles got through grasp and lift; two others collided with the
neighboring yellow object during grasp. The final error incorrectly emphasized
grasp angle even though the main failure was the carrying waypoint.

The same recorded destination and all existing obstacle checks were replayed at
247.31, 197.31, and 115.91 mm. The first two failed at carry; the last passed all
seven native previews. This isolates the over-high intermediate waypoint as a
cause, rather than assuming the requested final destination was impossible.

## Why evaluation missed them

The previous 42/42 score covered language proposals: decision, object references,
command order, and displacement. It did not call `prepare_transfer`, the native
planner, the observation follow-up loop, or physical execution. The observation
unit test covered observe-then-reject, not observe-then-success. Synthetic scenes
did not test the interaction of a short move near reach limits with a distant tall
object. Separate successful motion previews covered other arrangements.

That was insufficient coverage for a working robot application. Language success
was given too much weight before end-to-end controller behavior was established.
The earlier simulator checks were arm-only or separate synthetic physics checks;
none exercised this natural-language controller through the complete task.

## Changes and evidence

- Pass completed observation metadata into the follow-up interpretation; finish
  inspection-only requests with a fresh status summary. Status reports now have
  a successful result. Distinguish a repeated observation request from camera
  failure.
- Start transfers with 50 mm clearance above grasp and release TCP heights.
  Retain the old higher route as a fallback. Every candidate still requires all
  native previews, carried-object geometry, all neighbors, and wall sweeps.
  Error output identifies the failing stage and attempted height.
- Three focused regression tests failed before these changes; the full local
  suite then passed 26/26. These are software tests, not robot-success statistics.
- Six real-model observation-state regressions passed structured checks and four
  factual rubrics. They use recorded measurements with no images: older wrist
  images had been overwritten, so current images were not substituted as history.
- Actual controller plus real interpreter completed the observation workflow with
  its sensor/motion boundary replayed from recorded telemetry. A separate run of
  the actual controller with fresh camera data passed the 5 cm request through
  native planning in preview mode. Neither run moved hardware.

Evidence under `artifacts/diagnosis/`:

- `text-task-20261016T223950399444Z.json`: original observation failure.
- `text-task-20261016T224126296656Z.json`: original translation failure.
- `two-failure-preview-replay.json`: controlled travel-height comparison.
- `two-failure-fixed-native-preview.json`: modified production-code native replay.
- `text-observation-regressions-failure-fix.json`: six model regression results.
- `two-failure-controller-replay.json`: controller-level verification and limits.

## Completion gate

Do not optimize latency until the supported tabletop task suite passes through
the complete controller with stateful simulated outcomes, including failure paths
and an independently authored final set. Report synthetic perception/contact,
native kinematic planning, and physical evidence separately. An end-to-end software
simulation does not prove grasp friction, detector accuracy, or physical safety.

The design retains Viam's documented approach, descend, grasp, lift, place, release,
and withdraw flow, with obstacles included in motion planning. See the official
[pick guide](https://docs.viam.com/motion-planning/move-an-arm/pick-an-object/) and
[place guide](https://docs.viam.com/motion-planning/move-an-arm/place-an-object/).
Travel height selection is a project adaptation, not a Viam-prescribed formula.

## Additional failures found by complete controller evaluation

The first 20-run stateful integration suite passed 14 runs. It found issues that
the earlier language-only tests could not expose:

- Three carton scenarios selected an approach joint configuration that could
  not follow the required straight descent. The recovery now probes a grasp
  configuration, plans the straight reverse path up to an approach, then checks
  the complete forward route. Only the checked forward route is executed; the
  unconstrained grasp probe is never executed. No fixed joint angles or case
  coordinates were added.
- Unstacking needed a perpendicular grasp to clear the neighboring support.
  The generic candidate search now includes both perpendicular jaw orientations
  when the measured object fits. Native collision checks remain unchanged.
- Two equally matching visible objects triggered a redundant camera movement.
  The instructions now distinguish ambiguous user intent from missing visual
  evidence: another view cannot determine which identical object was meant.
- A simulator observation exposed a static fixture obstacle as model metadata
  that the production camera does not provide. The model safely rejected that
  case before native planning, so it did not test the intended collision path.
  Fixture obstacles now stay in the native world geometry and outside synthetic
  camera detections. This was an evaluation-adapter error, not an unsafe action.

Independent review also tightened the outcome oracle: actual higher camera pose,
immutable history, independent source/release positions, intermediate release
milestones, observable-fault containment, and explicit pending prose review.
Passing a final coordinate alone is insufficient for a multi-step task.

The untouched eight-case set first passed seven cases. The remaining request
timed out in the model subprocess before any robot command. The nominal 60-second
timeout returned after 128.9 seconds. Inspection of the installed CLI launcher
showed that it spawns a native child with inherited output pipes; killing only
the launcher left cleanup waiting for that child. A local launcher/child test
reproduced the delayed cleanup. The interpreter now owns a separate process
group, kills that group on timeout/cancellation, and bounds output cleanup. The
one-second regression test finishes in about one second with its child stopped.
The original task passed on replay in 12.5 seconds; the first-pass failure remains
in `office-e2e-holdout-1.json` and is not rewritten as a fresh held-out pass.

The latency comparison initially hit the active-operation guard. A read-only
probe reproduced the rejection and recorded only `GetObjectPointClouds` and
`GetPose` operations in the rejected samples. These are scene queries, not arm
commands. The guard now permits those two documented query methods and continues
to block actuator and unknown methods, with method names in the error message.
The regression verifies that concurrent scene queries pass while Motion.Move,
Gripper.Grab, Arm.DoCommand and unknown operations remain blocking. See
[`active-operation-probe.json`](../artifacts/diagnosis/active-operation-probe.json),
[official vision API](https://python.viam.dev/autoapi/viam/services/vision/client/index.html#viam.services.vision.client.VisionClient.get_object_point_clouds),
and [official pose API](https://python.viam.dev/autoapi/viam/robot/client/index.html#viam.robot.client.RobotClient.get_pose).
