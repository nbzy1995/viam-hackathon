# Text-control evaluation, second iteration

**Coverage correction:** the 42/42 result below is language-only. Two subsequent
live requests exposed untested observation-state and motion-waypoint failures.
See [the investigation](text-failure-investigation.md). These results do not pass
the end-to-end acceptance gate now required before latency optimization.

This evaluates the existing three actions: translate, place on an observed support,
and restore a verified position. It does not add a parser, a model service, or a
robot transport. No evaluation in this iteration sends robot commands.

## Protocol fixed before inspecting results

1. Development: 22 cases spanning camera direction changes, units and longer
   distances, relative geometry, stacking roles, ordered commands, verified history,
   missing observations/depth, ambiguous references, negation, status, and new labels.
   One case reproduces the reported stacking failure; it is a regression, not held out.
2. Correctness before speed: grade the complete structured action, including source
   AND support IDs, order, displacement (0.2 mm tolerance), schema, and whether all
   references can resolve. Negative-control unit tests inject wrong supports,
   reversed commands, nonfinite numbers, and missing history into the grader.
   Prose facts receive separate manual review; a pending rubric is never a full pass.
3. Latency: four fixed recorded-image cases, two trials each, alternating baseline/
   candidate order by trial (AB then BA). Both use the same binary/default model,
   low reasoning, images, request, history, schema, sandbox, and tool restrictions.
   Change one candidate setting at a time. No other interpreter/evaluation runs
   overlap this measurement. Report paired changes and tokens, not an unrelated
   earlier request's elapsed time. Cached tokens are retained as a confounder.
4. Adoption gate: preserve structured and factual correctness on the paired cases
   and development set, and demonstrate lower paired median inference time.
   Then run the separately authored 12-case holdout once. No holdout prompt or oracle
   is read for tuning. Any examined failure becomes a known regression; repairs
   would require new cases before claiming additional held-out evidence.

The final holdout was authored without reading production instructions, existing
results, or implementation. Its author froze a SHA-256 before inference. Both
sets use explicit expected behavior rather than copying model outputs into labels.
Reports preserve input/prompt/schema/interpreter hashes and raw results. Unique
run labels prevent accidental replacement of earlier results. The model receives
only the current request, scene, and history, never case IDs or expected outputs.

The checks are intentionally distinct: language proposal correctness, native
motion-preview feasibility, and visually verified physical execution. The latter
two retain their separate existing reports. These synthetic and recorded-image
language checks do not establish detector accuracy, grasp success, stack stability,
or current workspace state. Paired cases are correlated; sample sizes are too small
for a deployment success-rate estimate or latency SLA.

## Reproduce

```sh
uv run pytest -q
uv run python evaluate_text.py --suite config/text-development-v2.json
uv run python benchmark_text.py --suite config/text-latency-v2.json --run-id my-paired-run \
  --baseline-instructions artifacts/diagnosis/text-instructions-v2-baseline.md \
  --candidate-instructions artifacts/diagnosis/text-instructions-v2-concise.md
uv run python evaluate_text.py --suite config/text-generalization-holdout-v2.json
```

After its first run, a holdout replay is a regression check, not fresh generalization
evidence. Every command above is offline with respect to the robot; model calls
still use the installed Codex login.

This applies the official guidance to use representative task-specific criteria,
separate tuning from final tests, retain failures, and test meaningful dimensions
instead of accumulating similar prompts:
[OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
[structured evaluation design](https://developers.openai.com/cookbook/examples/evaluation/building_resilient_prompts_using_an_evaluation_flywheel).

## Results, October 16, 2026

The wider development set passed **22/22** before changing the prompt and **22/22**
after the concise-output candidate. All seven factual rubrics passed manual review
in each run. The final, previously unopened holdout passed **12/12** structured
checks on its first attempt: seven actionable requests and five cases requiring
observation, rejection, or factual status. There were no unexpected executions or
unnecessary nonexecution decisions in this holdout. The original eight regressions
also passed, including the reported carton typo. That is **42/42 final command
checks**, with the development and regression scores kept separate from holdout.

All five explicit holdout prose rubrics passed independent review. Three of the
12 responses have wording caveats: two unnecessarily mention the camera view for
object-relative geometry, and one describes verification that would occur later
in the planned sequence. Their commands and numerical grounding are correct;
these are not claims that every explanation is perfect. No prompt edits followed
the holdout. Automatic score files retain pending rubric markers; the separate
review files preserve the completed manual verdicts.

The grader was repaired before the first run: it previously ignored `target_id`,
so stacking onto the wrong support could pass. It now checks every executable
argument. A review also caught a manifest filename that could overwrite an earlier
run; manifests now have the same unique run label as their results. No holdout
failure was hidden, retried, or used to edit the production instructions.

| Paired experiment | Baseline median | Candidate median | Median paired change | Decision |
|---|---:|---:|---:|---|
| Omit automatic skill catalog | 5.095 s | 5.027 s | +0.3045 s | Rejected: only 2/8 matched pairs improved |
| Shorter message and grounding | 5.483 s | 4.7695 s | −0.457 s | Retained after correctness checks |

Each row uses four recorded-image requests, two trials each, with AB/BA ordering.
Both variants passed all eight structured responses in each experiment. Independent
factual review passed all 16 responses in the concise experiment. The retained
change requests brief explanations without dropping requested status facts; it
changes no action capability, coordinate interpretation, or collision check.

**Latency evidence is limited.** The concise candidate improved only 4/8 individual
pairs. Its median output decreased from 127 to 116 tokens, while median cached input
also differed (12,800 versus 15,616). The observed median improvement is about 13%,
but this small, cache-affected sample does not establish a repeatable speedup or
prove that brevity caused all of the difference. It measures complete inference
calls, including CLI startup, and excludes camera capture, planning, and arm travel.
The skill-removal experiment reduced median input from 19,219 to 13,662 tokens
without improving paired latency; that option is kept only for reproducible testing.

The same installed CLI, 0.144.5, resolved its default to `gpt-5.6-sol`, with low
reasoning, according to its cached model catalog and version-pinned selection code.
A model ID was not independently reported for every response. No model, transport,
or persistent inference service was replaced. The Viam SDK connection remains
persistent, and the editable robot instructions still reload on each request.

Evidence:

- [Baseline development](../artifacts/diagnosis/text-development-v2-baseline.json)
- [Concise development](../artifacts/diagnosis/text-development-v2-concise-final.json)
- [First-pass holdout](../artifacts/diagnosis/text-generalization-holdout-v2-first-pass.json)
- [Independent holdout prose review](../artifacts/diagnosis/text-generalization-holdout-v2-first-pass-prose-review.json)
- [Original regressions](../artifacts/diagnosis/text-evaluation-concise-regression.json)
- [Rejected skill-removal experiment](../artifacts/diagnosis/text-latency-paired-v2.json)
- [Concise paired benchmark](../artifacts/diagnosis/text-latency-concise-v2.json)
- [Independent benchmark factual review](../artifacts/diagnosis/text-latency-concise-v2-prose-review.json)

The local Python suite passed **23 tests**; compilation checks and `git diff --check`
also passed. No physical grasping, stacking, or cycle-speed result is claimed by this
iteration. Previously recorded motion previews and physical carton tests remain
separate evidence.

Cleanup removed duplicate stdout logs and all task-owned evaluation workspaces.
No evaluation or benchmark process remains. Compact JSON evidence is retained;
the existing physical console was left running. Disk space remained 22 GiB free.
