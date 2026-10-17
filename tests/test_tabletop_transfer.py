import asyncio
import json
from unittest.mock import AsyncMock
import numpy as np
import pytest
import tabletop_transfer as module
from tabletop_transfer import surface_geometry, prepare_transfer, transfer_object, box


def test_depth_geometry_rotates_with_object_and_preserves_support_height():
    x, y = np.meshgrid(np.linspace(-45, 45, 40), np.linspace(-15, 15, 20))
    cloud = np.column_stack([x.ravel(), y.ravel(), np.full(x.size, 25.)])
    angle = np.deg2rad(37)
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    cloud[:, :2] = cloud[:, :2] @ rotation.T + [400, -300]
    g = surface_geometry(cloud, 5)
    np.testing.assert_allclose(g['center_top_world_mm'], [400, -300, 25], atol=.1)
    assert g['width_mm'] == pytest.approx(30)
    assert g['length_mm'] == pytest.approx(90)
    assert g['theta_degrees'] == pytest.approx(143)
    # High stereo outliers must not turn a broad flat top into a tiny corner.
    outliers = cloud[:60].copy()
    outliers[:, 2] += 16
    robust = surface_geometry(np.vstack([cloud, outliers]), 5)
    np.testing.assert_allclose(robust['center_top_world_mm'], g['center_top_world_mm'], atol=.1)
    assert robust['width_mm'] == pytest.approx(g['width_mm'])


def test_stacking_uses_support_top_and_keeps_fingers_above_table():
    source = dict(center_top_world_mm=[400, -300, 25], top_z_mm=25, bottom_z_mm=5,
                  length_mm=90, width_mm=30, theta_degrees=143, surface_residual_mm=1)
    support = source | dict(center_top_world_mm=[200, -200, 65], top_z_mm=65, length_mm=30)
    scene = {'table_surface_z_mm': 5, 'objects': [
        {'id': 'piece', 'world_mm': source['center_top_world_mm'], 'geometry': source},
        {'id': 'base', 'world_mm': support['center_top_world_mm'], 'geometry': support}]}
    command = dict(object_id='piece', action='place_on', target_id='base', target_xy=[200, -200])
    plan = prepare_transfer(scene, command)
    assert plan['target_top_z_mm'] == 86  # 65 support + 20 object + 1 release clearance.
    assert plan['tcp_grasp_z_mm'] - 50 > scene['table_surface_z_mm']
    assert plan['tcp_place_z_mm'] - plan['tcp_grasp_z_mm'] == 61
    assert np.linalg.norm(np.array(plan['target_xy']) - plan['source_xy']) > 200
    # Translation and restoring are not tied to a label or 5 cm maximum.
    plan = prepare_transfer(scene, command | dict(action='translate', target_id=None, target_xy=[600, -300]))
    assert plan['target_top_z_mm'] == 26
    history = [dict(object_id='piece', verified=True, before_support_z_mm=65,
                    after_support_z_mm=5, after_world_mm=[400, -300, 25], after_top_z_mm=25)]
    restored = prepare_transfer(scene, command | dict(action='restore', target_id=None), history)
    assert restored['target_top_z_mm'] == 86


def test_unmeasured_support_or_wrong_grasp_width_fails_before_robot_calls():
    g = dict(center_top_world_mm=[1, 2, 30], top_z_mm=30, bottom_z_mm=0,
             length_mm=100, width_mm=100, surface_residual_mm=1)
    scene = dict(table_surface_z_mm=0, objects=[dict(id='piece', world_mm=[1, 2, 30], geometry=g)])
    with pytest.raises(ValueError, match='width'):
        prepare_transfer(scene, dict(object_id='piece', target_xy=[20, 20]))


def test_distant_tall_object_does_not_force_every_transfer_to_a_high_plane():
    source = dict(center_top_world_mm=[540, -360, 22], top_z_mm=22, bottom_z_mm=8,
                  length_mm=82, width_mm=29, theta_degrees=212)
    scene = dict(table_surface_z_mm=8, objects=[dict(id='piece', world_mm=[540, -360, 22], geometry=source)])
    command = dict(object_id='piece', action='translate', target_xy=[555, -408])
    original = prepare_transfer(scene, command)
    tall = source | dict(center_top_world_mm=[300, -100, 150], top_z_mm=150)
    scene['objects'].append(dict(id='tall-neighbor', world_mm=[300, -100, 150], geometry=tall))
    plan = prepare_transfer(scene, command)
    assert plan['clearance_z_mm'] == original['clearance_z_mm']
    assert plan['clearance_z_mm'] - max(plan['tcp_grasp_z_mm'], plan['tcp_place_z_mm']) == 50
    assert plan['fallback_clearance_z_mm'] > plan['clearance_z_mm']
    assert plan['target_xy'] == command['target_xy']


def test_higher_route_remains_available_when_low_route_collides(monkeypatch):
    geom = dict(length_mm=80, width_mm=30, theta_degrees=20)
    seen = []
    async def preview(*args, **kwargs):
        candidate, execute = args[4:6]
        assert not execute
        seen.append(candidate['clearance_z_mm'])
        if candidate['clearance_z_mm'] == 120:
            raise module.NativePreviewError('Native carry preview: collision with neighbor')
        return {'preflight_passed': True}
    monkeypatch.setattr(module, '_transfer_object', preview)
    result = asyncio.run(transfer_object(None, None, None, {},
        dict(geometry=geom, clearance_z_mm=120, fallback_clearance_z_mm=250), False, {}, lambda: None))
    assert result['preflight_passed'] and seen[0] == 120 and seen[-1] == 250


