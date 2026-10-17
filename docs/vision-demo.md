# Vision round-trip demo

The product shows plain suggested prompts, not action buttons. Say
**Move the carton to point B and then back to A** (or “cartoon” from speech
transcription). The existing AI interpreter recognizes this intent and selects
`roundtrip`; the executor invokes the same `workshop_vision.run_cycle` used by
the CLI. It does not generate substitute translation commands.

Transfer speed is 8 degrees/second (previously 4); acceleration remains
6 degrees/second². A live UI run at 8 degrees/second completed in approximately
113 seconds, with 15.5 mm error at B and 4.6 mm at A (45 mm tolerance).
Evidence: `vision-cycle-20261017T153532649815Z.json` in `artifacts/diagnosis`.

The routine observes the carton, plans each transfer with the existing native
motion/geometry checks, executes, returns home, and observes again to verify
placement. It runs A → B → A; a start at B first adds a B → A recovery leg.
The routine's existing placement tolerance is 45 mm. Completion requires both
final destinations to pass fresh vision checks. Preview, cancellation, failed
grasp, and failed verification cannot produce a completion response.

Use the checked workshop setup, an empty gripper, the home pose and an upright
carton. Keep the transfer route clear as in the original workshop demonstration.
The routine retains the original carton-specific geometry; it is not a general
multi-object transfer planner. The separate natural-language controller remains
available for other tasks.

## Separate QA and demo worktrees

The demo worktree serves http://127.0.0.1:8089; QA retains port 8088. Configure
`VOICE_UI_PORT=8089` in the ignored `voice-ui/.env`. Set `VOICE_ROBOT_SOURCE` to
the checkout owning `.env.viam.json` and `.arm-control.lock`. Both controllers
must use that same lock. A busy robot is refused, never queued or commandeered.
The demo uses its own code, calibration, reports and build assets.

Run from the demo worktree:

```sh
uv sync --extra voice-ui
npm --prefix voice-ui ci
npm --prefix voice-ui run build:chat
uv run --extra voice-ui --env-file voice-ui/.env python voice-ui/server.py
```

Say or type **Check robot**, then **Move the carton to point B and back to A**.
Use **Prepare robot** only
when the empty arm needs a checked return to home. **Stop robot** cancels the
active task. A stop request is not a confirmed acknowledgement. With live voice enabled, the finished result is spoken automatically. Typed
responses can be played using **Read reply**.

## Regression checks

```sh
uv run --extra voice-ui pytest tests voice-ui qa-console/test_persistent_sim.py -q
```

80 offline tests passed after the integration. Added tests cover A/B starting
states, fresh verification after each leg, preview-only behavior, failed motion,
wrong placement, cancellation, explicit preset routing and cross-worktree lock
exclusion. Hardware is mocked in these tests. Live reports are saved under
`artifacts/diagnosis/vision-cycle-*.json`.

## Live product result — October 17, 2026

The UI button completed the physical A → B → A cycle, all 16 motion stages,
and return home. Fresh vision measured 10.714 mm placement error at B and
2.844 mm at A, within the unchanged 45 mm tolerance. The UI displayed success;
Read reply entered Speaking using the real ElevenLabs response stream.

An initial attempt was refused while QA held the robot lock; the successful
attempt ran after that lock was released. No QA process was stopped. Compact
measured evidence is in [vision-demo-result.json](checkpoints/vision-demo-result.json).
This is one physical fixed-case run, not validation of arbitrary tasks or
microphone-triggered motion. B-start recovery was tested with fake hardware and
has earlier CLI evidence.
