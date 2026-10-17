# Simulation QA — 2026-10-16

## Result

Passed the local simulation gate. Physical execution is not validated.

- `python -m pytest -q`: 4 tests passed. Includes three consecutive contact-based transfers, missing object, obstructed path, and lost-contact detection.
- `python simulation.py --cycles 3 --render`: exit 0, all three trials successful.
- Each trial completed all nine stages, lifted the block by at least 128 mm, placed its full bounding box within B, established stationary table support, released all gripper contact, and returned the flange within 5 mm of home.
- No robot-table or robot-obstacle penetration exceeding 0.5 mm was detected on moving links during the cycles. This check does not claim exhaustive self-collision validation.
- Inspected rendered descend, transport and final home frames: block starts at A, is carried above B, and ends resting at B with the gripper withdrawn.

## Evidence

- `artifacts/simulation-report.json`: per-trial measurements and stage completion.
- `artifacts/simulation.gif`: first cycle only, labelled simulation.
- `artifacts/stage-*.png`: intermediate and final states from that cycle.
- `tests/test_simulation.py`: acceptance and failure-case assertions.

Trials reset joint and object initial conditions between cycles, with no resets or object attachment during a cycle. The repeatability result applies to those fixed initial conditions. The missing-object and obstruction tests stop without retrying; the lost-contact test injects transport without an object held and verifies rejection.

## Remaining physical work

Recover the servo motor 2 fault, verify safety settings and station geometry, locate the actual blue marks, teach A/B poses, and run supervised physical trials. The simulation uses synthetic positions and assumed friction; it supplies no camera calibration or real target coordinates.
