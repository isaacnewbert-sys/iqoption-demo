import unittest,types
from unittest.mock import patch
from profit_exit import ProfitTracker,monitor_profit
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=ProfitTracker(4,76);self.t.bind(99)
  self.row={'instrument_type':'digital-option','user_balance_id':4,'active_id':76,'external_id':999,'id':'position-a','invest':1,'status':'open','raw_event':{'digital_options_position_changed1':{'order_ids':[99]}}}
  self.t.ingest_position(self.row)
  self.t.metrics={'sell_profit':1.08,'pnl_net':.08,'quote_timestamp':1000,'received_at':0}
 def test_gross_proceeds_use_net_profit(self):
  value=self.t.valuation(1000,1);self.assertTrue(value['target_reached']);self.assertEqual(value['profit_pct'],8);self.assertEqual(value['valuation_mode'],'gross_proceeds')
 def test_net_profit_protocol(self):
  self.t.metrics['sell_profit']=.08;self.assertTrue(self.t.valuation(1000,1)['target_reached'])
 def test_below_threshold_is_not_rounded_up(self):
  self.t.metrics.update(sell_profit=1.07999,pnl_net=.07999);self.assertFalse(self.t.valuation(1000,1)['target_reached'])
 def test_stale_and_inconsistent_values_block(self):
  self.assertIsNone(self.t.valuation(1000,4));self.assertIsNone(self.t.valuation(1010,1))
  self.t.metrics['pnl_net']=.80;self.assertIsNone(self.t.valuation(1000,1))
 def test_wrong_account_order_asset_and_size_ignored(self):
  for change in ({'user_balance_id':1},{'active_id':1},{'invest':10},{'raw_event':{'order_ids':[100]}}):
   tracker=ProfitTracker(4,76);tracker.bind(99);tracker.ingest_position(dict(self.row,**change));self.assertIsNone(tracker.position)
 def test_closed_update_keeps_previously_verified_position_identity(self):
  self.t.ingest_position(dict(self.row,status='closed',raw_event={}))
  self.assertEqual(self.t.position['status'],'closed')
 def test_state_does_not_mix_positions(self):
  self.t.receive({'name':'positions-state','msg':{'positions':[{'id':'someone-else','instrument_type':'digital-option','sell_profit':9,'pnl_net':8}]}})
  self.assertEqual(self.t.metrics['sell_profit'],1.08)
 def test_close_ack_is_not_closed_position(self):
  self.t.close_request_id='close-1';self.t.receive({'name':'result','request_id':'close-1','msg':{'success':True}})
  self.assertTrue(self.t.close_ack);self.assertEqual(self.t.position['status'],'open')
 def simulate(self,close='confirmed',mode='PRACTICE',loss=False):
  tracker=self.t
  if loss:tracker.metrics.update(sell_profit=.95,pnl_net=-.05)
  calls=[];clock=[0]
  def tick():clock[0]+=.02;return clock[0]
  def send(name,msg,request_id):
   calls.append(msg)
   if msg['name']=='digital-options.close-position' and close=='confirmed':
    tracker.close_ack=True;tracker.ingest_position(dict(self.row,status='closed',close_reason='default',pnl_realized=.09))
  api=types.SimpleNamespace(send_websocket_request=send,timesync=types.SimpleNamespace(server_timestamp=1000))
  client=types.SimpleNamespace(api=api,trace=types.SimpleNamespace(profit_tracker=tracker,request_id='trace'),get_balance_mode=lambda:mode,get_balance_id=lambda:4)
  with patch('profit_exit.time.monotonic',side_effect=tick),patch('profit_exit.time.sleep'):
   result=monitor_profit(client,{'order_id':99,'expiration_timestamp':1001,'order_status':'ORDEM_DEMO_CONFIRMADA'})
  return result,[c for c in calls if c['name']=='digital-options.close-position']
 def test_target_closes_only_owned_position_and_waits_for_confirmation(self):
  result,calls=self.simulate();self.assertEqual(len(calls),1);self.assertEqual(calls[0]['body']['position_id'],999);self.assertTrue(result['early_sell_verified'])
 def test_no_loss_stop(self):
  result,calls=self.simulate(loss=True);self.assertFalse(calls);self.assertFalse(result['early_sell_verified'])
 def test_never_closes_real_balance(self):
  result,calls=self.simulate(mode='REAL');self.assertFalse(calls);self.assertEqual(result['monitor_status'],'MONITOR_INTERROMPIDO_CONTA_ALTERADA')
 def test_unknown_close_not_retried(self):
  result,calls=self.simulate(close='unknown');self.assertEqual(len(calls),1);self.assertFalse(result['early_sell_verified'])
if __name__=='__main__':unittest.main()
