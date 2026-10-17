# Pre-publication audit — 2026-10-17

Reviewed implementation commit: `4646c630e9b452494237f6caa1c0f6de79204c85`.
Source/configuration SHA-256: `605f83e5bb8e40c48311b7d6ba876ebb68cf97e6174cf735c2dca2a5e7e437d0`.

This review changes documentation only. Production code, test code, dependency pins and benchmark configuration are unchanged, so the retained source-bound results remain applicable. No license or visibility change is authorized by this audit.

## Findings and corrections

- Clarified the quick start's asynchronous steps: wait for the first deployment to finish before submitting the second; request rollback while the previous worker is still retained. A 202 response alone does not mean completion, and waiting for the second deployment to reach `done` would miss its rollback window.
- Updated the remote-CI record to the reviewed implementation commit. Both GitHub jobs had no executed steps and were blocked by account billing/spending restrictions. They are not passing tests and are not evidence of a project test failure.
- No additional production defect was identified by this final consistency review. The earlier reproduced defects and their fixes remain documented in [first-review.md](first-review.md); this statement is not a proof that all faults are excluded.

## Correctness and evidence checks

- A fresh native run of the complete formal suite passed **68 tests in 40.536 seconds**. It did not overwrite the existing combined measurement records.
- Retained native and Colima Linux records each contain the same **68 unique test IDs**, all passing with no skips/errors/failures. Their complete source/configuration manifests match the current checkout. Linux was not rerun in this documentation-only audit.
- Native test, mutation, benchmark and orchestration records share one validation run ID. The five targeted mutations were detected. These selected faults do not establish exhaustive coverage.
- Lifecycle integration tests exercise the actual daemon/launcher/workers over sockets. Health tests challenge the production health client; identity, orchestration and report checks include unit/fault-injection tests. The 68-test total is not a claim that every test is an end-to-end deployment.
- Revalidated all nine planned trials and **2,700/2,700** scheduled responses, including identity, body hash, raw query, timing, schedule and RSS accounting. Re-rendering the retained JSON produces the exact committed HTML.
- Recomputed headline trial p95 ranges: direct **3.32–3.60 ms**, steady gateway **4.27–4.29 ms**, deployment **3.69–4.24 ms**. Median trial request-window sampled peak summed RSS: **80.1 / 80.4 / 119.3 MiB**. These agree with README and measurement documentation.
- Linux evidence records successful container removal and a VM stopped both before and after validation. Its 68-test result is VM/container correctness evidence, with no Linux throughput, latency or RSS comparison.

These are synthetic localhost results at 200 scheduled requests/s, not saturation throughput or a speedup claim. Direct mode includes an idle controller. RSS is sampled summed process RSS, excludes the generator, may double-count shared pages and is not an exact physical-memory peak. A smaller observed rollout p95 does not establish that deployment improves latency. Restart loses sockets; rollback does not undo application side effects.

## Installation, dependencies and privacy

- Built the wheel with the declared isolated build process. Its contents are the five `rollout` source modules plus package metadata; no state database, credentials, tests, reports, virtual environment or downloaded binary is packaged. The wheel remains local and was not published.
- Exercised the installed CLI using the unchanged example manifests: serve, v1 deployment, v2 switch, rollback during retention, status, history and explicit stop all succeeded, with real gateway responses checked after each revision change.
- Installed pinned dependency versions and their license metadata agree with `requirements.lock` and [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Dependency consistency checking passed. Dependencies and tool/container binaries are obtained separately; none are vendored into Git.
- Inspected the 45 baseline tracked files and scanned all **92 reachable historical file blobs** for common private-key/token patterns, personal absolute paths and private-mailbox patterns; no matches were found. Commit authors use the public GitHub noreply address. This is a bounded pattern/content audit, not a guarantee that every possible secret format can be detected.
- Confirmed ignore rules cover environments, local state, tokens, databases, identity records, logs, build output and personal `AGENTS.md`. Large raw JSON reports are intentional evidence. No personal instructions, VM disk, container image, screenshot or unrelated project file is tracked. Relative documentation links resolve.

## Remaining status

GitHub remains **Private**, owned by `andrew29mo`, with only the owner in the collaborator list. Actions default permissions are read-only and workflows cannot approve pull requests.

There is still **no project LICENSE** and no license declared in project metadata; README, notices and GitHub's empty license field agree. Public visibility would not itself grant an open-source license. Choosing a license remains a separate owner decision.

GitHub-hosted CI remains blocked before testing by billing/spending restrictions; local evidence does not change that status. See [validation.md](../docs/validation.md). No account billing setting, access grant or publication setting was changed.
