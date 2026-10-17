"""Paired language latency replay, including a recorded wrist image. No robot RPCs.

uv run python benchmark_text.py --suite config/text-latency-v2.json --run-id NAME
"""
import argparse
import asyncio
import hashlib
import json
import shutil
import statistics
import subprocess
import time
from pathlib import Path

from evaluate_text import grade
from task_interpreter import ROOT, WORKSPACE, interpret, write_json


def verify_images(suite):
    for path, digest in suite.get('image_sha256', {}).items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Recorded image changed: {path}')


async def main(suite_path, run_id, repeats=2, candidate_instructions=None, baseline_instructions=None):
    if not run_id.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Use a simple run label')
    source = (ROOT / suite_path).read_bytes()
    suite = json.loads(source)
    if repeats < 1 or not suite['cases']:
        raise ValueError('Need cases and positive repetitions')
    verify_images(suite)
    output = ROOT / 'artifacts/diagnosis' / f'text-latency-{run_id}.json'
    manifest = output.with_name(output.stem + '-manifest.json')
    if output.exists() or manifest.exists():
        raise FileExistsError(output)
    workspace = output.with_suffix('')
    workspace.mkdir()
    instructions = (Path(baseline_instructions) if baseline_instructions else WORKSPACE / 'INSTRUCTIONS.md').read_bytes()
    candidate = Path(candidate_instructions).read_bytes() if candidate_instructions else instructions
    (workspace / 'INSTRUCTIONS.md').write_bytes(instructions)
    report = {'scope': 'Matched serial inference only; fixed recorded scene, no robot execution.',
              'suite_sha256': hashlib.sha256(source).hexdigest(),
              'instructions_sha256': hashlib.sha256(instructions).hexdigest(),
              'candidate_instructions_sha256': hashlib.sha256(candidate).hexdigest(),
              'variant': 'instructions only' if candidate_instructions else 'automatic skill instructions only',
              'cli_version': subprocess.check_output(['codex', '--version'], text=True).strip(),
              'interpreter_sha256': hashlib.sha256((ROOT / 'task_interpreter.py').read_bytes()).hexdigest(),
              'repeats': repeats, 'order': 'AB then BA per case; CLI default model and low reasoning for both',
              'pairs': []}
    write_json(manifest, report | {'suite': suite, 'baseline_instructions': instructions.decode(),
                                  'candidate_instructions': candidate.decode()})
    try:
        for trial in range(repeats):
            for case in suite['cases']:
                pair = {'id': case['id'], 'trial': trial + 1, 'runs': {}}
                for label in (['baseline', 'candidate'] if trial % 2 == 0 else ['candidate', 'baseline']):
                    include_skills = bool(candidate_instructions) or label == 'baseline'
                    (workspace / 'INSTRUCTIONS.md').write_bytes(instructions if label == 'baseline' else candidate)
                    verify_images(suite)
                    started = time.perf_counter()
                    try:
                        result = await interpret(case['request'], case['scene'], case['history'], workspace,
                                                 include_skill_instructions=include_skills)
                        verify_images(suite)
                        errors = grade(result, case['expected'], case['scene'], case['history'])
                        record = {'passed': not errors, 'errors': errors, 'result': result,
                                  'inference': json.loads((workspace / 'inference-metrics.json').read_text())}
                    except Exception as exc:
                        record = {'passed': False, 'error': str(exc)}
                    pair['runs'][label] = record | {'seconds': round(time.perf_counter() - started, 3)}
                report['pairs'].append(pair)
                write_json(output, report)
                print(json.dumps({'id': case['id'], 'trial': trial + 1,
                                  **{k: {'passed': v['passed'], 'seconds': v['seconds']} for k, v in pair['runs'].items()}}), flush=True)
        report['summary'] = {mode: {'passed': sum(p['runs'][mode]['passed'] for p in report['pairs']),
                                   'n': len(report['pairs']),
                                   'median_seconds': statistics.median(p['runs'][mode]['seconds'] for p in report['pairs'])}
                             for mode in ('baseline', 'candidate')}
        deltas = [p['runs']['candidate']['seconds'] - p['runs']['baseline']['seconds'] for p in report['pairs']]
        report['summary']['median_paired_delta_seconds'] = statistics.median(deltas)
        write_json(output, report)
        return 0 if all(p['runs'][m]['passed'] for p in report['pairs'] for m in ('baseline', 'candidate')) else 1
    finally:
        shutil.rmtree(workspace)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--candidate-instructions', type=Path)
    parser.add_argument('--baseline-instructions', type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.suite, args.run_id, args.repeats,
                                     args.candidate_instructions, args.baseline_instructions)))
