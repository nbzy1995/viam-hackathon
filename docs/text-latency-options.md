# Smallest text-interpreter latency experiment

Checked October 16, 2026. The main session tested the skills-only candidate in
eight matched pairs. Both variants remained correct, but the median paired
candidate-minus-baseline time was **+0.3045 seconds**, so it was **not adopted**.
Fewer input tokens alone did not establish a latency benefit. The original
one-setting experiment was:

```python
'-c', 'skills.include_instructions=false',
```

This suppresses the automatically injected skill catalog/instruction block. It
does not replace the model's base instructions, change approval policy, weaken
the sandbox, or remove the robot `INSTRUCTIONS.md` that this program explicitly
passes on stdin. Keep the same CLI binary, model, reasoning level, images, scene,
history, output schema, disabled shell/web settings, and credential isolation.

## Evidence and compatibility

- The exact installed npm CLI release, **0.144.5**, defines
  `SkillsConfig.include_instructions` in its official source. Its skill extension
  returns before constructing the automatic block when that setting is false.
  [Pinned configuration source](https://github.com/openai/codex/blob/rust-v0.144.5/codex-rs/config/src/skills_config.rs#L32),
  [pinned extension source](https://github.com/openai/codex/blob/rust-v0.144.5/codex-rs/ext/skills/src/extension.rs#L113).
- A local, non-inference config check succeeded:
  `codex -c 'skills.include_instructions=false' -c 'skills.bundled.enabled=false' features list`.
  No robot/MCP calls or model inference were performed for this investigation.
- `--ephemeral` controls session persistence; its local help does not promise to
  remove contextual instructions. `--ignore-user-config` skips user config but
  is not a switch for the automatically discovered skill catalog.
- The interpreter already supplies its robot instructions directly, uses a
  small JSON schema, and sets low reasoning. Those files measured about 4.3 KB
  and 0.75 KB during inspection; the reported large unrelated context is a more
  promising first target than rewriting this prompt or adding a service.

## Limits and next measurement

This is a context-size optimization hypothesis, not a measured speedup. The
setting suppresses automatic catalog injection; it is not a security boundary
that makes every skill inaccessible. Keep the existing tool restrictions.

Compare baseline and candidate using the same frozen scene and images, alternate
their order over a few identical cases, and report elapsed inference time plus
input/cached/output tokens where available. Preserve interpretation accuracy,
especially numeric units, relational targets, negation, undo/history, missing
objects, and requests needing another observation. Do not mix a CLI/model update
into this comparison.

`skills.bundled.enabled=false` is optional and narrower: it disables bundled
system skills, not the user's large catalog. It is not needed to establish the
effect of `include_instructions=false`.

The official config also has `project_doc_max_bytes`, controlling bytes loaded
from `AGENTS.md`. Do **not** set it to zero in the first experiment: that could
remove useful operating constraints as well as unrelated prose. If skills-only
optimization is insufficient, inspect the remaining context and retain all
applicable constraints explicitly before trimming it.
[Official configuration reference](https://developers.openai.com/codex/config-reference).

No production code, global configuration, authentication, model selection,
approval controls, or robot state was changed. Only this recommendation note
was added; the main session owns implementation and paired measurements.

## Default model metadata for the measured CLI

The installed shell CLI is **0.144.5**, at
`/Users/Yang/.nvm/versions/node/v22.17.0/bin/codex`. Its current default resolves
to **`gpt-5.6-sol`** when no model override is supplied. This conclusion uses
local catalog metadata and the exact release's selection code, not a new
inference request:

- `codex debug models --bundled` reads only the shipped catalog. Its first
  visible model by priority is `gpt-5.6-sol`.
- The locally present `models_cache.json` was produced for client **0.144.5**.
  The snapshot inspected at `2026-10-16T22:24:08.180520Z` lists visible models
  `gpt-5.6-sol` (priority 5), `gpt-5.6-terra` (8), and `gpt-5.6-luna` (9).
- The version-pinned source sorts by priority and marks the first picker-visible
  model as default. A lower-priority-number hidden entry therefore does not
  become the default.
  [Catalog ordering](https://github.com/openai/codex/blob/rust-v0.144.5/codex-rs/models-manager/src/manager.rs#L122),
  [default selection](https://github.com/openai/codex/blob/rust-v0.144.5/codex-rs/protocol/src/openai_models.rs#L646).

The interpreter's low reasoning override remains in effect. The cache lists
text and image input and low reasoning support for all three visible models.
`gpt-5.6-luna` is described by the shipped catalog as a fast, affordable model,
and by the current cache as an older fast and efficient model. That establishes
a catalog-supported future candidate on this CLI/auth route, not measured
latency, accuracy, or an inference verification. No model switch is proposed
for the current concise-output experiment.

Existing metrics say only `CLI default`: they did not record a model identifier
from every response. Label historical model attribution as resolved local
metadata, rather than claiming a per-response receipt. For later reproducible
runs, pass `--model gpt-5.6-sol` explicitly and record the CLI version and actual
model argument; this preserves the presently resolved default and prevents
catalog changes from silently changing future comparisons.

This inspection did not refresh the catalog, read credential content, perform
inference, or call a robot/MCP endpoint. No runtime or global settings changed.
