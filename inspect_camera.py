"""Read-only wrist camera snapshot and arm telemetry. Never commands motion."""
import asyncio
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from google.protobuf.json_format import MessageToDict
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from viam.media.video import CameraMimeType
from viam.proto.common import Pose, PoseInFrame


def blue_regions(rgb):
    pixels = np.asarray(rgb).astype(float)
    mask = (pixels[:, :, 2] > 1.25 * pixels[:, :, 1]) & (pixels[:, :, 2] > 1.5 * pixels[:, :, 0]) & (pixels[:, :, 2] > 45)
    remaining = set(zip(*np.nonzero(mask)))
    regions = []
    while remaining:
        seed = remaining.pop()
        todo, region = [seed], [seed]
        while todo:
            y, x = todo.pop()
            for point in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                if point in remaining:
                    remaining.remove(point)
                    todo.append(point)
                    region.append(point)
        if len(region) >= 100:
            regions.append(np.asarray(region))
    return sorted(regions, key=lambda r: float(r[:, 1].mean()))


async def main(force_relay=False):
    root = Path(__file__).parent
    connection = json.loads((root / '.env.viam.json').read_text())
    options = RobotClient.Options.with_api_key(
        api_key=connection['api_key'], api_key_id=connection['api_key_id'])
    options.dial_options.initial_connection_attempts = 1
    options.dial_options.initial_connection_attempt_timeout = 15
    options.dial_options.force_relay = force_relay
    machine = await asyncio.wait_for(
        RobotClient.at_address(connection['address'], options), 30)
    try:
        camera = Camera.from_robot(machine, 'cam')
        arm = Arm.from_robot(machine, 'arm')
        gripper = Gripper.from_robot(machine, 'gripper')
        images, metadata = await camera.get_images(timeout=15)
        properties = await camera.get_properties(timeout=10)
        record = {
            'captured_at': metadata.captured_at.ToJsonString(),
            'arm_pose': MessageToDict(await arm.get_end_position(timeout=10)),
            'arm_joints': MessageToDict(await arm.get_joint_positions(timeout=10)),
            'arm_moving': await arm.is_moving(timeout=10),
            'camera_properties': MessageToDict(properties),
            'images': [],
        }
        for image in images:
            record['images'].append({'name': image.name, 'mime_type': str(image.mime_type),
                                     'width': image.width, 'height': image.height})
            if image.mime_type == CameraMimeType.VIAM_RAW_DEPTH:
                depth = np.asarray(image.bytes_to_depth_array(), dtype=np.uint16)
                np.save(root / 'artifacts/current-depth.npy', depth)
                valid = depth[depth > 0]
                record['depth_nonzero_fraction'] = float(np.count_nonzero(depth) / depth.size)
                record['depth_quantiles_mm'] = np.percentile(valid, [5, 50, 95]).tolist() if valid.size else []
            elif image.name == 'color':
                Image.open(io.BytesIO(image.data)).save(root / 'artifacts/current-color.png')
        rgb = Image.open(root / 'artifacts/current-color.png').convert('RGB')
        intr = properties.intrinsic_parameters
        record['blue_candidates'] = []
        for region in blue_regions(rgb):
            v, u = region.mean(axis=0)
            depths = depth[region[:, 0], region[:, 1]]
            valid = depths[depths > 0]
            candidate = {'pixels': len(region), 'pixel_center_uv': [float(u), float(v)],
                         'bbox_uv': [int(region[:,1].min()), int(region[:,0].min()), int(region[:,1].max()), int(region[:,0].max())],
                         'valid_depth_fraction': float(len(valid)/len(depths))}
            if valid.size:
                z = float(np.median(valid))
                camera_point = Pose(x=(u-intr.center_x_px)*z/intr.focal_x_px,
                                    y=(v-intr.center_y_px)*z/intr.focal_y_px, z=z, o_z=1)
                world = await machine.transform_pose(PoseInFrame(reference_frame='cam', pose=camera_point), 'world')
                candidate.update(camera_point=MessageToDict(camera_point), world_point=MessageToDict(world.pose))
            record['blue_candidates'].append(candidate)
        (root / 'artifacts/current-observation.json').write_text(json.dumps(record, indent=2))
        print(json.dumps(record, indent=2))
    finally:
        await machine.close()


if __name__ == '__main__':
    asyncio.run(main())
