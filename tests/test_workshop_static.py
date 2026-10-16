"""Failure handling tests use fakes; they never connect to the robot."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from workshop_static import NAMES, run_sequence


def station(*, holding=False, grab=True, failing_pose=None):
    arm = SimpleNamespace(is_moving=AsyncMock(return_value=False),
        do_command=AsyncMock(return_value={'error info': [0, 0]}),
        get_end_position=AsyncMock(return_value=SimpleNamespace(x=0., y=0., z=0.)),
        stop=AsyncMock())
    gripper = SimpleNamespace(
        is_holding_something=AsyncMock(return_value=SimpleNamespace(is_holding_something=holding)),
        open=AsyncMock(), grab=AsyncMock(return_value=grab))
    poses = {name: SimpleNamespace(set_position=AsyncMock()) for name in NAMES}
    if failing_pose:
        poses[failing_pose].set_position.side_effect = RuntimeError('motion failed')
    return arm, gripper, poses, {name: {'X': 0., 'Y': 0., 'Z': 0.} for name in NAMES}, {'stages': []}


def test_failed_grasp_does_not_carry_or_release():
    arm, gripper, poses, targets, report = station(grab=False)
    with pytest.raises(RuntimeError, match='Grab failed'):
        asyncio.run(run_sequence(arm, gripper, poses, targets, report))
    poses['travel-pose'].set_position.assert_not_awaited()
    assert gripper.open.await_count == 1  # only the pre-grasp opening
    arm.stop.assert_awaited_once()
    assert report['success'] is False


def test_initially_held_object_is_not_released():
    arm, gripper, poses, targets, report = station(holding=True)
    with pytest.raises(RuntimeError, match='empty gripper'):
        asyncio.run(run_sequence(arm, gripper, poses, targets, report))
    gripper.open.assert_not_awaited()
    for pose in poses.values():
        pose.set_position.assert_not_awaited()


def test_motion_failure_stops_without_release_or_retry():
    arm, gripper, poses, targets, report = station(failing_pose='above-place-pose')
    gripper.is_holding_something.side_effect = [
        SimpleNamespace(is_holding_something=False),
        SimpleNamespace(is_holding_something=True),
        SimpleNamespace(is_holding_something=True)]
    with pytest.raises(RuntimeError, match='motion failed'):
        asyncio.run(run_sequence(arm, gripper, poses, targets, report))
    poses['above-place-pose'].set_position.assert_awaited_once()
    poses['place-pose'].set_position.assert_not_awaited()
    assert gripper.open.await_count == 1
    arm.stop.assert_awaited_once()


def test_lost_grasp_prevents_carry():
    arm, gripper, poses, targets, report = station()
    with pytest.raises(RuntimeError, match='retain'):
        asyncio.run(run_sequence(arm, gripper, poses, targets, report))
    poses['travel-pose'].set_position.assert_not_awaited()
    arm.stop.assert_awaited_once()


def test_failed_regrasp_at_B_does_not_start_return():
    arm, gripper, poses, targets, report = station()
    gripper.grab.side_effect = [True, False]
    gripper.is_holding_something.side_effect = [
        SimpleNamespace(is_holding_something=v)
        for v in [False, True, True, True, True, False]]
    with pytest.raises(RuntimeError, match='Grab failed'):
        asyncio.run(run_sequence(arm, gripper, poses, targets, report))
    assert report['stages'][-1] == 'release-at-B'
    assert poses['above-place-pose'].set_position.await_count == 1
    arm.stop.assert_awaited_once()
