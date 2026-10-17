import asyncio
import json
import os
import secrets
import socket
import sys
import tempfile
import time
from pathlib import Path
import psutil
from aiohttp import ClientSession, ClientTimeout

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]

class Harness:
    def __init__(self,max_inflight=128,request_timeout=5):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        registry=os.environ.get("SHIFTSTEAD_TEST_REGISTRY")
        if registry:
            (Path(registry)/(secrets.token_hex(8)+".json")).write_text(json.dumps({"state":str(self.root)}))
        self.port,self.admin = port(),port()
        self.max_inflight,self.request_timeout = max_inflight,request_timeout
        self.process = self.session = None
    async def start(self):
        self.process = await asyncio.create_subprocess_exec(sys.executable,'-m','rollout','--state',str(self.root),'--admin-port',str(self.admin),'serve','--port',str(self.port),'--max-inflight',str(self.max_inflight),'--request-timeout',str(self.request_timeout),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        line = await asyncio.wait_for(self.process.stdout.readline(),5)
        if not line:
            raise RuntimeError((await self.process.stderr.read()).decode())
        assert json.loads(line)['ready']
        self.session = ClientSession(timeout=ClientTimeout(total=10),headers={'Authorization':'Bearer '+(self.root/'admin.token').read_text()})
        self.session._retry_connection = False
        return self
    async def call(self,path,data=None):
        method = self.session.get if data is None else self.session.post
        async with method(f'http://127.0.0.1:{self.admin}'+path,**({} if data is None else {'json':data})) as r:
            raw = await r.text()
            try: value = json.loads(raw)
            except ValueError: value = raw
            return r.status,value
    async def status(self):
        code,value = await self.call('/status')
        assert code == 200,value
        return value
    async def wait(self,predicate,timeout=8):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            value = await self.status()
            if predicate(value):return value
            await asyncio.sleep(.01)
        raise AssertionError('condition timeout: '+json.dumps(await self.status()))
    def spec(self,version,args=(),**kw):
        return {'version':version,'command':[sys.executable,'-m','rollout.demo','--version',version,*args],'startup_timeout':1.5,'observe':.15,'drain_timeout':1,'retain':.15,**kw}
    async def deploy(self,version,args=(),**kw):
        code,value = await self.call('/deploy',{'id':version,'spec':self.spec(version,args,**kw)})
        assert code == 202,value
        return value['generation']
    async def settled(self):
        return await self.wait(lambda s:s['operation'] and s['operation']['state'] in {'done','failed','rolled_back'})
    async def get(self,path='/',method='GET',body=None):
        async with self.session.request(method,f'http://127.0.0.1:{self.port}'+path,data=body) as r:
            return r.status,dict(r.headers),await r.read()
    async def crash(self):
        self.process.kill()
        await self.process.wait()
        await self.session.close()
        self.session = None
    async def cleanup(self):
        if self.process and self.process.returncode is None:
            try:await self.call('/stop',{})
            except Exception:pass
            self.process.terminate()
            try:await asyncio.wait_for(self.process.wait(),5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.session:await self.session.close()
        for f in self.root.glob('*.identity'):
            r = json.loads(f.read_text())
            try:
                p = psutil.Process(r['pid'])
                if abs(p.create_time()-r['created'])<.001:p.kill()
            except psutil.Error:pass
        self.tmp.cleanup()
