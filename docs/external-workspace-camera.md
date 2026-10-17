# External workspace camera

The Logitech Brio 101 is connected to the local Mac. A successful 1280 x 720 still image was captured on 2026-10-16 at approximately 13:47 America/New_York. The Viam machine resource list still contains only the wrist camera `cam`.

Use the local camera directly for setup inspection; no additional Viam server or camera module is needed for this step:

```sh
uv run python workspace_camera.py
```

This captures one still image to `artifacts/workspace-camera.png` and records capture timing in `artifacts/workspace-camera.json`. It selects `Brio 101` by device name, records no audio, makes no robot connection, and times out after 45 seconds. Check successful exit and current metadata before interpreting an image; a failed capture can leave an older file in place.

The reusable command was verified successfully at 13:48:31 America/New_York, completing in 3.772 seconds. FFmpeg reported that device configuration fell back to its default; the returned image was viewed successfully. No continuous capture process is kept running.

The first image showed most of the arm and nearby panels, but not the two blue markers. After camera repositioning, the 13:51:37 America/New_York capture shows a drink carton near the top and an exposed blue tape marker below it. The user confirmed that A (pickup) is the marker under the carton and B (placement) is the exposed marker. A's marker center remains hidden, and part of the lower arm is cropped. The reference image and label record are saved in `artifacts/markers-external-reference.png` and `artifacts/table-markers.json`. Robot-frame positions and grasp/place poses remain unset.

This uncalibrated color view supports visual inspection. It does not establish distances, robot-frame target coordinates, exact wall clearance, hardware stop state, or collision-free motion. It is a still-image aid, not a live protective stop system. The physical run remains halted after the reported wall contact; see `wall-contact-2026-10-16.md`.

Source for the capture interface: [FFmpeg AVFoundation documentation](https://ffmpeg.org/ffmpeg-devices.html#avfoundation).
