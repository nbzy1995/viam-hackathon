"""One physical task at a time, with independent stop and streamed progress."""
import asyncio
import json
import os
from pathlib import Path
import sys


class RobotHarness:
    def __init__(self):
        self.process = None
        self.progress = 'Ready'
        self.starting = False
        self.stop_requested = False

    async def reply(self, history):
        if self.process is not None or self.starting:
            return 'The robot is busy. The request was not queued.'
        env = {k:v for k,v in os.environ.items() if k in {
            'PATH','HOME','USER','TMPDIR','CODEX_HOME','SSL_CERT_FILE','SSL_CERT_DIR','VOICE_ROBOT_SOURCE'}}
        self.progress = 'Acquiring robot control'
        self.starting = True
        self.stop_requested = False
        try:
            process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).with_name('robot_worker.py')),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env)
        finally:
            self.starting = False
        self.process = process
        answer = None
        try:
            process.stdin.write((history[-1]['content'].replace('\n',' ')+'\n').encode())
            if self.stop_requested: process.stdin.write(b'/stop\n')
            await process.stdin.drain()
            async with asyncio.timeout(300):
                async for line in process.stdout:
                    try: event = json.loads(line)
                    except ValueError: continue
                    if event.get('event') == 'answer': answer = event['text']
                    else: self.progress = event.get('message') or event.get('event', 'Working')
                await process.wait()
            return answer or 'Robot worker ended without confirming task completion.'
        finally:
            if process.returncode is None:
                await self.stop()
                try: await asyncio.wait_for(process.wait(), 15)
                except asyncio.TimeoutError:
                    # Do not kill a worker that may still be attempting its physical stop.
                    self.progress = 'Stop unconfirmed; robot worker still active'
                    asyncio.create_task(self._reap(process))
                    raise RuntimeError("Robot stop is unconfirmed; worker remains active")
            if process.returncode is not None:
                self.process = None
                self.progress = 'Ready'

    async def _reap(self, process):
        await process.wait()
        if self.process is process: self.process = None

    async def stop(self):
        self.stop_requested = True
        if self.starting:
            return 'Stop requested before robot connection completed.'
        process = self.process
        if process is None or process.returncode is not None:
            return 'This voice interface has no active robot task. It cannot stop another controller.'
        try:
            process.stdin.write(b'/stop\n')
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            return 'Robot worker disconnected. Stop is not confirmed.'
        return 'Stop requested. Waiting for the robot acknowledgement.'
