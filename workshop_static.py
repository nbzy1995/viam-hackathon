"""Viam workshop: one trigger runs A -> B -> A using native saved-pose switches.

uv run python workshop_static.py            # read-only readiness check
uv run python workshop_static.py --execute  # physical round trip
Reference: https://docs.viam.com/tutorials/pick-and-place/control-the-robot-from-python/
"""
import argparse
import asyncio
import json
import fcntl
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from google.protobuf.json_format import MessageToDict
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.components.switch import Switch

ROOT = Path(__file__).parent
NAMES = ['home-pose', 'approach-pose', 'grasp-pose', 'travel-pose', 'above-place-pose', 'place-pose']

@contextmanager
def control_lock():
    """Prevent these workshop scripts from commanding the arm concurrently."""
    with (ROOT/'.arm-control.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another workshop control run is active') from None
        yield

async def check_arm(arm):
    if await arm.is_moving(timeout=5):
        raise RuntimeError('Arm is already moving')
    if (await arm.do_command({'get_error': True}, timeout=5)).get('error info', [])[-2:] != [0, 0]:
        raise RuntimeError('Controller fault; recovery must happen separately')

async def run_sequence(arm, gripper, poses, targets, report, save=lambda: None):
    async def move(name):
        await check_arm(arm)
        report['pending'] = name; save()
        await poses[name].set_position(2, timeout=120)
        await check_arm(arm)
        p = await arm.get_end_position(timeout=5)
        if max(abs(getattr(p, k.lower())-targets[name][k]) for k in ('X','Y','Z')) > 2:
            raise RuntimeError(f'{name}: endpoint mismatch')
        report['stages'].append(name); report['pending'] = None; save()
        print(f'Completed {name}', flush=True)

    async def hold():
        if not (await gripper.is_holding_something(timeout=5)).is_holding_something:
            raise RuntimeError('Gripper did not retain the carton')

    async def grab():
        if not await gripper.grab(timeout=15):
            raise RuntimeError('Grab failed; no carrying move attempted')
        await asyncio.sleep(.3)
        await hold()

    async def release(where):
        await gripper.open(timeout=15)
        if (await gripper.is_holding_something(timeout=5)).is_holding_something:
            raise RuntimeError('Release not confirmed')
        report['stages'].append(f'release-at-{where}'); save()
        await asyncio.sleep(.5)

    try:
        await check_arm(arm)
        if (await gripper.is_holding_something(timeout=5)).is_holding_something:
            raise RuntimeError('Start with an empty gripper and carton at A')
        await arm.do_command({'set_speed': 3., 'set_acceleration': 6.}, timeout=5)
        await move('home-pose'); await move('approach-pose')
        await gripper.open(timeout=15)
        await move('grasp-pose'); await grab()
        for name in ['travel-pose', 'above-place-pose', 'place-pose']:
            await move(name); await hold()
        await release('B')
        await grab()  # Re-grasp at B without withdrawing or requiring a reset.
        for name in ['above-place-pose', 'travel-pose', 'grasp-pose']:
            await move(name); await hold()
        await release('A')
        await move('approach-pose'); await move('home-pose')
        report['success'] = True; save()
    except BaseException as exc:
        report.update(success=False, error=f'{type(exc).__name__}: {exc}')
        try:
            await arm.stop(timeout=5); report['stop_requested'] = True
        except Exception as stop_error:
            report['stop_error'] = str(stop_error)
        save()
        raise

async def main(execute):
    c = json.loads((ROOT/'.env.viam.json').read_text())
    opts = RobotClient.Options.with_api_key(api_key=c['api_key'], api_key_id=c['api_key_id'])
    opts.dial_options.force_relay = True
    opts.dial_options.initial_connection_attempts = 1
    opts.dial_options.initial_connection_attempt_timeout = 15
    robot = await asyncio.wait_for(RobotClient.at_address(c['address'], opts), 25)
    report = {'at': datetime.now(timezone.utc).isoformat(), 'execution_attempted': False, 'success': False, 'stages': []}
    output = ROOT/'artifacts/diagnosis'/f'roundtrip-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
    def save(): output.write_text(json.dumps(report, indent=2))
    try:
        arm, gripper = Arm.from_robot(robot, 'arm'), Gripper.from_robot(robot, 'gripper')
        poses = {n: Switch.from_robot(robot, n) for n in NAMES}
        cfg = {n: json.loads((await p.do_command({'cfg': True}, timeout=5))['as_json']) for n,p in poses.items()}
        checked = json.loads((ROOT/'artifacts/roundtrip-checked-setup.json').read_text())
        frames = {f.frame.reference_frame: MessageToDict(f.frame) for f in await robot.get_frame_system_config()}
        if not checked['preflight_passed'] or cfg != checked['poses'] or frames != checked['frames']:
            raise RuntimeError('Setup changed since route preview; review the changed setup first')
        await check_arm(arm)
        q = list((await arm.get_joint_positions(timeout=5)).values)
        if max(abs(a-b) for a,b in zip(q, checked['home_joints'])) > .1:
            raise RuntimeError('Start at the checked home position')
        if execute:
            report['execution_attempted'] = True; save()
            await run_sequence(arm, gripper, poses, {n:c['point'] for n,c in cfg.items()}, report, save)
            print('A -> B -> A round trip completed; arm home.', flush=True)
        else:
            print('Native saved poses match the checked route; arm stationary at home. No motion.')
    except BaseException as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'; save(); raise
    finally:
        await asyncio.wait_for(robot.close(), 5)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    with control_lock():
        asyncio.run(main(parser.parse_args().execute))
