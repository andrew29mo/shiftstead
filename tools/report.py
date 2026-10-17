"""Validate retained raw evidence and render HTML without executing supplied markup."""
import html
import json
import math
from pathlib import Path
from tools.benchmark import percentile
from tools.evidence import provenance


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate(b, tests=None):
    if b.get('schema') != 2 or b.get('kind') != 'real-process-open-loop' or not b.get('trials'):
        raise ValueError('missing benchmark trials')
    from tools.benchmark import MODES, PAYLOAD_SHA, response_correct
    import hashlib
    plan = b['plan']
    n, rate, repeats = plan['count'], plan['rate'], plan['trials']
    if type(n) is not int or n <= 0 or type(repeats) is not int or repeats <= 0 or not finite(rate) or rate <= 0:
        raise ValueError('invalid experiment plan')
    order = [{'trial': i + 1, 'mode': mode} for i in range(repeats) for mode in MODES[i % 3:] + MODES[:i % 3]]
    if plan['order'] != order or [{'trial': t['trial'], 'mode': t['mode']} for t in b['trials']] != order:
        raise ValueError('missing, reordered or duplicated planned trial')
    if b['method']['payload_bytes'] != 256 or b['method']['payload_sha256'] != PAYLOAD_SHA or b['method']['worker_delay_s'] != .002:
        raise ValueError('workload metadata mismatch')
    expected_schedule = [i / rate for i in range(n)]
    digest = hashlib.sha256(json.dumps(expected_schedule).encode()).hexdigest()
    outcomes, schedules = [], set()
    fatal = False
    for t in b['trials']:
        if t.get('fatal_error'):
            if t['passed'] is not False:
                raise ValueError('fatal trial marked passing')
            outcomes.append(False)
            fatal = True
            continue
        mode, rows = t['mode'], t['requests']
        if t['scheduled'] != n or t['offered_rps'] != rate or len(rows) != n or any(type(r['id']) is not int for r in rows) or {r['id'] for r in rows} != set(range(n)):
            raise ValueError('missing, duplicate or invalid requests')
        if t['received'] != n or t['unique_ids'] != n:
            raise ValueError('request accounting mismatch')
        good = 0
        for r in rows:
            if r['scheduled_s'] != expected_schedule[r['id']]:
                raise ValueError('arrival schedule/rate mismatch')
            correct = response_correct(r, mode)
            body = r['response'] if isinstance(r['response'], dict) else {}
            if correct != r['correct'] or body.get('version') != r['version']:
                raise ValueError('response correctness mismatch')
            good += correct
            keys = ['scheduled_s', 'sent_s', 'completed_s', 'scheduled_e2e_ms', 'service_latency_ms', 'send_lag_ms']
            if any(not finite(r[k]) for k in keys):
                raise ValueError('non-finite time')
            e2e = (r['completed_s'] - r['scheduled_s']) * 1000
            service = (r['completed_s'] - r['sent_s']) * 1000
            lag = max(0, r['sent_s'] - r['scheduled_s']) * 1000
            if e2e < 0 or service < 0 or any(abs(x - y) > .00001 for x, y in [(e2e, r['scheduled_e2e_ms']), (service, r['service_latency_ms']), (lag, r['send_lag_ms'])]):
                raise ValueError('latency mismatch')
        if t['schedule_sha256'] != digest:
            raise ValueError('schedule digest mismatch')
        schedules.add(digest)
        expected = good == n and (mode != 'deploy' or (t['deployment']['state'] == 'done' and {r['version'] for r in rows} == {'v1', 'v2'}))
        if good != t['correct'] or n - good != t['errors'] or expected != t['passed']:
            raise ValueError('outcome mismatch')
        observation = max(r['completed_s'] for r in rows)
        if not finite(t['observation_s']) or not math.isclose(observation, t['observation_s'], abs_tol=1e-9):
            raise ValueError('observation window mismatch')
        if not finite(t['achieved_correct_rps']) or not math.isclose(t['achieved_correct_rps'], good / observation):
            raise ValueError('throughput mismatch')
        for label, values, p in [('scheduled_e2e_p50_ms', [r['scheduled_e2e_ms'] for r in rows], .5), ('scheduled_e2e_p95_ms', [r['scheduled_e2e_ms'] for r in rows], .95), ('send_lag_p95_ms', [r['send_lag_ms'] for r in rows], .95)]:
            if not finite(t[label]) or not math.isclose(t[label], percentile(values, p)):
                raise ValueError('percentile mismatch')
        memory = t['memory_samples']
        if not memory or any(not finite(r['at_s']) for r in memory) or any(memory[i]['at_s'] >= memory[i+1]['at_s'] for i in range(len(memory)-1)):
            raise ValueError('invalid memory sample timing')
        for r in memory:
            if any(type(r[k]) is not int or r[k] < 0 for k in ['controller_rss_bytes', 'workers_rss_bytes', 'sum_rss_bytes']) or r['sum_rss_bytes'] != r['controller_rss_bytes'] + r['workers_rss_bytes']:
                raise ValueError('RSS accounting mismatch')
        common = [r for r in memory if 0 <= r['at_s'] <= observation]
        if not common or t['memory_window_s'] != [0, observation]:
            raise ValueError('RSS comparison window mismatch')
        for label, key in [('controller', 'controller_rss_bytes'), ('workers', 'workers_rss_bytes'), ('sum', 'sum_rss_bytes')]:
            if t[f'sampled_peak_{label}_rss_bytes'] != max(r[key] for r in common):
                raise ValueError('RSS peak mismatch')
        if t['sampled_lifecycle_peak_sum_rss_bytes'] != max(r['sum_rss_bytes'] for r in memory):
            raise ValueError('lifecycle RSS peak mismatch')
        outcomes.append(expected)
    same = not fatal and len(schedules) == 1
    expected = all(outcomes) and same and not b['source_changed']
    if b['same_schedule'] != same or b['passed'] != expected:
        raise ValueError('overall outcome mismatch')
    if tests is not None:
        if not tests['passed'] or tests.get('source_changed') or tests['tests'] <= 0 or tests['skipped'] or tests['failures'] or tests['errors'] or len(tests['cases']) != tests['tests'] or len({x['test'] for x in tests['cases']}) != tests['tests'] or any(x['outcome'] != 'passed' for x in tests['cases']):
            raise ValueError('test evidence not passing')
        if tests['source'] != b['source']:
            raise ValueError('test/benchmark source mismatch')
    return b['passed']


