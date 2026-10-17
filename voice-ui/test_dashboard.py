import asyncio
import fcntl
import io
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from google.protobuf.timestamp_pb2 import Timestamp
from PIL import Image

from dashboard import Dashboard, detection_boxes


def test_boxes_are_clipped_and_color_is_not_claimed_as_object_identity():
    detections = [SimpleNamespace(x_min=-5, y_min=2, x_max=100, y_max=80, class_name='blue'),
                  SimpleNamespace(x_min=80, y_min=2, x_max=100, y_max=3, class_name='red')]
    assert detection_boxes(detections, 64, 48) == [
        {'label': 'Blue region', 'color': 'blue', 'box': [0, 2, 64, 48]}]


def camera_fixture():
    data = io.BytesIO()
    Image.new('RGB', (64, 48), 'blue').save(data, format='PNG')
    captured = Timestamp(); captured.GetCurrentTime()
    camera = SimpleNamespace(get_images=AsyncMock(return_value=(
        [SimpleNamespace(name='color', data=data.getvalue())], SimpleNamespace(captured_at=captured))))
    return camera


def test_detections_use_exact_published_frame_and_failed_detector_does_not_hide_camera():
    async def run():
        dashboard = Dashboard(); dashboard.connected = True
        detector = SimpleNamespace(get_detections=AsyncMock(return_value=[
            SimpleNamespace(x_min=1, y_min=2, x_max=20, y_max=30, class_name='blue')]))
        failed = SimpleNamespace(get_detections=AsyncMock(side_effect=RuntimeError('unavailable')))
        await dashboard.capture(camera_fixture(), [detector, failed])
        snapshot = dashboard.snapshot()
        analyzed = detector.get_detections.call_args.args[0]
        assert analyzed.data == dashboard.frames[snapshot['frame']]
        assert snapshot['fresh'] and snapshot['vision_available'] and snapshot['vision_partial']
        assert snapshot['objects'][0]['box'] == [1, 2, 20, 30]
        await dashboard.capture(camera_fixture(), [failed])
        snapshot = dashboard.snapshot()
        assert snapshot['fresh'] and not snapshot['vision_available'] and snapshot['objects'] == []
    asyncio.run(run())


def test_old_capture_and_stale_status_are_independent_and_clear_boxes():
    async def run():
        dashboard = Dashboard(); dashboard.connected = True
        await dashboard.capture(camera_fixture(), [])
        dashboard.telemetry = {'received': time.monotonic() - 10, 'state': 'Moving',
                               'holding': True, 'updated_at': 'old'}
        assert dashboard.snapshot()['fresh'] and not dashboard.snapshot()['status_fresh']
        assert dashboard.snapshot()['holding'] is None
        dashboard.telemetry['received'] = time.monotonic()
        # A recently received response can still contain an old frozen camera image.
        dashboard.frame['captured_epoch'] -= 10
        result = dashboard.snapshot()
        assert result['status_fresh'] and not result['fresh']
        assert result['frame'] is None and result['objects'] == []
    asyncio.run(run())


def test_observer_yields_to_other_controller_without_retaining_lock(tmp_path):
    dashboard = Dashboard(tmp_path)
    assert not dashboard.external_control()
    with (tmp_path / '.arm-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert dashboard.external_control()
        dashboard.busy = lambda: True
        assert not dashboard.external_control()


def test_close_cancels_observer_task():
    async def run():
        dashboard = Dashboard()
        dashboard.task = asyncio.create_task(asyncio.sleep(100))
        task = dashboard.task
        await dashboard.close()
        assert task.cancelled() and dashboard.task is None
    asyncio.run(run())
