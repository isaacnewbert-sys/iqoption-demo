"""Explicitly started PRACTICE session. Fixed baseline, own realized P/L ledger."""
import json,sqlite3,time,uuid,threading
from decimal import Decimal
from profit_exit import number
MAX_OPEN_POSITIONS=3
DB='/tmp/iq-auto-session-v1.sqlite3'
def change(fn=None):
 with sqlite3.connect(DB,timeout=3) as db:
  db.execute('CREATE TABLE IF NOT EXISTS session (id INTEGER PRIMARY KEY,payload TEXT NOT NULL)');db.execute('BEGIN IMMEDIATE')
  row=db.execute('SELECT payload FROM session WHERE id=1').fetchone();s=json.loads(row[0]) if row else {}
  if fn:fn(s)
  db.execute('INSERT OR REPLACE INTO session VALUES(1,?)',(json.dumps(s),))
 return s

def claim(pair):
 token=uuid.uuid4().hex
 def f(s):
  if s.get('active') or s.get('uncertain') or s.get('submission_pending') or s.get('target_reached'):raise RuntimeError('Sessão ativa, incerta ou meta já atingida')
  if s.get('pair') and s['pair']!=pair:raise RuntimeError('Retome a sessão no mesmo ativo')
  s.setdefault('uncertain',False)
  s.update(token=token,pair=pair,active=True,stop=False,max_positions=MAX_OPEN_POSITIONS)
 change(f);return token

def update(token,**values):
 def f(s):
  if s.get('token')==token:s.update(values)
 return change(f)

def stopped(token):
 s=change();return s.get('token')!=token or s.get('stop',False)

def establish(token,balance,balance_id):
 n=number(balance)
 if n is None or n<1:raise RuntimeError('Saldo inválido')
 s=change()
 if s.get('balance_id') not in (None,balance_id):raise RuntimeError('Conta mudou')
 if 'initial_balance' not in s:s=update(token,initial_balance=str(n),target=str(n*Decimal('.01')),realized='0',balance_id=balance_id,ledger=[])
 return s

def settle(token,result):
 pnl=number(result.get('broker_pnl_realized'));oid=result.get('order_id')
 if result.get('monitor_status') not in ('POSICAO_ENCERRADA','FECHAMENTO_ANTECIPADO_CONFIRMADO') or pnl is None or not oid:raise RuntimeError('Encerramento ou lucro não confirmado')
 def f(s):
  if s.get('token')!=token:raise RuntimeError('Sessão mudou')
  if any(t['order_id']==oid for t in s.get('ledger',[])):return
  ledger=s.get('ledger',[])+[{'order_id':oid,'pnl':str(pnl),'direction':result.get('direction'),'setup':result.get('setup'),'regime':result.get('regime')}]
  realized=sum((Decimal(t['pnl']) for t in ledger),Decimal(0))
  s.update(ledger=ledger,realized=str(realized),target_reached=bool(s.get('target_reached')) or realized>=Decimal(s['target']))
 return change(f)

def bounded_history(client):
 client.api.candles.candles_data=None
 client.api.getcandles(client.trace.asset_id,60,120,int(client.api.timesync.server_timestamp))
 end=time.monotonic()+6
 while client.api.candles.candles_data is None and time.monotonic()<end:time.sleep(.05)
 rows=client.api.candles.candles_data
 return rows if isinstance(rows,list) else []

def no_positions(client):
 client.api.positions=None;client.api.get_positions('digital-option')
 end=time.monotonic()+5
 while client.api.positions is None and time.monotonic()<end:time.sleep(.05)
 r=client.api.positions
 return isinstance(r,dict) and r.get('status')==2000 and isinstance(r.get('msg'),dict) and r['msg'].get('positions')==[]

def demo_balance(client):
 if client.get_balance_mode()!='PRACTICE':raise RuntimeError('Conta não demonstrativa')
 bid=client.get_balance_id();client.api.balances_raw=None;client.api.get_balances()
 end=time.monotonic()+5
 while client.api.balances_raw is None and time.monotonic()<end:time.sleep(.05)
 response=client.api.balances_raw
 if not isinstance(response,dict) or not isinstance(response.get('msg'),list):raise RuntimeError('Saldo não confirmado')
 row=next((r for r in response['msg'] if r.get('id')==bid and r.get('type')==4),None)
 if not row:raise RuntimeError('Saldo demonstrativo não confirmado')
 return row['amount'],bid

