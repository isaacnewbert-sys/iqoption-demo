"""Six concurrent market streams, one demo wallet and causal per-entry ranking."""
import time,threading,uuid
from settings import basket_pairs,TRADE_AMOUNT,MAX_OPEN_POSITIONS
from strategy import analyze,candle
from profit_exit import ProfitTracker,monitor_profit,number
from auto_session import change,update,establish,settle,stopped,demo_balance,no_positions,TrackerGroup,PositionBook

class Market:
 def __init__(self,requested,trace=None):
  self.requested=requested;self.trace=trace;self.history=[];self.history_received=0;self.history_rid=None
  self.last_history=float('-inf');self.last_instruments=float('-inf');self.subscribed=set();self.refresh_error=False

class MarketHub:
 def __init__(self,client,mode):
  self.client=client;self.root=client.trace;self.mode=mode;self.markets={p:Market(p) for p in basket_pairs(mode)}
  self.root.market_hub=self;self.blocking_reason=None
 def receive(self,event):
  rid=str(event.get('request_id',''));body=event.get('msg')
  for market in list(self.markets.values()):
   trace=market.trace
   if trace is None:continue
   trace.receive(event)
   if rid==market.history_rid and isinstance(body,dict) and isinstance(body.get('candles'),list):
    if body.get('active_id',trace.asset_id)!=trace.asset_id:continue
    bars=[c for row in body['candles'] if (c:=candle(row)) is not None]
    if bars:market.history=bars[-120:];market.history_received=time.monotonic()
 def bind_catalog(self):
  from probe import WireTrace
  assets=self.root.catalog_assets;seen=set()
  for pair,market in self.markets.items():
   names=(pair,) if pair.endswith('-OTC') else (pair,pair+'-op')
   named=next((a for name in names for a in assets if a['name'].replace('/','')==name),None)
   if named is None or named.get('is_suspended') is True:continue
   aid=named['active_id']
   if isinstance(aid,bool) or not isinstance(aid,int) or aid<=0 or aid in seen:continue
   seen.add(aid)
   trace=WireTrace();trace.request_id=self.root.request_id+'-market-'+str(named['active_id']);trace.asset_id=named['active_id'];trace.pair=named['name'];trace.catalog_match=named;trace.catalog_received=True;trace.secrets=self.root.secrets
   market.trace=trace
 def bootstrap(self,progress):
  c=self.client;c.change_balance('PRACTICE')
  if c.get_balance_mode()!='PRACTICE':self.blocking_reason='CONTA_DEMO_NAO_CONFIRMADA';raise RuntimeError('Demo account required')
  progress('Consultando catálogo para os seis pares')
  c.api.send_websocket_request('sendMessage',{'name':'digital-option-instruments.get-underlying-list','version':'3.0','body':{'filter_suspended':True}},request_id=self.root.request_id+'-catalog')
  deadline=time.monotonic()+6
  while not self.root.catalog_received and time.monotonic()<deadline:time.sleep(.05)
  if not self.root.catalog_received:self.blocking_reason='CATALOGO_DIGITAL_NAO_CONFIRMADO';raise RuntimeError('Catalogue not confirmed')
  import iqoptionapi.constants as constants
  for asset in self.root.catalog_assets:constants.ACTIVES[asset['name']]=asset['active_id']
  self.bind_catalog()
  for market in self.markets.values():
   if market.trace is None:continue
   t=market.trace
   c.api.send_websocket_request('subscribeMessage',{'name':'candle-generated','params':{'routingFilters':{'active_id':str(t.asset_id),'size':60}}},request_id=t.request_id+'-candles')
   c.api.send_websocket_request('subscribeMessage',{'name':'digital-option-instruments.instrument-generated','version':'3.0','params':{'routingFilters':{'asset_id':t.asset_id}}},request_id=t.request_id+'-generated')
  self.refresh(force=True)
  deadline=time.monotonic()+9
  while time.monotonic()<deadline:
   self.refresh();ready=[m for m in self.markets.values() if m.trace]
   if ready and all(m.history_received and m.trace.instruments_received and m.trace.strategy_received for m in ready):break
   progress('Recebendo os seis fluxos de mercado em paralelo');time.sleep(.5)
 def refresh(self,force=False):
  # Issue all requests without waiting for individual replies. No SDK shared history buffer.
  for market in self.markets.values():
   if market.trace is None:continue
   t=market.trace;now=time.monotonic();server_now=self.client.api.timesync.server_timestamp
   try:
    if force or now-market.last_history>=20:
     market.history_rid=t.request_id+'-history-'+uuid.uuid4().hex;market.last_history=now
     self.client.api.send_websocket_request('sendMessage',{'name':'get-candles','version':'2.0','body':{'active_id':t.asset_id,'split_normalization':True,'size':60,'to':int(server_now),'count':120}},request_id=market.history_rid)
    if force or now-market.last_instruments>=25:
     market.last_instruments=now
     self.client.api.send_websocket_request('sendMessage',{'name':'digital-option-instruments.get-instruments','version':'3.0','body':{'asset_id':t.asset_id}},request_id=t.request_id+'-instruments')
    unique={i['index']:i for i in list(t.instruments) if i['period']==300 and 0<i['expiration']-server_now<=600 and i['expiration']-i['deadtime']-server_now>=15}
    for instrument in sorted(unique.values(),key=lambda i:i['expiration'])[:2]:
     key=(instrument['index'],instrument['expiration'])
     if key in market.subscribed:continue
     self.client.api.send_websocket_request('subscribeMessage',{'name':'trading-settings.digital-option-client-price-generated','version':'1.0','params':{'routingFilters':{'instrument_type':'digital-option','asset_id':t.asset_id,'instrument_index':int(instrument['index'])}}},request_id=t.request_id+'-prices')
     market.subscribed.add(key)
    market.refresh_error=False
   except Exception:market.refresh_error=True

