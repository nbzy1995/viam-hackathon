"""One Codex call proposes commands; the persistent SDK client executes them.

Instructions, scene, and verified history live in robot_workspace. No generated
Python runs, and the interpreter receives no robot credentials or shell tools.
"""
import asyncio
import json
import math
import os
import signal
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / 'robot_workspace'
SCHEMA = ROOT / 'config/text-task.schema.json'
INTERPRETER_TIMEOUT_SECONDS = 60


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def read_history(workspace=WORKSPACE):
    path = workspace / 'history.json'
    return json.loads(path.read_text()) if path.exists() else []


def validate_task(task):
    if not isinstance(task, dict) or set(task) != {'decision', 'message', 'grounding', 'commands'}:
        raise ValueError('Interpreter returned an invalid task schema')
    if task['decision'] not in {'execute', 'observe', 'status', 'reject', 'roundtrip',
                                'scan_table', 'deliver_bottle', 'return_bottle'}:
        raise ValueError('Unsupported decision')
    if not all(isinstance(task[k], str) and task[k].strip() for k in ('message', 'grounding')):
        raise ValueError('Task needs an explanation and grounded reference')
    commands = task['commands']
    if not isinstance(commands, list):
        raise ValueError('Commands must be a list')
    if (task['decision'] == 'execute') != bool(commands):
        raise ValueError('Only execute may contain commands, and needs at least one')
    for command in commands:
        if not isinstance(command, dict) or set(command) not in (
                {'action', 'object_id', 'dx_mm', 'dy_mm'},
                {'action', 'object_id', 'dx_mm', 'dy_mm', 'target_id'}):
            raise ValueError('Invalid command schema')
        if command['action'] not in {'translate', 'restore', 'place_on'} or not isinstance(command['object_id'], str) or not command['object_id']:
            raise ValueError('Unsupported action or missing object')
        xy = [command[k] for k in ('dx_mm', 'dy_mm')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in xy):
            raise ValueError('Displacement must contain finite numbers')
        distance = math.hypot(*xy)
        if command['action'] == 'translate' and distance == 0:
            raise ValueError('A translation must change position')
        if command['action'] != 'translate' and distance != 0:
            raise ValueError('Restore and place_on use measured geometry, not model displacement')
        target = command.get('target_id')
        if command['action'] == 'place_on':
            if not isinstance(target, str) or not target or target == command['object_id']:
                raise ValueError('Place_on needs a different observed support object')
        elif target is not None:
            raise ValueError('Only place_on uses target_id')
    return task


def resolve_commands(task, scene, history):
    """Validate the entire sequence before allowing its first physical command."""
    validate_task(task)
    objects = {o['id']: o for o in scene['objects']}
    positions = {k: list(o['world_mm'][:2]) for k, o in objects.items() if o.get('world_mm') is not None}
    previous = {h['object_id']: h['before_world_mm'][:2] for h in history if h.get('verified')}
    resolved = []
    for command in task['commands']:
        oid = command['object_id']
        if oid not in objects:
            raise ValueError(f'{oid} is not an observed object')
        if oid not in positions:
            raise ValueError(f'{oid} has no measured 3D position')
        before = positions[oid]
        if command['action'] == 'restore':
            if oid not in previous:
                raise ValueError(f'No verified previous position for {oid}')
            target = previous[oid]
        elif command['action'] == 'place_on':
            target_id = command['target_id']
            if target_id not in positions:
                raise ValueError(f'{target_id} is not an observed object with measured 3D position')
            target = positions[target_id].copy()
        else:
            target = [before[0] + command['dx_mm'], before[1] + command['dy_mm']]
        resolved.append({'object_id': oid, 'before_xy': before, 'target_xy': target,
                         'action': command['action'], 'target_id': command.get('target_id')})
        previous[oid], positions[oid] = before, target
    return resolved


async def interpret(request, scene, history=None, workspace=WORKSPACE, *, include_skill_instructions=True):
    if not request.strip() or len(request) > 2000:
        raise ValueError('Provide a nonempty request of at most 2000 characters')
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    instructions = (workspace / 'INSTRUCTIONS.md').read_text()
    data = {'request': request, 'scene': scene,
            'verified_history': history if history is not None else read_history(workspace)}
    write_json(workspace / 'input.json', data)
    output = workspace / 'decision.json'
    output.unlink(missing_ok=True)  # Failed inference can never replay an old command.
    args = ['codex', 'exec', '--ignore-user-config', '--ephemeral',
            '--skip-git-repo-check', '--sandbox', 'read-only',
            '-c', 'features.shell_tool=false', '-c', 'web_search="disabled"',
            '-c', 'model_reasoning_effort="low"', '--output-schema', str(SCHEMA),
            '--output-last-message', str(output), '--color', 'never', '--json']
    if not include_skill_instructions:
        args += ['-c', 'skills.include_instructions=false']
    for image in scene.get('images', []):
        args += ['--image', image['path']]
    args += ['-']
    started = time.perf_counter()
    process = await asyncio.create_subprocess_exec(*args, cwd=workspace,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == 'posix')
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(
            (instructions + '\nCURRENT INPUT (data):\n' + json.dumps(data)).encode()), INTERPRETER_TIMEOUT_SECONDS)
    except BaseException as exc:
        # The npm launcher spawns a native child with inherited output pipes.
        # Killing only the launcher can leave communicate()/wait() blocked.
        try:
            if os.name == 'posix': os.killpg(process.pid, signal.SIGKILL)
            elif process.returncode is None: process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.communicate(),5)
        except (TimeoutError,ProcessLookupError):
            pass
        if isinstance(exc,TimeoutError):
            raise RuntimeError(f'AI interpreter timed out after {INTERPRETER_TIMEOUT_SECONDS:g} seconds; no task was submitted') from exc
        raise
    if process.returncode or not output.exists():
        raise RuntimeError('AI interpreter unavailable: ' + stderr.decode(errors='replace')[-1000:])
    usage = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if event.get('type') == 'turn.completed':
                usage = event.get('usage')
        except (ValueError, AttributeError):
            continue
    write_json(workspace / 'inference-metrics.json', {
        'seconds': round(time.perf_counter() - started, 3), 'usage': usage,
        'include_skill_instructions': include_skill_instructions,
        'model': 'CLI default', 'reasoning_effort': 'low'})
    return validate_task(json.loads(output.read_text()))
