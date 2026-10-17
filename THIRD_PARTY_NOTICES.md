# Third-party components and project license status

No license has been selected for the original Shiftstead code, documentation and synthetic examples. This repository does not grant an open-source license for that original material. No external model, real-user dataset or copied third-party implementation is included.

The following packages are installed separately, pinned in requirements.lock and retain their own terms. License labels below were checked against the installed distribution metadata/license files for these versions. They do not relicense this project or constitute approval of every possible future binary/container redistribution.

| Package | Version | Upstream license expression / metadata |
|---|---|---|
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiosignal | 1.4.0 | Apache-2.0 |
| attrs | 26.1.0 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| multidict | 7.1.0 | Apache-2.0 |
| propcache | 0.5.4 | Apache-2.0 |
| typing_extensions | 4.16.0 | PSF-2.0 |
| yarl | 1.25.1 | Apache-2.0 |
| idna | 3.20 | BSD-3-Clause |

Python and its standard library retain the Python distribution's license/notices. SQLite is dedicated to the public domain by its authors; filesystem/platform and Python distribution components may carry additional terms. No Python/SQLite binaries or environments are uploaded.

Build tooling uses setuptools (MIT and notices for vendored components). CI uses actions/checkout and actions/setup-python (MIT), pinned by commit in the workflow. No actions or build-tool source is vendored here. Preserve upstream license files/notices if distributing dependencies; a future project license alone will not cover them.

References: https://github.com/aio-libs/aiohttp ; https://github.com/giampaolo/psutil ; https://docs.python.org/3.12/license.html ; https://www.sqlite.org/copyright.html

The supplemental Linux validation recipe uses a separately obtained official Python 3.12.14 Debian-based image, pinned by manifest digest. Its Python/Debian packages and their notices retain their own terms. The existing Colima/Lima and Docker tools are separately installed, not vendored or relicensed here. No VM disk, container image or downloaded tool binary is committed.
