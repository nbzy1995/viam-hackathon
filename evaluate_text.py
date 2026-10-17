"""Language checks on synthetic geometry; never contacts Viam.

uv run python evaluate_text.py            # known development regressions
uv run python evaluate_text.py --heldout  # replay independent, frozen cases
"""
import argparse
import asyncio
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from task_interpreter import ROOT, WORKSPACE, interpret, resolve_commands, validate_task, write_json

CASES = [
    ('slightly-right', 'Move this red block to the right slightly.', 'execute', 'red', 'translate', [20, 0]),
    ('left-5cm', 'Move the red block to the left for 5 cm.', 'execute', 'red', 'translate', [-50, 0]),
    ('previous-state', 'Move the red bin to the previous state.', 'execute', 'red', 'restore', [0, 0]),
    ('relative-object', 'Move the yellow bin closer to the red bin.', 'execute', 'yellow', 'translate', [-20, 0]),
    ('original-typo', 'move the cartoon 3 cm to the left of current location.', 'execute', 'carton', 'translate', [-30, 0]),
    ('negation', 'Do not move anything. What is on the table?', 'status', None, None, None),
    ('missing-object', 'Move the green block right slightly.', 'observe', None, None, None),
    ('missing-history', 'Put the yellow bin back in its previous state.', 'reject', None, None, None),
]


def fixture():
    return {'synthetic_fixture': True, 'images': [], 'overview_attempted': False,
        'default_view': 'wrist camera', 'camera_available': True,
        'objects': [{'id': name, 'label': label, 'world_mm': xyz, 'movable': True,
                     'view_directions': {'image_right_world_xy_unit': [1, 0],
                                         'image_down_world_xy_unit': [0, 1]}}
                    for name, label, xyz in [('red', 'red rectangular block', [350, -400, 30]),
                                            ('yellow', 'yellow bin', [450, -400, 30]),
                                            ('carton', 'blue and white carton', [400, -500, 150])]]}


def grade(result, expected, scene=None, history=None):
    """Check actionable arguments, not wording. Missing prose review stays pending."""
    errors = []
    try:
        validate_task(result)
    except (ValueError, TypeError, KeyError) as exc:
        return [f'invalid_schema: {exc}']
    decisions = expected['decision']
    if isinstance(decisions, str):
        decisions = [decisions]
    if result['decision'] not in decisions:
        errors.append('decision')
    commands, wanted = result['commands'], expected['commands']
    if len(commands) != len(wanted):
        errors.append('command_count')
    for i, (actual, target) in enumerate(zip(commands, wanted)):
        for key in ('object_id', 'action', 'target_id'):
            if actual.get(key) != target.get(key):
                errors.append(f'command_{i}.{key}')
        if math.dist([actual['dx_mm'], actual['dy_mm']], [target['dx_mm'], target['dy_mm']]) > .2:
            errors.append(f'command_{i}.displacement')
    if scene is not None and result['decision'] == 'execute':
        try:
            resolve_commands(result, scene, history or [])
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f'unresolvable: {exc}')
    return errors


def score(result, expected):
    return not grade(result, expected)


def summarize(records):
    elapsed = sorted(r['seconds'] for r in records)
    families = {}
    for record in records:
        group = families.setdefault(record['family'], {'passed': 0, 'total': 0})
        group['passed'] += int(record['passed'])
        group['total'] += 1
    actionable = [r for r in records if r.get('expected', {}).get('decision') == 'execute']
    nonactionable = [r for r in records if r.get('expected') and r not in actionable]
    return {'structured_passed': sum(r['passed'] for r in records), 'total': len(records),
            'actionable': {'passed': sum(r['passed'] for r in actionable), 'total': len(actionable)},
            'nonactionable': {'passed': sum(r['passed'] for r in nonactionable), 'total': len(nonactionable)},
            'unexpected_execution': sum(r.get('result', {}).get('decision') == 'execute' for r in nonactionable),
            'unnecessary_nonexecution': sum(r.get('result', {}).get('decision') in {'observe', 'reject', 'status'} for r in actionable),
            'families': families,
            'failure_categories': dict(Counter(e for r in records for e in r.get('errors', []))),
            'manual_review_pending': [r['id'] for r in records if r.get('manual_rubric')],
            'latency_seconds': {'p50': statistics.median(elapsed),
                                'p95_nearest_rank': elapsed[math.ceil(.95 * len(elapsed)) - 1],
                                'max': elapsed[-1]},
            'latency_note': 'Serial wall time including CLI startup. Small-sample p95 is descriptive, not an SLA.'}


