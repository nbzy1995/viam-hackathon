"""Offline command-loop checks; no Viam network or robot operations."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def console(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        'persistent_sim_test_module', Path(__file__).with_name('persistent_sim.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'qa-console' / 'persistent_sim.py'))
    (tmp_path / '.env.viam.json').write_text(json.dumps(
        {'address': 'unused.invalid', 'api_key_id': '00000000-0000-0000-0000-000000000000', 'api_key': 'test-key'}))
    return module


def run_console(module, monkeypatch, commands, available):
    calls = {'connect': 0, 'close': 0, 'status': 0, 'moves': [], 'targets': []}

    class Robot:
        resource_names = [SimpleNamespace(name='qa-sim-arm')] if available else []

        async def get_machine_status(self):
            calls['status'] += 1

        async def close(self):
            calls['close'] += 1

    class SimArm:
        async def move_to_position(self, pose, **kwargs):
            self.pose = pose
            calls['moves'].append((pose.x, pose.y, pose.z))

        async def get_end_position(self, **kwargs):
            return self.pose

        async def is_moving(self, **kwargs):
            return False

    async def connect(*args, **kwargs):
        calls['connect'] += 1
        return Robot()

    def arm_handle(robot, name):
        calls['targets'].append(name)
        assert name == 'qa-sim-arm'
        return SimArm()

    monkeypatch.setattr(module.RobotClient, 'at_address', connect)
    monkeypatch.setattr(module.Arm, 'from_robot', arm_handle)
    monkeypatch.setattr(module.sys, 'stdin', io.StringIO(commands))
    asyncio.run(module.main())
    return calls


def test_two_moves_share_one_connection(console, monkeypatch, capsys):
    calls = run_console(console, monkeypatch, 'status\nA\nB\nquit\n', True)
    assert calls == {'connect': 1, 'close': 1, 'status': 1,
                     'moves': [(400, -130, 320), (400, 130, 320)],
                     'targets': ['qa-sim-arm', 'qa-sim-arm']}
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(x['passed'] for x in results if x.get('motion_sent'))


def test_unavailable_simulator_sends_no_motion(console, monkeypatch, capsys):
    calls = run_console(console, monkeypatch, 'A\nB\nquit\n', False)
    assert calls['moves'] == calls['targets'] == []
    assert calls['connect'] == calls['close'] == 1
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [x['motion_sent'] for x in results if 'motion_sent' in x] == [False, False]


def test_unknown_commands_do_not_address_an_arm(console, monkeypatch):
    calls = run_console(console, monkeypatch, 'arm\nreset\nquit\n', True)
    assert calls['moves'] == calls['targets'] == []
    assert calls['close'] == 1
