"""Bounded validation subprocesses and identity-checked cleanup of test workers."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
import psutil


def terminate(processes):
    for p in processes:
        try:p.terminate()
        except psutil.Error:pass
    _,alive=psutil.wait_procs(processes,timeout=1)
    for p in alive:
        try:p.kill()
        except psutil.Error:pass
    psutil.wait_procs(alive,timeout=1)


def run_stage(args,timeout,cwd=None,capture=False):
    with tempfile.TemporaryDirectory() as registry:
        env=dict(os.environ,SHIFTSTEAD_TEST_REGISTRY=registry)
        p=subprocess.Popen(args,cwd=cwd,env=env,start_new_session=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.STDOUT if capture else None,text=True)
        timed_out=False;output=''
        try:
            if capture:output=p.communicate(timeout=timeout)[0]
            else:p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            try:
                root=psutil.Process(p.pid)
                terminate(root.children(recursive=True)+[root])
            except psutil.Error:pass
            if capture:output=p.communicate()[0]
            else:p.wait()
        leaked=[]
        for entry in Path(registry).glob('*.json'):
            state=Path(json.loads(entry.read_text())['state'])
            for record in state.glob('*.identity'):
                try:
                    r=json.loads(record.read_text());process=psutil.Process(r['pid'])
                    if abs(process.create_time()-r['created'])<.001 and process.status()!=psutil.STATUS_ZOMBIE:
                        leaked.append(process)
                except (OSError,ValueError,psutil.Error):pass
        if leaked:terminate(leaked)
        # psutil may reap a timed-out Popen child; use explicit timeout status.
        return 124 if timed_out else p.returncode,timed_out,output,len(leaked)
