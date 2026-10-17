import asyncio
import json
import sys
import unittest
from aiohttp import ClientSession
from tests.harness import Harness

class Integration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.h = await Harness().start()
    async def asyncTearDown(self):await self.h.cleanup()
    async def first(self):
        await self.h.deploy('v1')
        s = await self.h.settled()
        self.assertEqual(s['operation']['state'],'done')
        return s
    async def test_no_route_and_admin_auth(self):
        self.assertEqual((await self.h.get())[0],503)
        async with ClientSession() as c:
            async with c.get(f'http://127.0.0.1:{self.h.admin}/status') as r:self.assertEqual(r.status,401)
    async def test_real_worker_and_post(self):
        await self.first()
        code,headers,body = await self.h.get('/?id=42','POST',b'abc')
        self.assertEqual(code,200)
        self.assertEqual(headers['X-Rollout-Version'],'v1')
        self.assertEqual(json.loads(body),{'version':'v1','id':'42','bytes':3,'sha256':__import__('hashlib').sha256(b'abc').hexdigest(),'raw_path':'/?id=42'})
    async def test_start_failure_never_routes(self):
        await self.first()
        await self.h.deploy('bad',['--exit'],startup_timeout=.2)
        self.assertEqual((await self.h.settled())['operation']['state'],'failed')
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
    async def test_unready_timeout(self):
        await self.first()
        await self.h.deploy('bad',['--unready'],startup_timeout=1.5)
        self.assertEqual((await self.h.settled())['operation']['state'],'failed')
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
    async def test_readiness_blocks_early_route(self):
        await self.first()
        await self.h.deploy('v2',['--ready-after','.4'])
        await self.h.wait(lambda s:s['operation']['state']=='starting')
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
        await self.h.settled()
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v2')
    async def test_idempotency_and_conflict(self):
        spec = self.h.spec('v1',observe=.4)
        a,x = await self.h.call('/deploy',{'id':'same','spec':spec})
        b,y = await self.h.call('/deploy',{'id':'same','spec':spec})
        self.assertEqual((a,b),(202,202));self.assertEqual(x,y)
        self.assertEqual((await self.h.call('/deploy',{'id':'same','spec':self.h.spec('other')}))[0],409)
        self.assertEqual((await self.h.call('/deploy',{'id':'other','spec':self.h.spec('v2')}))[0],409)
    async def test_graceful_drain(self):
        old = (await self.first())['route']
        pending = asyncio.create_task(self.h.get('/?delay=.8&id=old'))
        await self.h.wait(lambda s:s['inflight'].get(old)==1)
        await self.h.deploy('v2')
        await self.h.wait(lambda s:s['route']!=old)
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v2')
        self.assertEqual(json.loads((await pending)[2])['version'],'v1')
        s = await self.h.settled()
        self.assertEqual(s['metrics']['forced'],0)
        self.assertEqual(s['metrics']['accepted'],s['metrics']['completed'])
    async def test_drain_expiry_counts_aborted(self):
        old = (await self.first())['route']
        pending = asyncio.create_task(self.h.get('/?delay=2'))
        await self.h.wait(lambda s:s['inflight'].get(old)==1)
        await self.h.deploy('v2',drain_timeout=.05)
        with self.assertRaises(Exception):await pending
        s = await self.h.settled()
        self.assertEqual(s['metrics']['forced'],1)
        self.assertEqual(s['metrics']['failed'],1)
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v2')
    async def test_auto_rollback(self):
        await self.first()
        await self.h.deploy('v2',['--fail-after','.3'],observe=.8)
        self.assertEqual((await self.h.settled())['operation']['state'],'rolled_back')
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
    async def test_unhealthy_rollback_target(self):
        await self.h.deploy('v1',['--fail-after','.7'])
        await self.h.settled()
        await self.h.deploy('v2',['--fail-after','.7'],observe=1.2)
        s = await self.h.settled()
        self.assertEqual(s['operation']['state'],'failed')
        self.assertEqual(s['degraded'],'rollback target unavailable')
    async def test_manual_rollback_fences_cleanup(self):
        await self.first()
        await self.h.deploy('v2',retain=1)
        await self.h.wait(lambda s:s['operation']['state']=='retaining')
        previous = (await self.h.status())['generation']
        code,reply = await self.h.call('/rollback',{'id':'undo'})
        self.assertEqual(code,202);self.assertGreater(reply['generation'],previous)
        self.assertEqual((await self.h.settled())['operation']['state'],'rolled_back')
        await asyncio.sleep(1.1)
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
    async def test_restart_route_and_idempotency(self):
        s = await self.first()
        await self.h.crash();await self.h.start()
        self.assertEqual((await self.h.status())['route'],s['route'])
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
        self.assertEqual((await self.h.call('/deploy',{'id':'v1','spec':self.h.spec('v1')}))[1]['generation'],1)
    async def test_restart_before_switch(self):
        await self.first()
        await self.h.deploy('v2',['--ready-after','2'],startup_timeout=3)
        await self.h.wait(lambda s:s['operation']['state']=='starting')
        await asyncio.sleep(.1)
        await self.h.crash();await self.h.start()
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
        self.assertTrue((await self.h.status())['operation']['recovered'])
        self.assertEqual((await self.h.status())['operation']['state'],'failed')
    async def test_restart_during_drain(self):
        old = (await self.first())['route']
        pending = asyncio.create_task(self.h.get('/?delay=2'))
        await self.h.wait(lambda s:s['inflight'].get(old)==1)
        await self.h.deploy('v2',drain_timeout=3)
        await self.h.wait(lambda s:s['operation']['state']=='draining')
        await self.h.crash()
        with self.assertRaises(Exception):await pending
        await self.h.start()
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v2')
        self.assertTrue((await self.h.status())['operation']['recovered'])
    async def test_restart_bad_committed_route(self):
        await self.first()
        await self.h.deploy('v2',['--fail-after','.6'],observe=2)
        await self.h.wait(lambda s:s['operation']['state']=='observing')
        await self.h.crash();await asyncio.sleep(.8);await self.h.start()
        self.assertEqual((await self.h.get())[1]['X-Rollout-Version'],'v1')
    async def test_compressed_body_preserved(self):
        import gzip
        await self.first()
        payload=b'compressed payload' * 20
        async with self.h.session.post(f'http://127.0.0.1:{self.h.port}/?id=gzip',data=gzip.compress(payload),headers={'Content-Encoding':'gzip'}) as r:
            self.assertEqual(r.status,200)
            value=await r.json()
            self.assertEqual(value['bytes'],len(payload))
            self.assertEqual(value['sha256'],__import__('hashlib').sha256(payload).hexdigest())
            self.assertEqual(value['id'],'gzip')
    async def test_stream_complete(self):
        await self.first()
        code,_,body = await self.h.get('/stream')
        self.assertEqual(code,200);self.assertEqual(body,b'x'*10240)
    async def test_body_and_upgrade_limits(self):
        await self.first()
        self.assertEqual((await self.h.get('/','POST',b'x'*(1024*1024+1)))[0],413)
        async with self.h.session.get(f'http://127.0.0.1:{self.h.port}/',headers={'Upgrade':'websocket'}) as r:self.assertEqual(r.status,501)
    async def test_validation_and_missing_rollback(self):
        self.assertEqual((await self.h.call('/rollback',{'id':'undo'}))[0],409)
        for spec in [{'version':'../bad','command':['x']},{'version':'ok','command':'shell'},self.h.spec('v',observe=float('nan'))]:
            self.assertEqual((await self.h.call('/deploy',{'id':'bad','spec':spec}))[0],400)
    async def test_stop_cleans_owned_processes(self):
        await self.first();await self.h.call('/stop',{})
        self.assertEqual((await self.h.get())[0],503)
        import psutil
        for f in self.h.root.glob('*.identity'):
            r = json.loads(f.read_text())
            try:self.assertNotEqual(psutil.Process(r['pid']).create_time(),r['created'])
            except psutil.NoSuchProcess:pass
    async def test_second_owner_rejected(self):
        p = await asyncio.create_subprocess_exec(sys.executable,'-m','rollout','--state',str(self.h.root),'serve',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        _,error = await asyncio.wait_for(p.communicate(),3)
        self.assertNotEqual(p.returncode,0);self.assertIn(b'already owned',error)

class Limits(unittest.IsolatedAsyncioTestCase):
    async def test_overload(self):
        h = await Harness(max_inflight=1).start()
        try:
            await h.deploy('v1');old=(await h.settled())['route']
            pending=asyncio.create_task(h.get('/?delay=.4'))
            await h.wait(lambda s:s['inflight'].get(old)==1)
            self.assertEqual((await h.get())[0],503)
            self.assertEqual((await pending)[0],200)
            self.assertEqual((await h.status())['metrics']['rejected'],1)
        finally:await h.cleanup()
