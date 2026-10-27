import unittest,tempfile,time,importlib.util
from unittest.mock import patch
import app
class Tests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.db=self.folder.name+'/state.sqlite3'
  self.patcher=patch.object(app,'STATE_DB',self.db);self.patcher.start()
  app.state.update(running=False,result=None,started_at=None,stage='Aguardando teste')
 def tearDown(self):self.patcher.stop();self.folder.cleanup()
 def test_shared_state_between_module_instances(self):
  token=app.begin_job()
  spec=importlib.util.spec_from_file_location('other_panel',app.__file__)
  other=importlib.util.module_from_spec(spec);spec.loader.exec_module(other);other.STATE_DB=self.db
  self.assertTrue(other.snapshot()['running'])
  app.update_job(token,running=False,result={'done':True})
  self.assertFalse(other.snapshot()['running']);self.assertTrue(other.snapshot()['result']['done'])
 def test_completed_job_releases_before_logging(self):
  token=app.begin_job()
  with patch.object(app,'run_process',return_value={'result':{'login_confirmed':True}}),patch('builtins.print',side_effect=OSError('log unavailable')):
   with self.assertRaises(OSError):app.job(False,token)
  self.assertFalse(app.snapshot()['running']);self.assertIsNotNone(app.snapshot()['result'])
 def test_stale_read_only_lease_released_and_old_result_ignored(self):
  old=app.begin_job();app.update_job(old,started_at=time.time()-87)
  self.assertFalse(app.snapshot()['running'])
  new=app.begin_job();app.update_job(old,running=False,result={'old':True})
  self.assertEqual(app.snapshot()['job_id'],new);self.assertTrue(app.snapshot()['running'])
 def test_order_is_never_unlocked_by_read_only_watchdog(self):
  token=app.begin_job(True);app.update_job(token,started_at=time.time()-87)
  self.assertTrue(app.snapshot()['running'])
 def test_opening_panel_does_not_start_worker(self):
  with patch.object(app.subprocess,'Popen') as child:
   self.assertFalse(app.snapshot()['running']);child.assert_not_called()
if __name__=='__main__':unittest.main()
