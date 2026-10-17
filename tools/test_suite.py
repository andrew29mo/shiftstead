import json
import os
import sys
import time
import unittest
from pathlib import Path
from tools.evidence import provenance,environment,atomic_json


def main():
    source=provenance()
    start=time.monotonic()
    suite=unittest.defaultTestLoader.discover('tests')
    class Result(unittest.TextTestResult):
        def __init__(self,*a,**kw):super().__init__(*a,**kw);self.records=[]
        def startTest(self,test):super().startTest(test);self.started=time.monotonic()
        def stopTest(self,test):
            bad={str(t) for t,_ in self.failures+self.errors}
            skipped={str(t) for t,_ in self.skipped}
            self.records.append({'test':test.id(),'outcome':'failed' if str(test) in bad else 'skipped' if str(test) in skipped else 'passed','seconds':time.monotonic()-self.started})
            super().stopTest(test)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    changed=provenance()!=source
    passed=result.wasSuccessful() and result.testsRun>0 and not result.skipped and not changed
    value={'schema':1,'kind':'formal-implementation-tests','passed':passed,'tests':result.testsRun,'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),'seconds':time.monotonic()-start,'environment':environment(),'run_id':os.environ.get('SHIFTSTEAD_VALIDATION_RUN'),'source':source,'source_changed':changed,'cases':result.records}
    Path('results').mkdir(exist_ok=True)
    atomic_json('results/tests.json',value)
    raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
