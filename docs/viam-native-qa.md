# Native Viam QA — 2026-10-16

## Result

Native component QA passed for the isolated simulated arm. Full motion-planning and pick-and-place QA is **blocked**, not passed.

Added `qa-sim-arm` to the existing `armfarm21-main` server using built-in `arm/simulated`, attributes `{"arm-model":"xarm6","speed":0.3,"simulate-time":true}`, and an identity frame under `world`. The component reports Ready. No physical arm or gripper motion command was issued. The existing physical component configuration was not edited in this QA session.

## Executed checks

| Check | Observed result | Status |
|---|---|---|
| Simulated component initialization | Six joints at zero; flange (207, 0, 112) mm; downward orientation; Ready | Pass |
| Six-joint repeatability | Three consecutive cycles: all joints 0° → 10° → 0°. Every endpoint read back at the target to the UI's 0.01° precision; no component resets between cycles | Pass |
| Stop during motion | From joint 0 = 90°, commanded −90° and immediately stopped. Readback held at 86.05° on a later independent observation; Idle | Pass |
| Recovery after stop | Commanded all joints back to zero; readback zero (including displayed −0.00) | Pass |
| Joint limit rejection | Joint 1 target 130° rejected: allowed range [−118°, 120°]. Joint state remained at zero | Pass |
| Native Preview move | Selected only `qa-sim-arm`; requested (218, 0, 112) mm with unchanged downward orientation | Blocked: unlinked `cam` frame |
| A-to-B multi-segment planning, obstacle and unreachable-goal rejection | Could not reach the planner because frame-system validation fails first | Not run |
| Tool/camera/payload envelope and self-collision coverage | No corresponding verified simulated attachments yet | Not validated |
| Real blue-marker coordinates, camera calibration, physical grasp/release | Not measured by these tests | Not validated |

Raw joint evidence: `artifacts/viam-native-joint-qa.json`. Setup screenshot: `artifacts/viam-native-qa.png`.

The first attempt to observe a Moving indicator timed out; the arm subsequently reached 90°. That attempt is not counted as a successful stop test. The separate immediate-stop test above verified interruption by position readback. UI polling is not suitable for measuring stop latency. Fast initial jog exploration also showed that issuing commands before reading back completion can overwrite targets; counted repeatability cycles waited for every endpoint.

## Planner blocker and ownership

Preview returned: `Some frames are not linked to the world frame. Unlinked parts: [cam]`.

The physical arm had a servo motor 2 error. Its missing frame leaves the attached camera unlinked. Viam's official `NewFromServiceMustBeConnected` checks unlinked parts before applying supplemental transforms, so adding preview-only world-state transforms does not resolve this failure. This is a frame-system prerequisite failure, not evidence that the requested target is unreachable.

The user is resolving the frame issue in a separate session. No camera detachment or physical configuration repair was performed here. The simulator was left idle at zero, with the pending joint target reset to current position. Its saved configuration is retained for the next QA stage.

## Next native QA stage

After the other session resolves the frame issue, first verify that Preview move succeeds. Inspect the existing table/wall/ceiling geometry and attach verified tool/camera envelopes to the simulated arm. Then plan the complete approach–descend–lift–transfer–descend–withdraw sequence, execute only against `qa-sim-arm`, and read back each endpoint across three cycles. Test a known unreachable target and an explicitly obstructed target; confirm rejection. All target coordinates remain synthetic until the real blue markers are measured.

This simulator provides kinematics and timed joint motion, not validated contact dynamics, payload behavior, grip friction, or hardware controller fidelity. Earlier local PyBullet results remain separate evidence and do not substitute for the blocked native Viam planner tests.

## Primary sources

- [Viam Move mode](https://docs.viam.com/visualization/3d-scene/move-mode/): Preview move does not execute the plan; playback timing is approximate, and visual collision readouts have limited geometry/self-collision coverage.
- [Viam simulated arm implementation](https://github.com/viamrobotics/rdk/blob/main/components/arm/sim/sim.go): simulated joint motion, stop, configuration, and joint-limit checks. Current upstream source is supporting context, not proof of the exact deployed server revision.
- [Viam frame-system validation](https://github.com/viamrobotics/rdk/blob/main/robot/framesystem/framesystem.go): `NewFromServiceMustBeConnected` rejects unlinked parts before constructing the augmented frame system.
- [Viam xArm6 kinematics](https://github.com/viamrobotics/rdk/blob/main/components/arm/kinematics/xarm6.json): joint limits for the built-in model.

## Retry after repair

A fresh native preview on 2026-10-16 succeeded for `qa-sim-arm`, from (207, 0, 112) to (217, 0, 112) mm, returning two configurations. The previously unlinked camera frame no longer blocks this preview. Full A-to-B planner QA remains incomplete.

The user then requested a real-arm test. A preview for the real `arm` succeeded from approximately (275.720, -551.036, 222.008) to (275.720, -551.036, 232.008) mm, preserving orientation. Two configurations were returned; the endpoint visual collision readout reported nothing intersecting. No execution was issued at this checkpoint. On-site clearance and emergency-stop readiness were requested before physical execution. Screenshot: `artifacts/real-arm-upward-preview.png`.

## Approved physical upward test

After the user confirmed clearance, an empty gripper, and an on-site emergency-stop operator, executed the previewed 10 mm upward move on the real `arm`. Refreshed a stale pose indicator before planning; the live starting position was unchanged. The initial pointer click opened the overlapping AI-assistant panel instead of executing; confirmed unchanged live pose before the single corrected keyboard activation of Execute plan.

Execution showed progress and then returned to the live pose without a reported error. Readback: (275.721797, -551.039288, 231.692128) mm versus start (275.720232, -551.036279, 222.008301) mm and target Z 232.008301 mm. Measured upward displacement from reported poses: 9.683827 mm; target position error approximately 0.316 mm. This verifies one small physical motion by machine telemetry, not A-to-B grasp or comprehensive hardware QA. No return movement or gripper command was issued.

Evidence: `artifacts/real-arm-upward-result.json` and `artifacts/real-arm-upward-result.png`.