def priority(analysis,price,contract=None):
 """An explicit ordering score, NOT a probability of success or calibrated confidence."""
 atr=number(analysis.get('atr'));trigger=number(analysis.get('trigger'));p=number(price)
 if atr is None or atr<=0 or trigger is None or p is None:return None
 atr=float(atr);p=float(p);trigger=float(trigger);eff=max(0,min(1,float(analysis.get('efficiency',0))))
 context=eff if analysis.get('regime','').startswith('TENDENCIA') else 1-eff
 timing=max(0,1-abs(p-trigger)/(.5*atr))
 boundary=analysis.get('resistance') if analysis['direction']=='call' else analysis.get('support')
 boundary=number(boundary);room=(float(boundary)-p if analysis['direction']=='call' else p-float(boundary)) if boundary is not None else 0
 space=min(1,room/(2*atr)) if room>0 else .25
 quote=contract or {};ask=number(quote.get('ask'));bid=number(quote.get('bid'))
 cost=1-min(1,max(0,float((ask-bid)/ask))) if ask is not None and ask>0 and bid is not None else .5
 return round(30+20*context+20*timing+15*space+15*cost,2)

def rank_markets(hub,book,used,now=None):
 from probe import verified_contracts
 server_now=hub.client.api.timesync.server_timestamp if now is None else now;clock=time.monotonic();rows=[]
 for requested,market in hub.markets.items():
  row={'evaluated_at':server_now,'pair':requested,'resolved_pair':market.trace.pair if market.trace else None,'status':'ATIVO_INDISPONIVEL','priority':None,'analysis':None,'signal_key':None,'feed':{}}
  if market.trace:
   t=market.trace;live=list(t.strategy_candles.values());age=clock-t.strategy_received if t.strategy_received else None;history_age=clock-market.history_received if market.history_received else None
   row['feed']={'live_age_seconds':round(age,2) if age is not None else None,'history_age_seconds':round(history_age,2) if history_age is not None else None,'history_bars_received':len(market.history),'live_bars_received':len(live),'candle_events':t.strategy_events,'rejected_candle_events':t.strategy_rejected,'candle_fields':t.strategy_schema}
   contracts=verified_contracts(t,server_now)
   row['analysis']=analyze(market.history+live,server_now)
   a=row['analysis'];key=requested+'|'+str(a.get('signal_id'));row['signal_key']=key
   if market.refresh_error:row['status']='ERRO_ATUALIZACAO'
   elif age is None or age>3 or history_age is None or history_age>35:row['status']='DADOS_ATRASADOS'
   elif not contracts:row['status']='CONTRATO_INDISPONIVEL'
   elif a.get('checks',{}).get('history') is False or a.get('checks',{}).get('continuous_history') is False:row['status']='HISTORICO_INCOMPLETO'
   elif not a.get('direction'):row['status']='SEM_SINAL'
   elif key in used:row['status']='SINAL_UTILIZADO'
   elif not book.can_enter(a['direction'],t.pair):row['status']='LIMITE_OU_DIRECAO'
   else:
    current=max((c for c in live if c['from']<=server_now<c['to']),key=lambda c:c['from'],default=None)
    score=priority(a,current['close'],next((q for q in contracts if q['direction']==a.get('direction')),None)) if current else None
    if score is not None:row.update(status='CANDIDATO',priority=score)
    else:row['status']='DADOS_ATRASADOS'
  rows.append(row)
 return sorted(rows,key=lambda r:(r['priority'] is None,-(r['priority'] or 0),r['pair']))

