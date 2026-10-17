# Milestone 1 simulator rehearsal — 2026-10-16

Wall calibration and physical recovery are owned by the other session. This work
does not change machine configuration or command the physical arm or gripper.

## Repeat the native Viam rehearsal

From the project root:

```sh
uv run python native_sim_cycle.py
uv run python native_sim_cycle.py --cycles 3
uv run python native_sim_cycle.py --checks-only
```

Uses the existing credentials file and **only `qa-sim-arm`**. Its live Viam
configuration was verified as `arm/simulated`, model `xarm6`, speed 0.3 rad/s,
time simulation enabled. The script also checks its kinematic model against the
saved simulator model before commanding it. It offers no real-arm selector.
Do not run multiple copies or manually control the simulator during a run.

Sequence: home → above A → descend A → lift A → above B → lower B → withdraw B
→ home. Coordinates are synthetic millimetre flange targets; they are not the
physical markers. A is `(400, -130)`, B is `(400, 130)`, lowered flange height is
190 mm, travel height is 320 mm, home is `(350, 0, 380)` mm. Tool points downward.

This is an **arm-only rehearsal**: grasp and release are not sent to any gripper.
The direct arm API makes this independent of the shared wall configuration;
therefore this does **not** certify world-obstacle clearance. The eventual real
script must use taught physical poses and the verified motion-planning setup.

## Results

- Three consecutive native cycles passed: 24/24 endpoint checks, without resetting
  the simulated component between cycles. Maximum position error was 0.000191 mm
  (numerical model readback, not physical accuracy).
- Unreachable 10 m target rejected with `asked for a pose too far`; no joint change.
- A 20° simulated waist rotation was interrupted at about 2.06°. Two readbacks
  0.3 seconds apart held position and `is_moving` was false.
- Simulator subsequently returned to home, then was left stopped.
- Unit tests verify no retry or later stage after an API error, timeout, or
  incorrect endpoint; the complete sequence returns home.

Evidence: `artifacts/native-sim-cycle.json`, `artifacts/native-sim-checks.json`.
The script exits nonzero on failure and requests stop on this simulated arm. It
does not automatically retreat or release a load after a failed stage.

## Separate physics gate

`uv run pytest -q tests/test_simulation.py` uses the existing local PyBullet
simulation. It tests three contact-based transfers, a missing object, an obstructed
path, and loss of finger contact. Its synthetic cube, gripper, table, and dynamics
are separate from the native Viam model; their success is not physical-station QA.

Fresh result: **4 physics tests passed in 75.27 seconds**, including the three
consecutive transfer test. **4 sequence unit tests passed** separately.

## Remaining physical milestone

Once the other session verifies the walls and recovery path, teach and verify the
real A/B grasp/place poses, finish one manual transfer, then adapt the sequence to
the real arm and gripper and verify three physical cycles. No physical deployment
or automatic trigger is enabled by this simulator script.

## Official references

- [Viam static positions](https://docs.viam.com/tutorials/pick-and-place/static-positions/)
  supports teaching fixed poses before automating the cycle.
- [Viam Python arm API](https://python.viam.dev/autoapi/viam/components/arm/client/index.html)
  supplies move, pose readback, joint readback, moving state, and stop calls.
- [Deployed version's simulated-arm implementation](https://github.com/viamrobotics/rdk/blob/v1.12.0/components/arm/sim/sim.go)
  supplies simulated joint motion and arm-level pose planning, not object contact dynamics.
