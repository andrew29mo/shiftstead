"""Scheduled real HTTP traffic; retain the full experiment plan and every trial."""
import argparse
import asyncio
import hashlib
import json
import os
import math
import time
from pathlib import Path
import psutil
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from tests.harness import Harness
from tools.evidence import provenance, environment, atomic_json

MODES = ['direct', 'proxy', 'deploy']
PAYLOAD = b'x' * 256
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def percentile(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * p) - 1)] if values else None


def response_correct(row, mode):
    body = row.get('response')
    allowed = {'v1', 'v2'} if mode == 'deploy' else {'v1'}
    return (row.get('error') is None and row.get('status') == 200 and
            isinstance(body, dict) and body.get('id') == str(row['id']) and
            body.get('bytes') == len(PAYLOAD) and body.get('sha256') == PAYLOAD_SHA and
            body.get('raw_path') == f"/?id={row['id']}&delay=.002" and
            body.get('version') in allowed)


def rss_snapshot(root, pid):
    controller = psutil.Process(pid).memory_info().rss
    workers = 0
    for path in root.glob('*.identity'):
        record = json.loads(path.read_text())
        try:
            p = psutil.Process(record['pid'])
            if abs(p.create_time() - record['created']) < .001 and p.status() != psutil.STATUS_ZOMBIE:
                workers += p.memory_info().rss
        except psutil.Error:
            pass
    return controller, workers


async def trial(mode, number, count, rate):
    h = Harness()
    rows, memory = [], []
    deployment = None
    sampler = deploy_task = None
    sampling = False
    schedule = [i / rate for i in range(count)]
    base = {'mode': mode, 'trial': number, 'offered_rps': rate, 'scheduled': count,
            'schedule_sha256': hashlib.sha256(json.dumps(schedule).encode()).hexdigest()}
    try:
        await h.start()
        await h.deploy('v1')
        s = await h.settled()
        if s['operation']['state'] != 'done':
            raise RuntimeError('initial deployment failed')
        worker_port = s['workers'][s['route']]['port']
        target = worker_port if mode == 'direct' else h.port
        async with ClientSession(timeout=ClientTimeout(total=5), connector=TCPConnector(limit=128), trust_env=False) as client:
            client._retry_connection = False
            for _ in range(20):
                async with client.post(f'http://127.0.0.1:{target}/warm', data=b'warm') as r:
                    if r.status != 200:
                        raise RuntimeError('warmup failed')
                    await r.read()
            async def sample():
                while sampling:
                    controller, workers = await asyncio.to_thread(rss_snapshot, h.root, h.process.pid)
                    memory.append({'at_s': time.monotonic() - start, 'controller_rss_bytes': controller,
                                   'workers_rss_bytes': workers, 'sum_rss_bytes': controller + workers})
                    await asyncio.sleep(.01)
            async def request(i, offset):
                await asyncio.sleep(max(0, start + offset - time.monotonic()))
                sent = time.monotonic()
                row = {'id': i, 'scheduled_s': offset, 'sent_s': sent - start,
                       'send_lag_ms': max(0, sent - start - offset) * 1000,
                       'status': None, 'version': None, 'error': None, 'response': None}
                try:
                    async with client.post(f'http://127.0.0.1:{target}/?id={i}&delay=.002', data=PAYLOAD) as r:
                        row['status'] = r.status
                        row['response'] = await r.json()
                        if isinstance(row['response'], dict):
                            row['version'] = row['response'].get('version')
                except Exception as e:
                    row['error'] = type(e).__name__
                row['completed_s'] = time.monotonic() - start
                row['service_latency_ms'] = (row['completed_s'] - row['sent_s']) * 1000
                row['scheduled_e2e_ms'] = (row['completed_s'] - offset) * 1000
                row['correct'] = response_correct(row, mode)
                rows.append(row)
            async def deploy():
                await asyncio.sleep(max(0, start + .35 - time.monotonic()))
                began = time.monotonic()
                await h.deploy('v2', observe=.2, retain=.2)
                s = await h.settled()
                return {'seconds': time.monotonic() - began, 'state': s['operation']['state'],
                        'switched_at': s['operation'].get('switched_at')}
            start = time.monotonic() + .05
            sampling = True
            sampler = asyncio.create_task(sample())
            deploy_task = asyncio.create_task(deploy()) if mode == 'deploy' else None
            await asyncio.gather(*(request(i, offset) for i, offset in enumerate(schedule)))
            observation = max(r['completed_s'] for r in rows)
            if deploy_task:
                deployment = await deploy_task
            sampling = False
            await sampler
        rows.sort(key=lambda r: r['id'])
        common = [r for r in memory if 0 <= r['at_s'] <= observation]
        if not common:
            raise RuntimeError('no common-window RSS samples')
        good = sum(r['correct'] for r in rows)
        peaks = {f'sampled_peak_{label}_rss_bytes': max(r[key] for r in common)
                 for label, key in [('controller', 'controller_rss_bytes'), ('workers', 'workers_rss_bytes'), ('sum', 'sum_rss_bytes')]}
        metrics = (await h.status())['metrics']
        return {**base, **peaks, 'received': len(rows), 'unique_ids': len({r['id'] for r in rows}),
                'correct': good, 'errors': count - good, 'observation_s': observation,
                'achieved_correct_rps': good / observation,
                'scheduled_e2e_p50_ms': percentile([r['scheduled_e2e_ms'] for r in rows], .5),
                'scheduled_e2e_p95_ms': percentile([r['scheduled_e2e_ms'] for r in rows], .95),
                'send_lag_p95_ms': percentile([r['send_lag_ms'] for r in rows], .95),
                'sampled_lifecycle_peak_sum_rss_bytes': max(r['sum_rss_bytes'] for r in memory),
                'memory_window_s': [0, observation], 'deployment': deployment,
                'gateway_metrics': metrics, 'requests': rows, 'memory_samples': memory,
                'passed': good == count and len({r['id'] for r in rows}) == count and
                (not deployment or (deployment['state'] == 'done' and {r['version'] for r in rows} == {'v1', 'v2'}))}
    except Exception as e:
        return {**base, 'passed': False, 'fatal_error': type(e).__name__,
                'requests': rows, 'memory_samples': memory, 'deployment': deployment}
    finally:
        sampling = False
        for task in [sampler, deploy_task]:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(x for x in [sampler, deploy_task] if x), return_exceptions=True)
        await h.cleanup()


