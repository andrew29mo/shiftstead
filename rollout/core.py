import asyncio
import copy
import fcntl
import json
import math
import os
import re
import secrets
import socket
import sqlite3
import sys
import time
from pathlib import Path

import psutil
from aiohttp import ClientSession, ClientTimeout, TCPConnector, web

HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'expect'}


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.lock = (self.root / 'owner.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError('state directory already owned by another controller')
        self.db = sqlite3.connect(self.root / 'state.sqlite', isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (n INTEGER PRIMARY KEY, at REAL, generation INTEGER, kind TEXT, detail TEXT)')
        row = self.db.execute('SELECT value FROM snapshot WHERE id=1').fetchone()
        self.failed = False
        self.state = json.loads(row[0]) if row else {'generation': 0, 'route': None, 'previous': None, 'workers': {}, 'operation': None, 'requests': {}, 'degraded': None}
        token = self.root / 'admin.token'
        if not token.exists():
            fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(secrets.token_urlsafe(32))
        self.token = token.read_text().strip()

    def save(self, kind, detail=None):
        try:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT OR REPLACE INTO snapshot VALUES (1, ?)', (json.dumps(self.state),))
            self.db.execute('INSERT INTO events(at,generation,kind,detail) VALUES (?,?,?,?)', (time.time(), self.state['generation'], kind, json.dumps(detail or {})))
            self.db.execute('COMMIT')
        except BaseException:
            self.failed = True
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def close(self):
        self.db.close()
        self.lock.close()


class Controller:
    def __init__(self, root, max_inflight=128, request_timeout=5):
        self.store = Store(root)
        self.s = self.store.state
        self.mu = asyncio.Lock()
        self.active = {}
        self.transports = {}
        self.max_inflight = max_inflight
        self.request_timeout = request_timeout
        self.metrics = {'accepted': 0, 'completed': 0, 'failed': 0, 'rejected': 0, 'forced': 0}
        self.session = None
        self.task = None
        self.children = {}
        self.closing = False

    async def start(self):
        self.session = ClientSession(timeout=ClientTimeout(total=self.request_timeout), connector=TCPConnector(limit=self.max_inflight, force_close=True), auto_decompress=False, trust_env=False)
        # Pinned aiohttp retries some idempotent requests after disconnect by default.
        # Disable it: the gateway must never silently replay an upstream operation.
        self.session._retry_connection = False
        await self.recover()

    def identity(self, worker):
        record = self.store.root / (worker['id'] + '.identity')
        try:
            r = json.loads(record.read_text())
            if r['token'] != worker['token']:
                return None
            p = psutil.Process(r['pid'])
            if abs(p.create_time() - r['created']) > .001 or p.status() == psutil.STATUS_ZOMBIE:
                return None
            return p
        except (OSError, ValueError, KeyError, psutil.Error):
            return None

    async def health(self, worker):
        if worker.get('stopping') or self.identity(worker) is None:
            return False
        try:
            async with self.session.get(f"http://127.0.0.1:{worker['port']}/readyz", timeout=ClientTimeout(total=.25)) as r:
                if r.content_length and r.content_length > 4096:
                    return False
                raw = await r.content.read(4097)
                if len(raw) > 4096:
                    return False
                value = json.loads(raw)
                return r.status == 200 and value.get('instance') == worker['token'] and value.get('ready') is True
        except (Exception,):
            return False

    def fence(self, generation):
        return generation == self.s['generation'] and not self.closing and not self.store.failed

    def phase(self, name, **fields):
        self.s['operation'].update(state=name, **fields)
        self.store.save(name)

    async def stop_worker(self, worker_id, generation):
        async with self.mu:
            if not self.fence(generation) or self.s['route'] == worker_id:
                return False
            w = self.s['workers'].get(worker_id)
            if not w:
                return True
            w['stopping'] = True
            self.store.save('stopping', {'worker': worker_id})
            process = self.identity(w)
            if process:
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
        for _ in range(20):
            if self.identity(w) is None:
                break
            await asyncio.sleep(.025)
        async with self.mu:
            if not self.fence(generation) or self.s['route'] == worker_id:
                return False
            process = self.identity(w)
            if process:
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            self.store.save('stopped', {'worker': worker_id})
        child = self.children.pop(worker_id, None)
        if child:
            await child.wait()
        return True

    @staticmethod
    def validate(spec):
        if not isinstance(spec, dict) or set(spec) - {'version', 'command', 'startup_timeout', 'observe', 'drain_timeout', 'retain'}:
            raise ValueError('unknown deployment fields')
        if not isinstance(spec.get('version'), str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', spec['version']):
            raise ValueError('invalid version')
        cmd = spec.get('command')
        if not isinstance(cmd, list) or not 1 <= len(cmd) <= 64 or any(not isinstance(x, str) or not x or len(x) > 4096 or '\0' in x for x in cmd):
            raise ValueError('command must be an argument vector')
        result = copy.deepcopy(spec)
        for k, default in [('startup_timeout', 5), ('observe', 1), ('drain_timeout', 5), ('retain', 3)]:
            v = spec.get(k, default)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not .05 <= v <= 300:
                raise ValueError(k + ' must be between .05 and 300 seconds')
            result[k] = float(v)
        return result

    async def submit(self, key, spec=None, rollback=False):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', key):
            raise ValueError('invalid request id')
        spec = None if rollback else self.validate(spec)
        fingerprint = json.dumps({'rollback': rollback, 'spec': spec}, sort_keys=True)
        async with self.mu:
            if self.closing or self.store.failed:
                raise web.HTTPServiceUnavailable(text='controller shutting down')
            old = self.s['requests'].get(key)
            if old:
                if old['fingerprint'] != fingerprint:
                    raise web.HTTPConflict(text='request id reused for different content')
                return old['generation']
            if len(self.s['requests']) >= 1000:
                raise web.HTTPInsufficientStorage(text='operation history limit reached')
            op = self.s['operation']
            if self.s['degraded']:
                raise web.HTTPConflict(text='recovery requires operator intervention')
            if not rollback and op and op['state'] not in {'done', 'failed', 'rolled_back'}:
                raise web.HTTPConflict(text='deployment already in progress')
            target = self.s['previous'] if rollback else None
            if rollback and (not target or self.s['workers'][target].get('stopping')):
                raise web.HTTPConflict(text='no retained rollback target')
            gen = self.s['generation'] + 1
            if self.task:
                self.task.cancel()
            self.s['generation'] = gen
            self.s['operation'] = {'generation': gen, 'id': key, 'state': 'accepted', 'kind': 'rollback' if rollback else 'deploy', 'spec': spec, 'target': target}
            self.s['requests'][key] = {'generation': gen, 'fingerprint': fingerprint}
            self.store.save('accepted')
            self.task = asyncio.create_task(self.run_rollback(gen, target) if rollback else self.deploy(gen, spec))
            self.task.add_done_callback(lambda task: self.task_done(task, gen))
            return gen

    def task_done(self, task, generation):
        if not task.cancelled() and task.exception() and task is self.task and self.fence(self.s['generation']):
            self.s['degraded'] = 'operation error; inspect events and restart'
            self.store.save('operation_error', {'type': type(task.exception()).__name__})

    async def change_route(self, generation, target, previous):
        async with self.mu:
            if not self.fence(generation) or self.s['workers'][target].get('stopping'):
                return False
            self.s['route'] = target
            self.s['previous'] = previous
            self.phase('observing', switched_at=time.time())
            return True

    async def deploy(self, gen, spec):
        old = self.s['route']
        if self.s['previous'] and self.s['previous'] != old:
            await self.stop_worker(self.s['previous'], gen)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        wid = 'w-' + secrets.token_hex(8)
        w = {'id': wid, 'version': spec['version'], 'token': secrets.token_hex(24), 'port': port, 'stopping': False}
        async with self.mu:
            if not self.fence(gen):
                return
            self.s['workers'][wid] = w
            self.s['operation'].update(candidate=wid, old=old)
            self.phase('launching')
        env = dict(os.environ, PORT=str(port), ROLLOUT_INSTANCE=w['token'])
        command = [sys.executable, '-m', 'rollout.launch', str(self.store.root / (wid + '.identity')), w['token'], *spec['command']]
        # Launch intent is durable before spawn. Identity is persisted by launcher before exec.
        child = await asyncio.create_subprocess_exec(*command, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        self.children[wid] = child
        async with self.mu:
            if not self.fence(gen):
                return
            self.phase('starting')
        deadline = time.monotonic() + spec['startup_timeout']
        successes = 0
        while time.monotonic() < deadline and self.fence(gen):
            successes = successes + 1 if await self.health(w) else 0
            if successes >= 2:
                break
            await asyncio.sleep(.05)
        if successes < 2:
            await self.stop_worker(wid, gen)
            async with self.mu:
                if self.fence(gen):
                    self.phase('failed', reason='candidate did not become ready')
            return
        if not await self.change_route(gen, wid, old):
            return
        deadline = time.monotonic() + spec['observe']
        failures = 0
        while time.monotonic() < deadline and self.fence(gen):
            failures = 0 if await self.health(w) else failures + 1
            if failures >= 2:
                async with self.mu:
                    if not self.fence(gen):
                        return
                    self.s['generation'] += 1
                    gen = self.s['generation']
                    self.s['operation']['generation'] = gen
                    self.store.save('auto_rollback_requested')
                await self.run_rollback(gen, old, reason='candidate health failed')
                return
            await asyncio.sleep(.05)
        await self.finish(gen, old, spec)

    async def drain(self, gen, wid, timeout):
        if not wid:
            return
        deadline = time.monotonic() + timeout
        while self.active.get(wid, 0) and time.monotonic() < deadline and self.fence(gen):
            await asyncio.sleep(.01)
        async with self.mu:
            if self.fence(gen) and self.active.get(wid, 0):
                connections = list(self.transports.get(wid, set()))
                self.metrics['forced'] += len(connections)
                self.store.save('drain_expired', {'worker': wid, 'requests': len(connections)})
                for transport in connections:
                    transport.close()
        # Give aborted gateway handlers a chance to cancel their upstream request.
        await asyncio.sleep(0)

    async def finish(self, gen, old, spec):
        async with self.mu:
            if not self.fence(gen):
                return
            self.phase('draining')
        await self.drain(gen, old, spec['drain_timeout'])
        async with self.mu:
            if not self.fence(gen):
                return
            self.phase('retaining')
        await asyncio.sleep(spec['retain'] if old else 0)
        if old:
            await self.stop_worker(old, gen)
        async with self.mu:
            if self.fence(gen):
                self.s['previous'] = None
                self.phase('done')

    async def run_rollback(self, gen, target, reason='manual rollback'):
        if not target or not await self.health(self.s['workers'][target]):
            current = self.s['route']
            current_healthy = current and await self.health(self.s['workers'][current])
            async with self.mu:
                if self.fence(gen):
                    if not current_healthy:
                        self.s['route'] = None
                    self.s['degraded'] = 'rollback target unavailable'
                    self.phase('failed', reason='rollback target unavailable')
            return
        old = self.s['route']
        if not await self.change_route(gen, target, None):
            return
        spec = {'drain_timeout': 2}
        await self.drain(gen, old, spec['drain_timeout'])
        # Superseded launches may exist even if they never became active.
        for wid in list(self.s['workers']):
            if wid != target:
                await self.stop_worker(wid, gen)
        async with self.mu:
            if self.fence(gen):
                self.phase('rolled_back', reason=reason)

    async def recover(self):
        # Gateway is not listening until reconciliation completes; old client sockets were lost.
        route = self.s['route']
        op = self.s['operation']
        unresolved = []
        for wid, w in self.s['workers'].items():
            path = self.store.root / (wid + '.identity')
            if not path.exists() and not w.get('stopping'):
                # Never blindly repeat a launch with uncertain outcome.
                unresolved.append(wid)
        if unresolved:
            self.s['degraded'] = 'launch outcome unknown; inspect identity records before retry'
            self.store.save('recovery_blocked', {'workers': unresolved})
            return
        if route and not await self.health(self.s['workers'][route]):
            previous = self.s['previous']
            if previous and await self.health(self.s['workers'][previous]):
                self.s['route'] = previous
                self.s['previous'] = None
                self.store.save('recovery_rollback')
            else:
                self.s['route'] = None
                self.s['degraded'] = 'no healthy route on recovery'
                self.store.save('recovery_degraded')
        if op and op['state'] not in {'done', 'failed', 'rolled_back'}:
            # Conservative recovery: retain committed healthy route, retire all other known workers.
            self.s['generation'] += 1
            gen = self.s['generation']
            for wid in list(self.s['workers']):
                if wid != self.s['route']:
                    await self.stop_worker(wid, gen)
            self.s['previous'] = None
            self.phase('done' if self.s['route'] else 'failed', recovered=True)
        self.store.save('reconciled')

    async def proxy(self, request):
        if request.headers.get('Upgrade') or request.method == 'CONNECT':
            raise web.HTTPNotImplemented(text='protocol upgrades are outside MVP')
        async with self.mu:
            wid = self.s['route']
            if self.closing or self.store.failed or not wid:
                self.metrics['rejected'] += 1
                raise web.HTTPServiceUnavailable(text='no active route')
            if sum(self.active.values()) >= self.max_inflight:
                self.metrics['rejected'] += 1
                raise web.HTTPServiceUnavailable(text='gateway overloaded')
            self.active[wid] = self.active.get(wid, 0) + 1
            self.transports.setdefault(wid, set()).add(request.transport)
            self.metrics['accepted'] += 1
            worker = self.s['workers'][wid]
        transport = request.transport
        response = None
        try:
            body = await request.read()
            excluded = HOP | {x.strip().lower() for x in request.headers.get('Connection', '').split(',')}
            headers = [(k, v) for k, v in request.headers.items() if k.lower() not in excluded]
            url = f"http://127.0.0.1:{worker['port']}" + request.raw_path
            async with self.session.request(request.method, url, headers=headers, data=body, allow_redirects=False) as upstream:
                excluded = HOP | {x.strip().lower() for x in upstream.headers.get('Connection', '').split(',')}
                response = web.StreamResponse(status=upstream.status, headers=[(k, v) for k, v in upstream.headers.items() if k.lower() not in excluded])
                response.headers['X-Rollout-Version'] = worker['version']
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                self.metrics['completed'] += 1
                return response
        except web.HTTPRequestEntityTooLarge:
            self.metrics['failed'] += 1
            raise
        except asyncio.CancelledError:
            self.metrics['failed'] += 1
            raise
        except Exception:
            self.metrics['failed'] += 1
            if response and response.prepared:
                if request.transport:
                    request.transport.close()
                return response
            raise web.HTTPBadGateway(text='upstream request failed; not retried')
        finally:
            async with self.mu:
                self.active[wid] -= 1
                self.transports.get(wid, set()).discard(transport)

    def status(self):
        return {'generation': self.s['generation'], 'route': self.s['route'], 'previous': self.s['previous'],
                'workers': {k: {x: v for x, v in w.items() if x != 'token'} for k, w in self.s['workers'].items()},
                'operation': self.s['operation'], 'degraded': self.s['degraded'], 'storage_failed': self.store.failed, 'inflight': dict(self.active), 'metrics': dict(self.metrics)}

    async def close(self):
        self.closing = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        # A normal controller shutdown retains workers for restart recovery.
        await self.session.close()
        self.store.close()
