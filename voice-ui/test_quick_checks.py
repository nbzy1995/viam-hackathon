"""Preset checks exercise planning, endpoint verification, and stop on failure."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import robot_prepare
import robot_checks


def setup(monkeypatch, tmp_path, module, start=None, fail=False):
    home = np.zeros(6)
    current = home.copy() if start is None else np.array(start)
    async def positions(**kw): return SimpleNamespace(values=current.tolist())
    arm = SimpleNamespace(get_joint_positions=positions, do_command=AsyncMock(), stop=AsyncMock())
    grip = SimpleNamespace(is_holding_something=AsyncMock(return_value=SimpleNamespace(is_holding_something=False)))
    async def plan(command, **kw):
        import json
        request = json.loads(command['plan'])['extra']
        return {'plan': [request['start_state']['configuration'], request['goal_state']['configuration']]}
    async def move(**kw):
        if fail: raise RuntimeError('transport interrupted')
        current[:] = np.degrees(kw['extra']['goal_state']['configuration']['arm'])
        return True
    motion = SimpleNamespace(do_command=AsyncMock(side_effect=plan), move=AsyncMock(side_effect=move))
    monkeypatch.setattr(module, 'validate_setup', AsyncMock())
    monkeypatch.setattr(module, 'check_arm', AsyncMock())
    monkeypatch.setattr(module.Gripper, 'from_robot', lambda *_: grip)
    monkeypatch.setattr(module.MotionClient, 'from_robot', lambda *_: motion)
    monkeypatch.setattr(robot_checks, '__file__', str(tmp_path/'voice-ui/robot_checks.py'))
    scene = SimpleNamespace(sweep=lambda *_: {'boundaries': {'wall-side': {'clearance_mm':60}}})
    controller = SimpleNamespace(robot=object(), arm=arm, checked={'home_joints':home.tolist()}, scene=scene)
    return controller, motion


def test_both_motion_legs_are_previewed_and_verified(monkeypatch,tmp_path):
    controller,motion=setup(monkeypatch,tmp_path,robot_checks)
    result=asyncio.run(robot_checks.motion_check(controller,lambda *a,**k: None))
    assert result['success'] and result['stages']==['turn','return']
    assert motion.do_command.await_count==2 and motion.move.await_count==2
    assert result['max_joint_error_degrees'] < .1


@pytest.mark.parametrize('kind',['prepare','motion'])
def test_motion_failure_stops_arm(monkeypatch,tmp_path,kind):
    module=robot_prepare if kind=='prepare' else robot_checks
    controller,motion=setup(monkeypatch,tmp_path,module,start=[1,0,0,0,0,0] if kind=='prepare' else None,fail=True)
    action=module.prepare_robot if kind=='prepare' else module.motion_check
    with pytest.raises(RuntimeError,match='interrupted'):
        asyncio.run(action(controller,lambda *a,**k: None))
    controller.arm.stop.assert_awaited_once()
    assert motion.move.await_count==1


def test_worker_imports_canonical_controller():
    import subprocess
    result=subprocess.run([sys.executable,'-c',
        "import sys;sys.path.insert(0,'voice-ui');import robot_worker, workshop_text;print(workshop_text.__file__)"],
        cwd=BASE.parent,text=True,capture_output=True,check=True)
    assert Path(result.stdout.strip()).resolve()==(BASE.parent/'workshop_text.py').resolve()
