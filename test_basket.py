import unittest,types,time,tempfile,threading
from datetime import datetime,timezone
from unittest.mock import patch
from probe import WireTrace,send_demo_test
from profit_exit import ProfitTracker
from auto_session import PositionBook
import auto_session as session
from settings import MAJOR_PAIRS,basket_pairs,TRADE_AMOUNT
from basket import MarketHub,rank_markets,priority,run_basket_session
from test_regime_strategy import pullback,START
from test_demo_order import Client
NOW=START+7201

def client_hub(mode='MAJORS'):
 root=WireTrace();root.catalog_received=True
 root.catalog_assets=[{'name':p+'-op','active_id':i+1,'is_suspended':False} for i,p in enumerate(MAJOR_PAIRS)]+[{'name':p+'-OTC','active_id':76+i,'is_suspended':False} for i,p in enumerate(MAJOR_PAIRS)]
 calls=[];api=types.SimpleNamespace(timesync=types.SimpleNamespace(server_timestamp=NOW),send_websocket_request=lambda n,p,request_id:calls.append((n,p,request_id)))
 client=types.SimpleNamespace(trace=root,api=api,get_balance_mode=lambda:'PRACTICE',get_balance_id=lambda:4)
 hub=MarketHub(client,mode);hub.bind_catalog();return client,hub,calls

