# Retained native-host MVP measurement

Environment: native macOS (Darwin), arm64, Python 3.12.14. The exact runtime/kernel and source manifest are in the JSON evidence. This is not a Linux VM result.

The complete validation passed 33 formal tests and detected all five targeted fault mutations. Nine real-process trials retained 2,700 scheduled requests: three each for direct worker access, steady gateway access and gateway access during deployment. All 2,700 returned the expected request identity, payload length and permitted release version. Deployment trials observed both revisions. No trial was discarded.

| Mode | Correct / scheduled | Trial p95 scheduled E2E range | Median of trial sampled peak summed RSS |
|---|---:|---:|---:|
| Direct worker access | 900 / 900 | 3.73–4.16 ms | 80.0 MiB |
| Steady gateway | 900 / 900 | 4.98–5.62 ms | 80.3 MiB |
| Gateway during rollout | 900 / 900 | 4.73–4.97 ms | 119.2 MiB |

The configured arrival rate was 200 requests/s. Achieved correct-response rates were near that offered rate; this does not establish maximum capacity. Rollout operation durations were 0.729, 0.733 and 0.710 seconds in these trials, including startup/readiness, observation and the configured retention window. They are not rollback/restart recovery times.

RSS is sampled every 10 ms. Summed controller + worker RSS can double-count shared pages and excludes the load generator. The direct scenario deliberately leaves the controller resident but idle; this is not standalone-worker-only deployment memory. The extra worker during rollout explains the larger stack footprint. This is a trade-off for retaining a rollback target, not a memory-optimization claim.

The same schedule, payload, configured 2 ms worker delay and source were used in all modes; trial order rotates. The localhost demo does not represent an internet-facing service, saturation, persistent application state or arbitrary application health. An absence of request errors in these trials does not prove zero downtime under all faults. Restart interruption and drain-expiry behavior are challenged separately by correctness tests.

Installed CLI smoke check also exercised the README manifests: deploy v1, deploy v2, manual rollback to v1, status/history access and explicit stop. The HTML report was visually checked in a browser. These manual checks do not replace retained automated evidence.
