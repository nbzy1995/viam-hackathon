# Text-control generalization check

This is the historical audit from before the general stacking adapter. The
current protocol and new results are in [text evaluation v2](text-evaluation-v2.md).

October 16, 2026. The earlier 8/8 result was a **known development regression
suite**, not evidence of generalization. The model had been given instructions
written with those requests in mind.

## Changes and first-pass evidence

Code inspection found no keyword command parser, evaluation imports, expected
answer lookup, or case IDs in the interpreter. However, the instructions named
the exact known typo “cartoon.” That example was replaced with a general rule:
resolve an obvious misspelling only when scene context identifies a unique object.
The original typo still passed a separate known regression afterward.

An independent reviewer then supplied 16 cases without reading the production
instructions, existing tests, or previous results. The suite and instructions
were frozen and hashed before inference. Each model call received only the
request, scene, and history; oracles and case IDs remained outside its input.
Each case ran once. There were no retries or prompt changes during the run.

**16/16 command-selection checks passed.** Coverage included unfamiliar object
names and opaque IDs, rotated camera directions, different target positions,
unit conversion, negation, three-command ordering, ambiguity, missing evidence,
and verified versus failed or absent history. Identical wording required
opposite answers in paired camera-direction and target-position cases.
Commands were graded by decision, object ID, action, order, and displacement
within 0.2 mm; explanatory prose was not scored automatically.

The numeric score missed one weakness: H15 said “The robot is available” based
only on camera availability. Manual review marked that assertion unsupported.
The original first-pass result, including that response, is preserved:

- [First-pass results](../artifacts/diagnosis/text-heldout-first-pass.json)
- [Frozen inputs and oracles](../artifacts/diagnosis/text-heldout-first-pass-manifest.json)
- [Prompt snapshots and audit](../artifacts/diagnosis/text-overfit-audit.json)

## General correction and fresh validation

The instructions now require status claims to follow supplied facts. Camera
access does not establish readiness, empty history does not establish an idle
arm, and earlier verified movement does not establish the current pose or
contents of the gripper. Missing status evidence must be identified as unknown.

H15 was rerun as a **known regression**, not a held-out success. It correctly
reported the missing facts as unknown. The independent reviewer supplied four
new status cases, frozen before inference. These mixed explicit current facts,
missing facts, and historical records, so blanket “unknown” answers would fail.
**4/4 decisions and 4/4 manual factual rubrics passed**, one attempt each.

- [Fresh status cases](../config/text-status-heldout.json)
- [Results and manual factual review](../artifacts/diagnosis/text-status-heldout.json)
- [Known status regression](../artifacts/diagnosis/text-status-regression.json)

## Meaning and limits

This provides evidence that interpretation follows supplied geometry and state
instead of memorizing the original eight answers. It does not prove general
robotic competence. The sample is small and hand-designed, uses synthetic scene
data without images, and does not validate camera perception, collision planning,
grasping, or unseen hardware tasks. Only the carton grasp has physical validation.

At the time of this audit, the controller imposed a 5–50 mm action limit and a
carton-only execution restriction. Both were subsequently removed. Calibrated
wrist-view directions and the 20 mm “slightly” default remain declared behavior.

Replaying these now-known cases is useful regression testing. It is no longer an
unseen evaluation. Future behavior changes should use a new frozen set before
claiming new generalization evidence; keep first-pass failures and distinguish
command accuracy from the truth of status explanations.

```sh
uv run python evaluate_text.py --heldout
uv run python evaluate_text.py --suite config/text-status-heldout.json
```

These commands use live model calls and do not connect to or move the robot.
