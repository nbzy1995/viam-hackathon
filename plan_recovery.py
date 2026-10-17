"""Plan-only positive-Y recovery probe. Never executes or enables motion."""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from google.protobuf.json_format import MessageToDict
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.services.motion import MotionClient
from scene_sweep import Scene

ROOT = Path(__file__).parent

async def main(distance_mm=5):
    c = json.loads((ROOT / '.env.viam.json').read_text())
    opts = RobotClient.Options.with_api_key(api_key=c['api_key'], api_key_id=c['api_key_id'])
    opts.dial_options.initial_connection_attempts = 1
    opts.dial_options.initial_connection_attempt_timeout = 15
    robot = await RobotClient.at_address(c['address'], opts)
    try:
        arm = Arm.from_robot(robot, 'arm')
        before = list((await arm.get_joint_positions(timeout=10)).values)
        target = MessageToDict(await arm.get_end_position(timeout=10))
        target['y'] += distance_mm
        request = {'name': 'builtin', 'destination': {'referenceFrame': 'world', 'pose': target}, 'componentName': 'arm'}
        response = await MotionClient.from_robot(robot, 'builtin').do_command({'plan': json.dumps(request)}, timeout=30)
        waypoints = [np.degrees(w['arm']).tolist() for w in response['plan']]
        scene = Scene()
        samples = []
        initial_vertices = scene.vertices(before)
        max_displacement = 0
        for a,b in zip(waypoints, waypoints[1:]):
            for q in np.linspace(a,b,101):
                samples.append(scene.clearances(q)['wall-side']['clearance_mm'])
                for name, vertices in scene.vertices(q).items():
                    max_displacement = max(max_displacement, float(np.max(np.linalg.norm(vertices-initial_vertices[name], axis=1)))*1000)
        report = {'scope': 'Plan-only; no motion, reset, or enable command',
                  'at': datetime.now(timezone.utc).isoformat(), 'request': request, 'response': response,
                  'sweep': scene.sweep(waypoints),
                  'endpoint_clearances': scene.clearances(waypoints[-1]),
                  'side_clearance_monotonically_increases': bool(min(np.diff(samples)) >= -0.001),
                  'max_mesh_vertex_displacement_mm': max_displacement,
                  'joints_before': before, 'joints_after': list((await arm.get_joint_positions(timeout=10)).values),
                  'moving_after': await arm.is_moving(timeout=10)}
        (ROOT / f'artifacts/diagnosis/recovery-{distance_mm}mm-plan.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k != 'response'}, indent=2))
    finally:
        await robot.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distance-mm', type=int, choices=[5, 50], default=5)
    asyncio.run(main(parser.parse_args().distance_mm))
