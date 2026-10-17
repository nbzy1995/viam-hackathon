## Integrated live dashboard — 2026-10-17

- Reused the separate `f0d0` worktree's dashboard layout and voice controls in `d3a9` on port 8089.
- Real wrist-camera JPEGs and matching native color-detection boxes verified in the browser.
- Six live samples: camera and telemetry fresh throughout; measured 2.4 frame updates/second.
- Measured arm Home and gripper empty; current harness activity displayed.
- Web UI “Check robot” completed while the dashboard stayed live. No physical motion requested.
- `uv run --extra voice-ui pytest tests voice-ui qa-console/test_persistent_sim.py -q`: 101 passed.
- Final shipping check after the five operation-compatibility cases: full suite 106 passed; frontend build passed.
- `npm --prefix voice-ui run build:chat` and `git diff --check`: passed.
- Other servers (8088 and 8090) were not restarted or edited.
- Camera frames are bounded in memory; temporary camera probe removed.
- Evidence: `docs/checkpoints/live-dashboard-result.json`; implementation details: `DASHBOARD.md`.

# Conversational table demo — 2026-10-17

The physical UI scan, delivery to the new blue tape marker, and return to the
saved pickup coordinates all passed. Scan: three distinct images, home return,
and grounded description in 31.965 seconds. Delivery: 10.827 mm placement error,
100.296 seconds. Return: 3.228 mm error from the saved origin, 74.249 seconds.
Both transfers completed all eight stages and verified the empty arm at home.

The first camera rotation triggered the controller self-collision check; a more
extended high pose passed. The original outward pickup location was unreachable,
so the user repositioned the carton. A subsequent descent-branch failure was
resolved by reusing the main harness's `approach_from_grasp` helper. Failures were
retained in the local reports; no failed attempt was recorded as completion.

Restarting only the demo server reloaded valid speech credentials after a stale
server returned HTTP 401. Live microphone speech was transcribed; the interpreter
asked for clarification for an ambiguous utterance without moving, and its reply
played automatically. Delivery and return confirmations played through Read reply.
The three physical commands were typed, so this does not claim one uninterrupted
three-command spoken trial. The microphone is left off for the user's demo.

- 93 offline tests passed; 5 known real-model demo intent cases passed.
- Person recognition is not implemented; delivery uses the predefined marker.
- [Demo instructions](../docs/table-demo.md).
- [Compact measured result](../docs/checkpoints/table-demo-result.json).

---

# Voice intent and suggested prompts — 2026-10-17

Quick-check buttons were replaced with non-interactive suggested prompt text.
The existing AI interpreter now selects `decision=roundtrip` for an explicit
carton B-then-A demo request. `TextController` dispatches that validated decision
to the existing `run_cycle`, respecting physical versus preview mode. The exact
round-trip shortcut in the voice worker was removed; paraphrases use the same
single interpreter as other natural-language requests. No generated translation
sequence replaces the fixed routine. Transfer speed remains 8 degrees/second.

- 82 offline tests passed; browser bundle built.
- 10 real-model intent regressions passed, including the user's exact sentence
  “move the cartoon to point B and then to A back”, paraphrases, spoken letter
  spellings, negation, explanation, wrong object, one-way and mixed actions.
- An initial one-way case incorrectly requested observation; the instructions
  now distinguish fixed routine destinations from missing perceptual objects.
  The original failed result is retained alongside the successful rerun.
- Reproduce with `uv run python evaluate_text.py --suite config/text-roundtrip-regressions.json`.
- The active physical run was allowed to finish before refreshing the browser.
  The refreshed UI shows plain suggestions and retains Start live voice and Stop
  robot controls. No robot motion was commanded by the language regression tests.
- Exact report: `artifacts/diagnosis/text-roundtrip-regressions-voice-demo-routing-fixed.json`.
  This validates text intent recognition plus executor dispatch tests; it does
  not claim a new microphone-to-motion hardware trial.

---

# Isolated vision-demo product — 2026-10-17

The new worktree serves http://127.0.0.1:8089. QA's server at port 8088 was
left running. `VOICE_ROBOT_SOURCE` selects its existing shared credentials/lock;
this worktree supplies code and calibration and owns its reports.

- Added **Vision round trip**, invoking the same `workshop_vision.run_cycle`
  as the CLI, with no model-generated recreation of the sequence.
- **80 tests passed**; browser bundle built. Existing Starlette/httpx deprecation
  and npm's Node engine warning remain.
- Live readiness: stationary, calibrated, empty gripper, at home.
- First UI attempt correctly refused while QA held the shared robot lock.
- After release, the UI completed all **16 physical stages of A → B → A**.
  Fresh vision measured **10.714 mm** error at B and **2.844 mm** at A, both
  within the unchanged **45 mm** station tolerance. The arm returned home.
- UI displayed verified success; **Read reply** entered **Speaking** with the
  real ElevenLabs stream. The preset also requests automatic spoken playback.
- Full local report: `artifacts/diagnosis/vision-cycle-20261017T152954715695Z.json`.
  Compact evidence: `docs/checkpoints/vision-demo-result.json`.
- Microphone-triggered round-trip execution was not exercised in this run.
  B-start recovery is covered by tests and previous CLI evidence, not this run.

See `docs/vision-demo.md` for the fixed demo and its setup. Earlier sections
below describe previous versions and their verification limits.

---

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
