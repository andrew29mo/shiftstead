"""Real HTTP demo worker; failure knobs are for integration tests and demos."""
import argparse
import asyncio
import os
import time
from aiohttp import web


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--version', required=True)
    p.add_argument('--ready-after', type=float, default=0)
    p.add_argument('--fail-after', type=float)
    p.add_argument('--unready', action='store_true')
    p.add_argument('--exit', action='store_true')
    a = p.parse_args()
    if a.exit:
        raise SystemExit(23)
    start = time.monotonic()
    async def health(request):
        age = time.monotonic() - start
        ready = not a.unready and age >= a.ready_after and (a.fail_after is None or age < a.fail_after)
        return web.json_response({'instance': os.environ['ROLLOUT_INSTANCE'], 'ready': ready}, status=200 if ready else 503)
    async def work(request):
        delay = min(10, max(0, float(request.query.get('delay', 0))))
        await asyncio.sleep(delay)
        body = await request.read()
        return web.json_response({'version': a.version, 'id': request.query.get('id'), 'bytes': len(body)})
    async def stream(request):
        r = web.StreamResponse()
        await r.prepare(request)
        for _ in range(10):
            await r.write(b'x' * 1024)
            await asyncio.sleep(.05)
        await r.write_eof()
        return r
    app = web.Application(client_max_size=1024 * 1024)
    app.router.add_get('/readyz', health)
    app.router.add_get('/stream', stream)
    app.router.add_route('*', '/{tail:.*}', work)
    web.run_app(app, host='127.0.0.1', port=int(os.environ['PORT']), print=None, access_log=None)


if __name__ == '__main__':
    main()
