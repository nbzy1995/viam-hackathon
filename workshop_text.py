"""Milestone 2: natural-language requests -> validated Viam carton actions.

uv run python workshop_text.py             # persistent preview console
uv run python workshop_text.py --execute   # persistent physical console
uv run python workshop_text.py --prompt 'Move the carton 3 cm toward B.'
"""
import argparse
import asyncio
import json
import sys
import time
import traceback
from copy import deepcopy
from datetime import datetime, timezone

import numpy as np
from viam.components.arm import Arm
from viam.robot.client import RobotClient

from scene_sweep import Scene
from task_interpreter import WORKSPACE, interpret, validate_task, resolve_commands, read_history, write_json
from robot_scene import camera_directions, capture_scene, capture_overview
from workshop_static import check_arm, control_lock
from workshop_vision import ROOT, validate_setup
from tabletop_transfer import prepare_transfer, transfer_object


def emit(event, **data):
    print(json.dumps({'event': event, **data}), flush=True)


def verify_translation(before, after, delta):
    error = float(np.linalg.norm(np.asarray(after)[:2] - np.asarray(before)[:2] - delta))
    tolerance = min(10., float(np.linalg.norm(delta)) / 3)
    if error > tolerance:
        raise RuntimeError(f'Placement error {error:.1f} mm exceeds {tolerance:.1f} mm')
    return {'error_mm': error, 'tolerance_mm': tolerance,
            'observed_displacement_mm': (np.asarray(after)[:2] - np.asarray(before)[:2]).tolist()}


class TextController:
    """One robot session; concurrent requests are rejected rather than queued."""
    def __init__(self, robot, execute=False, notify=emit, workspace=WORKSPACE):
        self.robot, self.execute, self.notify = robot, execute, notify
        self.arm = Arm.from_robot(robot, 'arm')
        self.checked = json.loads((ROOT / 'artifacts/roundtrip-checked-setup.json').read_text())
        self.scene = Scene()
        self.busy = False
        self.workspace = workspace
        self.table_z = None

    async def observe(self):
        scene = await capture_scene(self.robot, self.checked, self.workspace,
                                    table_z=getattr(self, 'table_z', None))
        # The configured table is fixed for this checked station/session.
        self.table_z = scene.get('table_surface_z_mm')
        return scene

    async def run(self, request):
        if self.busy:
            self.notify('rejected', reason='Robot is busy; request was not queued.')
            return {'success': False, 'error': 'busy'}
        self.busy = True
        started = time.perf_counter()
        report = {'at': datetime.now(timezone.utc).isoformat(), 'request': request,
                  'execute': self.execute, 'execution_attempted': False,
                  'success': False, 'transfers': [], 'timing_seconds': {}}
        output = ROOT / 'artifacts/diagnosis' / f'text-task-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json'

        def save():
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + '\n')

        def elapsed():
            return round(time.perf_counter() - started, 3)

        def progress(message):
            if 'previews passed' in message:
                report['timing_seconds']['preview_ready'] = elapsed()
            self.notify('progress', message=message, elapsed_seconds=elapsed())

        try:
            self.notify('received', request=request, mode='physical' if self.execute else 'preview')
            report['timing_seconds']['acknowledged'] = elapsed()
            await validate_setup(self.robot, self.checked)
            history = read_history(self.workspace)
            scene = await self.observe()
            self.notify('observed', objects=[o['label'] for o in scene['objects']],
                        images=scene.get('images', []), errors=scene.get('errors', {}))
            report['timing_seconds']['observed'] = elapsed()
            for attempt in range(2):
                report['scene'] = scene
                model_started = time.perf_counter()
                task = validate_task(await interpret(request, scene, history, self.workspace))
                report.setdefault('interpretations', []).append(task)
                report['task'] = task
                report['timing_seconds']['interpretation'] = round(time.perf_counter() - model_started, 3)
                self.notify('interpreted', **task, elapsed_seconds=elapsed())
                save()
                if task['decision'] != 'observe':
                    break
                if not self.execute:
                    report['outcome'] = 'observation_required'
                    self.notify('observation_required', message='Higher view needed; preview mode does not move the arm.')
                    return report
                if not scene.get('camera_available', True):
                    raise RuntimeError('Wrist camera evidence unavailable; cannot perform another observation')
                if attempt:
                    raise RuntimeError('Higher observation already completed; interpreter requested it again')
                self.notify('observing', message='Checking the higher observation pose, looking, and returning home.')
                scene = await capture_overview(self.robot, self.scene, self.checked, report, save, self.workspace)
                # The helper returns only after the capture and verified return home.
                # Make that completed operation explicit when interpreting the same request.
                scene['completed_actions'] = [dict(action='observe', view='higher',
                    camera_available=scene.get('camera_available', False), returned_home=True)]
            if task['decision'] != 'execute':
                report['outcome'] = task['decision']
                report['success'] = task['decision'] == 'status'
                self.notify(task['decision'], message=task['message'])
                return report
            commands = resolve_commands(task, scene, history)
            report['commands'] = commands
            await self.run_tabletop(commands, scene, history, report, save, progress, elapsed, output)
            return report
        except BaseException as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            report['error_traceback'] = traceback.format_exc()
            if report['execution_attempted']:
                try:
                    await self.arm.stop(timeout=5)
                    report['stop_requested'] = True
                except Exception as stop:
                    report['stop_error'] = str(stop)
            self.notify('failed', reason=report['error'], elapsed_seconds=elapsed())
            if not isinstance(exc, Exception):
                raise
            return report
        finally:
            report['timing_seconds']['total'] = elapsed()
            save()
            self.busy = False
            self.notify('report', path=str(output))

    async def run_tabletop(self, commands, observation, history, report, save, progress, elapsed, output):
        """The same depth-derived pick/place sequence for every observed object."""
        virtual, virtual_history = deepcopy(observation), deepcopy(history)
        transfers = []
        for command in commands:
            transfer = prepare_transfer(virtual, command, virtual_history)
            await transfer_object(self.robot, self.scene, self.checked, virtual, transfer, False,
                                  report, save, progress=progress)
            transfers.append(transfer)
            obj = next(o for o in virtual['objects'] if o['id'] == command['object_id'])
            before = obj['world_mm']
            obj['world_mm'] = [*transfer['target_xy'], transfer['target_top_z_mm']]
            if 'grasp_tcp_z_mm' in obj['geometry']:
                obj['geometry']['grasp_tcp_z_mm'] += transfer['target_top_z_mm'] - obj['geometry']['top_z_mm']
            obj['geometry'].update(center_top_world_mm=obj['world_mm'], top_z_mm=transfer['target_top_z_mm'],
                                   bottom_z_mm=transfer['target_support_z_mm'])
            virtual_history.append(dict(object_id=obj['id'], before_world_mm=before,
                after_world_mm=obj['world_mm'], before_support_z_mm=transfer['source_support_z_mm'],
                after_support_z_mm=transfer['target_support_z_mm'], after_top_z_mm=transfer['target_top_z_mm'],
                verified=True))  # Local predicted state only; never persisted or sent to the interpreter.
        if not self.execute:
            report['outcome'] = 'preview_passed'
            self.notify('preview_passed', commands=commands, elapsed_seconds=elapsed())
            return
        for command, planned in zip(commands, transfers):
            fresh = await self.observe()
            objects = {o['id']: o for o in fresh['objects']}
            before = objects.get(command['object_id'])
            if before is None or np.linalg.norm(np.array(before['world_mm'][:2]) - planned['source_xy']) > 5:
                raise RuntimeError('Object changed position during planning; a fresh plan is needed')
            transfer = prepare_transfer(fresh, command, history)
            async def guard():
                await validate_setup(self.robot, self.checked)
                current = await self.observe()
                positions = {o['id']: o['world_mm'] for o in current['objects']}
                for obj in fresh['objects']:
                    if obj['id'] not in positions or np.linalg.norm(
                            np.array(positions[obj['id']]) - obj['world_mm']) > 5:
                        raise RuntimeError('Observed scene changed during preview; a fresh plan is needed')
                report['timing_seconds']['execution_started'] = elapsed()
                self.notify('executing', target_world_xy_mm=transfer['target_xy'], elapsed_seconds=elapsed())
            await transfer_object(self.robot, self.scene, self.checked, fresh, transfer, True,
                                  report, save, progress=progress, before_execute=guard)
            after_scene = await self.observe()
            after = next((o for o in after_scene['objects'] if o['id'] == command['object_id']), None)
            if after is None:
                raise RuntimeError('Object was not visible after placement; result is unverified')
            target = np.array([*transfer['target_xy'], transfer['target_top_z_mm']])
            error = float(np.linalg.norm(np.array(after['world_mm']) - target))
            distance = float(np.linalg.norm(target - before['world_mm']))
            tolerance = min(10., distance / 3)
            if error > tolerance:
                raise RuntimeError(f'Observed placement error {error:.1f} mm exceeds {tolerance:.1f} mm')
            report['verification'] = {'error_mm': error, 'tolerance_mm': tolerance}
            report.setdefault('verifications', []).append(report['verification'])
            history.append(dict(at=datetime.now(timezone.utc).isoformat(), request=report['request'],
                object_id=command['object_id'], before_world_mm=before['world_mm'],
                after_world_mm=after['world_mm'], target_world_xy_mm=transfer['target_xy'],
                before_support_z_mm=transfer['source_support_z_mm'], after_support_z_mm=transfer['target_support_z_mm'],
                after_top_z_mm=float(after['world_mm'][2]), verified=True, report=str(output)))
            write_json(self.workspace / 'history.json', history)
        report['success'], report['outcome'] = True, 'completed'
        self.notify('completed', **report['verification'], elapsed_seconds=elapsed())


