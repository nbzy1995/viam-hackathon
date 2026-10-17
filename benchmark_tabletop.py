"""Four paired, alternating-order E2E planning-overhead comparisons; no hardware motion.

uv run python benchmark_tabletop.py
The retained baseline differs only in tabletop_transfer.py. Model, fixture,
controller, timeout handling, scorer and planner are shared between variants.
"""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
from types import SimpleNamespace
from unittest.mock import patch

import evaluate_tabletop as evaluator
import workshop_text
from task_interpreter import write_json

ROOT = Path(__file__).parent
BASELINE = ROOT/'artifacts/diagnosis/tabletop-transfer-before-latency.py'
OUTPUT = ROOT/'artifacts/diagnosis/office-e2e-latency-pairs.json'


async def main():
    if OUTPUT.exists(): raise FileExistsError('Preserve previous benchmark evidence')
    spec = importlib.util.spec_from_file_location('transfer_latency_baseline',BASELINE)
    baseline = importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
    current = workshop_text.transfer_object
    fingerprints = evaluator.fingerprints
    result = {'scope':'Real model and native planning; synthetic sensing, local kinematic execution. Not physical cycle time.',
              'baseline_sha256':hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
              'candidate_sha256':hashlib.sha256((ROOT/'tabletop_transfer.py').read_bytes()).hexdigest(),
              'pairs':[]}
    for index,case in enumerate(('D03','D04','D08','D10')):
        pair = {'case':case}; result['pairs'].append(pair)
        order = ('baseline','candidate') if index%2==0 else ('candidate','baseline')
        pair['order'] = order
        for variant in order:
            args = SimpleNamespace(suite=ROOT/'config/office-e2e-development.json',freeze=None,
                replay_of=None,case=case,run_id=f'latency-pair-{case}-{variant}')
            overrides = {'benchmark_transfer_variant':variant,
                         'benchmark_transfer_sha256':result[variant+'_sha256']}
            with patch.object(workshop_text,'transfer_object',baseline.transfer_object if variant=='baseline' else current), \
                 patch.object(evaluator,'fingerprints',lambda: fingerprints()|overrides):
                code = await evaluator.main(args)
            path = ROOT/'artifacts/diagnosis'/f'office-e2e-{args.run_id}.json'
            run = json.loads(path.read_text())['runs'][0]
            times = [t['response']['timing_seconds'] for t in run['turns']]
            pair[variant] = dict(passed=run['automated_passed'],evidence=str(path.relative_to(ROOT)),
                total_seconds=sum(t['total'] for t in times),
                interpreter_seconds=sum(t['interpretation'] for t in times),
                post_interpretation_seconds=sum(t['total']-t['observed']-t['interpretation'] for t in times),
                native_plan_calls=sum(e['event']=='native_plan_attempt' for t in run['turns'] for e in t['events']))
            write_json(OUTPUT,result)
            if code: raise RuntimeError('Correctness failure; do not claim latency gain')
        pair['candidate_minus_baseline'] = {key:round(pair['candidate'][key]-pair['baseline'][key],3)
            for key in ('total_seconds','interpreter_seconds','post_interpretation_seconds','native_plan_calls')}
        write_json(OUTPUT,result)
    result['summary'] = {'pairs':len(result['pairs']),'all_correct':True,
        'median_paired_delta':{key:statistics.median(p['candidate_minus_baseline'][key] for p in result['pairs'])
                              for key in result['pairs'][0]['candidate_minus_baseline']}}
    write_json(OUTPUT,result)
    print(json.dumps(result['summary']),flush=True)


if __name__=='__main__': asyncio.run(main())
