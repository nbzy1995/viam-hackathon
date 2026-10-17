"""Fresh native Viam scene observations; Brio provides optional visual context."""
import asyncio
import io
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from google.protobuf.json_format import MessageToDict
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.proto.common import Pose, PoseInFrame
from viam.services.vision import VisionClient

from scene_sweep import pose_matrix
from task_interpreter import write_json
from workshop_static import check_arm
from workshop_vision import STATIONS, locate_carton, overview, CartonNotVisible, point_cloud_world
from tabletop_transfer import surface_geometry, table_height


def saved_table_height(checked):
    path = Path(__file__).parent / 'config/tabletop-surface.json'
    if not path.exists(): return None
    calibration = json.loads(path.read_text())
    fingerprint = hashlib.sha256(json.dumps(checked['frames'], sort_keys=True).encode()).hexdigest()
    return calibration['height_world_mm'] if fingerprint == calibration['frames_sha256'] else None


def camera_directions(point, camera_world):
    """Invert the calibrated projection on the tabletop, without a manual axis map."""
    transform = pose_matrix(camera_world)
    rotation = transform[:3, :3].T
    p = rotation @ (np.asarray(point) - transform[:3, 3] * 1000)
    if p[2] <= 0:
        raise ValueError('Object is behind the wrist camera')
    jacobian = np.vstack([rotation[i, :2] - p[i] / p[2] * rotation[2, :2] for i in (0, 1)])
    if np.linalg.cond(jacobian) > 20:
        raise ValueError('Camera view cannot ground a tabletop direction')
    inverse = np.linalg.inv(jacobian)
    return {name: (inverse[:, i] / np.linalg.norm(inverse[:, i])).tolist()
            for i, name in enumerate(('image_right_world_xy_unit', 'image_down_world_xy_unit'))}


