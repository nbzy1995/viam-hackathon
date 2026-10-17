# Milestone 1 architecture

One Python program runs a fixed xArm6 pick-and-place cycle in a local PyBullet physics world. A small QA runner executes three trials and writes measured results plus a rendered demonstration. No server, UI framework, learning system, or physical robot connection is needed for this gate.

## Decisions

- **Physics:** PyBullet with its bundled xArm6-with-gripper URDF, authored by UFACTORY. This includes the actual six-joint kinematic chain and gripper collision shapes. Prefer this existing model over a hand-built arm or converting an unrelated seven-joint model. Model and object parameters remain simulation assumptions, not station calibration.
- **Control:** fixed Cartesian waypoints converted to joint targets; position motors act through physics at bounded speed. Grasping uses contact/friction, never teleportation or a constraint attaching the object to the gripper.
- **Verification:** inspect object pose, support contacts, gripper contacts, unintended robot contacts, and return pose. A moving animation alone cannot pass. Negative cases must fail.
- **Scope:** simulation A/B are explicitly synthetic fixtures. The real blue markers, servo recovery, and on-site validation remain separate open requirements. No simulator result authorizes physical execution.

## Sources

- [Viam static-position sequence](https://docs.viam.com/tutorials/pick-and-place/static-positions/)
- [Bullet's UFACTORY xArm6 model](https://github.com/bulletphysics/bullet3/blob/master/examples/pybullet/gym/pybullet_data/xarm/xarm6_with_gripper.urdf)
- [UFACTORY simulation project](https://github.com/xArm-Developer/uf-gym)

## Simulation scenarios and test map

| Scenario | Given / When / Then | Test | Status |
|---|---|---|---|
| Transfer | Given a supported block at A, when one cycle runs, then it is lifted, carried, placed wholly inside B, released and resting on table, and the arm returns home | tests/test_simulation.py | passed |
| Repeatability | Given manual object resets between trials, when three consecutive cycles run, then each transfer passes with no intervention during the cycle | tests/test_simulation.py | passed |
| No object | Given no object at A, when grasp is attempted, then the cycle fails before transport and does not retry | tests/test_simulation.py | passed |
| Obstructed motion | Given an obstruction on the programmed path, when executing, then the run fails and does not count as successful | tests/test_simulation.py | passed |

Physical emergency-stop availability, actual friction/payload, actual A/B, camera extrinsics, and real controller fault recovery are not established by these tests.

## Gripper coupling diagnosis

The bundled URDF declares five joints mimicking `drive_joint`. Sending the same motor target independently did not enforce that coupling under contact load: finger angles diverged and the block slipped. The implementation now uses one drive motor and five gear constraints with ratio -1 (equal joint angles). Initial coarse solves still diverged; 1,000 solver iterations with four substeps produced a measured successful contact-based transfer. The approach flange height is 190 mm, chosen from finger/linkage contact measurements. Three-cycle acceptance and rendered verification passed; see `artifacts/simulation-report.json` and `docs/simulation-qa.md`.

Reference: [Bullet mimic-joint constraint example](https://github.com/bulletphysics/bullet3/blob/master/examples/pybullet/examples/mimicJointConstraint.py).
