"""Adversarial real-process/socket checks added during the first review."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
import psutil
from aiohttp import web
from rollout.core import Controller
from tests.harness import Harness

class LifecycleReview(unittest.IsolatedAsyncioTestCase):
    async def test_stop_serializes_new_deployment(self):
        h=await Harness().start()
        pending=stopping=None
        try:
            await h.deploy('v1');wid=(await h.settled())['route']
            pending=asyncio.create_task(h.get('/?delay=.7'))
            await h.wait(lambda s:s['inflight'].get(wid)==1)
            stopping=asyncio.create_task(h.call('/stop',{}))
            await h.wait(lambda s:s['route'] is None)
            code,_=await h.call('/deploy',{'id':'new','spec':h.spec('v2')})
            self.assertEqual(code,409,'a stop in progress must reserve the lifecycle')
            self.assertEqual((await stopping)[0],200)
            self.assertEqual((await pending)[0],200)
            self.assertIsNone((await h.status())['route'])
        finally:
            await asyncio.gather(*(x for x in [pending,stopping] if x),return_exceptions=True)
            await h.cleanup()
    async def test_health_not_starved_by_gateway_connector(self):
        h=await Harness(max_inflight=1).start();pending=None
        try:
            await h.deploy('v1');wid=(await h.settled())['route']
            pending=asyncio.create_task(h.get('/?delay=1.4'))
            await h.wait(lambda s:s['inflight'].get(wid)==1)
            await h.deploy('v2',startup_timeout=.7,drain_timeout=2)
            s=await h.settled()
            self.assertEqual(s['operation']['state'],'done')
            self.assertEqual((await pending)[0],200)
        finally:
            if pending:await asyncio.gather(pending,return_exceptions=True)
            await h.cleanup()
    async def test_unknown_launch_still_checks_committed_route(self):
        h=await Harness().start()
        try:
            await h.deploy('v1');s=await h.settled();wid=s['route']
            await h.crash()
            rec=json.loads((h.root/(wid+'.identity')).read_text())
            psutil.Process(rec['pid']).kill();await asyncio.sleep(.05)
            c=Controller(h.root)
            c.s['workers']['uncertain']={'id':'uncertain','token':'unknown','port':1,'stopping':False}
            c.store.save('launching');c.store.close()
            await h.start();s=await h.status()
            self.assertIsNone(s['route'],'unknown launch must not bypass route health')
            self.assertEqual((await h.get())[0],503)
        finally:await h.cleanup()
    async def test_rollback_during_drain_preserves_old_request(self):
        h=await Harness().start();pending=None
        try:
            await h.deploy('v1');wid=(await h.settled())['route']
            pending=asyncio.create_task(h.get('/?delay=1.1'))
            await h.wait(lambda s:s['inflight'].get(wid)==1)
            await h.deploy('v2',drain_timeout=2)
            await h.wait(lambda s:s['operation']['state']=='draining')
            self.assertEqual((await h.call('/rollback',{'id':'undo'}))[0],202)
            self.assertEqual(json.loads((await pending)[2])['version'],'v1')
            self.assertEqual((await h.settled())['operation']['state'],'rolled_back')
            self.assertEqual((await h.get())[1]['X-Rollout-Version'],'v1')
        finally:
            if pending:await asyncio.gather(pending,return_exceptions=True)
            await h.cleanup()

class HealthReview(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Controller(self.tmp.name)
        await self.c.start();self.runner=None
        self.worker={'id':'probe','token':'known','stopping':False}
        (Path(self.tmp.name)/'probe.identity').write_text(json.dumps({'pid':psutil.Process().pid,'created':psutil.Process().create_time(),'token':'known'}))
    async def asyncTearDown(self):
        if self.runner:await self.runner.cleanup()
        await self.c.close();self.tmp.cleanup()
    async def backend(self,handler):
        app=web.Application();app.router.add_get('/{tail:.*}',handler)
        self.runner=web.AppRunner(app,access_log=None)
        await self.runner.setup();site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        self.worker['port']=site._server.sockets[0].getsockname()[1]
    async def test_fragmented_valid_health_body(self):
        async def handler(r):
            response=web.StreamResponse();await response.prepare(r)
            await response.write(b'{"instance":"known",');await asyncio.sleep(.03)
            await response.write(b'"ready":true}');await response.write_eof();return response
        await self.backend(handler)
        self.assertTrue(await self.c.health(self.worker))
    async def test_valid_prefix_plus_invalid_tail_is_not_healthy(self):
        async def handler(r):
            response=web.StreamResponse();await response.prepare(r)
            await response.write(b'{"instance":"known","ready":true}');await asyncio.sleep(.03)
            try:await response.write(b'not-json');await response.write_eof()
            except ConnectionResetError:pass
            return response
        await self.backend(handler)
        self.assertFalse(await self.c.health(self.worker))
    async def test_redirect_is_not_readiness(self):
        async def handler(r):
            if r.path=='/readyz':raise web.HTTPFound('/elsewhere')
            return web.json_response({'instance':'known','ready':True})
        await self.backend(handler)
        self.assertFalse(await self.c.health(self.worker))
    async def test_false_readiness_in_200(self):
        async def handler(r):return web.json_response({'instance':'known','ready':False})
        await self.backend(handler)
        self.assertFalse(await self.c.health(self.worker))
    async def test_oversized_health_body_rejected(self):
        async def handler(r):return web.Response(body=b' '*4097)
        await self.backend(handler)
        self.assertFalse(await self.c.health(self.worker))
    async def test_health_timeout_is_bounded(self):
        async def handler(r):
            await asyncio.sleep(.2)
            return web.json_response({'instance':'known','ready':True})
        await self.backend(handler)
        self.assertFalse(await self.c.health(self.worker,timeout=.03))

class TokenReview(unittest.TestCase):
    def test_empty_existing_token_does_not_disable_auth(self):
        from rollout.core import Store
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'admin.token').write_text('')
            with self.assertRaisesRegex(RuntimeError,'token invalid'):Store(root)
            (Path(root)/'admin.token').unlink()
            store=Store(root)
            self.assertGreaterEqual(len(store.token),32)
            self.assertEqual((Path(root)/'admin.token').stat().st_mode & 0o777,0o600)
            store.close()

class StopReview(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_does_not_cancel_stop(self):
        h=await Harness().start();pending=None
        try:
            await h.deploy('v1');wid=(await h.settled())['route']
            pending=asyncio.create_task(h.get('/?delay=.6'))
            await h.wait(lambda s:s['inflight'].get(wid)==1)
            reader,writer=await asyncio.open_connection('127.0.0.1',h.admin)
            token=(h.root/'admin.token').read_text().strip()
            message=f'POST /stop HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\nContent-Length: 2\r\n\r\n{{}}'
            writer.write(message.encode());await writer.drain()
            await h.wait(lambda s:s['operation']['state']=='stopping')
            writer.close();await writer.wait_closed()
            s=await h.settled()
            self.assertTrue(s['operation']['stopped'])
            self.assertIsNone(s['route'])
            self.assertEqual((await pending)[0],200)
        finally:
            if pending:await asyncio.gather(pending,return_exceptions=True)
            await h.cleanup()
    async def test_restart_finishes_persisted_stop(self):
        h=await Harness().start();pending=stopping=None
        try:
            await h.deploy('v1');wid=(await h.settled())['route']
            pending=asyncio.create_task(h.get('/?delay=2'))
            await h.wait(lambda s:s['inflight'].get(wid)==1)
            stopping=asyncio.create_task(h.call('/stop',{}))
            await h.wait(lambda s:s['operation']['state']=='stopping')
            await h.crash()
            await asyncio.gather(pending,stopping,return_exceptions=True)
            await h.start();s=await h.status()
            self.assertEqual(s['operation']['state'],'done')
            self.assertTrue(s['operation']['stopped'])
            self.assertIsNone(s['route'])
            await h.deploy('v2');self.assertEqual((await h.settled())['operation']['state'],'done')
        finally:
            await asyncio.gather(*(x for x in [pending,stopping] if x),return_exceptions=True)
            await h.cleanup()
    async def test_uncommitted_rollback_not_reported_as_success(self):
        h=await Harness().start()
        try:
            await h.deploy('v1');await h.settled()
            await h.deploy('v2',retain=3)
            s=await h.wait(lambda s:s['operation']['state']=='retaining')
            target=s['previous'];current=s['route']
            await h.crash()
            c=Controller(h.root)
            c.s['generation']+=1
            c.s['operation']={'kind':'rollback','id':'interrupted-rollback','generation':c.s['generation'],'state':'accepted','target':target}
            c.store.save('accepted');c.store.close()
            await h.start();s=await h.status()
            self.assertEqual(s['route'],current)
            self.assertEqual(s['operation']['state'],'failed')
            self.assertTrue(s['operation']['recovered'])
        finally:await h.cleanup()
    async def test_encoded_path_and_query_preserved(self):
        from yarl import URL
        h=await Harness().start()
        try:
            await h.deploy('v1');await h.settled()
            path='/a%2fb?id=%2f&z=%30'
            async with h.session.get(URL(f'http://127.0.0.1:{h.port}'+path,encoded=True)) as r:
                self.assertEqual(r.status,200)
                self.assertEqual((await r.json())['raw_path'],path)
        finally:await h.cleanup()

class IdentityReview(unittest.TestCase):
    def test_nonfinite_identity_cannot_authorize_a_signal(self):
        with tempfile.TemporaryDirectory() as root:
            c=Controller(root)
            worker={'id':'probe','token':'known','stopping':False}
            path=Path(root)/'probe.identity'
            try:
                for created in [float('nan'),float('inf'),True,-1]:
                    path.write_text(json.dumps({'pid':psutil.Process().pid,'created':created,'token':'known'}))
                    self.assertIsNone(c.identity(worker))
                    self.assertTrue(c.unknown_identity(worker))
            finally:c.store.close()

class CleanupReview(unittest.IsolatedAsyncioTestCase):
    async def check(self, rollback):
        h=await Harness().start();path=None;original=None
        try:
            await h.deploy('v1');await h.settled()
            await h.deploy('v2',retain=.4 if not rollback else 2)
            s=await h.wait(lambda s:s['operation']['state']=='retaining')
            wid=s['route'] if rollback else s['previous']
            path=h.root/(wid+'.identity');original=path.read_text()
            record=json.loads(original);record['created']=float('nan');path.write_text(json.dumps(record))
            if rollback:
                self.assertEqual((await h.call('/rollback',{'id':'undo-corrupt-cleanup'}))[0],202)
            s=await h.settled()
            self.assertEqual(s['operation']['state'],'failed','incomplete cleanup must not be marked complete')
            self.assertIsNotNone(s['degraded'])
            if rollback:self.assertEqual(s['workers'][s['route']]['version'],'v1')
        finally:
            if path and original:path.write_text(original)
            await h.cleanup()
    async def test_deploy_cleanup_failure_is_not_done(self):await self.check(False)
    async def test_rollback_cleanup_failure_is_not_complete(self):await self.check(True)

class ValidationInterruptReview(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_reaps_stage_and_its_child(self):
        import signal
        stage="import subprocess,sys,json,time,psutil; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']); print(json.dumps({'pid':p.pid,'created':psutil.Process(p.pid).create_time()}),flush=True); time.sleep(20)"
        driver="from tools.process import run_stage; import sys; run_stage([sys.executable,'-c',"+repr(stage)+"],30)"
        p=await asyncio.create_subprocess_exec(sys.executable,'-c',driver,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        record=None
        try:
            record=json.loads(await asyncio.wait_for(p.stdout.readline(),5))
            p.send_signal(signal.SIGINT)
            await asyncio.wait_for(p.wait(),5)
            self.assertNotEqual(p.returncode,0)
            try:
                child=psutil.Process(record['pid'])
                self.assertTrue(child.create_time()!=record['created'] or child.status()==psutil.STATUS_ZOMBIE)
            except psutil.NoSuchProcess:pass
        finally:
            if p.returncode is None:p.kill();await p.wait()
            if record:
                try:
                    child=psutil.Process(record['pid'])
                    if child.create_time()==record['created']:child.kill()
                except psutil.Error:pass
