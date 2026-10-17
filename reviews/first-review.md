# First correctness and evidence review — 2026-10-17

Baseline: `d247c026e31a08eedc0de775381b43c8647b9542` (Private MVP). The baseline raw measurements remain available in that Git commit; they are not represented as current results after these fixes.

## Reproduced defects and fixes

1. **Stop/deploy race.** `/stop` cleared the route without reserving the lifecycle. A new deploy received 202 while old work was draining, and stop cleanup could be superseded. Stop is now a persisted, generation-fenced operation; conflicting deployment receives 409, duplicate stop waits for the same task, and request disconnection cannot cancel it. Restart completes a committed stop intent.
2. **Health transport correctness.** A single `read()` could reject a valid fragmented JSON response or accept a valid JSON prefix followed by invalid content. Redirects were followed, and probes shared the gateway connector, allowing slow traffic to starve readiness. Probes now use an independent bounded pool, require the direct endpoint's 200 response and complete bounded JSON, and enforce the remaining startup deadline.
3. **Recovery bypass and false success.** An uncertain launch caused an early return before validating the committed route. A still-healthy old service could also cause an interrupted pre-switch deployment/rollback to be marked complete. Recovery now checks routing health first, fails closed on uncertain/corrupt identities, and derives the operation outcome from the requested committed revision rather than mere service availability.
4. **Process/authentication edge cases.** Non-finite identity timestamps could defeat a comparison. Token creation was not atomic and an empty pre-existing token could weaken authentication. Identity types/timestamps are validated, corrupt identity cleanup is blocked, exit is confirmed after kill, incomplete worker cleanup prevents successful deployment/rollback completion, and tokens are created durably and validated on startup.
5. **Payload oracle and raw URL fidelity.** Counting bytes alone could miss same-length corruption. The real demo worker now returns body SHA-256 and raw path; tests and the benchmark check content, identity, release and workload query. Encoded paths/queries are forwarded without recanonicalization. These are genuine gateway/worker tests, not a replacement implementation.

The initial seven adversarial checks produced six failures before fixes; the rollback-during-drain check already passed. See `reproduction-before.json`. A later pair of real-process corruption checks also exposed ignored cleanup failures after strict identity rejection was added; their failures were reproduced before propagation was fixed. Subsequent regression checks additionally cover stop cancellation/restart, uncommitted rollback outcomes, identity types and report evidence.

## Measurement/report corrections

- Schema 2 records the complete predeclared rotated trial plan. Missing whole trial groups, changed rate/schedule, wrong baseline release, wrong body hash and altered sender-lag headlines are rejected.
- All planned attempts remain represented. Fatal infrastructure errors become failed trial records rather than silently retaining an older successful benchmark.
- Throughput uses the exact last recorded request completion. RSS headline peaks use only the common request window; full lifecycle peaks remain separately available. RSS sampling is sampled summed process RSS, not unique physical memory or an exact high-water mark.
- The sampler performs process inspection in a worker thread; it remains in the load-generator process. Sender lag is retained. Connection policies are explicit: load-client keep-alive, per-request upstream connections, independent health probes. This is not an isolated estimate of routing algorithm cost.
- Validation-stage interruption now also terminates its child tree and performs identity-checked orphan cleanup, preventing leftover load from contaminating a later experiment. A new validation immediately invalidates old success JSON and HTML. A run ID binds test/mutation/benchmark/validation records; rendering rejects stale same-source data or an already-failed validation. Source/configuration manifests are captured before execution and checked afterward, so edits during a run cannot be stamped as if they were tested.

## Evidence boundaries

Lifecycle integration checks run the production daemon, launcher and demo worker over actual sockets. Protocol checks use controlled HTTP endpoints to challenge the production health client. State-machine/identity/report unit checks call the actual implementations; orchestration unit tests stub only external stage execution and use real isolated record files to inject failures/source changes. Five targeted mutations challenge selected guards; passing them is not exhaustive proof.

The revised benchmark adds content hashing and a stricter comparison window, so its numbers should not be marketed as a speedup over the baseline. The workload remains a synthetic localhost HTTP service with asynchronous delay, not CPU saturation, WAN behavior, application compatibility proof or a universal zero-downtime guarantee. Controller restart still loses sockets, and application/database side effects are not rolled back. Missing/deleted state under a malicious same-account user is outside the local-trust model.

Final source-matched native and Linux correctness records, native measurements and orchestration outcomes are in `results/`. Linux container duration is correctness evidence, not a Linux/native performance comparison. GitHub-hosted CI status is reported separately; account billing restrictions are not a passing CI result. No visibility or license change is part of this review.
