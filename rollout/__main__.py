import argparse
import asyncio
import json
import secrets
import signal
import sys
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout, web
from .core import Controller

async def serve(a):
    c = Controller(a.state, a.max_inflight, a.request_timeout)
    await c.start()
    @web.middleware
    async def auth(r, handler):
        if not secrets.compare_digest(r.headers.get('Authorization', ''), 'Bearer ' + c.store.token):
            raise web.HTTPUnauthorized()
        try:
            return await handler(r)
        except (ValueError, KeyError, TypeError) as e:
            raise web.HTTPBadRequest(text=str(e))
    async def status(r):
        return web.json_response(c.status())
    async def history(r):
        rows = c.store.db.execute('SELECT at,generation,kind,detail FROM events ORDER BY n DESC LIMIT 200').fetchall()
        return web.json_response([dict(at=x[0],generation=x[1],kind=x[2],detail=json.loads(x[3])) for x in rows])
    async def submit(r):
        v = await r.json()
        g = await c.submit(v['id'], v.get('spec'), r.path == '/rollback')
        return web.json_response({'generation': g}, status=202)
    async def stop(r):
        stopped = await c.stop_all()
        return web.json_response({'stopped': stopped}, status=200 if stopped else 409)
    admin = web.Application(middlewares=[auth], client_max_size=65536)
    admin.router.add_get('/status', status)
    admin.router.add_get('/history', history)
    admin.router.add_post('/deploy', submit)
    admin.router.add_post('/rollback', submit)
    admin.router.add_post('/stop', stop)
    async def proxy(r):
        try:
            async with asyncio.timeout(a.request_timeout):
                return await c.proxy(r)
        except TimeoutError:
            if r.transport:
                r.transport.close()
            raise web.HTTPGatewayTimeout()
    gateway = web.Application(client_max_size=1024*1024)
    gateway.router.add_route('*', '/{tail:.*}', proxy)
    runners = []
    done = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, done.set)
    try:
        for app, port in [(admin,a.admin_port),(gateway,a.port)]:
            runner = web.AppRunner(app, access_log=None, handler_cancellation=True, shutdown_timeout=1, auto_decompress=False)
            runners.append(runner)
            await runner.setup()
            await web.TCPSite(runner,'127.0.0.1',port).start()
        print(json.dumps({'ready':True,'port':a.port,'admin_port':a.admin_port}),flush=True)
        await done.wait()
    finally:
        for runner in reversed(runners):
            await runner.cleanup()
        await c.close()

async def client(a):
    token = (Path(a.state)/'admin.token').read_text().strip()
    async with ClientSession(timeout=ClientTimeout(total=10),headers={'Authorization':'Bearer '+token}) as s:
        url = f'http://127.0.0.1:{a.admin_port}/'+a.action
        if a.action in {'status','history'}:
            r = await s.get(url)
        else:
            data = {'id':a.id} if hasattr(a,'id') else {}
            if a.action == 'deploy':
                data['spec'] = json.loads(Path(a.manifest).read_text())
            r = await s.post(url,json=data)
        print(await r.text())
        if r.status >= 400:
            raise SystemExit(1)

def main():
    p = argparse.ArgumentParser(prog='shiftstead',description='Single-host HTTP deployment controller')
    p.add_argument('--state',default='.state')
    p.add_argument('--admin-port',type=int,default=9401)
    sub = p.add_subparsers(dest='action',required=True)
    s = sub.add_parser('serve')
    s.add_argument('--port',type=int,default=9400)
    s.add_argument('--max-inflight',type=int,default=128)
    s.add_argument('--request-timeout',type=float,default=5)
    for action in ['status','history','stop']:
        sub.add_parser(action)
    d = sub.add_parser('deploy')
    d.add_argument('manifest')
    d.add_argument('--id',required=True)
    r = sub.add_parser('rollback')
    r.add_argument('--id',required=True)
    a = p.parse_args()
    if not 1 <= a.admin_port <= 65535:
        p.error('invalid admin port')
    if a.action == 'serve' and (not 1 <= a.port <= 65535 or not 1 <= a.max_inflight <= 4096 or not .1 <= a.request_timeout <= 300):
        p.error('invalid serving limits')
    try:
        asyncio.run(serve(a) if a.action == 'serve' else client(a))
    except KeyboardInterrupt:
        pass
    except (OSError,RuntimeError) as e:
        print(str(e),file=sys.stderr)
        raise SystemExit(1)

if __name__ == '__main__':
    main()
