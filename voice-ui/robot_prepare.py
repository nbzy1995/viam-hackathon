"""Return an empty arm to its checked observation pose through a validated plan."""
import json
import numpy as np
from viam.components.gripper import Gripper
from viam.services.motion import MotionClient
from workshop_static import check_arm
from workshop_vision import validate_setup


def checked_home_path(plan, start, home, scene):
    waypoints = plan.get('plan', [])
    if not waypoints or any('arm' not in w for w in waypoints):
        raise RuntimeError('Preparation planner returned no arm path')
    if any(w[k] != waypoints[0][k] for w in waypoints for k in w if k != 'arm'):
        raise RuntimeError('Preparation preview moves another resource')
    path = np.degrees([w['arm'] for w in waypoints])
    if path.shape[1:] != (6,) or not np.isfinite(path).all():
        raise RuntimeError('Preparation preview has invalid joints')
    if max(abs(path[0] - start)) > .1 or max(abs(path[-1] - home)) > .1:
        raise RuntimeError('Preparation preview endpoints differ from requested joints')
    if len(path) == 1: path = np.vstack([path,path])
    sweep = scene.sweep(path,.5)
    for name,finding in sweep['boundaries'].items():
        required = 50 if name.startswith('wall-') else 0
        if finding['clearance_mm'] < required:
            raise RuntimeError(f'Preparation lacks clearance at {name}')
    return sweep


async def prepare_robot(controller, notify):
    robot, arm = controller.robot, controller.arm
    await validate_setup(robot,controller.checked)
    await check_arm(arm)
    grip = Gripper.from_robot(robot,'gripper')
    if (await grip.is_holding_something(timeout=5)).is_holding_something:
        raise RuntimeError('Preparation requires an empty gripper')
    start = np.array((await arm.get_joint_positions(timeout=5)).values)
    home = np.array(controller.checked['home_joints'])
    if max(abs(start-home)) <= .1:
        return {'outcome':'ready','success':True}
    motion = MotionClient.from_robot(robot,'builtin')
    goal = {'configuration':{'arm':np.radians(home).tolist()}}
    request = {'name':'builtin','componentName':'arm','extra':{'timeout':5,
        'start_state':{'configuration':{'arm':np.radians(start).tolist()}},'goal_state':goal}}
    notify('progress',message='Checking the path to the observation pose.')
    plan = await motion.do_command({'plan':json.dumps(request)},timeout=15)
    sweep = checked_home_path(plan,start,home,controller.scene)
    await validate_setup(robot,controller.checked)
    await check_arm(arm)
    if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-start)) > .05:
        raise RuntimeError('Arm moved during preparation preview')
    if (await grip.is_holding_something(timeout=5)).is_holding_something:
        raise RuntimeError('Gripper state changed during preparation preview')
    notify('progress',message='Returning to the checked observation pose.')
    await arm.do_command({'set_speed':3.,'set_acceleration':6.},timeout=5)
    try:
        if not await motion.move(component_name='arm',destination=None,timeout=120,extra={'goal_state':goal}):
            raise RuntimeError('Preparation move failed')
        await check_arm(arm)
        if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-home)) > .1:
            raise RuntimeError('Preparation endpoint differs from checked observation pose')
    except BaseException:
        await arm.stop(timeout=5)
        raise
    return {'outcome':'ready','success':True,'preparation_sweep':sweep}
