"""Temporary metadata roots only; never imports production or dispatches work."""
import tempfile,unittest
from pathlib import Path
from harness import JobHarness,read,write
class HarnessTests(unittest.TestCase):
    def test_normal_by_job_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'E';h=JobHarness(root,Path(tmp)/'receipts');calls=[]
            def runner(actual):
                self.assertEqual(actual,root)
                write(actual/'run.json',{'rows':[{'job_id':'J07','status':'NOT_RUN'},{'job_id':'J00','status':'COMPLETE'}]})
                return {'literal':'RESULT'}
            result,row=h.run('J00',runner,calls)
            self.assertEqual(row['production_status'],'COMPLETE');self.assertEqual(result,{'literal':'RESULT'})
    def test_other_directory_is_never_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'E';other=Path(tmp)/'continuation'
            write(other/'run.json',{'rows':[{'job_id':'J00','status':'COMPLETE'}]})
            def runner(actual):
                write(actual/'run.json',{'rows':[{'job_id':'J00','status':'TECHNICAL_FAILURE'}]})
            _,row=JobHarness(root,Path(tmp)/'receipts').run('J00',runner,[])
            self.assertEqual(row['production_status'],'TECHNICAL_FAILURE')
    def test_missing_run_keeps_original_exception_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[];original=RuntimeError('ORIGINAL_DISPATCH_ERROR')
            def runner(root):calls.append({'pure_marker':'NOT_A_REAL_MONITOR'});raise original
            h=JobHarness(Path(tmp)/'E',Path(tmp)/'receipts')
            with self.assertRaises(RuntimeError) as caught:h.run('J00',runner,calls)
            self.assertIs(caught.exception,original)
            row=read(Path(tmp)/'receipts/J00.json')
            self.assertEqual(row['original_error']['detail'],'ORIGINAL_DISPATCH_ERROR')
            self.assertEqual(row['status_read_error']['type'],'FileNotFoundError')
            self.assertEqual(row['monitor_dispatch_records'],calls)
    def test_missing_run_after_return_and_stale_other_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp)/'continuation/run.json',{'rows':[{'job_id':'J00','status':'COMPLETE'}]})
            h=JobHarness(Path(tmp)/'E',Path(tmp)/'receipts');calls=[{'pure_marker':1}]
            with self.assertRaises(FileNotFoundError):h.run('J00',lambda root:None,calls)
            row=read(Path(tmp)/'receipts/J00.json')
            self.assertEqual(row['production_status'],'UNKNOWN');self.assertEqual(row['monitor_dispatch_records'],calls)
if __name__=='__main__':unittest.main()
