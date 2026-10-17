# Public release and repository security — 2026-10-17

The owner authorized changing [andrew29mo/shiftstead](https://github.com/andrew29mo/shiftstead) to Public. GitHub reports `private: false`, recognizes the MIT license, and unauthenticated API requests can read the license and retained macOS/Linux validation evidence. No package or container image was published.

README, LICENSE, package license metadata and THIRD_PARTY_NOTICES.md agree. Repository visibility is separate from the license, which covers original project material and does not replace dependency terms.

## Retained local evidence

Native macOS and Colima Linux each passed the same 68 formal tests against source/configuration SHA-256 `dbf0c8a4c38f99b1ba07d34cc054dae2de89f322b71ce346ecb1b7dadf80ecda`. Native validation detected five targeted fault mutations and retained all nine trials with 2,700 correct scheduled responses. JSON-derived HTML matches the retained report. The Linux container was removed and the VM stopped; Linux performance and RSS were not measured.

The visibility/security/documentation changes do not modify production code, tests, workflow, dependency versions or the source-bound benchmark configuration. Existing local records remain applicable. See [validation.md](validation.md), [measurement.md](measurement.md) and the raw `results/` records.

## Security settings read back after publication

- Secret scanning and secret-scanning push protection: enabled. These are detection/prevention features, not proof that all secret formats are covered.
- Dependabot vulnerability alerts and automatic security updates: enabled. Weekly pip and GitHub Actions update checks are configured in `.github/dependabot.yml`, limited to three open update PRs per ecosystem. Updates still require review and validation; no automatic merge was enabled.
- Private vulnerability reporting: enabled, linked from SECURITY.md.
- Actions: only `actions/checkout` and `actions/setup-python` allowed, with full commit-SHA pinning required. Workflow token defaults to read-only and cannot approve pull requests. The workflow disables persisted checkout credentials, has bounded job runtime, and does not use `pull_request_target`.
- Workflow runs from all external contributors require approval. Public fork contributions do not receive repository secrets or write-token privileges through this configuration.
- Active main-history rules prohibit branch deletion and non-fast-forward updates, with no configured bypass actors.
- A separate active rule requires Linux and macOS CI checks on main. Repository administrators can bypass this CI rule for the requested single-maintainer workflow; passing CI is therefore not mechanically mandatory for every owner push. The history-protection rule remains separate.
- Collaborator list contains only the owner. There are no deploy keys, webhooks or repository Actions secrets. No new collaborator or access grant was created.

Security settings are mutable server state checked at publication time. Enabled scanners are not a completed vulnerability audit, and the repository guardrails do not make the local-trust MVP production-ready. Application security boundaries and reporting instructions remain in [SECURITY.md](../SECURITY.md).

## Remote correctness CI

[Public run 39013250488, attempt 2](https://github.com/andrew29mo/shiftstead/actions/runs/39013250488/attempts/2) passed on licensed implementation commit `7884a1fc6989777cf91d86b9bd4a33d62ec77108`. Actual job logs show 68 formal tests on each of Ubuntu and macOS, and successful installed CLI checks. No billing settings were changed; successful public CI does not prove that private-repository billing/quota is resolved.