def render(b,tests):
    passed=validate(b,tests)
    e=html.escape
    rows=''
    for t in b['trials']:
        if t.get('fatal_error'):
            rows += f"<tr><td>{e(t['mode'])}</td><td>{t['trial']}</td><td colspan='6'>FAILED: {e(t['fatal_error'])}</td></tr>"
            continue
        rows+=f"<tr><td>{e(t['mode'])}</td><td>{t['trial']}</td><td>{t['correct']}/{t['scheduled']}</td><td>{t['errors']}</td><td>{t['achieved_correct_rps']:.1f}</td><td>{t['scheduled_e2e_p95_ms']:.2f}</td><td>{t['send_lag_p95_ms']:.2f}</td><td>{t['sampled_peak_sum_rss_bytes']/1048576:.1f}</td></tr>"
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Shiftstead — measured deployment evidence</title>
<style>body{{font:16px system-ui;max-width:1120px;margin:40px auto;padding:0 20px;color:#172e32;background:#f6f8f7}}h1{{font-size:36px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #ddd}}code{{overflow-wrap:anywhere}}.tag{{color:#14765a}}p{{line-height:1.6}}@media(max-width:700px){{table{{font-size:12px}}td,th{{padding:6px}}}}</style>
<h1>Shiftstead</h1><p>Single-host HTTP deployments with health gates, draining and recovery.</p>
<p class="tag">Evidence: {'PASS' if passed else 'FAIL'} · {tests['tests']} formal tests · 5 targeted mutations detected · {len(b['trials'])} real-process trials</p>
<p>Environment: {e(json.dumps(b['environment']))}</p><p>Source SHA-256: <code>{e(b['source']['sha256'])}</code></p>
<h2>All trials</h2><div style="overflow:auto"><table><tr><th>Mode</th><th>Trial</th><th>Correct/offered</th><th>Errors</th><th>Achieved req/s</th><th>Scheduled p95 ms</th><th>Sender lag p95 ms</th><th>Request-window RSS MiB</th></tr>{rows}</table></div>
<h2>Interpretation and limits</h2><p>{e(b['method']['throughput'])}. {e(b['method']['latency'])}. {e(b['method']['memory'])}. {e(b['method']['transport'])}.</p>
<p>Identical scheduled arrivals, payloads and worker delay; comparison order rotates. Deployment trials must observe both versions. Every planned trial is required; fatal trials remain failures. Payload hashes and release versions are checked. RSS collection runs in a sampler thread in the load-generator process, so instrumentation and host scheduling can affect measured latency. RSS is sampled, not an exact peak or unique physical-memory measure.</p>
<p>{e(b['method']['scope'])}. Controller restart may interrupt connections; rollback does not undo database changes. Readiness is an application assertion, not proof of business correctness. Benchmark failures or missing evidence must fail validation.</p>
<p><a href="benchmark.json">Raw benchmark JSON</a> · <a href="tests.json">Test evidence</a> · <a href="validation.json">Validation status</a></p></html>'''


def main():
    b=json.loads(Path('results/benchmark.json').read_text())
    t=json.loads(Path('results/tests.json').read_text())
    validate(b,t)
    mutations=json.loads(Path('results/mutations.json').read_text())
    validation=json.loads(Path('results/validation.json').read_text())
    run_id=validation.get('run_id')
    if not run_id or any(x.get('run_id')!=run_id for x in [b,t,mutations]):
        raise SystemExit('evidence belongs to different validation run')
    stages=validation.get('stages',[])
    if validation.get('status') not in {'running','passed'} or validation.get('source')!=b['source'] or len(stages)<3 or any(x['exit_code'] or x['timed_out'] or x['leaked_workers_cleaned'] for x in stages):
        raise SystemExit('validation not ready for successful rendering')
    if not mutations['passed'] or mutations['source']!=b['source'] or len(mutations['cases'])!=5 or any(not x['detected'] or x['timed_out'] for x in mutations['cases']):
        raise SystemExit('mutation evidence not passing/current')
    if b['source']!=provenance():raise SystemExit('source changed since evidence generation')
    Path('results/report.html').write_text(render(b,t))
    if not b['passed']:
        raise SystemExit(1)
if __name__=='__main__':main()