def inspect_basket(client,mode,progress):
 root=client.trace;hub=MarketHub(client,mode)
 try:
  hub.bootstrap(progress)
  rows=rank_markets(hub,PositionBook(),set())
  return {'account':'PRACTICE','login_confirmed':True,'requested_pair':mode,'pair':mode,'orders_sent':0,'contracts_verified':any(r['status'] not in ('ATIVO_INDISPONIVEL','CONTRATO_INDISPONIVEL','DADOS_ATRASADOS','ERRO_ATUALIZACAO') for r in rows),'ranking':rows,'markets_scanned':6,'amount':TRADE_AMOUNT,'status':'CESTA_ANALISADA_SEM_ORDENS'}
 finally:root.market_hub=None

def run_basket_session(client,mode,token,progress,emit):
 from probe import send_demo_test
 root=client.trace;group=TrackerGroup();book=PositionBook();root.profit_tracker=group;hub=MarketHub(client,mode)
 lock=threading.RLock();wire=threading.RLock();threads=[];original=client.api.send_websocket_request
 def send(*args,**kwargs):
  with wire:return original(*args,**kwargs)
 client.api.send_websocket_request=send
 result={'account':'PRACTICE','automatic_demo':True,'requested_pair':mode,'pair':mode,'orders_sent':0,'amount':TRADE_AMOUNT,'max_positions':MAX_OPEN_POSITIONS,'markets_scanned':6,'ranking':[]}
 fields=('initial_balance','target','realized','target_reached','active','stop','uncertain','submission_pending','max_positions','pair')
 def publish():
  with lock:
   s=change();emit(dict(result,positions=book.snapshot(),open_positions=len(book.active()),session={k:s.get(k) for k in fields}))
 def watch(entry,tracker):
  try:
   closed=monitor_profit(client,entry,progress,lambda r:(book.update(entry['order_id'],r),publish()),tracker=tracker,position_ids_provider=group.position_ids)
   settle(token,closed);book.update(entry['order_id'],closed,done=True)
  except Exception:
   update(token,uncertain=True,stop=True);book.update(entry['order_id'],dict(entry,monitor_status='ENCERRAMENTO_INCERTO_CONFIRA_IQ'),done=True)
  finally:group.remove(tracker);publish()
 try:
  hub.bootstrap(progress)
  if not no_positions(client):result['blocking_reason']='POSICAO_DIGITAL_PREVIA_OU_CONSULTA_NAO_CONFIRMADA';raise RuntimeError('Existing positions')
  balance,bid=demo_balance(client);establish(token,balance,bid)
  used=set(change().get('used_signals',[]));last_trade=float('-inf');deadline=time.monotonic()+21600
  while time.monotonic()<deadline and not stopped(token):
   s=change()
   if s.get('target_reached') or s.get('uncertain'):break
   if client.get_balance_mode()!='PRACTICE' or client.get_balance_id()!=bid:raise RuntimeError('Account changed')
   hub.refresh();rows=rank_markets(hub,book,used);candidates=[r for r in rows if r['status']=='CANDIDATO'];winner=candidates[0] if candidates else None
   preview=winner or next((r for r in rows if r['status'] in ('SEM_SINAL','SINAL_UTILIZADO','LIMITE_OU_DIRECAO')),None)
   with lock:
    result.update(ranking=rows,analysis=preview['analysis'] if preview else {'direction':None,'reason':'Nenhum sinal elegível neste ciclo. Consulte os motivos no radar.'},feed=preview['feed'] if preview else {},analysis_pair=preview['pair'] if preview else None,selected_pair=winner['pair'] if winner else None,execution_checks={'signal_present':bool(winner),'new_signal':bool(winner),'cooldown_seconds_remaining':max(0,round(60-(time.monotonic()-last_trade),1)),'capacity_and_direction':len(book.active())<MAX_OPEN_POSITIONS,'session_target_reached':bool(s.get('target_reached')),'uncertain':bool(s.get('uncertain'))})
   progress('Analisando 6 pares · '+('melhor sinal: '+winner['pair']+' · prioridade '+str(winner['priority']) if winner else 'aguardando sinal elegível'));publish()
   if winner and time.monotonic()-last_trade>=60:
    available,current_bid=demo_balance(client)
    if current_bid!=bid or number(available) is None or number(available)<TRADE_AMOUNT:result['blocking_reason']='SALDO_INSUFICIENTE_PARA_100';break
    # Compare ALL six again immediately before the only order write.
    validated=[None]
    def guard():
     state=change();latest=rank_markets(hub,book,used);ready=[r for r in latest if r['status']=='CANDIDATO']
     valid=not stopped(token) and not state.get('target_reached') and not state.get('uncertain') and bool(ready) and ready[0]['signal_key']==winner['signal_key']
     if valid:validated[0]=ready[0]
     return valid
    market=hub.markets[winner['pair']];tracker=ProfitTracker(bid,market.trace.asset_id,amount=TRADE_AMOUNT);group.add(tracker);update(token,submission_pending=True)
    client.trace=market.trace
    try:entry=send_demo_test(client,take_profit_8=True,direction=winner['analysis']['direction'],entry_guard=guard,tracker=tracker,allowed_positions=group.open_positions)
    finally:client.trace=root
    choice=validated[0] or winner
    entry.update(pair=market.trace.pair,requested_pair=choice['pair'],amount=TRADE_AMOUNT,setup=choice['analysis'].get('setup'),regime=choice['analysis'].get('regime'),priority=choice['priority'],trigger=choice['analysis'].get('trigger'))
    last_trade=time.monotonic()
    if entry.get('order_attempted'):
     used.add(winner['signal_key']);update(token,used_signals=sorted(used)[-1000:])
    if entry.get('order_status')=='ORDEM_DEMO_CONFIRMADA':
     from learning import record_entry
     entry['selection_snapshot']={'priority':choice['priority'],'evaluated_at':choice['evaluated_at'],'markets_compared':6,'feed':choice['feed']}
     entry['memory_recorded']=record_entry(entry,choice['analysis'])
     tracker.bind(entry['order_id']);book.add(entry);update(token,submission_pending=False)
     with lock:result['orders_sent']+=1;result['last_selection']={'pair':winner['pair'],'signal_key':winner['signal_key'],'priority':choice['priority'],'compared_at':choice['evaluated_at'],'markets_compared':6,'rule':'Maior prioridade por contexto, momento, espaço e spread entre os sinais válidos; desempate pelo nome do par'}
     thread=threading.Thread(target=watch,args=(dict(entry),tracker),daemon=True);threads.append(thread);thread.start()
     market.trace.order_attempted=False;market.trace.order_reply=None;market.trace.order_request_id=None
    elif entry.get('order_attempted') and entry.get('orders_sent') is None:
     with lock:result['last_entry']=entry
     update(token,uncertain=True,submission_pending=False);group.remove(tracker);raise RuntimeError('Unknown submission')
    else:
     group.remove(tracker);update(token,submission_pending=False)
     with lock:result['last_entry']=entry
    publish()
   time.sleep(2)
  result['automation_status']='META_ATINGIDA' if change().get('target_reached') else 'SESSAO_PAUSADA'
 except Exception:
  if hub.blocking_reason:result['blocking_reason']=hub.blocking_reason
  if change().get('submission_pending'):update(token,uncertain=True,submission_pending=False)
  result['automation_status']='INTERROMPIDA_CONFIRA_PAINEL_E_IQ'
 finally:
  client.trace=root
  while any(t.is_alive() for t in threads):
   progress('Novas entradas pausadas · acompanhando posições abertas');publish()
   for thread in threads:thread.join(timeout=.2)
  if change().get('uncertain'):result['automation_status']='INTERROMPIDA_CONFIRA_PAINEL_E_IQ'
  elif change().get('target_reached'):result['automation_status']='META_ATINGIDA'
  update(token,active=False);publish();root.market_hub=None;client.api.send_websocket_request=original
 result['session']={k:change().get(k) for k in fields};result['positions']=book.snapshot()
 return result
