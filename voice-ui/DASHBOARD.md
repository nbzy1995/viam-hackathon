# Live robot dashboard

The demo server on port 8089 incorporates the camera/activity layout and voice
controls from worktree `f0d0`, with this worktree's three suggested demo prompts.
The original scripted scan, delivery, and return commands are unchanged.

When `VOICE_ROBOT_ENABLED=1`, `dashboard.py` opens one read-only Viam connection
using the existing `VOICE_ROBOT_SOURCE` credentials. All browser tabs share it.
It captures the wrist camera and passes that exact JPEG to the existing
`carton-detector`, `red-detector`, and `yellow-detector` services. Each published
image has matching bounding boxes. These services detect colored regions;
the overlay does not claim that every blue region is a carton. The scan skill
still uses the AI interpreter to describe the table.

`GET /api/dashboard` returns the current frame ID, boxes, camera timestamp,
arm state, gripper state, and the active harness progress message.
`GET /api/camera/{name}` serves that exact JPEG from a bounded 30-frame memory
cache. The browser refreshes every 250 ms; actual image updates depend on the
camera/vision RPC latency (about 2 frames per second in the live check).
This is a continuously refreshed JPEG feed, not 30 FPS video.

Camera and telemetry expire independently after five seconds. Unavailable
recognition clears boxes without hiding a valid camera image. Connection
failures reconnect; server shutdown cancels observation and closes its client.
There is no camera archive or new dashboard credential setting.

The observer calls only GetImages, GetDetections, IsMoving, GetJointPositions,
and IsHoldingSomething. It never commands motion or holds the control lock.
It pauses reads when another controller owns the shared lock. This worktree's
setup validation permits these read-only methods; actuator and unknown
operations still block a new task. The other worktree servers are unmodified.

Voice input and voice replies have separate controls. Typed replies can speak
automatically. Stop audio cancels playback; Stop robot uses the existing worker
stop path. The imported UI also offers device voice as a fallback when the
ElevenLabs API key reaches its credit limit.

Verification: `../docs/checkpoints/live-dashboard-result.json`. The web UI's
read-only “Check robot” passed while real camera images, detections, and robot
telemetry continued updating. No physical motion was needed for this UI check.
