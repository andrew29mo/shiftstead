import asyncio
import copy
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tools.benchmark import PAYLOAD_SHA
from tools.report import validate


def fixture(repeats=2):
    order=[{'trial':i+1,'mode':m} for i in range(repeats) for m in ['direct','proxy','deploy'][i%3:]+['direct','proxy','deploy'][:i%3]]
    trials=[]
    for item in order:
        rows=[]
        for i in range(2):
            version='v2' if item['mode']=='deploy' and i==1 else 'v1'
            rows.append({'id':i,'scheduled_s':i,'sent_s':i+.001,'completed_s':i+.01,'send_lag_ms':1.,'service_latency_ms':9.,'scheduled_e2e_ms':10.,'response':{'id':str(i),'version':version,'bytes':256,'sha256':PAYLOAD_SHA,'raw_path':f'/?id={i}&delay=.002'},'status':200,'version':version,'error':None,'correct':True})
        trials.append({**item,'offered_rps':1.,'scheduled':2,'received':2,'unique_ids':2,'correct':2,'errors':0,'passed':True,'schedule_sha256':hashlib.sha256(json.dumps([0.,1.]).encode()).hexdigest(),'requests':rows,'observation_s':1.01,'achieved_correct_rps':2/1.01,'scheduled_e2e_p50_ms':10.,'scheduled_e2e_p95_ms':10.,'send_lag_p95_ms':1.,'memory_window_s':[0,1.01],'memory_samples':[{'at_s':-.01,'controller_rss_bytes':100,'workers_rss_bytes':900,'sum_rss_bytes':1000},{'at_s':.5,'controller_rss_bytes':100,'workers_rss_bytes':200,'sum_rss_bytes':300}],'sampled_peak_controller_rss_bytes':100,'sampled_peak_workers_rss_bytes':200,'sampled_peak_sum_rss_bytes':300,'sampled_lifecycle_peak_sum_rss_bytes':1000,'deployment':{'state':'done'} if item['mode']=='deploy' else None})
    return {'schema':2,'kind':'real-process-open-loop','plan':{'trials':repeats,'count':2,'rate':1.,'order':order},'trials':trials,'method':{'payload_bytes':256,'payload_sha256':PAYLOAD_SHA,'worker_delay_s':.002},'same_schedule':True,'passed':True,'source_changed':False}


class ReportReview(unittest.TestCase):
    def test_valid_raw_fixture(self):self.assertTrue(validate(fixture()))
    def test_missing_whole_trial_group_rejected(self):
        value=fixture();value['trials']=value['trials'][:3]
        with self.assertRaises(ValueError):validate(value)
    def test_changed_payload_with_same_length_rejected(self):
        value=fixture();value['trials'][0]['requests'][0]['response']['sha256']='0'*64
        with self.assertRaises(ValueError):validate(value)
    def test_wrong_baseline_version_rejected(self):
        value=fixture();r=value['trials'][0]['requests'][0];r['version']=r['response']['version']='v2'
        with self.assertRaises(ValueError):validate(value)
    def test_sender_lag_headline_recomputed(self):
        value=fixture();value['trials'][0]['send_lag_p95_ms']=0
        with self.assertRaises(ValueError):validate(value)
    def test_nonfinite_raw_latency_rejected(self):
        value=fixture();value['trials'][0]['requests'][0]['service_latency_ms']=float('nan')
        with self.assertRaises(ValueError):validate(value)
    def test_rss_pre_window_peak_cannot_be_headline(self):
        value=fixture();value['trials'][0]['sampled_peak_sum_rss_bytes']=1000
        with self.assertRaises(ValueError):validate(value)
    def test_wrong_rate_metadata_rejected(self):
        value=fixture();value['trials'][0]['offered_rps']=2
        with self.assertRaises(ValueError):validate(value)
    def test_fatal_trial_prevents_success(self):
        value=fixture();value['trials'][0]={'mode':'direct','trial':1,'fatal_error':'Injected','passed':False}
        with self.assertRaises(ValueError):validate(value)
        value['passed']=value['same_schedule']=False
        self.assertFalse(validate(value))


