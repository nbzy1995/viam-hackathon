"""Robot adapter tests: fake SDK only; never connect to hardware."""
import asyncio
import fcntl
import importlib.util
import json
from pathlib import Path
import sys
import types

BASE = Path(__file__).parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker(monkeypatch, tmp_path, result=None, wait=False):
    events = []
    class Arm:
        stops = 0
        async def stop(self, **kwargs): self.stops += 1
    arm = Arm()
    class Controller:
        def __init__(self, robot, **kwargs): self.arm = arm
        async def run(self, request):
            if wait: await asyncio.Event().wait()
            return result
    monkeypatch.setitem(sys.modules, 'workshop_text', types.SimpleNamespace(TextController=Controller))
    monkeypatch.syspath_prepend(str(BASE))
    module = load('fake_worker', 'robot_worker.py')
    monkeypatch.setattr(module, 'emit', lambda event, **kw: events.append(dict(event=event, **kw)))
    class Robot:
        closed = False
        async def close(self): self.closed = True
    robot = Robot()
    async def connect(*args): return robot
    monkeypatch.setattr(module.RobotClient, 'at_address', connect)
    (tmp_path / '.arm-control.lock').touch()
    (tmp_path / '.env.viam.json').write_text(json.dumps(dict(api_key='fake',api_key_id='00000000-0000-0000-0000-000000000000',address='fake')))
    monkeypatch.setattr(module, 'SOURCE', tmp_path)
    return module, events, arm, robot


def test_completion_is_based_on_executor_result(monkeypatch, tmp_path):
    module, events, arm, robot = worker(monkeypatch,tmp_path,dict(outcome='completed',success=True))
    async def check(): await module.run('request', asyncio.StreamReader())
    asyncio.run(check())
    assert 'verified' in events[-1]['text']
    assert robot.closed and arm.stops == 0


def test_failure_never_claims_completed(monkeypatch, tmp_path):
    module, events, _, _ = worker(monkeypatch,tmp_path,dict(error='Camera verification failed'))
    async def check(): await module.run('request', asyncio.StreamReader())
    asyncio.run(check())
    assert 'No object transfer was started' in events[-1]['text']


def test_stop_preempts_running_task(monkeypatch,tmp_path):
    module, events, arm, robot = worker(monkeypatch,tmp_path,wait=True)
    async def check():
        reader=asyncio.StreamReader()
        task=asyncio.create_task(module.run('request',reader))
        await asyncio.sleep(.02)
        reader.feed_data(b'/stop\n')
        await asyncio.wait_for(task,1)
    asyncio.run(check())
    assert arm.stops >= 1 and robot.closed
    assert 'stop acknowledged' in events[-1]['text']


def test_buffered_stop_is_not_lost(monkeypatch,tmp_path):
    module, events, arm, robot = worker(monkeypatch,tmp_path,wait=True)
    async def check():
        reader=asyncio.StreamReader(); reader.feed_data(b'/stop\n')
        await asyncio.wait_for(module.run('request',reader),1)
    asyncio.run(check())
    assert arm.stops >= 1 and robot.closed


def test_shared_lock_blocks_robot_connection(monkeypatch,tmp_path):
    module, events, arm, robot = worker(monkeypatch,tmp_path)
    async def forbidden(*args): raise AssertionError('Robot must not connect while lock is held')
    monkeypatch.setattr(module.RobotClient,'at_address',forbidden)
    with (tmp_path/'.arm-control.lock').open('r') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        async def check(): await module.run('request',asyncio.StreamReader())
        asyncio.run(check())
    assert 'existing workshop console' in events[-1]['text']
    assert arm.stops == 0


def test_stop_during_subprocess_startup(monkeypatch):
    bridge=load('robot_bridge_test','robot_bridge.py')
    class Input:
        data=b''
        def write(self,data): self.data+=data
        async def drain(self): pass
    class Process:
        returncode=0
        stdin=Input()
        stdout=None
        async def wait(self): return 0
    process=Process()
    async def check():
        process.stdout=asyncio.StreamReader()
        process.stdout.feed_data(b'{"event":"answer","text":"Stopped"}\n');process.stdout.feed_eof()
        harness=bridge.RobotHarness()
        async def create(*args,**kwargs):
            assert 'ELEVENLABS_API_KEY' not in kwargs['env']
            await harness.stop()
            return process
        monkeypatch.setattr(asyncio,'create_subprocess_exec',create)
        assert await harness.reply([dict(content='request')]) == 'Stopped'
        assert process.stdin.data == b'request\n/stop\n'
        assert harness.process is None
    asyncio.run(check())


def test_preparation_path_checks_endpoints_resources_and_clearance(monkeypatch,tmp_path):
    import numpy as np
    import pytest
    worker(monkeypatch,tmp_path)
    prepare=load('robot_prepare_test','robot_prepare.py')
    class Scene:
        clearance=60
        def sweep(self,path,step):
            return {'boundaries':{'wall-front':{'clearance_mm':self.clearance},'table':{'clearance_mm':10}}}
    scene=Scene();start=np.zeros(6);home=np.ones(6)
    plan={'plan':[{'arm':np.radians(start).tolist(),'other':[0]}, {'arm':np.radians(home).tolist(),'other':[0]}]}
    assert prepare.checked_home_path(plan,start,home,scene)
    with pytest.raises(RuntimeError,match='endpoints'):
        prepare.checked_home_path(plan,start,home+1,scene)
    plan['plan'][1]['other']=[1]
    with pytest.raises(RuntimeError,match='another resource'):
        prepare.checked_home_path(plan,start,home,scene)
    plan['plan'][1]['other']=[0];scene.clearance=49
    with pytest.raises(RuntimeError,match='clearance'):
        prepare.checked_home_path(plan,start,home,scene)


def test_result_narration_distinguishes_planning_failure_from_motion_failure():
    messages=load('robot_messages_test','robot_messages.py')
    assert 'No object transfer' in messages.task_answer({'error':'Native preview collision','execution_attempted':False})
    text=messages.task_answer({'error':'Camera verification failed','execution_attempted':True,'stop_requested':True})
    assert 'could not be verified' in text and 'acknowledged a stop' in text
    assert 'Task completed' not in messages.task_answer({'outcome':'completed','success':False})
    assert '1.2 mm' in messages.task_answer({'outcome':'completed','success':True,'verification':{'error_mm':1.2}})