async def main(args):
    credentials = json.loads((ROOT / '.env.viam.json').read_text())
    options = RobotClient.Options.with_api_key(api_key=credentials['api_key'], api_key_id=credentials['api_key_id'])
    options.dial_options.force_relay = True
    options.dial_options.initial_connection_attempts = 1
    options.dial_options.initial_connection_attempt_timeout = 15
    started = time.perf_counter()
    robot = await asyncio.wait_for(RobotClient.at_address(credentials['address'], options), 25)
    active = None
    try:
        controller = TextController(robot, args.execute)
        emit('connected', connection_seconds=round(time.perf_counter() - started, 3),
             mode='physical' if args.execute else 'preview', commands='/stop, /quit, or a natural-language request',
             workspace=str(controller.workspace), default_view='wrist camera; slightly = 20 mm')
        if args.prompt:
            result = await controller.run(args.prompt)
            return 0 if result.get('outcome') in {'completed', 'preview_passed', 'status', 'reject', 'observation_required'} else 1
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            command = line.strip()
            if not line or command == '/quit':
                break
            if command == '/stop':
                if active and not active.done():
                    active.cancel()
                    await asyncio.gather(active, return_exceptions=True)
                await controller.arm.stop(timeout=5)
                await check_arm(controller.arm)
                emit('stopped')
            elif command:
                if active and not active.done():
                    emit('rejected', reason='Busy; request was not queued. /stop is available.')
                else:
                    active = asyncio.create_task(controller.run(command))
    finally:
        if active and not active.done():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        await asyncio.wait_for(robot.close(), 5)
        emit('closed')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--prompt')
    with control_lock():
        raise SystemExit(asyncio.run(main(parser.parse_args())))
