# Deployment and recovery contracts

## Components

A single asyncio daemon contains administration, the rollout state machine, and the HTTP gateway. SQLite stores a snapshot and append-only transition events in one transaction. A POSIX owner lock prevents two controllers from operating one state directory. Each worker is a separate process. The launcher writes PID, process creation time and a per-instance token before exec; health must echo that token.

The gateway registers its selected worker and client transport under the same lock used for route commits. Selection remains pinned until response completion/cancellation. Request body reading happens after registration, so slow uploads are included in drain accounting. Response writes observe downstream flow control. Gateway-side automatic request decompression is disabled: compressed request bytes must agree with forwarded Content-Encoding and Content-Length. A real gzip POST regression test exercises this through the formal gateway and worker. New keep-alive requests select the current route, not the connection's original revision. The Python gateway is deliberately limited; a future Caddy adapter would need equivalent evidence for its own draining semantics.

## Durable transitions

`accepted -> launching -> starting -> observing -> draining -> retaining -> done`

A startup failure reaches `failed` without changing the route. Post-switch readiness failures start a generation-fenced rollback; success reaches `rolled_back`. Missing/unhealthy rollback targets reach `failed` with explicit degradation. Manual rollback advances the generation and cancels the old operation; delayed callbacks and cleanup must validate their generation before mutations or signals. Workers marked stopping can never be promoted.

Snapshot and event commit precede route-lock release and accepted responses. The route is not published by a separate external proxy, avoiding a two-controller distributed commit problem. An SQLite failure prevents further admission/side effects; recovery requires investigating storage and restarting. This does not constitute a power-loss hardware test.

## Restart reconciliation

Listeners open only after reconciliation. Persisted route + healthy matching instance: keep it. Unhealthy route + healthy retained previous: persist fallback. No healthy route: publish no route and mark degraded. Incomplete operations get a newer generation; superseded processes are retired. In-flight socket state is not recoverable, so counters reset and interrupted pre-crash requests cannot be reconstructed exactly from transient gateway metrics.

Launch intent precedes process creation. The launcher's durable identity precedes exec. If launch outcome cannot be established (for example, missing identity), do not repeat the command: fail closed and require inspection. The launcher checks persisted stop intent before exec to avoid a late launch outliving a superseding stop. Process signaling requires both recorded PID and matching creation time. This is for trusted local users, not protection against a malicious process running under the same OS account.

## Deliberate bounds

Single service, local POSIX filesystem, cooperative foreground worker, at most two application revisions in ordinary rollout, HTTP/1.1, no persistent application state migration. State directory owner-only; loopback administration with a bearer token. Deploy commands inherit the controller environment; never accept manifests from untrusted callers. New host ports are selected from ephemeral loopback ports; a bind race causes readiness failure, not permission to adopt another service without the instance token.
