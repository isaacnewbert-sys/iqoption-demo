import os,sys,time,json,subprocess,unittest,types
from probe import WireTrace,inspect_client
from unittest.mock import patch
with patch.dict(os.environ,{'IQ_EMAIL':'','IQ_PASSWORD':''}):
 import app
class Tests(unittest.TestCase):
 def test_structured_progress_and_final(self):
  script="import json,time;print(json.dumps({'progress':'Consultando catálogo'}),flush=True);time.sleep(.05);print(json.dumps({'result':{'login_confirmed':True}}),flush=True)"
  result=app.run_process([sys.executable,'-c',script],2)
  self.assertTrue(result['result']['login_confirmed'])
  self.assertEqual(app.state['stage'],'Consultando catálogo')
 def test_empty_instruments_does_not_wait_for_prices(self):
  trace=WireTrace()
  class API:
   timesync=types.SimpleNamespace(server_timestamp=1793138400)
   def send_websocket_request(self,name,msg,request_id):
    if msg['name'].endswith('instrument-generated'):
     trace.receive(json.dumps({'name':'result','request_id':request_id,'msg':{'success':True}}));return
    if msg['name'].endswith('get-underlying-list'):
     body={'underlying':[{'active_id':1,'name':'EURUSD','is_suspended':False}]}
    elif msg['name'].endswith('get-instruments'):
     body={'instruments':[]}
    else:return
    trace.receive(json.dumps({'name':'reply','request_id':request_id,'msg':body}))
  client=types.SimpleNamespace(trace=trace,api=API(),change_balance=lambda _:None,get_balance_mode=lambda:'PRACTICE')
  package=types.ModuleType('iqoptionapi');package.__path__=[]
  constants=types.ModuleType('iqoptionapi.constants');constants.ACTIVES={'EURUSD':1}
  started=time.monotonic()
  with patch.dict(sys.modules,{'iqoptionapi':package,'iqoptionapi.constants':constants}):result=inspect_client(client,'EURUSD')
  self.assertLess(time.monotonic()-started,.5)
  self.assertFalse(result['contracts_verified'])
  self.assertTrue(trace.instruments_received)
 def test_deadline_terminates_child(self):
  started=time.monotonic()
  with self.assertRaises(subprocess.TimeoutExpired):app.run_process([sys.executable,'-c','import time;time.sleep(5)'],.1)
  self.assertLess(time.monotonic()-started,2)
 def test_unstructured_output_not_exposed(self):
  result=app.run_process([sys.executable,'-c',"print('private-sdk-output')"],2)
  self.assertNotIn('private-sdk-output',json.dumps(result))
if __name__=='__main__':unittest.main()
