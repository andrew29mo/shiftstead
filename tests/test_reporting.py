import unittest
from tools.report import validate
from rollout.core import Controller

class EvidenceSafety(unittest.TestCase):
    def test_empty_report_rejected(self):
        with self.assertRaises(ValueError):validate({'schema':1,'kind':'real-process-open-loop','trials':[],'passed':True})
    def test_nan_and_infinity_rejected(self):
        for x in [float('nan'),float('inf'),-1,0,True]:
            with self.assertRaises(ValueError):Controller.validate({'version':'v','command':['x'],'observe':x})
    def test_unknown_manifest_fields_rejected(self):
        with self.assertRaises(ValueError):Controller.validate({'version':'v','command':['x'],'shell':True})

class ValidationTimeout(unittest.TestCase):
    def test_nonzero_and_timeout_are_not_success(self):
        import sys
        from tools.process import run_stage
        code,timed_out,_,leaked=run_stage([sys.executable,'-c','raise SystemExit(7)'],2,capture=True)
        self.assertEqual(code,7);self.assertFalse(timed_out);self.assertEqual(leaked,0)
        code,timed_out,_,leaked=run_stage([sys.executable,'-c','import time;time.sleep(20)'],.05,capture=True)
        self.assertNotEqual(code,0);self.assertTrue(timed_out);self.assertEqual(leaked,0)
