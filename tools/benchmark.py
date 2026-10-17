"""Open-loop scheduled requests against real processes; no sample exclusion."""
import argparse
import asyncio
import hashlib
import json
import math
import statistics
import time
from pathlib import Path
import psutil
from aiohttp import ClientSession,ClientTimeout,TCPConnector
from tests.harness import Harness
from tools.evidence import provenance,environment


def percentile(values,p):
    values=sorted(values)
    return values[max(0,math.ceil(len(values)*p)-1)] if values else None

async def trial(mode,number,count,rate):
    h=await Harness().start()
    rows=[];memory=[];deployment=None
    try:
        await h.deploy('v1');s=await h.settled()
        worker_port=s['workers'][s['route']]['port']
        target=worker_port if mode=='direct' else h.port
        async with ClientSession(timeout=ClientTimeout(total=5),connector=TCPConnector(limit=128),trust_env=False) as client:
            client._retry_connection=False
            for _ in range(20):
                async with client.post(f'http://127.0.0.1:{target}/warm',data=b'warm') as r:
                    if r.status!=200:raise RuntimeError('warmup failed')
                    await r.read()
            sampling=True
            async def sample():
                while sampling:
                    controller=psutil.Process(h.process.pid).memory_info().rss
                    workers=0
                    for f in h.root.glob('*.identity'):
                        record=json.loads(f.read_text())
                        try:
                            p=psutil.Process(record['pid'])
                            if abs(p.create_time()-record['created'])<.001 and p.status()!=psutil.STATUS_ZOMBIE:
                                workers+=p.memory_info().rss
                        except psutil.Error:pass
                    memory.append({'at_s':time.monotonic()-start,'controller_rss_bytes':controller,'workers_rss_bytes':workers,'sum_rss_bytes':controller+workers})
                    await asyncio.sleep(.01)
            async def request(i,offset):
                await asyncio.sleep(max(0,start+offset-time.monotonic()))
                sent=time.monotonic()
                row={'id':i,'scheduled_s':offset,'send_lag_ms':max(0,sent-start-offset)*1000,'status':None,'version':None,'error':None,'correct':False,'response':None,'sent_s':sent-start}
                try:
                    # Unique request id and identical payload/delay in every mode.
                    async with client.post(f'http://127.0.0.1:{target}/?id={i}&delay=.002',data=b'x'*256) as r:
                        row['status']=r.status
                        body=await r.json()
                        row['response']=body
                        row['version']=body.get('version')
                        row['correct']=r.status==200 and body.get('id')==str(i) and body.get('bytes')==256 and body.get('version') in {'v1','v2'}
                except Exception as e:row['error']=type(e).__name__
                finished=time.monotonic()
                row['completed_s']=finished-start
                row['service_latency_ms']=(finished-sent)*1000
                row['scheduled_e2e_ms']=(finished-start-offset)*1000
                rows.append(row)
            async def deploy():
                await asyncio.sleep(max(0,start+.35-time.monotonic()))
                began=time.monotonic()
                await h.deploy('v2',observe=.2,retain=.2)
                s=await h.settled()
                return {'seconds':time.monotonic()-began,'state':s['operation']['state'],'switched_at':s['operation'].get('switched_at')}
            schedule=[i/rate for i in range(count)]
            start=time.monotonic()+.05
            sampler=asyncio.create_task(sample())
            deploy_task=asyncio.create_task(deploy()) if mode=='deploy' else None
            await asyncio.gather(*(request(i,t) for i,t in enumerate(schedule)))
            end=time.monotonic()
            if deploy_task:deployment=await deploy_task
            sampling=False;await sampler
        ids=[r['id'] for r in rows]
        good=sum(r['correct'] for r in rows)
        metrics=(await h.status())['metrics']
        return {'mode':mode,'trial':number,'offered_rps':rate,'scheduled':count,'received':len(rows),'unique_ids':len(set(ids)),'correct':good,'errors':len(rows)-good,'schedule_sha256':hashlib.sha256(json.dumps(schedule).encode()).hexdigest(),'observation_s':end-start,'achieved_correct_rps':good/(end-start),'scheduled_e2e_p50_ms':percentile([r['scheduled_e2e_ms'] for r in rows],.5),'scheduled_e2e_p95_ms':percentile([r['scheduled_e2e_ms'] for r in rows],.95),'send_lag_p95_ms':percentile([r['send_lag_ms'] for r in rows],.95),'sampled_peak_controller_rss_bytes':max(r['controller_rss_bytes'] for r in memory),'sampled_peak_workers_rss_bytes':max(r['workers_rss_bytes'] for r in memory),'sampled_peak_sum_rss_bytes':max(r['sum_rss_bytes'] for r in memory),'deployment':deployment,'gateway_metrics':metrics,'requests':sorted(rows,key=lambda r:r['id']),'memory_samples':memory,'passed':good==count and len(set(ids))==count and (not deployment or (deployment['state']=='done' and {r['version'] for r in rows}=={'v1','v2'}))}
    finally:await h.cleanup()

async def run(a):
    rows=[]
    modes=['direct','proxy','deploy']
    for n in range(a.trials):
        # Rotate order, never select only favorable runs.
        for mode in modes[n%3:]+modes[:n%3]:
            print(f'trial {n+1}: {mode}',flush=True)
            rows.append(await trial(mode,n+1,a.count,a.rate))
    checks=len({r['schedule_sha256'] for r in rows})==1
    value={'schema':1,'kind':'real-process-open-loop','passed':all(r['passed'] for r in rows) and checks,'same_schedule':checks,'environment':environment(),'source':provenance(),'method':{'warmups':20,'payload_bytes':256,'worker_delay_s':.002,'rss_sample_interval_s':.01,'latency':'scheduled arrival to complete response, including sender lag; all outcomes retained','throughput':'correct responses / (last completion - first scheduled arrival), not capacity','memory':'sampled sum of controller and owned worker RSS; shared pages may count multiple times; excludes load generator. Direct mode retains idle controller.','scope':'loopback demo model, offered load only; not maximum throughput, production SLO or zero-downtime proof'},'trials':rows}
    Path('results/benchmark.json').write_text(json.dumps(value,indent=2)+'\n')
    if not value['passed']:raise SystemExit(1)

def main():
    p=argparse.ArgumentParser();p.add_argument('--trials',type=int,default=3);p.add_argument('--count',type=int,default=300);p.add_argument('--rate',type=float,default=200)
    a=p.parse_args()
    if a.trials<1 or a.count<150 or not 1<=a.rate<=300:p.error('invalid experiment size/rate')
    asyncio.run(run(a))
if __name__=='__main__':main()
