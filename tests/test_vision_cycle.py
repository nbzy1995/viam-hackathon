"""The UI and CLI share one cycle; only verified placements can finish it."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
import workshop_vision as vision


@pytest.mark.parametrize('method,allowed', [
    ('/viam.component.camera.v1.CameraService/GetImages', True),
    ('/viam.service.vision.v1.VisionService/GetDetections', True),
    ('/viam.component.arm.v1.ArmService/GetJointPositions', True),
    ('/viam.component.arm.v1.ArmService/MoveToJointPositions', False),
    ('/viam.component.arm.v1.ArmService/DoCommand', False),
])
def test_dashboard_reads_can_coexist_but_control_operations_still_block(monkeypatch, method, allowed):
    robot = SimpleNamespace(get_frame_system_config=AsyncMock(return_value=[]),
                            get_operations=AsyncMock(return_value=[SimpleNamespace(method=method)]))
    monkeypatch.setattr(vision.Switch, 'from_robot', lambda *_: SimpleNamespace(
        do_command=AsyncMock(return_value={'as_json': '{}'})))
    checked = {'frames': {}, 'poses': {name: {} for name in vision.NAMES}}
    if allowed:
        asyncio.run(vision.validate_setup(robot, checked))
    else:
        with pytest.raises(RuntimeError, match='Another robot operation'):
            asyncio.run(vision.validate_setup(robot, checked))


def fixture(monkeypatch, tmp_path, *, initial='A', failure=None, wrong_placement=False):
    monkeypatch.setattr(vision, 'ROOT', tmp_path)
    monkeypatch.setattr(vision, 'validate_setup', AsyncMock())
    arm = SimpleNamespace(stop=AsyncMock())
    monkeypatch.setattr(vision.Arm, 'from_robot', lambda *_: arm)
    state = {'station': initial, 'legs': [], 'observations': 0}
    async def observe(*args):
        state['observations'] += 1
        station = state['station']
        cap = np.array([*vision.STATIONS[station], 150.])
        if wrong_placement and state['legs']: cap[:2] += 100
        return cap, station, np.zeros(6)
    async def transfer(robot,scene,checked,execute,report,save,cap,source,q,dest,**kwargs):
        state['legs'].append((source,dest))
        kwargs['progress']('Native previews passed')
        if failure == 'preview': raise RuntimeError('Preview lacks workspace clearance')
        if execute:
            report['execution_attempted'] = True
            if failure == 'motion': raise RuntimeError('Grasp not retained')
            if failure == 'cancel': raise asyncio.CancelledError()
            state['station'] = dest
    monkeypatch.setattr(vision,'observe_carton',observe)
    monkeypatch.setattr(vision,'transfer_carton',transfer)
    return state, arm


@pytest.mark.parametrize('initial,expected', [('A',[('A','B'),('B','A')]),('B',[('B','A'),('A','B'),('B','A')])])
def test_cycle_redetects_and_verifies_each_leg(monkeypatch,tmp_path,initial,expected):
    state,arm=fixture(monkeypatch,tmp_path,initial=initial)
    events=[]
    result=asyncio.run(vision.run_cycle(None,None,{},True,notify=lambda event,**data:events.append((event,data))))
    assert result['success'] and result['outcome']=='roundtrip_completed'
    assert state['legs']==expected and state['observations']==len(expected)+1
    assert [v['destination'] for v in result['verifications']]==[b for a,b in expected]
    assert all(v['error_mm']==0 for v in result['verifications'])
    assert any(e=='progress' for e,d in events)
    assert list((tmp_path/'artifacts/diagnosis').glob('vision-cycle-*.json'))
    arm.stop.assert_not_awaited()


def test_preview_cannot_claim_round_trip_completion(monkeypatch,tmp_path):
    state,arm=fixture(monkeypatch,tmp_path)
    result=asyncio.run(vision.run_cycle(None,None,{},False))
    assert result['outcome']=='preview_passed' and not result['success']
    assert not result['execution_attempted'] and state['observations']==1


@pytest.mark.parametrize('failure,stop', [('preview',False),('motion',True)])
def test_failure_never_proceeds_to_next_leg(monkeypatch,tmp_path,failure,stop):
    state,arm=fixture(monkeypatch,tmp_path,failure=failure)
    result=asyncio.run(vision.run_cycle(None,None,{},True))
    assert not result['success'] and result['error']
    assert len(state['legs'])==1 and arm.stop.await_count==int(stop)


def test_bad_placement_stops_before_return_leg(monkeypatch,tmp_path):
    state,arm=fixture(monkeypatch,tmp_path,wrong_placement=True)
    result=asyncio.run(vision.run_cycle(None,None,{},True))
    assert not result['success'] and 'placement' in result['error']
    assert len(state['legs'])==1
    arm.stop.assert_awaited_once()


def test_cancel_preserves_stop_and_propagates(monkeypatch,tmp_path):
    state,arm=fixture(monkeypatch,tmp_path,failure='cancel')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(vision.run_cycle(None,None,{},True))
    arm.stop.assert_awaited_once()


@pytest.mark.parametrize('cancel', [False, True])
def test_overview_takes_three_views_and_never_moves_home_after_cancel(monkeypatch, cancel):
    arm = SimpleNamespace(get_joint_positions=AsyncMock(return_value=SimpleNamespace(values=[0.]*6)),
                          do_command=AsyncMock())
    grip = SimpleNamespace(is_holding_something=AsyncMock(return_value=SimpleNamespace(is_holding_something=False)))
    motion = SimpleNamespace(do_command=AsyncMock(return_value={'plan': [{'arm': [0.]*6}, {'arm': [0.]*6}]}),
                             move=AsyncMock(return_value=True))
    home = SimpleNamespace(set_position=AsyncMock())
    for cls, value in [(vision.Arm, arm), (vision.Gripper, grip), (vision.MotionClient, motion), (vision.Switch, home)]:
        monkeypatch.setattr(cls, 'from_robot', lambda *args, value=value: value)
    monkeypatch.setattr(vision, 'check_arm', AsyncMock())
    scene = SimpleNamespace(sweep=lambda *args: {'boundaries': {'table': {'clearance_mm': 100}}})
    checked = {'home_joints': [0.]*6, 'poses': {'home-pose': {'orientation': {'x':0,'y':0,'z':-1,'th':90}}}}
    scan = AsyncMock(side_effect=asyncio.CancelledError() if cancel else [{'view': 1}, {'view': 2}, {'view': 3}])
    call = vision.overview(None, scene, checked, True, {}, lambda: None, scan, angles=(0., -15., 15.))
    if cancel:
        with pytest.raises(asyncio.CancelledError): asyncio.run(call)
        home.set_position.assert_not_called()
    else:
        assert asyncio.run(call) == [{'view':1}, {'view':2}, {'view':3}]
        assert motion.move.await_count == 3
        home.set_position.assert_awaited_once()


def test_carton_reuses_grasp_branch_helper_before_any_execution(monkeypatch):
    import tabletop_transfer
    requests = []
    async def plan(command, **kwargs):
        requests.append(json.loads(command['plan']))
        if len(requests) == 2:
            raise RuntimeError('linear with cbirrt not allowed and no direct solutions found')
        return {'plan': [{'arm': [0.]*6}, {'arm': [0.]*6}]}
    motion = SimpleNamespace(do_command=plan, move=AsyncMock())
    monkeypatch.setattr(vision.MotionClient, 'from_robot', lambda *args: motion)
    monkeypatch.setattr(vision.Arm, 'from_robot', lambda *args: object())
    monkeypatch.setattr(vision.Gripper, 'from_robot', lambda *args: object())
    branch = AsyncMock(return_value=[0.]*6)
    monkeypatch.setattr(tabletop_transfer, 'approach_from_grasp', branch)
    tf = np.diag([1., -1., -1., 1.]); tf[2, 3] = .4
    scene = SimpleNamespace(sweep=lambda *args: {'boundaries': {'table': {'clearance_mm': 100}}},
                            forward=lambda *args: {'link_eef': tf})
    report = {'transfers': []}
    asyncio.run(vision.transfer_carton(None, scene, {'home_joints': [0.]*6}, False, report,
        lambda: None, np.array([387., -429., 144.]), 'A', np.zeros(6), 'your marker',
        destination_xy=[475.9, -241.7], via_b=True, progress=lambda message: None))
    branch.assert_awaited_once()
    assert requests[2]['componentName'] == 'arm' and 'goal_state' in requests[2]['extra']
    assert report['transfers'][0]['approach_branch_retry']
    assert report['transfers'][1]['preflight_passed']
    assert len(report['transfers'][1]['previews']) == 8
    motion.move.assert_not_called()
