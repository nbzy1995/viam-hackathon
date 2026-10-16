# Ringside reuse for the robot voice interface

Date: 2026-10-16

## Source and retrieval

The user confirmed the intended source is **Ringside, the AI × Finance hackathon
project**. The team's [hackathon announcement](https://www.linkedin.com/posts/tracy-huang22_our-team-won-1st-place-out-of-30-teams-at-activity-7506113553599315968-I5fn)
links through `https://lnkd.in/eS4-Q2YK` to
[JoeyYu23/ringside](https://github.com/JoeyYu23/ringside).

Retrieved a shallow checkout of its public `main` branch into
`references/ringside/`, at commit
`ddbecfad47d194b5fc163dde65d3d9325a56ba12`.
The source is included as a pinned Git submodule, preserving its upstream
history and attribution. No upstream code was changed or executed.

Reproduce the reference checkout from the project root:

```sh
git submodule update --init --recursive references/ringside
```

This is an integration addendum to [the published A→B→A checkpoint](checkpoints/phase-4-roundtrip.md).
Retrieval and source inspection are complete. Robot UI implementation and
integration testing have not started.

## What the retrieved code actually provides

The inspected revision implements an insurance-sales coaching interface with
human, scripted, and AI-prospect modes. Although the event announcement mentions
Prism and ElevenLabs, this revision uses local MLX Whisper and Gemini Live;
we should plan from the code rather than assume the earlier event stack remains.

| Source in the pinned checkout | Verified capability | Robot adaptation proposed |
| --- | --- | --- |
| `app/static/call.html` | Microphone test and selector, live transcript, stage display, prominent cue, session end button | One robot task page with microphone, transcript, execution stage, and explicit controls |
| `app/static/coach.js`, `coach.css` | Shared browser audio/UI helpers and styling | Reuse the audio and visual foundation with robot-specific labels |
| `app/server.py` | FastAPI sessions; `/ws/seat/{call_id}/{seat}` for seat communication; `/ws/events/{call_id}` for event subscribers | One robot job controller with streamed status |
| `app/stt.py` | `Segmenter`, `LocalWhisper`, `SeatSTT` for speech segmentation and transcription | Spoken requests become text before command validation |
| `app/prospect.py` | Gemini Live audio/transcripts; limited `transfer` and `end_call` tools | Adapt to robot status dialogue and a small robot command vocabulary; existing tools are not robot controls |
| `app/coach/` | Rules/state-machine classification and curated coaching cues | Reuse the principle of bounded commands, not insurance rules |
| `tests/test_engine.py`, `tests/test_memory.py` | Existing deterministic coaching and memory tests | Reference for offline testing; these do not test robot integration |

The upstream README reports latency measurements. They have not been reproduced
here and must not be presented as robot command latency.

## Minimal proposed approach

Keep the existing Viam execution sequence as the motion authority. The UI and
voice layer should request a known task, rather than invent trajectories.

```text
Browser button or spoken request
    → validated command: status / preview / round_trip / stop
    → single robot job controller
    → checked Viam workshop sequence
    → actual progress/result events
    → UI status and spoken response
```

For the first interface milestone:

- One page: microphone toggle, transcript, simulated/physical target indicator,
  current stage, Preview, Run A→B→A, and Stop controls.
- Voice and buttons call the same operation. Start with a fixed phrase such as
  “move the carton from A to B and back”; ambiguous requests do not execute.
- Wrap the checked workshop sequence first. Retain its configuration checks,
  previews, failure behavior, and process lock; avoid rewriting its motion logic
  or adding a persistent SDK connection until it provides a measured benefit.
- Allow only one job at a time. Reject additional requests as busy rather than
  queueing unexpected later moves. Browser reconnects must not repeat execution.
- Stop must reach the robot stop API. Killing a Python process is not evidence
  that the arm stopped. The UI control does not replace the hardware emergency stop.
- Spoken acknowledgements distinguish “started” from “completed.” Announce
  success only after the executor returns success, and display the actual error
  on failure. Do not let model-generated narration override executor results.

These are proposed implementation choices, not a claim that robot control is
already available through Ringside.

## Validation and scope

Next, implement a fake executor to test recognized requests, busy rejection,
reconnect behavior, success/failure reporting, and stop handling without hardware.
Then validate against the intended simulator in isolation before physical tests.
No existing sales-coach test establishes safe robot motion.

The reference clone is small and has no installed dependencies or downloaded
speech models. No server was started, provider API called, or robot moved.
No build, microphone, latency, or end-to-end test was run in this inspection.

The repository has no detected LICENSE file and GitHub reports no license.
Preserve attribution and establish reuse rights before publishing adapted source.
For now, this project records provenance and keeps the upstream checkout separate.
The unrelated receptionist and Android coach candidates were not imported.
