import unittest,tempfile,time,importlib.util,os
from unittest.mock import patch
import app
class Tests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.db=self.folder.name+'/state.sqlite3'
  self.patcher=patch.object(app,'STATE_DB',self.db);self.patcher.start()
  app.state.update(running=False,result=None,started_at=None,stage='Aguardando teste')
 def tearDown(self):self.patcher.stop();self.folder.cleanup()
 def test_memory_error_does_not_break_authenticated_status(self):
  import base64
  with patch.dict(os.environ,{'PANEL_PASSWORD':'local-test'}),patch.object(app.trade_memory,'snapshot',side_effect=ImportError('partially initialized module')):
   r=app.app.test_client().get('/status',headers={'Authorization':'Basic '+base64.b64encode(b'isaac:local-test').decode()})
  self.assertEqual(r.status_code,200);self.assertEqual(r.json['learning']['mode'],'MEMORY_STATUS_UNAVAILABLE');self.assertIn('running',r.json)
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
 def test_put_route_passes_direction_and_monitor(self):
  import base64
  env={'PANEL_PASSWORD':'test-local','IQ_EMAIL':'demo','IQ_PASSWORD':'demo'}
  h={'Authorization':'Basic '+base64.b64encode(b'isaac:test-local').decode(),'X-Demo-Panel':'1'}
  with patch.dict(os.environ,env),patch.object(app,'HOLD_FILE',self.folder.name+'/hold'),patch.object(app.threading,'Thread') as thread:
   c=app.app.test_client()
   self.assertEqual(c.post('/demo-order',headers=h,json={'direction':'bad'}).status_code,400)
   r=c.post('/demo-order',headers=h,json={'pair':'EURUSD-OTC','direction':'put'})
   self.assertEqual(r.status_code,202);self.assertEqual(r.json['direction'],'put')
   self.assertEqual(thread.call_args.kwargs['args'][3:],(True,'put'))
 def test_temporary_release_capability_is_scoped_single_use_and_expiring(self):
  env={'PANEL_PASSWORD':'test-local','IQ_EMAIL':'demo','IQ_PASSWORD':'demo','DEMO_RELEASE_TEST_TOKEN':'local-cap','DEMO_RELEASE_TEST_EXPIRES':str(time.time()+300)}
  with patch.dict(os.environ,env),patch.object(app,'HOLD_FILE',self.folder.name+'/hold'),patch.object(app.threading,'Thread') as thread:
   c=app.app.test_client();h={'X-Demo-Release-Test':'local-cap'}
   self.assertEqual(c.post('/release-demo-test').status_code,401)
   self.assertEqual(c.post('/run',headers=h).status_code,401)
   with patch.dict(os.environ,{'DEMO_RELEASE_TEST_EXPIRES':str(time.time()-1)}):self.assertEqual(c.post('/release-demo-test',headers=h).status_code,401)
   response=c.post('/release-demo-test',headers=h,json={'account':'REAL','amount':999,'pair':'BTCUSD'})
   self.assertEqual(response.status_code,202);self.assertEqual(response.json['account'],'PRACTICE');self.assertEqual(response.json['amount'],100)
   self.assertEqual(thread.call_args.kwargs['args'][2],'EURUSD-OTC');self.assertTrue(thread.call_args.kwargs['args'][3])
   app.update_job(app.snapshot()['job_id'],running=False)
   self.assertEqual(c.post('/release-demo-test',headers=h).status_code,409)
if __name__=='__main__':unittest.main()
