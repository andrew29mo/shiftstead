# Validation environments and remote CI status

## Native macOS

`SHIFTSTEAD_EXECUTION=native-host .venv/bin/python -m tools.validate` runs formal tests, isolated fault mutations, scheduled-load measurements and HTML rendering. The retained final performance run was performed after stopping the Linux VM. See `results/validation.json`, `tests.json`, `mutations.json`, `benchmark.json` and `report.html`. Execution-context labels are explicit operator metadata, not automatic proof of physical hardware; an omitted label is recorded as unspecified.

## Linux in Colima

A separately installed existing Colima/Lima runtime was used. The VM initially reported Stopped, was started for this check, and was confirmed Stopped after completion. No system DNS change, global Docker context activation or host workspace mount was requested. The container copied a source snapshot, had no external network, ran as UID 10001 with an init/reaper, and had limits of 2 CPUs, 1 GiB memory and 128 PIDs.

`results/linux-tests.json` records 68 formal tests, no skips/failures/errors, plus environment and the same source manifest as the native tests. `results/linux-validation.json` records the fixed base-image digest, built image identity, exit code and cleanup outcome. The container was removed. Linux performance/RSS was **not measured**; test duration is not a cross-platform performance comparison.

The retained recipe is `containers/validation.Dockerfile`. Against an explicitly selected local Linux Docker daemon, the equivalent container commands are:

```sh
docker build -f containers/validation.Dockerfile -t shiftstead-check .
docker run --init --name shiftstead-check --network none --cpus 2 --memory 1g --pids-limit 128 shiftstead-check
docker cp shiftstead-check:/workspace/results/tests.json results/linux-tests.json
docker rm shiftstead-check
```

Check the actual container exit code and JSON result; successful `docker cp`/cleanup does not make failed tests pass. A caller must bound execution and remove the container after failure/timeout too. This is a retained supplemental correctness check, not a fully automated Colima installation/lifecycle workflow. `.dockerignore` excludes local state, tokens, environments and personal instructions from an ordinary build context.

## GitHub-hosted CI

The initial push and the reviewed implementation commit's Linux and macOS jobs did not execute any test steps. GitHub rejected both at runner admission:

> The job was not started because recent account payments have failed or your spending limit needs to be increased.

Initial run: https://github.com/andrew29mo/shiftstead/actions/runs/39010122224

Rechecked implementation commit `4646c630e9b452494237f6caa1c0f6de79204c85`: https://github.com/andrew29mo/shiftstead/actions/runs/39012449385 . Both job records have empty step lists; the runner-admission annotation still reports the billing/spending restriction. This does not identify a failing project test.

This is a remote-CI limitation, not a passing CI result. Account billing/spending settings were not changed. The retained native and container evidence does not change the GitHub run's failure status. The workflow remains available for rerun after the account issue is resolved; this project remains Private.

The first review adds before/after source checks and a shared native validation run ID. Interrupted validation also cleans its stage process tree and registered test workers. Linux evidence has its own invocation context; its source/configuration manifest matches native, but it is not part of the native performance trial.