class TrackerGroup:
 """Fan out account events; each tracker accepts only its mapped order/position."""
 def __init__(self):self.trackers=[];self.lock=threading.RLock()
 def add(self,tracker):
  with self.lock:self.trackers.append(tracker)
 def remove(self,tracker):
  with self.lock:
   if tracker in self.trackers:self.trackers.remove(tracker)
 def receive(self,event):
  with self.lock:trackers=list(self.trackers)
  for tracker in trackers:tracker.receive(event)
 def open_positions(self):
  with self.lock:trackers=list(self.trackers)
  return [dict(t.position) for t in trackers if t.position and t.position.get('status')=='open']
 def position_ids(self):return [p['id'] for p in self.open_positions()]

class PositionBook:
 MAX=MAX_OPEN_POSITIONS
 def __init__(self):self.rows={};self.lock=threading.RLock()
 def active(self):
  with self.lock:return [dict(r['result']) for r in self.rows.values() if not r['done']]
 def can_enter(self,direction):
  positions=self.active()
  return len(positions)<self.MAX and all(r.get('direction')==direction for r in positions)
 def add(self,entry):
  with self.lock:
   if entry['order_id'] in self.rows or not self.can_enter(entry['direction']):raise RuntimeError('Limite, ordem duplicada ou direção conflitante')
   self.rows[entry['order_id']]={'result':dict(entry),'done':False}
 def update(self,oid,result,done=False):
  with self.lock:self.rows[oid]={'result':dict(result),'done':done}
 def snapshot(self):
  with self.lock:return [dict(r['result'],monitor_finished=r['done']) for r in self.rows.values()][-20:]

