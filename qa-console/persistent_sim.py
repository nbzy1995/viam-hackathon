# /// script
# requires-python = ">=3.11"
# dependencies = ["viam-sdk==0.84.0"]
# ///
"""Persistent Viam SDK console restricted to qa-sim-arm.

Run: uv run python -u qa-console/persistent_sim.py
Commands: status, A, B, quit. A/B are synthetic rehearsal poses in mm,
not the physical blue markers. Never targets the real arm or gripper.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.proto.common import Pose

TARGET = 'qa-sim-arm'
POSES = {'A': (400, -130, 320), 'B': (400, 130, 320)}


def emit(**data):
    print(json.dumps({'pid': os.getpid(), **data}), flush=True)


async def main():
    credentials = json.loads((Path(__file__).resolve().parents[1] / '.env.viam.json').read_text())
    options = RobotClient.Options.with_api_key(
        api_key=credentials['api_key'], api_key_id=credentials['api_key_id'])
    options.dial_options.force_relay = True
    options.dial_options.initial_connection_attempts = 1
    options.dial_options.initial_connection_attempt_timeout = 15
    started = time.perf_counter()
    robot = await asyncio.wait_for(RobotClient.at_address(credentials['address'], options), 25)
    emit(event='connected', connection_ms=round((time.perf_counter()-started)*1000, 1),
         target=TARGET, commands=['status', 'A', 'B', 'quit'])
    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line or line.strip().lower() == 'quit':
                break
            command = line.strip()
            started = time.perf_counter()
            if command.lower() == 'status':
                try:
                    await asyncio.wait_for(robot.get_machine_status(), 5)
                    emit(command='status', rpc_ms=round((time.perf_counter()-started)*1000, 1),
                         simulator_available=TARGET in [x.name for x in robot.resource_names])
                except Exception as exc:
                    emit(command='status', error=str(exc))
                continue
            if command.upper() not in POSES:
                emit(error='Use status, A, B, or quit.')
                continue
            if TARGET not in [x.name for x in robot.resource_names]:
                emit(command=command.upper(), motion_sent=False,
                     error='qa-sim-arm unavailable. Enable the simulator safely in the main thread first.')
                continue
            # This console can address only the known simulator name.
            arm = Arm.from_robot(robot, TARGET)
            xyz = POSES[command.upper()]
            try:
                await arm.move_to_position(Pose(x=xyz[0], y=xyz[1], z=xyz[2], o_z=-1), timeout=30)
                pose = await arm.get_end_position(timeout=5)
                error_mm = sum((a-b)**2 for a,b in zip(xyz, (pose.x,pose.y,pose.z)))**.5
                moving = await arm.is_moving(timeout=5)
                emit(command=command.upper(), motion_sent=True,
                     elapsed_ms=round((time.perf_counter()-started)*1000, 1),
                     position_mm=[pose.x,pose.y,pose.z], error_mm=error_mm,
                     passed=error_mm < 2 and not moving)
            except BaseException as exc:
                await arm.stop(timeout=5)
                emit(command=command.upper(), error=str(exc), simulator_stop_sent=True)
                if not isinstance(exc, Exception):
                    raise
    finally:
        await asyncio.wait_for(robot.close(), 5)
        emit(event='closed')


if __name__ == '__main__':
    asyncio.run(main())
