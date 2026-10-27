import unittest,sys,time,json,types,os,tempfile
from unittest.mock import patch
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe import WireTrace,send_demo_test
class API:
 def __init__(self,t):self.t=t;self.timesync=types.SimpleNamespace(server_timestamp=1793138400);self.positions=None;self.calls=[];self.fail=False;self.open=False
 def get_positions(self,k):self.positions={'status':2000,'msg':{'positions':[{}] if self.open else []}}
 def send_websocket_request(self,n,p,request_id):
  self.calls.append((n,p,request_id))
  if self.fail:raise OSError('lost ack')
  self.t.receive(json.dumps({'name':'digital-option-placed','request_id':request_id,'msg':{'id':99}}))
class Client:
 def __init__(self):
  self.mode='PRACTICE';self.typ=4;self.trace=WireTrace();t=self.trace;t.asset_id=1861;t.pair='EURUSD-op';self.api=API(t)
  d=datetime.fromtimestamp(1793138700,timezone.utc);prefix='do1861A'+d.strftime('%Y%m%dD%H%M%S')+'T5M'
  sides={direction:{'symbol':prefix+letter+'SPT','ask':50,'bid':48} for direction,letter in [('call','C'),('put','P')]}
  t.receive(json.dumps({'name':'client-price-generated','msg':{'asset_id':1861,'prices':[{'strike':'SPT',**sides}]}}))
  t.instruments=[{'asset_id':1861,'index':123,'period':300,'expiration':1793138700,'deadtime':30,'symbols':[{'direction':k,'symbol':v['symbol']} for k,v in sides.items()]}]
 def get_balance_mode(self):return self.mode
 def get_balance_id(self):return 1234
 def get_profile_ansyc(self):return {'balances':[{'id':1234,'type':self.typ}]}
class Tests(unittest.TestCase):
 def setUp(self):self.c=Client()
 def test_demo_only(self):
  r=send_demo_test(self.c);self.assertEqual(r['orders_sent'],1);self.assertEqual(r['order_id'],99)
  self.assertEqual(len(self.c.api.calls),1);body=self.c.api.calls[0][1]['body'];self.assertEqual(body['amount'],'1');self.assertEqual(body['user_balance_id'],1234);self.assertEqual(body['asset_id'],1861)
 def test_real_blocked(self):
  self.c.mode='REAL';r=send_demo_test(self.c);self.assertEqual(r['orders_sent'],0);self.assertFalse(self.c.api.calls)
 def test_wrong_balance_type(self):
  self.c.typ=1;self.assertEqual(send_demo_test(self.c)['orders_sent'],0);self.assertFalse(self.c.api.calls)
 def test_open_position(self):
  self.c.api.open=True;self.assertEqual(send_demo_test(self.c)['orders_sent'],0);self.assertFalse(self.c.api.calls)
 def test_no_quotes(self):
  self.c.trace.new_packets=[];self.assertEqual(send_demo_test(self.c)['orders_sent'],0);self.assertFalse(self.c.api.calls)
 def test_unknown_not_retried(self):
  self.c.api.fail=True;r=send_demo_test(self.c);self.assertIsNone(r['orders_sent']);send_demo_test(self.c);self.assertEqual(len(self.c.api.calls),1)
 def test_expired(self):
  self.c.api.timesync.server_timestamp=1793138800;self.assertEqual(send_demo_test(self.c)['orders_sent'],0);self.assertFalse(self.c.api.calls)
 def test_quote_ack_alone_not_order(self):
  self.c.trace.order_request_id='one';self.c.trace.receive(json.dumps({'name':'result','request_id':'one','msg':{'success':True}}));self.assertIsNone(self.c.trace.order_reply)
 def test_panel_requires_auth_and_deduplicates(self):
  import base64
  with patch.dict(os.environ,{'PANEL_PASSWORD':'local-test','IQ_EMAIL':'','IQ_PASSWORD':''}):
   import app
  app.state.update(running=False,result=None)
  with tempfile.TemporaryDirectory() as folder,patch.object(app,'HOLD_FILE',folder+'/hold'),patch.object(app,'STATE_DB',folder+'/state.sqlite3'),patch.object(app.threading,'Thread'):
   with patch.dict(os.environ,{'PANEL_PASSWORD':'local-test','IQ_EMAIL':'demo','IQ_PASSWORD':'demo'}):
    c=app.app.test_client();self.assertEqual(c.post('/demo-order').status_code,401)
    h={'Authorization':'Basic '+base64.b64encode(b'isaac:local-test').decode()};self.assertEqual(c.post('/demo-order',headers=h).status_code,403)
    h['X-Demo-Panel']='1';self.assertEqual(c.post('/demo-order',headers=h).status_code,202)
    app.update_job(app.snapshot()['job_id'],running=False);self.assertEqual(c.post('/demo-order',headers=h).status_code,409)
if __name__=='__main__':unittest.main()
