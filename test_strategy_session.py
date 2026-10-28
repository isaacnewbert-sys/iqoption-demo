import tempfile,unittest
from unittest.mock import patch
from decimal import Decimal
import auto_session as session
from strategy import analyze
from probe import WireTrace

class Tests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.p=patch.object(session,'DB',self.folder.name+'/session.sqlite');self.p.start()
 def tearDown(self):self.p.stop();self.folder.cleanup()
 def test_fixed_baseline_and_target(self):
  t=session.claim('EURUSD-OTC');s=session.establish(t,100,4)
  session.establish(t,200,4)
  self.assertEqual(session.change()['initial_balance'],'100');self.assertEqual(Decimal(s['target']),1)
 def test_realized_only_and_deduplication(self):
  t=session.claim('EURUSD-OTC');session.establish(t,100,4)
  r={'order_id':1,'broker_pnl_realized':.6,'monitor_status':'POSICAO_ENCERRADA'}
  session.settle(t,r);session.settle(t,r)
  self.assertEqual(Decimal(session.change()['realized']),Decimal('.6'));self.assertFalse(session.change()['target_reached'])
  session.settle(t,dict(r,order_id=2,broker_pnl_realized=.4));self.assertTrue(session.change()['target_reached'])
 def test_losses_reduce_session_profit(self):
  t=session.claim('EURUSD-OTC');session.establish(t,100,4)
  for oid,pnl in [(1,.8),(2,-1)]:session.settle(t,dict(order_id=oid,broker_pnl_realized=pnl,monitor_status='POSICAO_ENCERRADA'))
  self.assertEqual(Decimal(session.change()['realized']),Decimal('-.2'))
 def test_open_or_unknown_profit_cannot_count(self):
  t=session.claim('EURUSD-OTC');session.establish(t,100,4)
  for r in [dict(order_id=1,broker_pnl_realized=2,monitor_status='OPEN'),dict(order_id=1,monitor_status='POSICAO_ENCERRADA')]:
   with self.assertRaises(RuntimeError):session.settle(t,r)
 def test_resume_preserves_baseline_and_stop(self):
  t=session.claim('EURUSD-OTC');session.establish(t,100,4);session.update(t,stop=True,active=False)
  self.assertTrue(session.stopped(t));other=session.claim('EURUSD-OTC');self.assertFalse(session.stopped(other));self.assertEqual(session.change()['initial_balance'],'100')
 def test_uncertain_and_target_block_resume(self):
  t=session.claim('EURUSD-OTC');session.update(t,active=False,uncertain=True)
  with self.assertRaises(RuntimeError):session.claim('EURUSD-OTC')
  session.update(t,uncertain=False,target_reached=True)
  with self.assertRaises(RuntimeError):session.claim('EURUSD-OTC')
 def test_panel_auto_start_stop_and_goal_blocks_manual(self):
  import app,base64,os
  h={'Authorization':'Basic '+base64.b64encode(b'isaac:test-local').decode(),'X-Demo-Panel':'1'}
  with patch.dict(os.environ,{'PANEL_PASSWORD':'test-local','IQ_EMAIL':'demo','IQ_PASSWORD':'demo'}),patch.object(app,'STATE_DB',self.folder.name+'/panel.sqlite'),patch.object(app,'HOLD_FILE',self.folder.name+'/hold'),patch.object(app.threading,'Thread') as thread:
   c=app.app.test_client()
   self.assertEqual(c.post('/automation/start').status_code,401)
   self.assertEqual(c.post('/automation/start',headers=h,json={'pair':'bad'}).status_code,400)
   self.assertEqual(c.post('/automation/start',headers=h,json={'pair':'EURUSD-OTC'}).status_code,202)
   self.assertEqual(len(thread.call_args.kwargs['args']),6)
   self.assertEqual(c.post('/automation/start',headers=h).status_code,409)
   self.assertEqual(c.post('/automation/stop',headers=h).status_code,202);self.assertTrue(session.change()['stop'])
   app.update_job(app.snapshot()['job_id'],running=False);session.change(lambda s:s.update(active=False,target_reached=True))
   self.assertEqual(c.post('/demo-order',headers=h).status_code,409)
   self.assertEqual(c.post('/automation/start',headers=h).status_code,409)
   self.assertEqual(c.post('/automation/new',headers=h).status_code,200);self.assertEqual(session.change(),{})
 def bars(self):
  start=1793142000//300*300
  rows=[dict(**{'from':start+i*60,'to':start+(i+1)*60},open=100,close=100,min=99.8,max=100.2) for i in range(120)]
  now=start+120*60+10
  live=dict(**{'from':start+120*60,'to':start+121*60},open=100,close=100,min=99.8,max=100.2)
  return rows,live,now
 def test_support_rejection_call_intrabar(self):
  rows,live,now=self.bars();rows[-1].update(open=99.95,close=100.05,min=99.7,max=100.08);live.update(close=100.12,max=100.15)
  self.assertEqual(analyze(rows+[live],now)['direction'],'call')
 def test_resistance_rejection_put_intrabar(self):
  rows,live,now=self.bars();rows[-1].update(open=100.05,close=99.95,min=99.92,max=100.3);live.update(close=99.88,min=99.85)
  self.assertEqual(analyze(rows+[live],now)['direction'],'put')
 def test_no_breakout_no_signal_and_missing_history_blocks(self):
  rows,live,now=self.bars();self.assertIsNone(analyze(rows+[live],now)['direction'])
  rows.pop(-10);self.assertIsNone(analyze(rows+[live],now)['direction'])
 def test_future_bar_does_not_change_signal(self):
  rows,live,now=self.bars();a=analyze(rows+[live],now)
  future=dict(live);future['from']+=60;future['to']+=60;future['close']=10000;future['max']=10000
  self.assertEqual(a,analyze(rows+[live,future],now))
 def test_auto_entry_monitor_target_and_no_second_entry(self):
  import types,time
  rows,live,now=self.bars();rows[-1].update(open=99.95,close=100.05,min=99.7,max=100.08);live.update(close=100.12,max=100.15)
  trace=types.SimpleNamespace(asset_id=76,strategy_candles={live['from']:live},strategy_received=time.monotonic())
  client=types.SimpleNamespace(trace=trace,api=types.SimpleNamespace(timesync=types.SimpleNamespace(server_timestamp=now)),get_balance_mode=lambda:'PRACTICE',get_balance_id=lambda:4)
  t=session.claim('EURUSD-OTC');entry=dict(order_status='ORDEM_DEMO_CONFIRMADA',orders_sent=1,order_id=88,direction='call',expiration_timestamp=now+100)
  closed=dict(entry,monitor_status='FECHAMENTO_ANTECIPADO_CONFIRMADO',broker_pnl_realized=8)
  with patch.object(session,'no_positions',return_value=True),patch('probe.inspect_client'),patch('probe.send_demo_test',return_value=entry) as send,patch('profit_exit.monitor_profit',return_value=closed) as monitor,patch.object(session,'bounded_history',return_value=rows+[live]),patch.object(session,'demo_balance',return_value=(800,4)),patch.object(session.time,'sleep'):
   result=session.run_session(client,'EURUSD-OTC',t,lambda _:None,lambda _:None)
  self.assertEqual(send.call_count,1);self.assertTrue(send.call_args.kwargs['take_profit_8']);self.assertEqual(send.call_args.kwargs['direction'],'call')
  self.assertEqual(monitor.call_count,1);self.assertEqual(result['automation_status'],'META_ATINGIDA');self.assertFalse(session.change()['active'])
 def test_stop_during_trade_does_not_interrupt_monitor(self):
  import types,time
  rows,live,now=self.bars();rows[-1].update(open=99.95,close=100.05,min=99.7,max=100.08);live.update(close=100.12,max=100.15)
  client=types.SimpleNamespace(trace=types.SimpleNamespace(asset_id=76,strategy_candles={live['from']:live},strategy_received=time.monotonic()),api=types.SimpleNamespace(timesync=types.SimpleNamespace(server_timestamp=now)),get_balance_mode=lambda:'PRACTICE',get_balance_id=lambda:4)
  t=session.claim('EURUSD-OTC');entry=dict(order_status='ORDEM_DEMO_CONFIRMADA',order_id=88,direction='call')
  def monitor(*args,**kwargs):
   session.update(t,stop=True)
   return dict(entry,monitor_status='POSICAO_ENCERRADA',broker_pnl_realized=-1)
  with patch.object(session,'no_positions',return_value=True),patch('probe.inspect_client'),patch('probe.send_demo_test',return_value=entry),patch('profit_exit.monitor_profit',side_effect=monitor) as m,patch.object(session,'bounded_history',return_value=rows+[live]),patch.object(session,'demo_balance',return_value=(100,4)),patch.object(session.time,'sleep'):
   session.run_session(client,'EURUSD-OTC',t,lambda _:None,lambda _:None)
  self.assertEqual(m.call_count,1);self.assertEqual(session.change()['realized'],'-1');self.assertTrue(session.change()['stop'])
 def test_external_position_block_explained_without_order(self):
  import types
  client=types.SimpleNamespace(trace=types.SimpleNamespace(asset_id=76),api=types.SimpleNamespace())
  t=session.claim('EURUSD-OTC');updates=[]
  with patch('probe.inspect_client'),patch.object(session,'no_positions',return_value=False),patch('probe.send_demo_test') as send:
   result=session.run_session(client,'EURUSD-OTC',t,lambda _:None,updates.append)
  send.assert_not_called();self.assertEqual(result['blocking_reason'],'POSICAO_DIGITAL_PREVIA_OU_CONSULTA_NAO_CONFIRMADA');self.assertFalse(session.change()['active'])
 def test_setup_and_regime_are_recorded_for_evaluation(self):
  t=session.claim('EURUSD-OTC');session.establish(t,100,4)
  session.settle(t,dict(order_id=1,broker_pnl_realized=.08,monitor_status='POSICAO_ENCERRADA',setup='PULLBACK_TENDENCIA',regime='TENDENCIA_ALTA'))
  self.assertEqual(session.change()['ledger'][0]['setup'],'PULLBACK_TENDENCIA')
 def test_live_wire_retains_ohlc_and_rejects_other_asset(self):
  rows,live,now=self.bars();t=WireTrace();t.asset_id=76
  t.receive({'name':'candle-generated','msg':dict(live,active_id=76)})
  self.assertEqual(len(t.strategy_candles),1);self.assertGreater(t.strategy_received,0)
  t.receive({'name':'candle-generated','msg':dict(rows[0],active_id=1)})
  self.assertEqual(len(t.strategy_candles),1)
if __name__=='__main__':unittest.main()
