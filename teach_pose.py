"""Save a stationary tutorial pose using native pose saver; never moves the arm.

Installed vmodutils saves Cartesian targets when motion=builtin. Also retain
measured joints so replay follows a joint goal through the built-in planner.
"""
import argparse
import asyncio
import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from viam.app.viam_client import ViamClient
from viam.rpc.dial import DialOptions, Credentials
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.switch import Switch

ROOT = Path(__file__).parent
PART = 'f3d9c05f-c163-47c5-8291-1f58f13e46f0'
POSES = ['home-pose', 'approach-pose', 'grasp-pose', 'travel-pose', 'place-pose', 'above-place-pose']

async def teach(name):
    c = json.loads((ROOT/'.env.viam.json').read_text())
    options = RobotClient.Options.with_api_key(api_key=c['api_key'], api_key_id=c['api_key_id'])
    options.dial_options.force_relay = True
    options.dial_options.initial_connection_attempts = 1
    options.dial_options.initial_connection_attempt_timeout = 15
    robot = await asyncio.wait_for(RobotClient.at_address(c['address'], options), 25)
    app = None
    try:
        arm = Arm.from_robot(robot, 'arm')
        switch = Switch.from_robot(robot, name)
        if await arm.is_moving(timeout=5):
            raise RuntimeError('Arm must be stationary')
        before = list((await arm.get_joint_positions(timeout=5)).values)
        await switch.set_position(1, timeout=15)
        after = list((await arm.get_joint_positions(timeout=5)).values)
        if max(abs(a-b) for a,b in zip(before,after)) > .05 or await arm.is_moving(timeout=5):
            raise RuntimeError('Arm moved during teaching; pose needs review')
        app = await ViamClient.create_from_dial_options(DialOptions(
            auth_entity=c['api_key_id'], credentials=Credentials(type='api-key', payload=c['api_key'])))
        part = await app.app_client.get_robot_part(PART)
        config = copy.deepcopy(part.robot_config)
        resource = next(x for x in config['components'] if x['name'] == name)
        if resource['attributes'].get('motion') != 'builtin':
            raise RuntimeError('Pose must use builtin motion')
        resource['attributes']['joints'] = [math.radians(x) for x in after]
        await app.app_client.update_robot_part(part.id, part.name, robot_config=config, last_known_update=part.last_updated)
        actual = await app.app_client.get_robot_part(PART)
        if actual.robot_config != config:
            raise RuntimeError('Cloud pose readback mismatch')
        record = {'at':datetime.now(timezone.utc).isoformat(), 'name':name,
                  'attributes':resource['attributes'], 'joints_degrees':after,
                  'return_verified':False, 'motion_commands':False}
        (ROOT/'artifacts/diagnosis'/f'taught-{name}.json').write_text(json.dumps(record,indent=2))
        print(json.dumps(record,indent=2))
    finally:
        if app: app.close()
        await asyncio.wait_for(robot.close(),5)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name',choices=POSES)
    asyncio.run(teach(parser.parse_args().name))
