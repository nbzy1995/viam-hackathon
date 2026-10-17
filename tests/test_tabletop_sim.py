"""Isolation and independent state evolution of the kinematic test adapter."""
import asyncio
import numpy as np
import pytest

from tabletop_sim import TabletopSim


class Geometry:
    def forward(self, joints):
        pose = np.diag([1., -1., -1., 1.])
        pose[:3, 3] = np.asarray(joints[:3]) / 1000
        return {'link_eef': pose}


def make_sim(planner=None, faults=None):
    frame = {'poseInObserverFrame': {'referenceFrame': 'arm', 'pose': {'oZ': 1}}}
    checked = {'home_joints': [100, 200, 60, 0, 0, 0],
               'frames': {'cam': frame, 'gripper': frame}, 'poses': {'home-pose': {}}}
    fixture = {'table_z_mm': 0, 'image_right_xy': [1, 0], 'image_up_xy': [0, 1],
               'objects': [{'id': 'thing', 'label': 'red block', 'center_xy_mm': [100, 200],
                            'size_xyz_mm': [40, 20, 20], 'yaw_deg': 0}]}
    return TabletopSim(planner, checked, Geometry(), fixture, faults)


def test_object_follows_actual_fk_without_task_or_expected_target():
    async def run():
        sim = make_sim()
        assert await sim.gripper.grab()
        sim.set_joints([137, 191, 100, 0, 0, 0])
        assert sim.objects['thing']['world_mm'] == pytest.approx([137, 191, 60])
        await sim.gripper.open()
        assert sim.objects['thing']['world_mm'] == pytest.approx([137, 191, 20])
        assert sim.holding is None
    asyncio.run(run())


def test_bad_grasp_does_not_attach_or_move_object():
    async def run():
        sim = make_sim()
        sim.set_joints([150, 200, 60, 0, 0, 0])
        assert not await sim.gripper.grab()
        sim.set_joints([200, 300, 100, 0, 0, 0])
        assert sim.objects['thing']['world_mm'] == [100, 200, 20]
    asyncio.run(run())


def test_only_native_plan_can_cross_real_client_boundary():
    async def run():
        sent = []
        async def planner(command, **kwargs):
            sent.append(command)
            return {'plan': [{'arm': [0] * 6}]}
        sim = make_sim(planner)
        for command in ({'move': {}}, {'plan': '{}'}, {'plan': '{}', 'execute': True}):
            with pytest.raises(RuntimeError):
                await sim.motion.do_command(command)
        await sim.arm.do_command({'get_error': True})
        await sim.arm.stop()
        await sim.gripper.open()
        assert not sent
        await sim.native_plan({'plan': '{"componentName":"arm","name":"builtin"}'})
        assert len(sent) == 1 and set(sent[0]) == {'plan'}
    asyncio.run(run())


def test_one_shot_release_fault_is_not_success_and_logs_empty_open():
    async def run():
        sim = make_sim(faults={'release': {'kind': 'rpc_error', 'occurrence': 1}})
        await sim.gripper.open()
        assert sim.events[-1]['event'] == 'gripper_open'
        assert await sim.gripper.grab()
        with pytest.raises(RuntimeError, match='release RPC'):
            await sim.gripper.open()
        assert sim.holding == 'thing'
        await sim.gripper.open()
        assert sim.holding is None
        assert len([e for e in sim.events if e['event'] == 'fault']) == 1
    asyncio.run(run())


def test_visibility_changes_observation_not_physical_world_and_preserves_axes():
    async def run():
        sim = make_sim()
        sim.visible_ids_before, sim.visible_ids_after_overview = [], ['thing']
        assert sim.scene_snapshot()['objects'] == []
        assert 'thing' in sim.objects
        scene = await sim.capture_scene(None, None, None, high=True)
        assert scene['objects'][0]['view_directions']['image_right_world_xy_unit'] == [1, 0]
        assert sim.scene_snapshot()['objects'][0]['id'] == 'thing'
    asyncio.run(run())


def test_execution_uses_checked_native_path_without_remote_move():
    async def run():
        sent = []
        async def planner(command, **kwargs):
            sent.append(command)
            return {'plan': [{'arm': np.radians([101, 202, 63, 0, 0, 0]).tolist()}]}
        sim = make_sim(planner)
        extra = {'goal_state': {'configuration': {'arm': [0] * 6}}}
        import json
        await sim.native_plan({'plan': json.dumps({'name': 'builtin', 'componentName': 'arm', 'extra': extra})})
        await sim.motion.move(component_name='arm', destination=None, extra=extra)
        assert sim.joints == pytest.approx([101, 202, 63, 0, 0, 0])
        assert len(sent) == 1 and set(sent[0]) == {'plan'}
        assert any(e['event'] == 'simulated_move' for e in sim.events)
    asyncio.run(run())