@contextmanager
def isolated_records():
    cwd=Path.cwd()
    with tempfile.TemporaryDirectory() as root:
        os.chdir(root)
        try:yield Path(root)
        finally:os.chdir(cwd)


class ValidationReview(unittest.TestCase):
    def test_old_success_is_invalidated_before_any_stage(self):
        from tools import validate as driver
        with isolated_records():
            Path('results').mkdir();Path('results/validation.json').write_text('{"passed":true}')
            def failed_stage(*args,**kwargs):
                value=json.loads(Path('results/validation.json').read_text())
                self.assertFalse(value['passed']);self.assertEqual(value['status'],'running')
                return 7,False,'',0
            with patch.object(driver,'run_stage',failed_stage),self.assertRaises(SystemExit) as error:
                driver.main()
            self.assertEqual(error.exception.code,1)
            self.assertFalse(json.loads(Path('results/validation.json').read_text())['passed'])
            self.assertIn('FAILED',Path('results/report.html').read_text())
    def test_source_change_during_stage_prevents_success(self):
        from tools import validate as driver
        with isolated_records() as root,patch('tools.evidence.ROOT',root):
            Path('rollout').mkdir();code=Path('rollout/probe.py');code.write_text('before')
            def changed(*args,**kwargs):code.write_text('after');return 0,False,'',0
            with patch.object(driver,'run_stage',changed),self.assertRaises(SystemExit):driver.main()
            value=json.loads(Path('results/validation.json').read_text())
            self.assertFalse(value['passed']);self.assertTrue(value['source_changed']);self.assertEqual(len(value['stages']),1)
    def test_source_change_during_passing_test_suite_is_rejected(self):
        from tools import test_suite
        with isolated_records() as root,patch('tools.evidence.ROOT',root):
            Path('rollout').mkdir();code=Path('rollout/probe.py');code.write_text('before')
            suite=unittest.TestSuite([unittest.FunctionTestCase(lambda:code.write_text('after'))])
            with patch.object(unittest.defaultTestLoader,'discover',return_value=suite),self.assertRaises(SystemExit):test_suite.main()
            value=json.loads(Path('results/tests.json').read_text())
            self.assertFalse(value['passed']);self.assertTrue(value['source_changed']);self.assertEqual(value['tests'],1)
    def test_infrastructure_failure_keeps_all_planned_trials(self):
        from tools import benchmark
        async def fail(*args,**kwargs):raise OSError('injected')
        with isolated_records(),patch.object(benchmark,'trial',fail):
            with self.assertRaises(SystemExit):asyncio.run(benchmark.run(SimpleNamespace(trials=1,count=300,rate=200)))
            value=json.loads(Path('results/benchmark.json').read_text())
            self.assertEqual(len(value['trials']),3);self.assertFalse(value['passed'])
            self.assertTrue(all(x['fatal_error']=='OSError' for x in value['trials']))

class ReportRunIdentity(unittest.TestCase):
    def records(self, stale=False, failed=False):
        from tools.evidence import provenance
        source=provenance();run='current-run'
        b=fixture();b.update(source=source,run_id='old-run' if stale else run,environment={})
        t={'passed':True,'tests':1,'skipped':0,'failures':0,'errors':0,'source':source,'run_id':run,'source_changed':False,'cases':[{'test':'example','outcome':'passed'}]}
        mutations={'passed':True,'source':source,'run_id':run,'cases':[{'detected':True,'timed_out':False} for _ in range(5)]}
        v={'source':source,'run_id':run,'status':'failed' if failed else 'running','stages':[{'exit_code':0,'timed_out':False,'leaked_workers_cleaned':0} for _ in range(3)]}
        Path('results').mkdir()
        for name,value in [('benchmark',b),('tests',t),('mutations',mutations),('validation',v)]:Path('results/'+name+'.json').write_text(json.dumps(value))
    def test_old_same_source_benchmark_cannot_join_new_run(self):
        from tools.report import main
        with isolated_records():
            self.records(stale=True)
            with self.assertRaisesRegex(SystemExit,'different validation run'):main()
    def test_renderer_cannot_turn_failed_validation_green(self):
        from tools.report import main
        with isolated_records():
            self.records(failed=True)
            with self.assertRaisesRegex(SystemExit,'validation not ready'):main()
