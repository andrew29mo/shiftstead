import asyncio
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
import psutil
from rollout.core import Controller, Store
from tests.harness import Harness

class Fences(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.c=Controller(self.tmp.name)
        await self.c.start()
    async def asyncTearDown(self):
        await self.c.close();self.tmp.cleanup()
    async def test_stale_route_and_stop_cannot_mutate(self):
        c=self.c
        c.s['generation']=7
        c.s['workers']={'new':{'id':'new','stopping':False}}
        c.s['route']='new'
        c.s['operation']={'state':'done'}
        snapshot=copy.deepcopy(c.s)
        self.assertFalse(await c.change_route(6,'new',None))
        self.assertFalse(await c.stop_worker('new',6))
        self.assertEqual(c.s,snapshot)
    async def test_identity_mismatch_never_signals_process(self):
        c=self.c
        p=await asyncio.create_subprocess_exec(sys.executable,'-c','import time;time.sleep(20)')
        try:
            w={'id':'other','token':'test','stopping':False}
            path=Path(self.tmp.name)/'other.identity'
            path.write_text(json.dumps({'pid':p.pid,'created':psutil.Process(p.pid).create_time()-1,'token':'test'}))
            c.s['workers']['other']=w
            self.assertIsNone(c.identity(w))
            await c.stop_worker('other',0)
            self.assertIsNone(p.returncode)
        finally:p.kill();await p.wait()
    async def test_storage_failure_fails_closed(self):
        c=self.c
        c.store.db.execute("CREATE TRIGGER fail_save BEFORE INSERT ON snapshot BEGIN SELECT RAISE(ABORT,'injected disk failure'); END")
        with self.assertRaises(Exception):c.store.save('fault')
        self.assertTrue(c.store.failed)
        self.assertFalse(c.fence(0))
        from aiohttp import web
        with self.assertRaises(web.HTTPServiceUnavailable):
            await c.submit('fail',{'version':'v','command':['false']})
    async def test_retry_disabled_in_formal_client(self):
        self.assertFalse(self.c.session._retry_connection)

class RecoverySafety(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_launch_outcome_is_not_relaunched(self):
        with tempfile.TemporaryDirectory() as root:
            c=Controller(root)
            c.s['workers']['lost']={'id':'lost','token':'missing','port':1,'stopping':False}
            c.store.save('launching');c.store.close()
            recovered=Controller(root)
            await recovered.start()
            try:
                self.assertIn('unknown',recovered.s['degraded'])
                self.assertIsNone(recovered.s['route'])
            finally:await recovered.close()
    async def test_client_disconnect_releases_capacity(self):
        h=await Harness(max_inflight=1).start()
        try:
            await h.deploy('v1');wid=(await h.settled())['route']
            reader,writer=await asyncio.open_connection('127.0.0.1',h.port)
            writer.write(b'GET /?delay=3 HTTP/1.1\r\nHost: localhost\r\n\r\n');await writer.drain()
            await h.wait(lambda s:s['inflight'].get(wid)==1)
            writer.close();await writer.wait_closed()
            await h.wait(lambda s:s['inflight'].get(wid)==0)
            self.assertEqual((await h.get())[0],200)
            self.assertEqual((await h.status())['metrics']['failed'],1)
        finally:await h.cleanup()
    async def test_no_healthy_route_after_restart_is_degraded(self):
        h=await Harness().start()
        try:
            await h.deploy('v1');s=await h.settled()
            await h.crash()
            r=json.loads((h.root/(s['route']+'.identity')).read_text())
            p=psutil.Process(r['pid']);p.kill()
            await asyncio.sleep(.1)
            await h.start()
            self.assertIsNone((await h.status())['route'])
            self.assertEqual((await h.get())[0],503)
            self.assertIn('no healthy',(await h.status())['degraded'])
        finally:await h.cleanup()

class FirstFailure(unittest.IsolatedAsyncioTestCase):
    async def test_first_release_unhealthy_has_no_route(self):
        h=await Harness().start()
        try:
            await h.deploy('v1',['--fail-after','.3'],observe=.8)
            s=await h.settled()
            self.assertEqual(s['operation']['state'],'failed')
            self.assertIsNone(s['route'])
            self.assertEqual((await h.get())[0],503)
            await h.call('/stop',{})
            self.assertIsNone((await h.status())['degraded'])
            await h.deploy('v2')
            self.assertEqual((await h.settled())['operation']['state'],'done')
        finally:await h.cleanup()
