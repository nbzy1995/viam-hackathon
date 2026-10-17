"""Voice transport for the canonical repository TextController and shared lock."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from workshop_text import TextController
from robot_prepare import prepare_robot
from robot_checks import robot_check, motion_check
from robot_messages import task_answer
from viam.robot.client import RobotClient


def emit(event, **data):
    print(json.dumps(dict(event=event, **data)), flush=True)


async def run(request, reader):
    source = Path(os.environ.get('VOICE_ROBOT_SOURCE', SOURCE)).resolve()
    # Open existing lock without truncating it; all worktrees contend on one inode.
    with (source / '.arm-control.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit('answer', text='The robot is controlled by the existing workshop console. Release that controller before using voice control. No motion was requested.')
            return
        credentials = json.loads((source / '.env.viam.json').read_text())
        options = RobotClient.Options.with_api_key(api_key=credentials['api_key'], api_key_id=credentials['api_key_id'])
        options.dial_options.force_relay = True
        options.dial_options.initial_connection_attempts = 1
        options.dial_options.initial_connection_attempt_timeout = 15
        emit('progress', message='Connecting to the robot.')
        robot = await asyncio.wait_for(RobotClient.at_address(credentials['address'], options), 25)
        controller = None
        active = None
        try:
            controller = TextController(robot, execute=True, notify=emit)
            checks = {'prepare robot':prepare_robot,'check robot':robot_check,'run motion check':motion_check}
            check = checks.get(request.strip().lower().rstrip('.!'))
            active = asyncio.create_task(check(controller, emit) if check else controller.run(request))
            stop = asyncio.create_task(reader.readline())
            try:
                done, _ = await asyncio.wait([active, stop], return_when=asyncio.FIRST_COMPLETED)
                if stop in done:
                    active.cancel()
                    # Stop first; do not wait for a blocked planner to finish.
                    await controller.arm.stop(timeout=5)
                    await asyncio.gather(active, return_exceptions=True)
                    emit('answer', text='Robot stop acknowledged. The task was cancelled; placement is not verified.')
                else:
                    result = await active
                    answer = task_answer(result)
                    emit('answer', text=answer)
            finally:
                stop.cancel()
                await asyncio.gather(stop, return_exceptions=True)
        finally:
            if active and not active.done():
                active.cancel()
                if controller: await controller.arm.stop(timeout=5)
                await asyncio.gather(active, return_exceptions=True)
            await asyncio.wait_for(robot.close(), 5)


async def main():
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    try:
        request = (await reader.readline()).decode().strip()
        if not request:
            return
        await run(request, reader)
    finally:
        transport.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        # SDK exception strings can contain credential-bearing URLs.
        emit('answer', text=f'Robot connection or control failed ({type(exc).__name__}). Task completion is not confirmed.')
        sys.exit(1)
