"""Run targeted tests against isolated faulty copies of the formal implementation."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from tools.evidence import ROOT,provenance
from tools.process import run_stage

CASES=[
 ('stale_route','rollout/core.py',"if not self.fence(generation) or self.s['workers'][target].get('stopping'):","if self.s['workers'][target].get('stopping'):",'tests.test_safety.Fences.test_stale_route_and_stop_cannot_mutate'),
 ('readiness_ignored','rollout/core.py',"return r.status == 200 and value.get('instance') == worker['token'] and value.get('ready') is True","return value.get('instance') == worker['token']",'tests.test_integration.Integration.test_unready_timeout'),
 ('skip_drain','rollout/core.py',"while self.active.get(wid, 0) and time.monotonic() < deadline and self.fence(gen):","while False:",'tests.test_integration.Integration.test_graceful_drain'),
 ('pid_identity_ignored','rollout/core.py',"if abs(p.create_time() - r['created']) > .001 or p.status() == psutil.STATUS_ZOMBIE:","if p.status() == psutil.STATUS_ZOMBIE:",'tests.test_safety.Fences.test_identity_mismatch_never_signals_process'),
 ('empty_report_accepted','tools/report.py',"raise ValueError('missing benchmark trials')","return True",'tests.test_reporting.EvidenceSafety.test_empty_report_rejected'),
]

def main():
    rows=[]
    for name,file,before,after,test in CASES:
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            for folder in ['rollout','tests','tools']:
                shutil.copytree(ROOT/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__'))
            p=target/file;s=p.read_text()
            if s.count(before)!=1:raise RuntimeError('mutation anchor changed: '+name)
            p.write_text(s.replace(before,after))
            code,timed_out,output,leaked=run_stage([sys.executable,'-m','unittest',test,'-v'],25,cwd=target,capture=True)
            detected=not timed_out and not leaked and code!=0 and ('FAIL:' in output or 'ERROR:' in output) and 'Ran 1 test' in output and 'ImportError' not in output
            rows.append({'mutation':name,'test':test,'detected':detected,'exit_code':code,'timed_out':timed_out,'leaked_workers_cleaned':leaked})
    passed=all(r['detected'] for r in rows) and len(rows)==len(CASES)
    Path('results/mutations.json').write_text(json.dumps({'passed':passed,'source':provenance(),'cases':rows},indent=2)+'\n')
    print(json.dumps(rows,indent=2))
    raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
