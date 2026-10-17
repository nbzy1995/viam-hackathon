# Milestone 1 Simulation Implementation Plan

> Execution workflow: engineering:executing-plans, in this session; routine decisions are authorized by the user.

**Goal:** Implement and verify a single-object A-to-B physics simulation, preserving physical deployment as a separate gate.

**Architecture:** Fixed sequence and existing xArm6/gripper URDF. Contact-based grasp, measured QA, no object attachment or teleportation during a trial.

**Tech Stack:** Python, uv, PyBullet, NumPy, Pillow, pytest.

1. Write acceptance tests in `tests/test_simulation.py`, including failed-grasp and obstructed-path cases. Run them and preserve expected failure evidence.
2. Implement `simulation.py` using the bundled model, synthetic marked A/B, and a small block. Initialize once, use physical motor control during each trial, and inspect all contacts.
3. Run tests, diagnose actual failures, and tune the controller/scene without weakening acceptance. Generate a compact report and animation in `artifacts/`.
4. Inspect rendered start/grasp/transfer/place/end states and compare measured results to every scenario. Document limitations and commands in README.
5. Check cleanup, disk use, and git diff. Do not claim the real robot milestone complete without its separate evidence.

The repository has no commits, so work is on the new `milestone-1-simulation` branch in the existing task-owned workspace; there is no committed base for a separate worktree.
