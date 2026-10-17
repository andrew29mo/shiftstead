# Shiftstead

**Move releases forward. Keep recovery explicit.**

A single-host HTTP deployment controller with readiness gates, request-level traffic switching, bounded draining, rollback and persisted restart recovery.

This is an early, local-first MVP for trusted operators and cooperative, stateless services. It is not a production ingress, Kubernetes replacement, database migration manager or a zero-downtime guarantee.

## What works

- Real subprocess workers and an HTTP gateway; the same implementation runs in the CLI, integration tests and measurements.
- Two consecutive identity-checked readiness successes before switching; two failures during the configured observation period trigger rollback.
- Every gateway request keeps its selected revision until completion. Requests selected after the switch use the new revision, including requests on an existing client keep-alive connection.
- Bounded draining; deadline expiry closes affected client connections and records forced interruptions. No automatic upstream retry.
- The previous worker remains available for a configured rollback window. Manual rollback receives a new generation and fences superseded work.
- SQLite WAL with synchronous FULL, idempotent operation IDs, a single controller owner lock, and process identity records written before worker exec.
- On restart, inspect actual process identities and health before opening listeners. Keep the committed healthy route, fall back to a healthy retained route when available, and retire superseded workers. An uncertain launch outcome fails closed rather than blindly launching again.
- Authenticated loopback-only administration, request body/deadline/concurrency limits and real-process JSON/HTML evidence.

## Quick start

Python 3.12+ on macOS or Linux. Windows is not supported (POSIX locking/process semantics).

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
.venv/bin/shiftstead serve --port 9400
```

In another terminal:

```sh
.venv/bin/shiftstead deploy examples/v1.json --id release-v1
.venv/bin/shiftstead status
.venv/bin/shiftstead deploy examples/v2.json --id release-v2
.venv/bin/shiftstead history
# During the retained-worker window:
.venv/bin/shiftstead rollback --id restore-v1
# Explicitly drain and stop managed workers:
.venv/bin/shiftstead stop
```

`--state` and `--admin-port` are global options placed before the subcommand. Default gateway/admin addresses are `127.0.0.1:9400` and `127.0.0.1:9401`. `serve` prints a readiness record after reconciliation and listener setup. Deployment acceptance (202) is not deployment success: poll `status` for a terminal result.

`examples/*.json` use `.venv/bin/python`, relative to the repository working directory. Real deployments should use an absolute executable path and a stable working directory. Commands are argument vectors, never shell strings. Run the controller in the application's intended working directory; commands and environment are trusted operator input.

## Application contract

The worker must bind `127.0.0.1:$PORT`, expose `GET /readyz` with a small JSON body, and report:

```json
{"instance": "the value of ROLLOUT_INSTANCE", "ready": true}
```

The controller injects `PORT` and `ROLLOUT_INSTANCE`. Readiness is an application assertion, not proof of business correctness. Use immutable release directories/artifacts: rollback reuses a retained process and does not reconstruct an already-retired release. Child-process trees and arbitrary daemonizing workers are outside this MVP's worker contract.

## Validate and measure

```sh
SHIFTSTEAD_EXECUTION=native-host .venv/bin/python -m tools.validate
```

This runs formal tests, five isolated fault mutations, three rotated trials of each comparison mode, validates raw counts/timings/RSS and writes:

- [`results/tests.json`](results/tests.json): test outcomes and source manifest.
- [`results/mutations.json`](results/mutations.json): tests challenged by deliberately broken implementation copies.
- [`results/benchmark.json`](results/benchmark.json): all scheduled requests, responses, sender lag, errors and RSS samples.
- [`results/report.html`](results/report.html): readable comparison and explicit limitations.
- [`results/validation.json`](results/validation.json): stage exit codes, timeouts and overall status.

Nonzero exits, timeouts, skipped/empty test suites, mismatched sources or incomplete comparisons fail validation. Read `validation.json` alongside HTML; an old HTML file is not evidence that a later failed run passed. Recorded evidence describes its exact source manifest, not every later change.

The benchmark uses a real HTTP demo worker with 256-byte POST bodies, 2 ms configured work delay, 300 scheduled arrivals at 200 requests/s, 20 warmups per mode and rotating mode order. All responses and errors are retained. Deployment trials must observe both versions. This is offered-load performance, **not maximum throughput**. End-to-end latency begins at the scheduled arrival, including sender lag. Requests are generated in the same host as the service.

RSS samples separate controller and workers. The summed RSS can double-count shared pages, excludes the load generator and is not exact peak physical memory. Direct mode keeps the controller resident but idle; its total is a controlled stack footprint, not standalone-worker deployment size. Set `SHIFTSTEAD_EXECUTION` to describe the actual execution context; omission is recorded as unspecified. No VM/container measurement is represented as native-host data.

## Recorded MVP result

Native macOS evidence: 34 formal tests, five detected fault mutations, nine real-process trials and 2,700/2,700 correct responses. At the tested 200 requests/s offered load, trial p95 scheduled end-to-end latency was 3.90–4.55 ms direct, 4.26–4.98 ms through the steady gateway, and 4.67–4.86 ms during rollout. Median trial sampled peak summed RSS was 80.0, 80.2 and 119.3 MiB respectively. See [measurement.md](docs/measurement.md) for methods and limits; no capacity, speedup or universal zero-downtime claim is made.

## Failure boundaries

- Controller restart can interrupt existing gateway connections. Deployment state recovery does not preserve sockets.
- Recovery conservatively ends an interrupted rollout and may end its rollback window; it does not resume every timer/step exactly where execution stopped.
- Startup failures leave the previous route intact. Rollback requires a healthy, non-stopping retained worker. If none exists, status is explicitly degraded; recovery with no healthy route serves 503.
- Health monitoring is limited to startup and the post-switch observation interval. This is not an always-on auto-healing supervisor.
- Database/schema changes, external side effects and application-level compatibility are not reverted.
- Request bodies are bounded at 1 MiB of received body bytes; compressed bytes are preserved for the application, which remains responsible for its own decompression/resource limits; upstream response streaming is bounded by flow control and total request deadlines. No WebSocket, CONNECT, HTTP/2, TLS termination or automatic application retries.
- At most two application workers are intended during ordinary rollout. Superseded workers are fenced and retired. The operation-ID history is capped at 1,000; this MVP has no history compaction command or general disk quota.
- State storage must be local and reliable. SQLite durability is subject to filesystem/hardware guarantees. Storage errors fail closed; corrupt or missing identity records can require operator intervention. After inspecting the cause, explicit `stop` retires tracked workers and resets degradation so a fresh deployment can be submitted.

## Platform evidence and remote CI

Native macOS and Colima Linux each passed 34 formal tests with the same source manifest. Linux is a VM/container correctness result, with no Linux performance/RSS claim. GitHub-hosted Linux/macOS jobs were blocked before running tests by account billing/spending restrictions; they are not reported as passing. See [validation.md](docs/validation.md) and the separate Linux JSON records.

## Project status and rights

Private MVP preparation. No license has been selected for the original project yet; no open-source license grant is implied. Third-party dependencies retain their respective licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The Shiftstead name passed an initial public-name screen; this is not formal trademark clearance. See [name-screen.md](docs/name-screen.md).
