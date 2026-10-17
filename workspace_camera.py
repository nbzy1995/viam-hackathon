"""Capture one workspace image from the local Brio camera. No robot connection."""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def main():
    output = Path(__file__).parent / "artifacts" / "workspace-camera.png"
    output.parent.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)
    timer = time.monotonic()
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "avfoundation", "-framerate", "30", "-video_size", "1280x720",
        "-pixel_format", "uyvy422", "-i", "Brio 101:none",
        "-ss", "1", "-frames:v", "1", "-update", "1", "-y", str(output),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise SystemExit("Camera capture timed out; no new image confirmed. Any existing image may be stale.")
    if result.returncode:
        raise SystemExit(f"Camera capture failed; any existing image may be stale.\n{result.stderr}")
    record = {
        "device": "Brio 101",
        "capture_started_at_utc": started.isoformat(),
        "capture_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - timer, 3),
        "image": str(output),
        "audio_captured": False,
        "robot_commands": False,
        "warnings": result.stderr.strip(),
    }
    output.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
