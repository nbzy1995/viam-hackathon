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
`.env.viam.json` only after acquiring its shared `.arm-control.lock`. Console and
web control cannot run concurrently. Voice credentials stay in the server and
are excluded from the robot/interpreter subprocess environment. The server binds
only to loopback; no ElevenLabs hosted agent, agent ID, or public tunnel is used.

The UI passes natural-language tasks to the canonical controller. Three exact
preset commands in `quick-checks.json` provide repeatable checks without model
interpretation. They are also available as buttons, with automatic spoken results:

1. **Check robot** — read connection, calibration, stationary arm and gripper status.
2. **Prepare robot** — preview and return an empty arm to its checked home pose.
3. **Run motion check** — preview both legs, turn the empty arm 5 degrees, return,
   and verify both joint endpoints. Requires checked home and an empty gripper.

The motion check uses native motion planning, configured scene boundaries,
50 mm wall clearance, and 3 degrees/second arm speed. Failures request a stop;
success requires measured endpoint agreement within 0.1 degrees. Reports go to
`artifacts/diagnosis/fast-check-*.json`. These checks establish a basic motion
path; object grasping and placement still require separate verification.

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