async def run(a):
    source = provenance()
    plan = [{'trial': n + 1, 'mode': mode} for n in range(a.trials)
            for mode in MODES[n % 3:] + MODES[:n % 3]]
    rows = []
    for item in plan:
        print(f"trial {item['trial']}: {item['mode']}", flush=True)
        try:
            result = await trial(item['mode'], item['trial'], a.count, a.rate)
        except Exception as e:
            result = {**item, 'passed': False, 'fatal_error': type(e).__name__, 'requests': [], 'memory_samples': []}
        rows.append(result)
    changed = provenance() != source
    same = not any(r.get('fatal_error') for r in rows) and len({r['schedule_sha256'] for r in rows}) == 1
    value = {'schema': 2, 'kind': 'real-process-open-loop',
             'passed': all(r['passed'] for r in rows) and same and not changed,
             'same_schedule': same, 'source_changed': changed,
             'plan': {'trials': a.trials, 'count': a.count, 'rate': a.rate, 'order': plan},
             'environment': environment(), 'run_id': os.environ.get('SHIFTSTEAD_VALIDATION_RUN'), 'source': source,
             'method': {'warmups': 20, 'payload_bytes': len(PAYLOAD), 'payload_sha256': PAYLOAD_SHA,
                        'worker_delay_s': .002, 'rss_sample_interval_s': .01,
                        'latency': 'scheduled arrival to complete response, including sender lag; failed outcomes retained',
                        'throughput': 'correct responses / (last recorded completion - first scheduled arrival), not capacity',
                        'memory': 'common request-window sampled controller + worker RSS; shared pages may count twice; excludes load generator. Direct mode retains idle controller; lifecycle peak recorded separately.',
                        'transport': 'load client uses keep-alive; gateway upstream connections close after each request; health probes have a separate connection pool; no retries',
                        'scope': 'synthetic HTTP demo with asynchronous delay, not CPU-bound work; offered load only, not capacity or zero-downtime proof'},
             'trials': rows}
    Path('results').mkdir(exist_ok=True)
    atomic_json('results/benchmark.json',value)
    if not value['passed']:
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--trials', type=int, default=3)
    p.add_argument('--count', type=int, default=300)
    p.add_argument('--rate', type=float, default=200)
    a = p.parse_args()
    if a.trials < 1 or a.count < 150 or not 1 <= a.rate <= 300:
        p.error('invalid experiment size/rate')
    asyncio.run(run(a))
if __name__ == '__main__':
    main()
