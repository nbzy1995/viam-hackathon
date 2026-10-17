import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import workshop_vision as module


def test_scene_queries_do_not_block_control_but_motion_and_unknown_operations_do(monkeypatch):
    robot = SimpleNamespace(get_frame_system_config=AsyncMock(return_value=[]),get_operations=AsyncMock())
    config = SimpleNamespace(do_command=AsyncMock(return_value={'as_json':json.dumps({})}))
    monkeypatch.setattr(module.Switch,'from_robot',lambda *_:config)
    checked={'frames':{},'poses':{n:{} for n in module.NAMES}}
    reads=['/viam.service.vision.v1.VisionService/GetObjectPointClouds','/viam.robot.v1.RobotService/GetPose']
    robot.get_operations.return_value=[SimpleNamespace(method=m) for m in reads]
    asyncio.run(module.validate_setup(robot,checked))
    for method in ('/viam.service.motion.v1.MotionService/Move',
                   '/viam.component.gripper.v1.GripperService/Grab',
                   '/viam.component.arm.v1.ArmService/DoCommand','unknown'):
        robot.get_operations.return_value=[SimpleNamespace(method=m) for m in [*reads,method]]
        with pytest.raises(RuntimeError,match='operation is active'):
            asyncio.run(module.validate_setup(robot,checked))