async def brio_image(output):
    process = await asyncio.create_subprocess_exec(
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-f', 'avfoundation',
        '-framerate', '30', '-video_size', '1280x720', '-pixel_format', 'uyvy422',
        '-i', 'Brio 101:none', '-ss', '0.3', '-frames:v', '1', '-update', '1', '-y', str(output),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, errors = await asyncio.wait_for(process.communicate(), 10)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(errors.decode(errors='replace')[-300:])
    return {'view': 'external Brio overview; uncalibrated', 'path': str(output)}


async def capture_scene(robot, checked, workspace, *, high=False, table_z=None):
    workspace = workspace.resolve()
    if table_z is None:
        table_z = saved_table_height(checked)
    workspace.mkdir(parents=True, exist_ok=True)
    arm = Arm.from_robot(robot, 'arm')
    await check_arm(arm)
    joints = np.array((await arm.get_joint_positions(timeout=5)).values)
    if not high and max(abs(joints - checked['home_joints'])) > .1:
        raise RuntimeError('Scene observation must start at the checked home pose')
    camera_world = await robot.transform_pose(PoseInFrame(reference_frame='cam', pose=Pose(o_z=1)), 'world')
    frame = MessageToDict(camera_world.pose)
    camera = Camera.from_robot(robot, 'cam')

    async def wrist_image():
        images, metadata = await camera.get_images(filter_source_names=['color'], timeout=15)
        color = next(i for i in images if i.name == 'color')
        output = workspace / 'wrist.jpg'
        Image.open(io.BytesIO(color.data)).convert('RGB').save(output, quality=85)
        return {'view': 'calibrated wrist camera; default left/right view', 'path': str(output),
                'captured_at': metadata.captured_at.ToJsonString()}

    results = await asyncio.gather(wrist_image(),
        VisionClient.from_robot(robot, 'vision-segment').get_object_point_clouds('cam', timeout=20),
        VisionClient.from_robot(robot, 'red-segment').get_object_point_clouds('cam', timeout=20),
        VisionClient.from_robot(robot, 'yellow-segment').get_object_point_clouds('cam', timeout=20),
        brio_image(workspace / 'overview.jpg'), return_exceptions=True)
    # The full camera cloud is much larger than object segments. Read it
    # separately so it cannot starve concurrent RPCs/connection health checks.
    table_error = None
    if table_z is None:
        try:
            cloud, _ = await Camera.from_robot(robot, 'cam').get_point_cloud(timeout=20)
            full_points = point_cloud_world(cloud, camera_world)
            from scene_sweep import Scene
            model_z = Scene().boundaries['table'][2] * 1000
            table_z = table_height(full_points, model_z)
        except Exception as exc:
            table_error = str(exc)
    await check_arm(arm)
    if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values) - joints)) > .05:
        raise RuntimeError('Arm moved during scene capture')
    scene = {'at': datetime.now(timezone.utc).isoformat(), 'objects': [], 'images': [],
             'errors': {}, 'native_counts': {}, 'camera_world': frame, 'joints_degrees': joints.tolist(),
             'landmarks_world_xy_mm': STATIONS, 'robot_base_world_mm': [0, 0, 0],
             'default_view': 'wrist camera', 'overview_attempted': high,
             'camera_available': not isinstance(results[0], BaseException)}
    if table_z is not None:
        scene['table_surface_z_mm'] = table_z
    elif table_error:
        scene['errors']['table_depth'] = table_error
    for name, result in zip(('wrist', 'native_segments', 'native_red', 'native_yellow', 'brio'), results):
        if isinstance(result, BaseException):
            scene['errors'][name] = f'{type(result).__name__}: {result}'
        elif name in ('wrist', 'brio'):
            scene['images'].append(result)
        elif name == 'native_segments':
            scene['native_counts'][name] = len(result)
            try:
                cap, station = locate_carton(result, camera_world)
                carton = {'id': 'carton', 'label': 'blue and white carton',
                    'world_mm': cap.tolist(), 'station': station, 'movable': True,
                    'source': 'native carton-detector and vision-segment',
                    'view_directions': camera_directions(cap, frame)}
                if 'table_surface_z_mm' in scene:
                    carton['geometry'] = {'center_top_world_mm': cap.tolist(), 'top_z_mm': float(cap[2]),
                        'bottom_z_mm': scene['table_surface_z_mm'], 'length_mm': 30., 'width_mm': 30.,
                        'body_length_mm': 100., 'body_width_mm': 100.,
                        'theta_degrees': 163., 'surface_residual_mm': 0., 'grasp_tcp_z_mm': float(cap[2] + 20)}
                scene['objects'].append(carton)
            except (CartonNotVisible, ValueError, RuntimeError) as exc:
                scene['errors']['carton'] = str(exc)
        else:
            scene['native_counts'][name] = len(result)
            for index, obj in enumerate(result):
                points = point_cloud_world(obj.point_cloud, camera_world)
                # Remove the tabletop in a native detection's depth segment.
                points = points[np.isfinite(points).all(axis=1) & (points[:, 2] > scene.get('table_surface_z_mm', 3) + 5)]
                if len(points) < 100:
                    continue
                label = obj.geometries.geometries[0].label
                center = np.median(points, axis=0)
                observation = {'id': f'{label}-{index + 1}', 'label': label,
                    'world_mm': center.tolist(),
                    'observed_bounds_world_mm': [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
                    'view_directions': camera_directions(center, frame),
                    'source': f'{name}: native detection and depth segment'}
                if 'table_surface_z_mm' in scene:
                    try:
                        observation['geometry'] = surface_geometry(points, scene['table_surface_z_mm'])
                        observation['world_mm'] = observation['geometry']['center_top_world_mm']
                        observation['view_directions'] = camera_directions(observation['world_mm'], frame)
                    except ValueError as exc:
                        observation['geometry_error'] = str(exc)
                scene['objects'].append(observation)
    write_json(workspace / 'scene.json', scene)
    return scene


async def capture_overview(robot, geometry, checked, report, save, workspace):
    async def scan():
        return await capture_scene(robot, checked, workspace, high=True)
    # Both legs are planned and swept by the existing workshop helper.
    return await overview(robot, geometry, checked, True, report, save, scan)
