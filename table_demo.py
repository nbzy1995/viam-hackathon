"""Small conversational demo skills on the existing checked vision/motion path.

No independent robot connection or lock: TextController owns both. The model
selects a skill; measured coordinates and verified state stay in Python.
"""
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from google.protobuf.json_format import MessageToDict
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.proto.common import Pose, PoseInFrame

from task_interpreter import write_json
from workshop_static import check_arm
from workshop_vision import overview, observe_carton, transfer_carton, PLACEMENT_TOLERANCE_MM

CONFIG = Path(__file__).parent / 'config/table-demo.json'
ACTIONS = {'scan_table', 'deliver_bottle', 'return_bottle'}


class DemoUnavailable(ValueError):
    """A missing demo prerequisite that can be explained directly to the user."""


def setup(checked):
    config = json.loads(CONFIG.read_text())
    signature = hashlib.sha256(json.dumps([checked['frames'], config], sort_keys=True).encode()).hexdigest()
    return config, signature


def read_state(workspace, signature):
    path = workspace / 'table-demo-state.json'
    state = json.loads(path.read_text()) if path.exists() else {}
    return state if state.get('setup_signature') == signature else {}


def context(workspace, checked):
    config, signature = setup(checked)
    state = read_state(workspace, signature)
    return {'object_id': config['object_id'], 'spoken_name': config['spoken_name'],
            'delivery_location': config['location_mode'],
            'phase': state.get('phase', 'not_delivered'),
            'has_verified_return_position': state.get('phase') == 'delivered'}


async def scan_table(robot, geometry, checked, workspace, observation, report, save, progress):
    """Three distinct high wrist-camera views; all moves previewed before motion."""
    arm, camera = Arm.from_robot(robot, 'arm'), Camera.from_robot(robot, 'cam')
    captures = []

    async def capture():
        await check_arm(arm)
        joints = np.array((await arm.get_joint_positions(timeout=5)).values)
        images, metadata = await camera.get_images(filter_source_names=['color'], timeout=15)
        color = next(i for i in images if i.name == 'color')
        pose = await robot.transform_pose(PoseInFrame(reference_frame='cam', pose=Pose(o_z=1)), 'world')
        await check_arm(arm)
        if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-joints)) > .05:
            raise RuntimeError('Arm moved during table scan capture')
        path = workspace / f'table-view-{len(captures)+1}.jpg'
        Image.open(io.BytesIO(color.data)).convert('RGB').save(path, quality=85)
        item = {'view': f'High table view {len(captures)+1} of 3', 'path': str(path.resolve()),
                'captured_at': metadata.captured_at.ToJsonString(),
                'camera_world': MessageToDict(pose.pose), 'joints_degrees': joints.tolist()}
        captures.append(item)
        report['table_scan_images'] = captures.copy()
        save()
        progress(f'Table photo {len(captures)} of 3 captured.')
        return item

    progress('Raising the camera and turning through three table views.')
    # Keep the wrist extended while rotating. The older near-base search pose
    # folds joint 5 to 161 degrees and the controller rejects a rotated view.
    await overview(robot, geometry, checked, True, report, save, capture,
                   xyz=(330., -280., 680.6), angles=(0., -15., 15.), speed=8.)
    return observation | {'images': captures, 'camera_available': True, 'overview_attempted': True,
        'completed_actions': [{'action': 'scan_table', 'image_count': 3, 'returned_home': True}]}


def verify_at(cap, target):
    error = float(np.linalg.norm(np.asarray(cap)[:2]-target))
    if error > PLACEMENT_TOLERANCE_MM:
        raise RuntimeError(f'Vision did not confirm bottle placement: {error:.1f} mm from target')
    return {'error_mm': error, 'tolerance_mm': PLACEMENT_TOLERANCE_MM,
            'cap_world_mm': np.asarray(cap).tolist(), 'target_world_xy_mm': list(target)}


async def move_bottle(action, robot, geometry, checked, workspace, execute, report, save, progress):
    config, signature = setup(checked)
    state = read_state(workspace, signature)
    path = workspace / 'table-demo-state.json'
    returning = action == 'return_bottle'
    if state.get('phase') in {'delivering', 'returning'}:
        raise DemoUnavailable('The previous bottle move was interrupted or unverified. Its saved origin is preserved; check the bottle before restarting this demo.')
    if returning and state.get('phase') not in {'delivered', 'returned'}:
        raise DemoUnavailable('I do not have a verified delivery to return yet. Ask me to bring the water bottle to you first.')
    progress('Locating the water bottle, using the higher view if needed.')
    cap, station, joints = await observe_carton(robot, geometry, checked, execute, report, save)
    target = state['original_world_mm'][:2] if returning else config['delivery_world_xy_mm']
    if state.get('phase') == ('returned' if returning else 'delivered'):
        report['verification'] = verify_at(cap, target)
        report.update(success=True, outcome='bottle_returned' if returning else 'bottle_delivered')
        return
    if returning:
        # Do not pick up a different/reset scene using yesterday's saved origin.
        verify_at(cap, state['delivered_world_mm'][:2])
    elif np.linalg.norm(cap[:2]-target) <= PLACEMENT_TOLERANCE_MM:
        raise DemoUnavailable('The bottle is already at your marked location, but I have no saved pickup position. Put it at its starting position before starting the delivery demo.')
    next_state = state.copy() if returning else {
        'setup_signature': signature, 'original_world_mm': cap.tolist(),
        'original_station': station, 'delivery_world_xy_mm': target,
    }
    destination = state['original_station'] if returning else 'your marker'

    async def before_execute():
        progress('Confirming the bottle position before pickup.')
        fresh, _, _ = await observe_carton(robot, geometry, checked, True, report, save)
        if np.linalg.norm(fresh-cap) > 5:
            raise RuntimeError('Bottle changed position during planning')
        # Persist before movement: cancellation must not erase or invent an origin.
        next_state.update(phase='returning' if returning else 'delivering', at=datetime.now(timezone.utc).isoformat())
        write_json(path, next_state)

    progress('Returning the water bottle to its saved pickup position.' if returning else 'Bringing the water bottle to your blue tape marker.')
    await transfer_carton(robot, geometry, checked, execute, report, save, cap, station, joints,
        destination, destination_xy=target, via_b=True, progress=progress, before_execute=before_execute)
    if not execute:
        report['outcome'] = 'preview_passed'
        return
    cap, _, _ = await observe_carton(robot, geometry, checked, True, report, save)
    report['verification'] = verify_at(cap, target)
    next_state.update(phase='returned' if returning else 'delivered',
                      at=datetime.now(timezone.utc).isoformat())
    next_state['returned_world_mm' if returning else 'delivered_world_mm'] = cap.tolist()
    write_json(path, next_state)
    report['demo_state'] = next_state
    report.update(success=True, outcome='bottle_returned' if returning else 'bottle_delivered')
    progress('Bottle placement verified; the arm is home.')
