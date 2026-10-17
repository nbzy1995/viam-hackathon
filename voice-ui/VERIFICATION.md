# Main-worktree integration — 2026-10-17

The current demo runs from `/Users/Yang/Documents/ChatGPT/viam-hackathon`,
branch `milestone-1-simulation`, on http://127.0.0.1:8088.
Voice files were imported additively from `codex/ringside-ui-integration`,
including its pending quick-check changes. This was a file integration, not a
Git merge of the dirty worktrees. Existing main harness sources and uncommitted
work were preserved byte-for-byte. Root changes are the voice dependency extra
and its lock resolution; the UI is under `voice-ui/`.

The production worker imports the main `workshop_text.py` directly. No copied
`robot-runtime` is present. Main calibration, scene, instructions and verified
history are used by the canonical controller. An automated subprocess import
check verifies this binding.

- `uv run --extra voice-ui pytest tests voice-ui -q`: **68 passed**.
  One upstream Starlette/httpx deprecation warning.
- Browser bundle built successfully; npm audit reported zero vulnerabilities.
  Node 22.17 emitted a dependency engine warning (machina requests >=22.22).
- Web UI **Check robot**: live connection, stationary arm, matching calibration,
  empty gripper and checked home confirmed.
- Web UI **Run motion check**: both native plans checked before movement;
  real arm turned 5 degrees and returned home. Both endpoints verified;
  maximum joint error **0.001804169 degrees**. Result appeared in the UI and
  the browser entered **Speaking**, then returned to **Ready**.
- Evidence: `artifacts/diagnosis/fast-check-20261017T151426152046Z.json`.
- A web text request asking what the camera sees, with no arm movement, used
  the main Codex interpreter and returned a live scene description. Report: `artifacts/diagnosis/text-task-20261017T151457260694Z.json`.
- New preset tests cover two-leg verification and stop on preparation/motion
  failure. Existing bridge tests cover shared-lock exclusion and cancellation.
- Server secret remains local, mode 0600 and Git-ignored. Robot subprocess
  environment excludes ElevenLabs credentials.

This establishes web button → live robot → measured result → streamed spoken
reply. Live microphone/Scribe transport was verified earlier below; a spoken
command driving real motion in one uninterrupted browser run is not yet verified.
Object grasp/placement through this UI remains unverified; prior carton routes
were blocked before object execution. Do not describe these checks as a verified
arbitrary physical-task agent.

The active loopback server and build dependencies are retained for the demo.
The isolated worktree remains as a recoverable integration source; its server
has been stopped. Historical evidence below describes earlier versions only.

---

# Integration verification — 2026-10-16

Base: `04aacc9`, isolated branch `codex/ringside-ui-integration`.

- Baseline: `uv run pytest -q` — 10 passed.
- Integration: `uv run --extra voice-ui pytest tests qa-console/test_persistent_sim.py voice-ui/test_server.py -q` — 21 passed. One upstream Starlette/httpx deprecation warning.
- Browser bundle: `npm run build:chat` — passed; generated bundle approximately 4.8 KiB. `npm ci` reported zero vulnerabilities.
- Real Codex adapter: minimal prompt returned `Local harness connected.`
- Browser at `http://127.0.0.1:8088`: expected initial state, microphone disabled without speech credentials, text turn returned `UI harness connected.`
- User activity appeared after the browser test; further UI mutations stopped and server was retained for use.
- Live ElevenLabs transcription/synthesis and physical microphone capture were not exercised. HTTP contracts were tested with a mock provider.
- No robot motion, robot credential copying, main checkout edits, remote pushes, or merges were performed.

Retained runtime: the loopback server on port 8088 and its worktree environment.
The worktree is an active deliverable, not disposable build output. Its Python
runtime is approximately 99 MiB and Node build dependencies approximately 10 MiB.
Available disk space after verification: approximately 22 GiB.


## Realtime integration, 2026-10-17

- Direct live ElevenLabs test: synthesized “Move the carton to the left.” as PCM,
  sent it over Scribe Realtime with VAD, and received that committed transcript.
- Robot bridge refused the request while the main console held its shared lock.
  No robot connection or motion was attempted. The refusal was synthesized as
  286,812 bytes of streamed audio across 221 received chunks.
- Background browser test server used a fake executor. Typed requests, Stop,
  live microphone transcripts, automatic submission, and streamed Web Audio
  playback were observed. The final playback check reached Speaking after
  successfully muting the capture track. Capture was disconnected afterward.
- `uv run --extra voice-ui pytest tests qa-console/test_persistent_sim.py
  voice-ui/test_server.py voice-ui/test_robot_bridge.py -q`: 30 passed.
  One Starlette/httpx deprecation warning remains.
- `npm --prefix voice-ui run build:chat`: passed.
- Tests cover execution-result narration, shared-lock refusal before connection,
  stop preemption, buffered startup stop, secret environment exclusion, busy
  stop availability, single-use speech tokens, PCM streaming, and provider error
  status before response headers.
- Real server: 127.0.0.1:8088, robot mode enabled, microphone initially off.
- Not verified: real robot motion, hardware stop acknowledgement, or successful
  camera/placement execution through this UI. Those require a supervised robot
  command. The existing validated controller remains responsible for motion.
- Source checkout was read only. Robot snapshot provenance is recorded in
  robot-runtime/SOURCE.json. Local calibration/output assets and .env are ignored.
