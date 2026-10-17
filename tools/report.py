"""Validate retained raw evidence and render HTML without executing supplied markup."""
import html
import json
import math
from pathlib import Path
from tools.benchmark import percentile
from tools.evidence import provenance


def validate(b,tests=None):
    if b.get('schema')!=1 or b.get('kind')!='real-process-open-loop' or not b.get('trials'):
        raise ValueError('missing benchmark trials')
    outcomes=[];schedules=set();pairs={}
    for t in b['trials']:
        mode=t['mode'];n=t['scheduled'];rows=t['requests'];pairs.setdefault(t['trial'],set()).add(mode)
        if mode not in {'direct','proxy','deploy'} or n<=0 or {r['id'] for r in rows}!=set(range(n)) or len(rows)!=n:
            raise ValueError('missing, duplicate or invalid requests')
        if t['received']!=n or t['unique_ids']!=n:raise ValueError('request accounting mismatch')
        good=0
        for r in rows:
            body=r['response'] or {}
            correct=r['status']==200 and body.get('id')==str(r['id']) and body.get('bytes')==256 and body.get('version') in {'v1','v2'}
            if correct!=r['correct'] or body.get('version')!=r['version']:raise ValueError('response correctness mismatch')
            good+=correct
            e2e=(r['completed_s']-r['scheduled_s'])*1000
            service=(r['completed_s']-r['sent_s'])*1000
            lag=max(0,r['sent_s']-r['scheduled_s'])*1000
            for v in [e2e,service,lag]:
                if not math.isfinite(v) or v<0:raise ValueError('invalid time')
            if any(abs(x-y)>.00001 for x,y in [(e2e,r['scheduled_e2e_ms']),(service,r['service_latency_ms']),(lag,r['send_lag_ms'])]):raise ValueError('latency mismatch')
        import hashlib
        schedule_hash=hashlib.sha256(json.dumps([r['scheduled_s'] for r in sorted(rows,key=lambda x:x['id'])]).encode()).hexdigest()
        if schedule_hash!=t['schedule_sha256']:raise ValueError('schedule digest mismatch')
        schedules.add(schedule_hash)
        expected=good==n and (mode!='deploy' or (t['deployment']['state']=='done' and {r['version'] for r in rows}=={'v1','v2'}))
        if good!=t['correct'] or n-good!=t['errors'] or expected!=t['passed']:raise ValueError('outcome mismatch')
        observation=max(r['completed_s'] for r in rows)
        if abs(observation-t['observation_s'])>.05:raise ValueError('observation window mismatch')
        if not math.isclose(t['achieved_correct_rps'],good/t['observation_s']):raise ValueError('throughput mismatch')
        for label,p in [('scheduled_e2e_p50_ms',.5),('scheduled_e2e_p95_ms',.95)]:
            if not math.isclose(t[label],percentile([r['scheduled_e2e_ms'] for r in rows],p)):raise ValueError('percentile mismatch')
        memory=t['memory_samples']
        if not memory or any(r['sum_rss_bytes']!=r['controller_rss_bytes']+r['workers_rss_bytes'] for r in memory):raise ValueError('RSS accounting mismatch')
        for label,key in [('controller','controller_rss_bytes'),('workers','workers_rss_bytes'),('sum','sum_rss_bytes')]:
            if t[f'sampled_peak_{label}_rss_bytes']!=max(r[key] for r in memory):raise ValueError('RSS peak mismatch')
        outcomes.append(expected)
    if any(modes!={'direct','proxy','deploy'} for modes in pairs.values()) or len(b['trials'])!=3*len(pairs):raise ValueError('incomplete/duplicated comparison')
    same=len(schedules)==1
    if b['same_schedule']!=same or b['passed']!=(all(outcomes) and same):raise ValueError('overall outcome mismatch')
    if tests is not None:
        if not tests['passed'] or tests['tests']<=0 or tests['skipped'] or tests['failures'] or tests['errors'] or len(tests['cases'])!=tests['tests'] or any(x['outcome']!='passed' for x in tests['cases']):raise ValueError('test evidence not passing')
        if tests['source']!=b['source']:raise ValueError('test/benchmark source mismatch')
    return b['passed']


def render(b,tests):
    passed=validate(b,tests)
    e=html.escape
    rows=''
    for t in b['trials']:
        rows+=f"<tr><td>{e(t['mode'])}</td><td>{t['trial']}</td><td>{t['correct']}/{t['scheduled']}</td><td>{t['errors']}</td><td>{t['achieved_correct_rps']:.1f}</td><td>{t['scheduled_e2e_p95_ms']:.2f}</td><td>{t['send_lag_p95_ms']:.2f}</td><td>{t['sampled_peak_sum_rss_bytes']/1048576:.1f}</td></tr>"
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Shiftstead — measured deployment evidence</title>
<style>body{{font:16px system-ui;max-width:1120px;margin:40px auto;padding:0 20px;color:#172e32;background:#f6f8f7}}h1{{font-size:36px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #ddd}}code{{overflow-wrap:anywhere}}.tag{{color:#14765a}}p{{line-height:1.6}}@media(max-width:700px){{table{{font-size:12px}}td,th{{padding:6px}}}}</style>
<h1>Shiftstead</h1><p>Single-host HTTP deployments with health gates, draining and recovery.</p>
<p class="tag">Evidence: {'PASS' if passed else 'FAIL'} · {tests['tests']} formal tests · 5 targeted mutations detected · {len(b['trials'])} real-process trials</p>
<p>Environment: {e(json.dumps(b['environment']))}</p><p>Source SHA-256: <code>{e(b['source']['sha256'])}</code></p>
<h2>All trials</h2><div style="overflow:auto"><table><tr><th>Mode</th><th>Trial</th><th>Correct/offered</th><th>Errors</th><th>Achieved req/s</th><th>Scheduled p95 ms</th><th>Sender lag p95 ms</th><th>Peak summed RSS MiB</th></tr>{rows}</table></div>
<h2>Interpretation and limits</h2><p>{e(b['method']['throughput'])}. {e(b['method']['latency'])}. {e(b['method']['memory'])}.</p>
<p>Identical scheduled arrivals, payloads and worker delay; comparison order rotates. Deployment trials must observe both versions. No failed trials are filtered from this report. RSS is sampled, not an exact peak or unique physical-memory measure.</p>
<p>{e(b['method']['scope'])}. Controller restart may interrupt connections; rollback does not undo database changes. Readiness is an application assertion, not proof of business correctness. Benchmark failures or missing evidence must fail validation.</p>
<p><a href="benchmark.json">Raw benchmark JSON</a> · <a href="tests.json">Test evidence</a> · <a href="validation.json">Validation status</a></p></html>'''


def main():
    b=json.loads(Path('results/benchmark.json').read_text())
    t=json.loads(Path('results/tests.json').read_text())
    validate(b,t)
    mutations=json.loads(Path('results/mutations.json').read_text())
    if not mutations['passed'] or mutations['source']!=b['source'] or len(mutations['cases'])!=5 or any(not x['detected'] or x['timed_out'] for x in mutations['cases']):
        raise SystemExit('mutation evidence not passing/current')
    if b['source']!=provenance():raise SystemExit('source changed since evidence generation')
    Path('results/report.html').write_text(render(b,t))
if __name__=='__main__':main()