async def main(heldout=False, suite_path=None, run_id=None, repeats=1, include_skills=True):
    suite_name = Path(suite_path).stem if suite_path else ('text-heldout' if heldout else 'text-evaluation')
    run_id = run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if not run_id.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Run ID must be a simple filename label')
    output = ROOT / 'artifacts/diagnosis' / f'{suite_name}-{run_id}.json'
    manifest = output.with_name(output.stem + '-manifest.json')
    if output.exists() or manifest.exists():
        raise FileExistsError(f'Preserve the earlier run: {output}')
    workspace = ROOT / 'artifacts/diagnosis' / f'{suite_name}-{run_id}-workspace'
    workspace.mkdir(exist_ok=True)
    instructions = (WORKSPACE / 'INSTRUCTIONS.md').read_bytes()
    (workspace / 'INSTRUCTIONS.md').write_bytes(instructions)
    if heldout or suite_path:
        suite = json.loads((Path(suite_path) if suite_path else ROOT / 'config/text-heldout.json').read_text())
        cases = suite['cases']
    else:
        suite = {'scope': 'Known development regressions, not a generalization score'}
        history = [{'object_id': 'red', 'before_world_mm': [330, -400, 30],
                    'after_world_mm': [350, -400, 30], 'verified': True}]
        cases = [{'id': name, 'request': prompt, 'scene': fixture(), 'history': history,
                  'expected': {'decision': decision, 'commands': [
                      {'action': action, 'object_id': oid, 'dx_mm': delta[0], 'dy_mm': delta[1]}] if oid else []}}
                 for name, prompt, decision, oid, action, delta in CASES]
    report = {'scope': suite['scope'], 'hardware': 'No robot calls; no visual/grasp validation',
              'grading': 'Schema, decision, command order, source AND support identities, displacement, executable references; prose reviewed separately',
              'run_id': run_id, 'repeats': repeats, 'include_skill_instructions': include_skills,
              'cli_version': subprocess.check_output(['codex', '--version'], text=True).strip(),
              'instructions_sha256': hashlib.sha256(instructions).hexdigest(),
              'cases_sha256': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
              'interpreter_sha256': hashlib.sha256((ROOT / 'task_interpreter.py').read_bytes()).hexdigest(),
              'grader_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'schema_sha256': hashlib.sha256((ROOT / 'config/text-task.schema.json').read_bytes()).hexdigest(),
              'tolerance_mm': .2, 'cases': []}
    if not cases or repeats < 1:
        raise ValueError('Evaluation requires at least one case and repetition')
    # Freeze inputs/oracles BEFORE inference. Oracles and case IDs are not sent
    # to interpret(), and shell tools are disabled in its separate workspace.
    write_json(manifest, report | {'cases': cases})
    try:
        for index in range(len(cases) * repeats):
            case = cases[index % len(cases)]
            started = time.perf_counter()
            record = {'id': case['id'], 'trial': index // len(cases) + 1,
                      'family': case.get('family', 'legacy'),
                      'request': case['request'], 'expected': case['expected'],
                      'manual_rubric': case.get('manual_rubric', [])}
            try:
                result = await interpret(case['request'], case['scene'], case['history'], workspace,
                                         include_skill_instructions=include_skills)
                errors = grade(result, case['expected'], case['scene'], case['history'])
                record.update(passed=not errors, errors=errors, result=result,
                              inference=json.loads((workspace / 'inference-metrics.json').read_text()))
            except Exception as exc:
                record.update(passed=False, errors=['runtime_error'], error=str(exc))
            record['seconds'] = round(time.perf_counter() - started, 3)
            report['cases'].append(record)
            report['summary'] = summarize(report['cases'])
            write_json(output, report)
            print(json.dumps(record), flush=True)
    finally:
        shutil.rmtree(workspace)
    return 0 if all(r['passed'] for r in report['cases']) else 1

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--heldout', action='store_true')
    choice.add_argument('--suite', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--omit-skill-instructions', action='store_true')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.heldout, args.suite, args.run_id, args.repeats,
                                      not args.omit_skill_instructions)))
