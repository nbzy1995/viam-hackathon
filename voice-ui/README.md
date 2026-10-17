# Voice demo

Run from the main repository with the existing Codex login and robot calibration:

```sh
uv sync --extra voice-ui
npm --prefix voice-ui ci
npm --prefix voice-ui run build:chat
# Configure voice-ui/.env from example.env (local, ignored).
uv run --extra voice-ui --env-file voice-ui/.env python voice-ui/server.py
```

Open http://127.0.0.1:8088. Start live voice, allow microphone access, speak,
and pause. ElevenLabs Scribe Realtime commits the transcript after a detected
pause. The local harness processes it; ElevenLabs Flash streams the answer into
browser audio. Microphone capture pauses during playback to prevent feedback.
Stop robot remains available. This is turn-taking conversation; task execution
can take longer than speech transcription. Text input also works.

## Main harness integration

`robot_worker.py` imports this repository's `workshop_text.TextController`
directly. Its existing schema, camera observations, planner, safety checks,
verification, and `robot_workspace/history.json` remain authoritative. There is
no controller snapshot in this UI. Restart between Python harness changes.

Set `VOICE_ROBOT_ENABLED=1` for physical mode. The worker reads the repository's
`.env.viam.json` only after acquiring its shared `.arm-control.lock`.
For a separate worktree, set `VOICE_ROBOT_SOURCE` to the checkout that owns
the robot credentials and lock. Only credentials and lock come from that path;
code, calibration, and reports stay in this worktree. Use a different
`VOICE_UI_PORT` (this demo uses 8089; QA uses 8088). Console and
web control cannot run concurrently. Voice credentials stay in the server and
are excluded from the robot/interpreter subprocess environment. The server binds
only to loopback; no ElevenLabs hosted agent, agent ID, or public tunnel is used.

The [table demo](../docs/table-demo.md) starts with “What do you see on my table?”,
then “Bring this water bottle to me”, then “Take the water bottle back”. These
select three small skills on the same controller. Delivery uses the separately
measured blue tape marker and persists the actual pickup position for return.

The UI passes natural-language tasks to the canonical controller. The three
table-demo suggestions are plain text, never action buttons. Earlier fast checks
remain in `quick-checks.json` with `suggested=false` and are still callable by
voice or text:

1. **Check robot** — read connection, calibration, stationary arm and gripper status.
2. **Prepare robot** — preview and return an empty arm to its checked home pose.
3. **Run motion check** — preview both legs, turn the empty arm 5 degrees, return,
   and verify both joint endpoints. Requires checked home and an empty gripper.
4. **Move the carton to point B and then back to A** — run the existing
   `workshop_vision.run_cycle` carton
   A → B → A routine. If the carton starts at B, it first returns it to A.
   Re-detect and verify the carton after every transfer; finish at A with the
   arm home. Type or say **Run vision round trip** to invoke the same routine.

The existing AI interpreter recognizes the full carton round-trip intent,
including natural paraphrases and “cartoon” transcription errors, and selects
`decision=roundtrip`. The executor calls the established routine; the model
does not reconstruct its movement commands. Questions, negations, one-way
requests and different objects must not select the round trip. The CLI and UI share one implementation. Its
existing 45 mm station-placement tolerance, native path previews, 60 mm sampled
workspace clearance, grasp/retention checks and endpoint checks are retained.
A preview alone never reports completion. Start at the checked home pose with
an empty gripper and the upright workshop carton in the calibrated workspace.
The table and transfer route must be clear as in the original workshop setup.
Reports are saved as `artifacts/diagnosis/vision-cycle-*.json`.

The motion check uses native motion planning, configured scene boundaries,
50 mm wall clearance, and 3 degrees/second arm speed. Failures request a stop;
success requires measured endpoint agreement within 0.1 degrees. Reports go to
`artifacts/diagnosis/fast-check-*.json`. The five-degree check establishes basic
arm motion. The separate vision demo verifies carton placement at both stations.

Say **stop**, **stop the robot**, or **cancel**, or press **Stop robot** to cancel
this interface's active task. An acknowledgement is shown only after the robot
responds. This UI cannot stop another controller. Busy requests are rejected;
network failure or closing the browser does not guarantee stop delivery.

## Regression checks

```sh
uv run --extra voice-ui pytest tests voice-ui -q
npm --prefix voice-ui run build:chat
```

Automated robot tests use fake hardware. See `VERIFICATION.md` for measured live
evidence and remaining limits. The original supplied UI provenance is retained
in `SOURCE.json`.

## Live demo dashboard

The robot-enabled server includes a live wrist-camera feed with matching native
color-detection boxes, measured arm/gripper state, and the current task progress.
The three demo prompts and existing control harness remain available. See
[DASHBOARD.md](DASHBOARD.md) for the observer, freshness, and integration details.
