"""One command; every failed, timed-out, skipped or empty stage fails closed."""
import json
import os
import signal
import subprocess
import sys
import time
import psutil
from pathlib import Path
from tools.evidence import environment,provenance
from tools.process import run_stage


def main():
    Path('results').mkdir(exist_ok=True)
    Path('results/report.html').write_text('<!doctype html><meta charset="utf-8"><h1>Validation in progress</h1><p>No current success result yet.</p>')
    stages=[]
    passed=True
    for module,timeout in [('tools.test_suite',180),('tools.mutation_check',180),('tools.benchmark',180),('tools.report',20)]:
        began=time.monotonic()
        code,timed_out,_,leaked=run_stage([sys.executable,'-m',module],timeout)
        stages.append({'module':module,'exit_code':code,'timed_out':timed_out,'leaked_workers_cleaned':leaked,'seconds':time.monotonic()-began})
        if code or timed_out or leaked:
            passed=False
            break
    value={'schema':1,'passed':passed and len(stages)==4,'stages':stages,'source':provenance(),'environment':environment()}
    Path('results/validation.json').write_text(json.dumps(value,indent=2)+'\n')
    if not value['passed']:
        Path('results/report.html').write_text('<!doctype html><meta charset="utf-8"><h1>Validation FAILED</h1><p>See <a href="validation.json">stage outcomes</a>. Retained older measurements are not a successful current validation.</p>')
    raise SystemExit(0 if value['passed'] else 1)
if __name__=='__main__':main()
