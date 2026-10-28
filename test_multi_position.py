import threading,time,tempfile,unittest,types
from unittest.mock import patch
import auto_session as session
from profit_exit import ProfitTracker
from test_demo_order import Client
from probe import send_demo_test

class Tests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.p=patch.object(session,'DB',self.folder.name+'/state');self.p.start()
 def tearDown(self):self.p.stop();self.folder.cleanup()
 def test_capacity_three_and_no_opposite_direction(self):
  b=session.PositionBook();b.add({'order_id':1,'direction':'call'})
  self.assertFalse(b.can_enter('put'));self.assertTrue(b.can_enter('call'))
  b.add({'order_id':2,'direction':'call'});self.assertTrue(b.can_enter('call'))
  b.add({'order_id':3,'direction':'call'});self.assertFalse(b.can_enter('call'))
  with self.assertRaises(RuntimeError):b.add({'order_id':4,'direction':'call'})
  b.update(1,{'order_id':1,'direction':'call'},done=True);self.assertTrue(b.can_enter('call'))
 def test_goal_latches_even_if_remaining_position_loses(self):
  t=session.claim('EURUSD-OTC');session.establish(t,100,4)
  for oid,pnl in [(1,1),(2,-1)]:session.settle(t,dict(order_id=oid,broker_pnl_realized=pnl,monitor_status='POSICAO_ENCERRADA'))
  self.assertTrue(session.change()['target_reached']);self.assertEqual(session.change()['realized'],'0')
 def test_one_settlement_cannot_clear_another_uncertain_order(self):
  t=session.claim('EURUSD-OTC');session.establish(t,100,4);session.update(t,uncertain=True)
  session.settle(t,dict(order_id=1,broker_pnl_realized=.08,monitor_status='POSICAO_ENCERRADA'))
  self.assertTrue(session.change()['uncertain'])
 def test_allowed_position_requires_exact_owned_identity(self):
  c=Client();owned=dict(id='owned',external_id=7,user_balance_id=1234,active_id=1861,instrument_type='digital-option')
  c.api.get_positions=lambda _:setattr(c.api,'positions',{'status':2000,'msg':{'positions':[owned]}})
  self.assertEqual(send_demo_test(c,allowed_positions=lambda:[dict(owned)])['orders_sent'],1)
  c=Client();c.api.get_positions=lambda _:setattr(c.api,'positions',{'status':2000,'msg':{'positions':[dict(owned,external_id=9)]}})
  self.assertEqual(send_demo_test(c,allowed_positions=lambda:[owned])['orders_sent'],0);self.assertFalse(c.api.calls)
 def test_dispatcher_maps_two_orders_and_valuations_independently(self):
  g=session.TrackerGroup();a=ProfitTracker(4,76);b=ProfitTracker(4,76);g.add(a);g.add(b);a.bind(10);b.bind(20)
  for oid,internal in [(10,'first'),(20,'second')]:
   g.receive({'name':'portfolio.position-changed','msg':dict(id=internal,external_id=oid+100,user_balance_id=4,active_id=76,instrument_type='digital-option',invest=1,status='open',order_ids=[oid])})
  g.receive({'name':'portfolio.positions-state','msg':{'positions':[dict(id='first',instrument_type='digital-option',sell_profit=1.08,pnl_net=.08),dict(id='second',instrument_type='digital-option',sell_profit=.7,pnl_net=-.3)]}})
  self.assertEqual(set(g.position_ids()),{'first','second'});self.assertTrue(a.valuation(100)['target_reached']);self.assertFalse(b.valuation(100)['target_reached'])
  self.assertEqual(a.position['external_id'],110);self.assertEqual(b.position['external_id'],120)
 def test_automatic_loop_accepts_three_signals_blocks_fourth_and_drains_all_on_pause(self):
  gate=threading.Event();clock=[1000];observations=[0];sent=[];monitored=[]
  trace=types.SimpleNamespace(asset_id=76,strategy_candles={0:{}},strategy_received=1000)
  client=types.SimpleNamespace(trace=trace,api=types.SimpleNamespace(timesync=types.SimpleNamespace(server_timestamp=1000)),get_balance_mode=lambda:'PRACTICE',get_balance_id=lambda:4)
  t=session.claim('EURUSD-OTC')
  def history(_):trace.strategy_received=clock[0];return []
  def analyze(*_):return dict(direction='call',reason='test',signal_id=str(clock[0]))
  def send(*args,**kw):
   self.assertTrue(kw['entry_guard']());entry=dict(order_id=len(sent)+1,direction='call',orders_sent=1,order_status='ORDEM_DEMO_CONFIRMADA');sent.append(entry);return entry
  def monitor(client,entry,*args,**kw):
   monitored.append((entry['order_id'],kw['tracker']))
   if not gate.wait(3):raise RuntimeError('gate timeout')
   return dict(entry,monitor_status='POSICAO_ENCERRADA',broker_pnl_realized=.08)
  def emit(row):
   if row.get('open_positions')==3:
    observations[0]+=1
    if observations[0]>=3:session.update(t,stop=True);gate.set()
  def sleep(_):clock[0]+=61;threading.Event().wait(.002)
  with patch('probe.inspect_client'),patch('probe.send_demo_test',side_effect=send),patch('profit_exit.monitor_profit',side_effect=monitor),patch('strategy.analyze',side_effect=analyze),patch.object(session,'bounded_history',side_effect=history),patch.object(session,'demo_balance',return_value=(100,4)),patch.object(session,'no_positions',return_value=True),patch.object(session.time,'monotonic',side_effect=lambda:clock[0]),patch.object(session.time,'sleep',side_effect=sleep):
   r=session.run_session(client,'EURUSD-OTC',t,lambda _:None,emit)
  self.assertEqual(len(sent),3);self.assertEqual(len(monitored),3);self.assertEqual(len({id(t) for _,t in monitored}),3);self.assertEqual(session.change()['realized'],'0.24');self.assertFalse(session.change()['active']);self.assertTrue(all(p['monitor_finished'] for p in r['positions']))
if __name__=='__main__':unittest.main()
