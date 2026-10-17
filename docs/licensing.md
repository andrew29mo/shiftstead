# License decision — 2026-10-17

Shiftstead's original code, documentation and synthetic examples use the MIT license in [LICENSE](../LICENSE), copyright (c) 2026 Andrew Yuan. Package metadata declares SPDX expression `MIT` and includes LICENSE and THIRD_PARTY_NOTICES.md in built distributions. The GitHub repository remains Private; no package or container is published by this change.

## Why MIT

The present goal is a small, reusable systems project that readers can study, modify and integrate into their own software. MIT permits commercial and proprietary reuse while requiring preservation of its copyright and permission notice. It does not require downstream source disclosure.

Apache-2.0 is a reasonable alternative for a future contributor ecosystem that prioritizes an explicit contributor patent grant and its patent-litigation termination clause. It also requires marking modified files and retaining applicable notices. MIT does not contain an equivalent explicit patent-grant clause. No patent clearance is claimed by this project. There is no current requirement for reciprocal source disclosure or a special commercial licensing model that would justify choosing a copyleft or custom license here.

This is a project-fit decision, not a statement that MIT is universally preferable. Any later licensing change must account for rights already granted and the rights of other contributors. The software license is separate from trademark clearance and makes no production-readiness or service-availability promise.

Primary texts: [MIT / OSI](https://opensource.org/license/mit), [Apache-2.0 / ASF](https://www.apache.org/licenses/LICENSE-2.0).

## Third-party boundary

The pinned dependency set contains MIT, BSD-3-Clause, Apache-2.0, PSF-2.0, and the aiohttp `Apache-2.0 AND MIT` expression. Installed distribution metadata and license files were checked against all eleven entries in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). None of these separately installed packages is relicensed as MIT by this project. No dependency source, binary, external model or real-user dataset is vendored.

Using these dependencies does not require changing the license of Shiftstead's original code to Apache-2.0. When redistributing dependencies or a bundled container, preserve their own license texts, applicable copyright/NOTICE material and other obligations; the package summary table alone does not replace those texts. The local wheel contains this project's modules and notices, without bundling dependencies. Python, SQLite, build tools, CI actions and the validation image retain their separately documented terms.

## Evidence after adopting MIT

Adding package license metadata changes the source/configuration manifest even though runtime and test code are unchanged. The retained macOS formal tests, targeted mutation checks and native measurements, plus Linux container correctness records, are refreshed against that new manifest. Historical reviews remain snapshots of their named commits. Current results and measurement limits are in [validation.md](validation.md), [measurement.md](measurement.md) and the raw `results/` records.

Verification completed: macOS and Linux each passed 68 formal tests against source/configuration SHA-256 `dbf0c8a4c38f99b1ba07d34cc054dae2de89f322b71ce346ecb1b7dadf80ecda`. Native validation also detected all five targeted mutations and passed all nine trials (2,700/2,700 correct responses); its shared run ID is `b8346c3ecefe8332b81f852f6f4a403c`. The VM was stopped before native performance collection. Wheel and editable-install metadata both declare `MIT`; the wheel contains exact copies of LICENSE and THIRD_PARTY_NOTICES.md and no bundled dependencies. The refreshed numbers replace the previous run in README and measurement documentation; differences between runs are not evidence of a runtime optimization.
