"""Record a manually taught, stationary real-arm pose. Never commands motion."""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from google.protobuf.json_format import MessageToDict
from viam.components.arm import Arm
from viam.robot.client import RobotClient

ROOT = Path(__file__).parent

async def record(name):
    c = json.loads((ROOT / '.env.viam.json').read_text())
    opts = RobotClient.Options.with_api_key(api_key=c['api_key'], api_key_id=c['api_key_id'])
    opts.dial_options.initial_connection_attempts = 1
    opts.dial_options.initial_connection_attempt_timeout = 15
    robot = await RobotClient.at_address(c['address'], opts)
    try:
        arm = Arm.from_robot(robot, 'arm')
        if await arm.is_moving(timeout=5):
            raise RuntimeError('Arm is moving; pose not recorded')
        first = list((await arm.get_joint_positions(timeout=5)).values)
        pose = await arm.get_end_position(timeout=5)
        await asyncio.sleep(.5)
        last = list((await arm.get_joint_positions(timeout=5)).values)
        if len(first) != 6 or len(last) != 6 or max(abs(a-b) for a,b in zip(first,last)) > .05 or await arm.is_moving(timeout=5):
            raise RuntimeError('Arm did not remain stationary; pose not recorded')
        output = ROOT / 'artifacts/taught-poses.json'
        data = json.loads(output.read_text()) if output.exists() else {}
        data[name] = {'captured_at': datetime.now(timezone.utc).isoformat(),
                      'pose': MessageToDict(pose), 'joints_degrees': last,
                      'source': 'On-site manual teaching; stationary readback',
                      'verified_return_path': False}
        output.write_text(json.dumps(data, indent=2)+'\n')
        print(json.dumps({name: data[name]}, indent=2))
    finally:
        await asyncio.wait_for(robot.close(), 5)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=['home', 'approach_A', 'grasp_A', 'travel', 'place_B', 'withdraw_B'])
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(record(args.name), 40))