def test_perpendicular_grasp_is_tried_when_it_fits_and_clears_a_neighbor(monkeypatch):
    geom = dict(length_mm=50, width_mm=24, theta_degrees=180)
    attempts = []
    async def preview(*args, **kwargs):
        candidate, execute = args[4:6]
        assert not execute
        attempts.append(candidate['grasp_theta_degrees'])
        if candidate['grasp_theta_degrees'] % 180 != 90:
            raise module.NativePreviewError('Native place preview: collision with neighbor')
        return {'preflight_passed': True}
    monkeypatch.setattr(module, '_transfer_object', preview)
    result = asyncio.run(transfer_object(None,None,None,{},
        dict(geometry=geom,clearance_z_mm=150),False,{},lambda:None))
    assert result['preflight_passed'] and any(a % 180 == 90 for a in attempts)


def test_reverse_approach_seed_retains_obstacles_and_restores_linear_constraint():
    from viam.proto.common import Pose, PoseInFrame
    request = {'componentName':'gripper', 'destination':{'pose':{'z':130}},
        'worldState':{'obstacles':[{'referenceFrame':'world','geometries':[{'label':'neighbor'}]}]},
        'constraints':{'linearConstraint':[{'lineToleranceMm':2}],
                       'collisionSpecification':[{'allows':[{'frame1':'gripper','frame2':'source'}]}]},
        'extra':{'start_state':{'configuration':{'arm':[1]*6}}}}
    motion = type('Motion',(),{})()
    motion.do_command = AsyncMock(side_effect=[{'plan':[{'arm':[.5]*6}]},{'plan':[{'arm':[.6]*6}]}])
    joints = asyncio.run(module.approach_from_grasp(motion,request,
        PoseInFrame(reference_frame='world',pose=Pose(z=180,o_z=-1)),[0]*6))
    np.testing.assert_allclose(joints,np.degrees([.6]*6))
    seed,reverse = [json.loads(c.args[0]['plan']) for c in motion.do_command.call_args_list]
    assert 'linearConstraint' not in seed['constraints']
    assert reverse['constraints'] == request['constraints']
    assert seed['worldState'] == reverse['worldState'] == request['worldState']
    assert seed['extra']['start_state']['configuration']['arm'] == [0]*6
    assert reverse['extra']['start_state']['configuration']['arm'] == [.5]*6


def test_alternate_grasp_keeps_object_orientation_and_never_executes_a_failed_plan(monkeypatch):
    geom = dict(center_top_world_mm=[0, 0, 25], top_z_mm=25, bottom_z_mm=0,
                length_mm=80, width_mm=30, theta_degrees=20)
    carried = box('held', geom, carried=True, tcp_z=65, grasp_theta=35)
    assert carried.center.theta == -15  # The object does not rotate when the jaws change angle.
    attempt = AsyncMock(side_effect=[module.NativePreviewError('Native grasp preview: collision'), {'passed': True}])
    monkeypatch.setattr(module, '_transfer_object', attempt)
    result = asyncio.run(transfer_object(None, None, None, {}, {'geometry': geom, 'clearance_z_mm': 120}, False, {}, lambda: None))
    assert result == {'passed': True}
    assert all(call.args[5] is False for call in attempt.call_args_list)
    assert attempt.call_args_list[1].args[4]['grasp_theta_degrees'] == 35
    attempt = AsyncMock(side_effect=module.NativePreviewError('Native grasp preview: collision'))
    monkeypatch.setattr(module, '_transfer_object', attempt)
    with pytest.raises(RuntimeError, match='No complete pick/place route'):
        asyncio.run(transfer_object(None, None, None, {}, {'geometry': geom, 'clearance_z_mm': 120}, True, {}, lambda: None))


def test_execute_checks_candidate_once_and_never_retries_an_execution_error(monkeypatch):
    transfer = dict(geometry=dict(length_mm=50,width_mm=24,theta_degrees=180),clearance_z_mm=120)
    attempt = AsyncMock(return_value={'preflight_passed':True})
    guard = AsyncMock()
    monkeypatch.setattr(module,'_transfer_object',attempt)
    asyncio.run(transfer_object(None,None,None,{},transfer,True,{},lambda:None,before_execute=guard))
    assert attempt.await_count == 1, 'Duplicate full planning pass before execution'
    assert attempt.call_args.args[5] is True and attempt.call_args.kwargs['before_execute'] is guard
    attempt = AsyncMock(side_effect=RuntimeError('Native execution collision'))
    monkeypatch.setattr(module,'_transfer_object',attempt)
    with pytest.raises(RuntimeError,match='Native execution collision'):
        asyncio.run(transfer_object(None,None,None,{},transfer,True,{},lambda:None))
    assert attempt.await_count == 1, 'Execution failures must stop, never try another grasp'
    attempt = AsyncMock(side_effect=module.NativePreviewError('Native approach preview: transport timeout'))
    monkeypatch.setattr(module,'_transfer_object',attempt)
    with pytest.raises(RuntimeError,match='transport timeout'):
        asyncio.run(transfer_object(None,None,None,{},transfer,True,{},lambda:None))
    assert attempt.await_count == 1, 'Transport failure does not justify grasp retries'