def run_session(client,pair,token,progress,emit):
 from probe import inspect_client,send_demo_test
 from profit_exit import monitor_profit,ProfitTracker
 from strategy import analyze
 outcome={'account':'PRACTICE','automatic_demo':True,'orders_sent':0,'max_positions':MAX_OPEN_POSITIONS,'requested_pair':pair};history=[]
 group=TrackerGroup();book=PositionBook();threads=[];publication=threading.RLock();client.trace.profit_tracker=group
 original_send=getattr(client.api,'send_websocket_request',None);wire_lock=threading.RLock()
 if callable(original_send):
  def serialized_send(*args,**kwargs):
   with wire_lock:return original_send(*args,**kwargs)
  client.api.send_websocket_request=serialized_send
 fields=('initial_balance','target','realized','target_reached','active','stop','uncertain','submission_pending','max_positions')
 def publish(**extra):
  with publication:
   if 'analysis' in extra:outcome['analysis']=extra['analysis']
   if 'last_entry' in extra:outcome['last_entry']=extra['last_entry']
   s=change();emit(dict(outcome,positions=book.snapshot(),open_positions=len(book.active()),session={k:s.get(k) for k in fields},**extra))
 def watch(entry,tracker,analysis):
  try:
   result=monitor_profit(client,entry,progress,lambda r:(book.update(entry['order_id'],r),publish()),tracker=tracker,position_ids_provider=group.position_ids)
   settle(token,result);book.update(entry['order_id'],result,done=True)
  except Exception:
   update(token,uncertain=True,stop=True)
   book.update(entry['order_id'],dict(entry,monitor_status='ENCERRAMENTO_INCERTO_CONFIRA_IQ'),done=True)
  finally:
   group.remove(tracker);publish()
 try:
  inspect_client(client,pair,progress)
  outcome['pair']=getattr(client.trace,'pair',pair);outcome['asset_id']=client.trace.asset_id
  if not no_positions(client):
   outcome['blocking_reason']='POSICAO_DIGITAL_PREVIA_OU_CONSULTA_NAO_CONFIRMADA'
   raise RuntimeError('Posições prévias ou não confirmadas')
  balance,bid=demo_balance(client);establish(token,balance,bid)
  deadline=time.monotonic()+21600;last_history=0;history=[];used=set(change().get('used_signals',[]));last_trade=0
  if change().get('last_signal'):used.add(change()['last_signal'])
  while time.monotonic()<deadline and not stopped(token):
   s=change()
   if s.get('target_reached') or s.get('uncertain'):break
   if client.get_balance_mode()!='PRACTICE' or client.get_balance_id()!=bid:raise RuntimeError('Conta mudou')
   now=client.api.timesync.server_timestamp
   if time.monotonic()-last_history>=20:
    history=bounded_history(client);last_history=time.monotonic()
   live=list(client.trace.strategy_candles.values())
   if not live or time.monotonic()-client.trace.strategy_received>3:analysis={'direction':None,'reason':'Cotação de vela atrasada ou formato ainda não confirmado'}
   else:analysis=analyze(history+live,now)
   now_mono=time.monotonic()
   outcome['feed']={'history_bars_received':len(history),'live_bars_received':len(live),'live_age_seconds':round(now_mono-client.trace.strategy_received,2) if client.trace.strategy_received else None,'candle_events':getattr(client.trace,'strategy_events',None),'rejected_candle_events':getattr(client.trace,'strategy_rejected',None),'candle_fields':getattr(client.trace,'strategy_schema',[])}
   eligible=book.can_enter(analysis.get('direction'))
   outcome['execution_checks']={'signal_present':bool(analysis.get('direction')),'new_signal':analysis.get('signal_id') not in used,'cooldown_seconds_remaining':max(0,round(60-(now_mono-last_trade),1)),'capacity_and_direction':eligible,'session_target_reached':bool(s.get('target_reached')),'uncertain':bool(s.get('uncertain'))}
   progress('Analisando: '+analysis['reason']+(' · limite ou direção conflitante' if not eligible else ''));publish(analysis=analysis)
   if analysis.get('direction') and analysis.get('signal_id') not in used and time.monotonic()-last_trade>=60 and eligible:
    inspect_client(client,pair,progress)
    fresh=analyze(bounded_history(client)+list(client.trace.strategy_candles.values()),client.api.timesync.server_timestamp)
    if stopped(token):break
    if time.monotonic()-client.trace.strategy_received>3 or fresh.get('signal_id')!=analysis['signal_id']:continue
    available,current_bid=demo_balance(client)
    if current_bid!=bid or number(available) is None or number(available)<1:raise RuntimeError('Saldo insuficiente ou conta mudou')
    update(token,submission_pending=True)
    tracker=ProfitTracker(bid,client.trace.asset_id);group.add(tracker)
    def entry_guard():
     latest=analyze(history+list(client.trace.strategy_candles.values()),client.api.timesync.server_timestamp)
     state=change()
     return not stopped(token) and not state.get('target_reached') and not state.get('uncertain') and book.can_enter(fresh['direction']) and time.monotonic()-client.trace.strategy_received<=3 and latest.get('signal_id')==fresh['signal_id']
    entry=send_demo_test(client,take_profit_8=True,direction=fresh['direction'],entry_guard=entry_guard,tracker=tracker,allowed_positions=group.open_positions)
    used.add(fresh['signal_id']);last_trade=time.monotonic();update(token,last_signal=fresh['signal_id'],used_signals=sorted(used)[-500:])
    entry.update(setup=fresh.get('setup'),regime=fresh.get('regime'),trigger=fresh.get('trigger'))
    if entry.get('order_status')=='ORDEM_DEMO_CONFIRMADA':
     tracker.bind(entry['order_id']);book.add(entry);update(token,submission_pending=False)
     outcome['orders_sent']+=1
     thread=threading.Thread(target=watch,args=(dict(entry),tracker,dict(fresh)),daemon=True);threads.append(thread);thread.start();publish(analysis=fresh)
     client.trace.order_attempted=False;client.trace.order_reply=None;client.trace.order_request_id=None
    elif entry.get('order_attempted') and entry.get('orders_sent') is None:
     group.remove(tracker);update(token,uncertain=True,submission_pending=False);raise RuntimeError('Envio incerto')
    else:
     group.remove(tracker);update(token,submission_pending=False);publish(last_entry=entry)
   time.sleep(2)
  outcome['automation_status']='META_ATINGIDA' if change().get('target_reached') else 'SESSAO_PAUSADA'
 except Exception:
  if change().get('submission_pending'):update(token,uncertain=True,submission_pending=False)
  outcome['automation_status']='INTERROMPIDA_CONFIRA_PAINEL_E_IQ'
 finally:
  # No new entries after stop/target; every accepted position keeps its own +8% monitor.
  while any(t.is_alive() for t in threads):
   progress('Novas entradas pausadas · acompanhando posições abertas até +8% ou vencimento');publish()
   for t in threads:t.join(timeout=.2)
  if change().get('uncertain'):outcome['automation_status']='INTERROMPIDA_CONFIRA_PAINEL_E_IQ'
  elif change().get('target_reached'):outcome['automation_status']='META_ATINGIDA'
  if callable(original_send):client.api.send_websocket_request=original_send
  update(token,active=False);publish()
 outcome['session']={k:change().get(k) for k in fields};outcome['positions']=book.snapshot()
 return outcome
