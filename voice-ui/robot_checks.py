"""Repeatable demo checks; motion uses checked native plans and joint feedback."""
from datetime import datetime, timezone
import json
from pathlib import Path
import numpy as np
from viam.components.gripper import Gripper
from viam.services.motion import MotionClient
from workshop_static import check_arm
from workshop_vision import validate_setup
from robot_prepare import checked_home_path


async def robot_check(controller, notify):
    await validate_setup(controller.robot,controller.checked)
    await check_arm(controller.arm)
    joints=list((await controller.arm.get_joint_positions(timeout=5)).values)
    holding=(await Gripper.from_robot(controller.robot,'gripper').is_holding_something(timeout=5)).is_holding_something
    return {'outcome':'robot_checked','success':True,'joints_degrees':joints,'holding':holding,
            'at_home':max(abs(np.array(joints)-controller.checked['home_joints'])) <= .1}


async def motion_check(controller, notify):
    report={'at':datetime.now(timezone.utc).isoformat(),'kind':'motion_check','success':False,'execution_attempted':False,'stages':[]}
    output=Path(__file__).resolve().parents[1]/'artifacts/diagnosis'/f'fast-check-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json'
    def save():
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2)+'\n')
    try:
        status=await robot_check(controller,notify)
        if status['holding']: raise RuntimeError('Motion check requires an empty gripper')
        if not status['at_home']: raise RuntimeError('Motion check requires the checked home pose; prepare robot first')
        home=np.array(controller.checked['home_joints']);away=home.copy();away[0]+=5
        motion=MotionClient.from_robot(controller.robot,'builtin')
        start=np.array(status['joints_degrees']);previews=[]
        notify('progress',message='Checking both legs of the 5° motion check.')
        for goal in (away,home):
            request={'name':'builtin','componentName':'arm','extra':{'timeout':5,
                'start_state':{'configuration':{'arm':np.radians(start).tolist()}},
                'goal_state':{'configuration':{'arm':np.radians(goal).tolist()}}}}
            plan=await motion.do_command({'plan':json.dumps(request)},timeout=15)
            previews.append(checked_home_path(plan,start,goal,controller.scene));start=goal
        report['previews']=previews;save()
        status=await robot_check(controller,notify)
        if status['holding'] or max(abs(np.array(status['joints_degrees'])-home))>.05:
            raise RuntimeError('Robot changed during motion-check preview')
        await controller.arm.do_command({'set_speed':3.,'set_acceleration':6.},timeout=5)
        report['execution_attempted']=True;save()
        errors=[]
        for name,goal in [('turn',away),('return',home)]:
            notify('progress',message='Turning the arm 5°.' if name=='turn' else 'Returning to the ready pose.')
            if not await motion.move(component_name='arm',destination=None,timeout=120,
                    extra={'goal_state':{'configuration':{'arm':np.radians(goal).tolist()}}}):
                raise RuntimeError('Motion check move failed')
            await check_arm(controller.arm)
            actual=np.array((await controller.arm.get_joint_positions(timeout=5)).values)
            error=float(max(abs(actual-goal)))
            if error>.1:raise RuntimeError('Motion check endpoint differs from preview')
            report['stages'].append(name);errors.append(error);save()
        report.update(outcome='motion_checked',success=True,max_joint_error_degrees=max(errors),
                      final_joints_degrees=actual.tolist())
        return report
    except BaseException:
        if report['execution_attempted']:
            try:
                await controller.arm.stop(timeout=5);report['stop_requested']=True
            except Exception: report['stop_requested']=False
        raise
    finally:
        save();notify('report',path=str(output))