def seed(client,hub):
 bars,live=pullback();expiry=(NOW//300+1)*300;date=datetime.fromtimestamp(expiry,timezone.utc).strftime('%Y%m%dD%H%M%S')
 for market in hub.markets.values():
  t=market.trace;market.history=bars;market.history_received=time.monotonic()
  client.trace.receive({'name':'candle-generated','msg':dict(live,active_id=t.asset_id)})
  symbols={direction:{'symbol':'do'+str(t.asset_id)+'A'+date+'T5M'+letter+'SPT','ask':50,'bid':48} for direction,letter in [('call','C'),('put','P')]}
  t.instruments=[dict(asset_id=t.asset_id,index=t.asset_id+100,period=300,expiration=expiry,deadtime=30,symbols=[{'direction':k,'symbol':v['symbol']} for k,v in symbols.items()])]
  client.trace.receive({'name':'digital-option-client-price-generated','msg':{'asset_id':t.asset_id,'instrument_index':t.asset_id+100,'quote_time':NOW,'prices':[dict(strike='SPT',**symbols)]}})

class Tests(unittest.TestCase):
 def test_parallel_requests_are_issued_for_six_markets_without_shared_buffer(self):
  c,h,calls=client_hub();h.refresh(force=True)
  hist=[x for x in calls if x[1]['name']=='get-candles'];self.assertEqual(len(hist),6);self.assertEqual(len({x[2] for x in hist}),6)
  self.assertEqual({x[1]['body']['active_id'] for x in hist},set(range(1,7)))
  bars,live=pullback()
  for n,p,rid in reversed(hist):c.trace.receive({'name':'candles','request_id':rid,'msg':{'active_id':p['body']['active_id'],'candles':[dict(b,close=b['close']) for b in bars]}})
  self.assertTrue(all(len(m.history)==120 for m in h.markets.values()))
 def test_out_of_order_history_cannot_cross_assets_or_replace_newer_request(self):
  c,h,calls=client_hub();h.refresh(True);market=h.markets['EURUSD'];old=market.history_rid;h.refresh(True);new=market.history_rid;bars,_=pullback()
  c.trace.receive({'name':'candles','request_id':old,'msg':{'candles':bars}});self.assertFalse(market.history)
  c.trace.receive({'name':'candles','request_id':new,'msg':{'active_id':999,'candles':bars}});self.assertFalse(market.history)
  c.trace.receive({'name':'candles','request_id':new,'msg':{'active_id':market.trace.asset_id,'candles':bars}});self.assertEqual(len(market.history),120)
  self.assertFalse(h.markets['GBPUSD'].history)
 def test_streams_and_contracts_are_isolated(self):
  c,h,_=client_hub();seed(c,h)
  rows=rank_markets(h,PositionBook(),set());self.assertEqual(len(rows),6);self.assertTrue(all(r['status']=='CANDIDATO' for r in rows),rows)
  original=h.markets['USDJPY'].trace.strategy_candles.copy();c.trace.receive({'name':'candle-generated','msg':dict(next(iter(original.values())),active_id=1,close=105.1)})
  self.assertEqual(original,h.markets['USDJPY'].trace.strategy_candles)
 def test_priority_prefers_timely_signal_and_tie_is_deterministic(self):
  a=dict(atr=1,trigger=100,efficiency=.8,regime='TENDENCIA_ALTA',direction='call',resistance=102)
  self.assertGreater(priority(a,100.05),priority(a,100.45))
  self.assertGreater(priority(a,100.05,{'ask':50,'bid':49}),priority(a,100.05,{'ask':50,'bid':40}))
  c,h,_=client_hub();seed(c,h);rows=rank_markets(h,PositionBook(),set())
  self.assertEqual(rows[0]['pair'],'AUDUSD');self.assertIsInstance(rows[0]['priority'],float)
 def test_stale_missing_contract_used_signal_and_unavailable_pair_are_excluded(self):
  c,h,_=client_hub();seed(c,h);rows=rank_markets(h,PositionBook(),set());used={rows[0]['signal_key']}
  h.markets['EURUSD'].trace.strategy_received-=10;h.markets['GBPUSD'].trace.new_packets=[];h.markets['USDCHF'].trace=None
  states={r['pair']:r['status'] for r in rank_markets(h,PositionBook(),used)}
  self.assertEqual(states['EURUSD'],'DADOS_ATRASADOS');self.assertEqual(states['GBPUSD'],'CONTRATO_INDISPONIVEL');self.assertEqual(states['USDCHF'],'ATIVO_INDISPONIVEL');self.assertEqual(states['AUDUSD'],'SINAL_UTILIZADO')
 def test_radar_excludes_final_minute_before_signal_ranking(self):
  c,h,_=client_hub();seed(c,h);now=(NOW//300+1)*300-60
  c.api.timesync.server_timestamp=now
  for m in h.markets.values():
   for packet in m.trace.new_packets:packet['quote_time']=now
  self.assertTrue(all(r['status']=='ULTIMO_MINUTO' for r in rank_markets(h,PositionBook(),set())))
 def test_normal_and_otc_do_not_fall_back_to_each_other(self):
  c,h,_=client_hub();self.assertEqual(h.markets['EURUSD'].trace.pair,'EURUSD-op')
  c,h,_=client_hub('MAJORS-OTC');self.assertEqual(h.markets['EURUSD-OTC'].trace.pair,'EURUSD-OTC')
  c.trace.catalog_assets=[a for a in c.trace.catalog_assets if a['name'].endswith('-OTC')];h2=MarketHub(c,'MAJORS');h2.bind_catalog();self.assertTrue(all(m.trace is None for m in h2.markets.values()))
 def test_cross_pair_direction_can_differ_but_same_pair_cannot_hedge(self):
  b=PositionBook();b.add(dict(order_id=1,direction='call',pair='EURUSD-op'))
  self.assertTrue(b.can_enter('put','USDJPY-op'));self.assertFalse(b.can_enter('put','EURUSD-op'))
 def test_send_accepts_only_exact_owned_other_asset_positions_and_fixed_100(self):
  c=Client();owned=dict(id='other-asset',external_id=70,user_balance_id=1234,active_id=77,instrument_type='digital-option')
  c.api.get_positions=lambda _:setattr(c.api,'positions',{'status':2000,'msg':{'positions':[owned]}})
  result=send_demo_test(c,allowed_positions=lambda:[owned]);self.assertEqual(result['amount'],100);self.assertEqual(c.api.calls[0][1]['body']['amount'],'100')
 def test_100_stake_target_is_eight_currency_units_not_point_zero_eight(self):
  tracker=ProfitTracker(4,76,amount=100);tracker.bind(1)
  tracker.ingest_position(dict(instrument_type='digital-option',user_balance_id=4,active_id=76,invest=100,id='p',external_id=99,status='open',order_ids=[1]))
  tracker.metrics=dict(sell_profit=100.08,pnl_net=.08,received_at=time.monotonic());self.assertFalse(tracker.valuation(NOW)['target_reached'])
  tracker.metrics.update(sell_profit=108,pnl_net=8);self.assertTrue(tracker.valuation(NOW)['target_reached']);self.assertEqual(tracker.valuation(NOW)['net_profit'],8)
  wrong=ProfitTracker(4,76,amount=100);wrong.bind(1);wrong.ingest_position(dict(instrument_type='digital-option',user_balance_id=4,active_id=76,invest=1,id='p',external_id=99,status='open',order_ids=[1]));self.assertIsNone(wrong.position)
 def test_basket_worker_selects_top_pair_rechecks_all_and_settles(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(session,'DB',folder+'/session'):
   c,h,_=client_hub();seed(c,h);token=session.claim('MAJORS');sent=[]
   def mock_send(client,**kw):
    self.assertTrue(kw['entry_guard']());sent.append(client.trace.pair)
    return dict(order_id=1,orders_sent=1,order_status='ORDEM_DEMO_CONFIRMADA',order_attempted=True,direction=kw['direction'],expiration_timestamp=NOW+200)
   def closed(client,entry,*args,**kwargs):
    result=dict(entry,monitor_status='FECHAMENTO_ANTECIPADO_CONFIRMADO',broker_pnl_realized=8)
    session.settle(token,result)
    return result
   with patch('basket.MarketHub',return_value=h),patch.object(h,'bootstrap'),patch.object(h,'refresh'),patch('basket.no_positions',return_value=True),patch('basket.demo_balance',return_value=(800,4)),patch('probe.send_demo_test',side_effect=mock_send),patch('basket.monitor_profit',side_effect=closed),patch('basket.MAX_OPEN_POSITIONS',1),patch('basket.time.sleep'):
    result=run_basket_session(c,'MAJORS',token,lambda _:None,lambda _:None)
   self.assertEqual(sent,['AUDUSD-op']);self.assertEqual(result['automation_status'],'META_ATINGIDA');self.assertEqual(session.change()['ledger'][0]['amount'],100);self.assertIsNone(c.trace.market_hub)
 def test_changed_winner_before_wire_blocks_the_previous_choice(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(session,'DB',folder+'/session'):
   c,h,_=client_hub();seed(c,h);token=session.claim('MAJORS');guards=[]
   def mock_send(client,**kw):
    market=h.markets['GBPUSD'];key=max(market.trace.strategy_candles);market.trace.strategy_candles[key]['close']=105.351
    guards.append(kw['entry_guard']())
    return dict(order_status='BLOQUEADO_SINAL_OU_SESSAO_ALTERADA',orders_sent=0,order_attempted=False)
   def emit(row):
    if row.get('last_entry'):session.update(token,stop=True)
   with patch('basket.MarketHub',return_value=h),patch.object(h,'bootstrap'),patch.object(h,'refresh'),patch('basket.no_positions',return_value=True),patch('basket.demo_balance',return_value=(800,4)),patch('probe.send_demo_test',side_effect=mock_send),patch('basket.time.sleep'):
    result=run_basket_session(c,'MAJORS',token,lambda _:None,emit)
   self.assertEqual(guards,[False]);self.assertEqual(result['orders_sent'],0)
 def test_unknown_submission_is_not_retried(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(session,'DB',folder+'/session'):
   c,h,_=client_hub();seed(c,h);token=session.claim('MAJORS')
   with patch('basket.MarketHub',return_value=h),patch.object(h,'bootstrap'),patch.object(h,'refresh'),patch('basket.no_positions',return_value=True),patch('basket.demo_balance',return_value=(800,4)),patch('probe.send_demo_test',return_value=dict(order_status='ENVIO_INCERTO_NAO_REPETIR',orders_sent=None,order_attempted=True)) as send:
    result=run_basket_session(c,'MAJORS',token,lambda _:None,lambda _:None)
   self.assertEqual(send.call_count,1);self.assertTrue(session.change()['uncertain']);self.assertEqual(result['last_entry']['amount'],100)
 def test_three_best_available_pairs_are_monitored_and_fourth_is_blocked(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(session,'DB',folder+'/session'):
   c,h,_=client_hub();seed(c,h);token=session.claim('MAJORS');clock=[1000];gate=threading.Event();sent=[];send_times=[];observations=[0]
   def refresh():
    for m in h.markets.values():
     m.history_received=m.trace.strategy_received=clock[0]
     for packet in m.trace.new_packets:packet['received_at_monotonic']=clock[0]
   def send(client,**kw):
    self.assertTrue(kw['entry_guard']());sent.append(client.trace.pair);send_times.append(clock[0])
    return dict(order_id=len(sent),direction='call',amount=100,order_status='ORDEM_DEMO_CONFIRMADA',orders_sent=1,order_attempted=True,expiration_timestamp=NOW+200)
   def monitor(client,entry,*args,**kw):
    self.assertEqual(kw['tracker'].expected_investment,100)
    if not gate.wait(3):raise RuntimeError('gate timeout')
    return dict(entry,monitor_status='POSICAO_ENCERRADA',broker_pnl_realized=8)
   def emit(row):
    if row.get('open_positions')==3:
     observations[0]+=1
     if observations[0]>=3:session.update(token,stop=True);gate.set()
   def sleep(_):clock[0]+=61;threading.Event().wait(.002)
   with patch('basket.MarketHub',return_value=h),patch.object(h,'bootstrap'),patch.object(h,'refresh',side_effect=refresh),patch('basket.no_positions',return_value=True),patch('basket.demo_balance',return_value=(10000,4)),patch('probe.send_demo_test',side_effect=send),patch('basket.monitor_profit',side_effect=monitor),patch('basket.time.monotonic',side_effect=lambda:clock[0]),patch('basket.time.sleep',side_effect=sleep):
    result=run_basket_session(c,'MAJORS',token,lambda _:None,emit)
   self.assertEqual(sent,['AUDUSD-op','EURUSD-op','GBPUSD-op']);self.assertEqual(send_times,[1000,1000,1000]);self.assertEqual(result['orders_sent'],3);self.assertEqual(session.change()['realized'],'24');self.assertTrue(all(r['monitor_finished'] for r in result['positions']))
 def test_insufficient_demo_balance_never_sends_an_order(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(session,'DB',folder+'/session'):
   c,h,_=client_hub();seed(c,h);token=session.claim('MAJORS')
   with patch('basket.MarketHub',return_value=h),patch.object(h,'bootstrap'),patch.object(h,'refresh'),patch('basket.no_positions',return_value=True),patch('basket.demo_balance',return_value=(99,4)),patch('probe.send_demo_test') as send:
    result=run_basket_session(c,'MAJORS',token,lambda _:None,lambda _:None)
   send.assert_not_called();self.assertEqual(result['blocking_reason'],'SALDO_INSUFICIENTE_PARA_100')
 def test_panel_accepts_basket_and_keeps_amount_fixed_to_100(self):
  import app,os,base64
  with tempfile.TemporaryDirectory() as folder,patch.object(session,'DB',folder+'/session'),patch.object(app,'STATE_DB',folder+'/panel'),patch.object(app,'HOLD_FILE',folder+'/hold'),patch.dict(os.environ,{'PANEL_PASSWORD':'qa','IQ_EMAIL':'demo','IQ_PASSWORD':'demo'}),patch.object(app.threading,'Thread') as thread:
   c=app.app.test_client();headers={'Authorization':'Basic '+base64.b64encode(b'isaac:qa').decode(),'X-Demo-Panel':'1'}
   r=c.post('/automation/start',headers=headers,json={'pair':'MAJORS-OTC','amount':9999,'account':'REAL'})
   self.assertEqual(r.status_code,202);self.assertEqual(r.json['amount'],100);self.assertEqual(r.json['scope'],'PRACTICE_AUTOMATIC');self.assertEqual(thread.call_args.kwargs['args'][2],'MAJORS-OTC')
   self.assertEqual(c.get('/health').json['trade_amount'],100)
 def test_basket_cannot_be_used_as_a_manual_order_and_request_size_is_ignored(self):
  import app,os,base64
  with tempfile.TemporaryDirectory() as folder,patch.object(session,'DB',folder+'/session'),patch.object(app,'STATE_DB',folder+'/panel'),patch.object(app,'HOLD_FILE',folder+'/hold'),patch.dict(os.environ,{'PANEL_PASSWORD':'qa','IQ_EMAIL':'demo','IQ_PASSWORD':'demo'}),patch.object(app.threading,'Thread') as thread:
   c=app.app.test_client();headers={'Authorization':'Basic '+base64.b64encode(b'isaac:qa').decode(),'X-Demo-Panel':'1'}
   self.assertEqual(c.post('/demo-order',headers=headers,json={'pair':'MAJORS'}).status_code,400);thread.assert_not_called()
   r=c.post('/demo-order',headers=headers,json={'pair':'USDCHF-OTC','amount':9999,'account':'REAL','direction':'put'})
   self.assertEqual(r.status_code,202);self.assertEqual(r.json['amount'],100);self.assertEqual(r.json['account'],'PRACTICE')
if __name__=='__main__':unittest.main()
