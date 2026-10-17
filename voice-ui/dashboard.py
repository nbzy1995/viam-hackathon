"""One read-only robot observer, shared by every browser in this server.

Images and detections are published together. Neither this observer nor its
HTTP endpoints can move the robot; the existing worker owns all control.
"""
import asyncio
from collections import OrderedDict
from contextlib import suppress
from datetime import datetime, timezone
import fcntl
import io
import json
import time
from pathlib import Path

from PIL import Image
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from viam.media.video import CameraMimeType, ViamImage
from viam.robot.client import RobotClient
from viam.services.vision import VisionClient

ROOT = Path(__file__).resolve().parents[1]
DETECTORS = ('carton-detector', 'red-detector', 'yellow-detector')
STALE_SECONDS = 5


def detection_boxes(detections, width, height):
    boxes = []
    for d in detections:
        x1, y1 = max(0, d.x_min), max(0, d.y_min)
        x2, y2 = min(width, d.x_max), min(height, d.y_max)
        if x2 <= x1 or y2 <= y1:
            continue
        # Native color detector confidence is not object identity confidence.
        boxes.append({'label': f'{d.class_name.capitalize()} region',
                      'color': d.class_name, 'box': [x1, y1, x2, y2]})
    return boxes


class Dashboard:
    def __init__(self, source=None, *, busy=lambda: False):
        self.source = Path(source) if source else None
        self.busy = busy
        self.connected = False
        self.paused = False
        self.frames = OrderedDict()
        self.frame = None
        self.telemetry = None
        self.sequence = 0
        self.task = None

    def external_control(self):
        if self.busy() or self.source is None:
            return False
        with (self.source / '.arm-control.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock, fcntl.LOCK_UN)
        return False

    def snapshot(self, *, activity='Waiting for a voice or text request.'):
        now = time.monotonic()
        frame, telemetry = self.frame, self.telemetry
        fresh = bool(self.connected and not self.paused and frame and
                     now - frame['received'] < STALE_SECONDS and
                     0 <= time.time() - frame['captured_epoch'] < STALE_SECONDS)
        status_fresh = bool(self.connected and not self.paused and telemetry and
                            now - telemetry['received'] < STALE_SECONDS)
        return {'connected': self.connected, 'fresh': fresh, 'status_fresh': status_fresh,
                'paused': self.paused, 'frame': frame['name'] if fresh else None,
                'updated_at': frame['captured_at'] if frame else None,
                'width': frame['width'] if fresh else None, 'height': frame['height'] if fresh else None,
                'objects': frame['objects'] if fresh else [],
                'vision_available': bool(fresh and frame['vision_available']),
                'vision_partial': bool(fresh and frame['vision_partial']),
                'state': telemetry['state'] if status_fresh else 'State unavailable',
                'holding': telemetry['holding'] if status_fresh else None,
                'activity': 'Another controller is using the robot; live view paused.' if self.paused else activity,
                'status_updated_at': telemetry['updated_at'] if status_fresh else None}

    async def start(self):
        if self.source is not None:
            self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        self.connected = False
        self.frames.clear()

    async def run(self):
        while True:
            robot = None
            try:
                credentials = json.loads((self.source / '.env.viam.json').read_text())
                options = RobotClient.Options.with_api_key(api_key=credentials['api_key'], api_key_id=credentials['api_key_id'])
                options.dial_options.force_relay = True
                options.dial_options.initial_connection_attempts = 1
                options.dial_options.initial_connection_attempt_timeout = 15
                robot = await asyncio.wait_for(RobotClient.at_address(credentials['address'], options), 25)
                self.connected = True
                async with asyncio.TaskGroup() as group:
                    group.create_task(self.camera_loop(robot))
                    group.create_task(self.status_loop(robot))
            except Exception:
                # Never expose SDK connection exceptions containing credential URLs.
                pass
            finally:
                self.connected = False
                if robot:
                    with suppress(Exception):
                        await asyncio.wait_for(robot.close(), 5)
            await asyncio.sleep(3)

    async def camera_loop(self, robot):
        camera = Camera.from_robot(robot, 'cam')
        detectors = [VisionClient.from_robot(robot, name) for name in DETECTORS
                     if any(r.name == name and r.subtype == 'vision' for r in robot.resource_names)]
        failures = 0
        while True:
            self.paused = self.external_control()
            if not self.paused:
                try:
                    await self.capture(camera, detectors)
                    failures = 0
                except Exception:
                    self.frame = None
                    failures += 1
                    if failures >= 3:
                        raise
            await asyncio.sleep(.1 if not failures else 1)

    async def capture(self, camera, detectors):
        images, metadata = await camera.get_images(filter_source_names=['color'], timeout=3)
        color = next(i for i in images if i.name == 'color')
        picture = Image.open(io.BytesIO(color.data)).convert('RGB')
        output = io.BytesIO()
        picture.save(output, format='JPEG', quality=80)
        jpeg = output.getvalue()
        image = ViamImage(jpeg, CameraMimeType.JPEG)
        results = await asyncio.gather(*(detector.get_detections(image, timeout=2) for detector in detectors),
                                       return_exceptions=True)
        successful = [result for result in results if not isinstance(result, BaseException)]
        boxes = detection_boxes([d for result in successful for d in result], picture.width, picture.height)
        self.sequence += 1
        name = f'frame-{self.sequence}.jpg'
        self.frames[name] = jpeg
        while len(self.frames) > 30:
            self.frames.popitem(last=False)
        self.frame = {'name': name, 'received': time.monotonic(),
                      'captured_at': metadata.captured_at.ToJsonString(),
                      'captured_epoch': metadata.captured_at.ToDatetime(tzinfo=timezone.utc).timestamp(),
                      'width': picture.width, 'height': picture.height, 'objects': boxes,
                      'vision_available': bool(successful), 'vision_partial': len(successful) < len(detectors)}

    async def status_loop(self, robot):
        arm, grip = Arm.from_robot(robot, 'arm'), Gripper.from_robot(robot, 'gripper')
        home = json.loads((ROOT / 'artifacts/roundtrip-checked-setup.json').read_text())['home_joints']
        while True:
            if not self.external_control():
                try:
                    moving, joints, holding = await asyncio.gather(arm.is_moving(timeout=3),
                        arm.get_joint_positions(timeout=3), grip.is_holding_something(timeout=3))
                    at_home = len(joints.values) == len(home) and max(abs(a-b) for a,b in zip(joints.values, home)) < .2
                    self.telemetry = {'received': time.monotonic(), 'updated_at': datetime.now(timezone.utc).isoformat(),
                        'state': 'Moving' if moving else 'Home' if at_home else 'Stationary',
                        'holding': holding.is_holding_something}
                except Exception:
                    self.telemetry = None
            await asyncio.sleep(.5)
