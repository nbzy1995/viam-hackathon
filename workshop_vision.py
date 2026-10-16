"""Native Viam vision + motion: one trigger runs A -> B -> A.

A carton left at B is first returned to A. Default is a preview of the next
transfer. --execute runs the cycle. The native segmenter's highest surface is
the cap; this small carton-specific grasp adjustment replaces the block offset.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from google.protobuf.json_format import MessageToDict
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.components.switch import Switch
from viam.services.motion import MotionClient
from viam.services.vision import VisionClient
from viam.proto.common import Pose, PoseInFrame
from viam.proto.service.motion import Constraints, LinearConstraint
from workshop_static import NAMES, check_arm, control_lock
from scene_sweep import Scene, pose_matrix

ROOT = Path(__file__).parent
STATIONS = {'A': (451.3, -509.), 'B': (391., -349.)}
SEARCH_RADIUS_MM = 200.
PLACEMENT_TOLERANCE_MM = 45.
# Higher and nearer the base: straight upward from home is unreachable.
OVERVIEW_XYZ = (250., -200., 700.6)
LINEAR = Constraints(linear_constraint=[LinearConstraint(line_tolerance_mm=2, orientation_tolerance_degs=2)])

class CartonNotVisible(RuntimeError):
    pass

def locate_carton(objects, camera_world):
    for obj in sorted(objects, key=lambda item: len(item.point_cloud), reverse=True):
        try:
            cap = cap_center(obj.point_cloud, camera_world)
        except (RuntimeError, ValueError):
            continue  # A blue tape segment is not an upright carton.
        station = min(STATIONS, key=lambda n: np.linalg.norm(cap[:2]-STATIONS[n]))
        if np.linalg.norm(cap[:2]-STATIONS[station]) > SEARCH_RADIUS_MM:
            raise RuntimeError('Carton is more than 20 cm from both stations')
        return cap, station
    raise CartonNotVisible('No upright carton resolved by native vision')

def verify_placement(cap, destination):
    # Search regions overlap at 20 cm; they must not become placement tolerances.
    if np.linalg.norm(cap[:2]-STATIONS[destination]) > PLACEMENT_TOLERANCE_MM:
        raise RuntimeError(f'Vision did not confirm placement at {destination}')

async def overview(robot, scene, checked, execute, report, save, scan):
    """Preview both empty-gripper legs, look from above once, then return home."""
    arm=Arm.from_robot(robot,'arm'); grip=Gripper.from_robot(robot,'gripper')
    motion=MotionClient.from_robot(robot,'builtin')
    await check_arm(arm)
    if (await grip.is_holding_something(timeout=5)).is_holding_something:
        raise RuntimeError('Overview requires an empty gripper')
    q=np.array((await arm.get_joint_positions(timeout=5)).values)
    if max(abs(q-np.array(checked['home_joints'])))>.1:
        raise RuntimeError('Overview must start from home')
    v=checked['poses']['home-pose']['orientation']
    p=PoseInFrame(reference_frame='world',pose=Pose(x=OVERVIEW_XYZ[0],y=OVERVIEW_XYZ[1],z=OVERVIEW_XYZ[2],o_x=v['x'],o_y=v['y'],o_z=v['z'],theta=v['th']))
    start=q.copy(); previews=[]
    for destination in (p,None):
        req={'name':'builtin','componentName':'arm','extra':{'timeout':5,'start_state':{'configuration':{'arm':np.radians(start).tolist()}}}}
        if destination is not None:req['destination']=MessageToDict(destination)
        else:req['extra']['goal_state']={'configuration':{'arm':np.radians(q).tolist()}}
        plan=await motion.do_command({'plan':json.dumps(req)},timeout=15)
        if any(w[k]!=plan['plan'][0][k] for w in plan['plan'] for k in w if k!='arm'):
            raise RuntimeError('Overview preview moves another resource')
        path=np.degrees([w['arm'] for w in plan['plan']]);sweep=scene.sweep(path,.5)
        if min(v['clearance_mm'] for v in sweep['boundaries'].values())<60:
            raise RuntimeError('Overview lacks workspace clearance')
        previews.append({'end_joints':path[-1].tolist(),'sweep':sweep});start=path[-1]
    record={'previews':previews,'executed':False};report.setdefault('overview_searches',[]).append(record);save()
    if not execute:
        raise CartonNotVisible('No carton at home view; higher overview preview passed. Use --execute to search physically.')
    if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-q))>.05:
        raise RuntimeError('Arm moved during overview preview')
    report['execution_attempted']=True;save()
    await arm.do_command({'set_speed':3.,'set_acceleration':6.},timeout=5)
    if not await motion.move(component_name='arm',destination=p,timeout=120):raise RuntimeError('Overview move failed')
    await check_arm(arm)
    if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-previews[0]['end_joints']))>.2:
        raise RuntimeError('Overview endpoint differs from preview')
    record['executed']=True;save()
    try:
        result=await scan()
        record['cap_world_mm']=result[0].tolist();save()
    finally:
        # Return only after a successfully completed overview move, never after a motion fault.
        await check_arm(arm)
        await Switch.from_robot(robot,'home-pose').set_position(2,timeout=120)
        await check_arm(arm)
        if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-q))>.1:
            raise RuntimeError('Overview did not return home')
        record['returned_home']=True;save()
    return result

def cap_center(pcd, camera_world):
    header, data = pcd.split(b'DATA binary\n', 1)
    if b'FIELDS x y z rgb\n' not in header or b'SIZE 4 4 4 4\n' not in header:
        raise RuntimeError('Unexpected native point-cloud format')
    points = np.frombuffer(data, dtype=[('x','<f4'),('y','<f4'),('z','<f4'),('rgb','<i4')])
    xyz = np.column_stack([points[k] for k in ('x','y','z')]) * 1000
    tf = pose_matrix(MessageToDict(camera_world.pose))
    world = xyz @ tf[:3,:3].T + tf[:3,3]*1000
    world = world[np.isfinite(world).all(axis=1) & (world[:,2]>70) & (world[:,2]<180)]
    if len(world)<500: raise RuntimeError('No upright carton in native segment')
    top = np.percentile(world[:,2],99)
    cap = world[world[:,2]>top-5]
    center, span = np.median(cap,axis=0), np.ptp(cap,axis=0)
    if len(cap)<100 or not 140<center[2]<160 or not all(15<span[:2]) or not all(span[:2]<45):
        raise RuntimeError('Native depth segment does not resolve the upright cap')
    return center

async def main(execute):
    c=json.loads((ROOT/'.env.viam.json').read_text())
    opts=RobotClient.Options.with_api_key(api_key=c['api_key'],api_key_id=c['api_key_id'])
    opts.dial_options.force_relay=True; opts.dial_options.initial_connection_attempts=1
    robot=await asyncio.wait_for(RobotClient.at_address(c['address'],opts),25)
    report={'at':datetime.now(timezone.utc).isoformat(),'execution_attempted':False,'success':False,'transfers':[]}
    output=ROOT/'artifacts/diagnosis'/f'vision-cycle-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
    def save(): output.write_text(json.dumps(report,indent=2))
    arm=Arm.from_robot(robot,'arm'); grip=Gripper.from_robot(robot,'gripper')
    motion=MotionClient.from_robot(robot,'builtin'); vision=VisionClient.from_robot(robot,'vision-segment')
    checked=json.loads((ROOT/'artifacts/roundtrip-checked-setup.json').read_text()); scene=Scene()
    async def observe():
        await check_arm(arm)
        q=np.array((await arm.get_joint_positions(timeout=5)).values)
        if max(abs(q-np.array(checked['home_joints'])))>.1: raise RuntimeError('Observe only from stationary home')
        async def scan():
            await check_arm(arm)
            before=np.array((await arm.get_joint_positions(timeout=5)).values)
            objects=await vision.get_object_point_clouds('cam',timeout=15)
            camera_world=await robot.transform_pose(PoseInFrame(reference_frame='cam',pose=Pose(o_z=1)),'world')
            await check_arm(arm)
            if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-before))>.05:
                raise RuntimeError('Arm moved during camera observation')
            return locate_carton(objects,camera_world)
        try:
            cap,station=await scan()
        except CartonNotVisible:
            cap,station=await overview(robot,scene,checked,execute,report,save,scan)
        return cap,station,q
    async def transfer(cap,source,q,dest):
        record={'source':source,'destination':dest,'cap_world_mm':cap.tolist(),'stages':[],'previews':[]}
        report['transfers'].append(record)
        def target(x,y,z): return PoseInFrame(reference_frame='world',pose=Pose(x=x,y=y,z=z,o_z=-1,theta=163))
        # TCP is 150 mm below flange. Fingers extend another 50 mm below TCP.
        grasp_z=float(cap[2]+20); x,y=map(float,cap[:2]); dx,dy=STATIONS[dest]
        approach=target(x,y,220); grasp=target(x,y,grasp_z)
        place=target(dx,dy,grasp_z+1)
        # Use the established B-side high transit, then the lower reachable A approach.
        steps=[('approach',approach,False,False),('grasp',grasp,True,False),
               ('lift',approach,True,True)]
        steps.append(('B-transit',target(*STATIONS['B'],300),False,True))
        steps += [('destination-approach',target(dx,dy,220),dest=='B',True),
                  ('place',place,True,True),('withdraw',target(dx,dy,220),True,False),
                  ('home',None,False,False)]
        start=q.copy()
        for name,p,linear,holding in steps:
            req={'name':'builtin','componentName':'gripper','extra':{'timeout':5,'start_state':{'configuration':{'arm':np.radians(start).tolist()}}}}
            if p is None:
                req['componentName']='arm';req['extra']['goal_state']={'configuration':{'arm':np.radians(checked['home_joints']).tolist()}}
            else: req['destination']=MessageToDict(p)
            if linear: req['constraints']=MessageToDict(LINEAR)
            plan=await motion.do_command({'plan':json.dumps(req)},timeout=15)
            if any(w[k]!=plan['plan'][0][k] for w in plan['plan'] for k in w if k!='arm'):
                raise RuntimeError('Preview moves another resource')
            path=np.degrees([w['arm'] for w in plan['plan']])
            if len(path)==1: path=np.vstack([path,path])
            sweep=scene.sweep(path,.5)
            if min(v['clearance_mm'] for v in sweep['boundaries'].values())<60: raise RuntimeError('Preview lacks workspace clearance')
            if holding and name not in ('lift','place'):
                for a,b in zip(path,path[1:]):
                    for point in np.linspace(a,b,max(2,int(np.ceil(max(abs(b-a))/.5))+1)):
                        tf=scene.forward(point)['link_eef'];px,py,pz=tf[:3,3]*1000
                        if not (tf[2,2]<-.9999 and pz>369.5 and px-70>-290 and py-70>-640 and pz+70<940):
                            raise RuntimeError('Carrying preview leaves checked carton envelope')
            record['previews'].append({'name':name,'sweep':sweep,'end_joints':path[-1].tolist()})
            start=path[-1]
        record['preflight_passed']=True;save();print(f'{source} -> {dest}: native previews passed; cap {np.round(cap,1).tolist()}',flush=True)
        if not execute:return
        if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-q))>.05: raise RuntimeError('Arm moved during preview')
        if (await grip.is_holding_something(timeout=5)).is_holding_something: raise RuntimeError('Expected empty gripper')
        report['execution_attempted']=True;save()
        await arm.do_command({'set_speed':3.,'set_acceleration':6.},timeout=5)
        await grip.open(timeout=15)
        # Resolve approach in camera frame before leaving home, as in the tutorial.
        approach_cam=await robot.transform_pose(approach,'cam')
        for i,(name,p,linear,holding) in enumerate(steps):
            await check_arm(arm);record['pending']=name;save()
            if name=='home': await Switch.from_robot(robot,'home-pose').set_position(2,timeout=120)
            else:
                destination=approach_cam if name=='approach' else p
                if name=='grasp':destination=PoseInFrame(reference_frame='gripper',pose=Pose(z=220-grasp_z,o_z=1))
                if not await motion.move(component_name='gripper',destination=destination,constraints=LINEAR if linear else None,timeout=120):
                    raise RuntimeError(f'{name} failed')
            await check_arm(arm)
            if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values)-record['previews'][i]['end_joints']))>.2:
                raise RuntimeError('Endpoint differs from preview')
            if name=='grasp' and not await grip.grab(timeout=15):raise RuntimeError('Native Grab failed; no carry attempted')
            if (holding or name=='grasp') and not (await grip.is_holding_something(timeout=5)).is_holding_something:
                raise RuntimeError('Grasp not retained')
            if name=='place':
                await grip.open(timeout=15)
                if (await grip.is_holding_something(timeout=5)).is_holding_something:raise RuntimeError('Release failed')
                await asyncio.sleep(.5)
            record['stages'].append(name);record['pending']=None;save();print(f'{source}->{dest}: {name}',flush=True)
        record['success']=True;save()
    try:
        frames={f.frame.reference_frame:MessageToDict(f.frame) for f in await robot.get_frame_system_config()}
        configs={n:json.loads((await Switch.from_robot(robot,n).do_command({'cfg':True},timeout=5))['as_json']) for n in NAMES}
        if frames!=checked['frames'] or configs!=checked['poses']:raise RuntimeError('Checked station setup changed')
        if await robot.get_operations():raise RuntimeError('Another robot operation is active')
        cap,station,q=await observe()
        if station=='B':
            await transfer(cap,station,q,'A')
            if not execute:return
            cap,station,q=await observe()
            verify_placement(cap,'A')
        for dest in ['B','A']:
            await transfer(cap,station,q,dest)
            if not execute:return
            cap,station,q=await observe()
            verify_placement(cap,dest)
        report['success']=True;save();print('Vision-guided A -> B -> A completed; carton at A, arm home.',flush=True)
    except BaseException as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
        if report['execution_attempted']:
            try:await arm.stop(timeout=5);report['stop_requested']=True
            except Exception as stop:report['stop_error']=str(stop)
        save();raise
    finally:await asyncio.wait_for(robot.close(),5)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    with control_lock():asyncio.run(main(parser.parse_args().execute))
