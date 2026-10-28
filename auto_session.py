"""Explicitly started PRACTICE session. Fixed baseline, own realized P/L ledger."""
import json,sqlite3,time,uuid
from decimal import Decimal
from profit_exit import number
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
  if s.get('active') or s.get('uncertain') or s.get('target_reached'):raise RuntimeError('Sessão ativa, incerta ou meta já atingida')
  if s.get('pair') and s['pair']!=pair:raise RuntimeError('Retome a sessão no mesmo ativo')
  s.update(token=token,pair=pair,active=True,stop=False)
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
  ledger=s.get('ledger',[])+[{'order_id':oid,'pnl':str(pnl),'direction':result.get('direction')}]
  realized=sum((Decimal(t['pnl']) for t in ledger),Decimal(0))
  s.update(ledger=ledger,realized=str(realized),target_reached=realized>=Decimal(s['target']),uncertain=False)
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

def run_session(client,pair,token,progress,emit):
 from probe import inspect_client,send_demo_test
 from profit_exit import monitor_profit
 from strategy import analyze
 outcome={'account':'PRACTICE','automatic_demo':True,'orders_sent':0}
 def publish(**extra):
  s=change();emit(dict(outcome,session={k:s.get(k) for k in ('initial_balance','target','realized','target_reached','active','stop','uncertain')},**extra))
 try:
  inspect_client(client,pair,progress)
  if not no_positions(client):raise RuntimeError('Posições prévias ou não confirmadas')
  balance,bid=demo_balance(client);establish(token,balance,bid)
  deadline=time.monotonic()+21600;last_history=0;history=[];last_signal=change().get('last_signal');last_trade=0
  while time.monotonic()<deadline and not stopped(token):
   s=change()
   if s.get('target_reached'):break
   if client.get_balance_mode()!='PRACTICE' or client.get_balance_id()!=bid:raise RuntimeError('Conta mudou')
   now=client.api.timesync.server_timestamp
   if time.monotonic()-last_history>=20:
    history=bounded_history(client);last_history=time.monotonic()
   live=list(client.trace.strategy_candles.values())
   if not live or time.monotonic()-client.trace.strategy_received>3:
    analysis={'direction':None,'reason':'Cotação de vela atrasada ou formato ainda não confirmado'}
   else:analysis=analyze(history+live,now)
   progress('Analisando: '+analysis['reason']);publish(analysis=analysis)
   if analysis.get('direction') and analysis.get('signal_id')!=last_signal and time.monotonic()-last_trade>=60:
    # Refresh broker catalogue/contracts before each entry, then reassess live signal.
    inspect_client(client,pair,progress)
    fresh=analyze(bounded_history(client)+list(client.trace.strategy_candles.values()),client.api.timesync.server_timestamp)
    if stopped(token):break
    if time.monotonic()-client.trace.strategy_received>3 or fresh.get('signal_id')!=analysis['signal_id']:continue
    available,current_bid=demo_balance(client)
    if current_bid!=bid or number(available) is None or number(available)<1:raise RuntimeError('Saldo insuficiente ou conta mudou')
    update(token,uncertain=True)
    def entry_guard():
     latest=analyze(history+list(client.trace.strategy_candles.values()),client.api.timesync.server_timestamp)
     return not stopped(token) and not change().get('target_reached') and time.monotonic()-client.trace.strategy_received<=3 and latest.get('signal_id')==fresh['signal_id']
    entry=send_demo_test(client,take_profit_8=True,direction=fresh['direction'],entry_guard=entry_guard)
    last_signal=fresh['signal_id'];last_trade=time.monotonic();update(token,last_signal=last_signal)
    if entry.get('order_status')=='ORDEM_DEMO_CONFIRMADA':
     outcome.update(entry);publish(analysis=fresh)
     result=monitor_profit(client,entry,progress,lambda r:publish(trade=r,analysis=fresh))
     settle(token,result);outcome.update(result);publish(analysis=fresh)
     client.trace.order_attempted=False;client.trace.order_reply=None;client.trace.order_request_id=None
    elif entry.get('order_attempted') and entry.get('orders_sent') is None:raise RuntimeError('Envio incerto')
    else:
     update(token,uncertain=False);publish(last_entry=entry)
   time.sleep(2)
  outcome['automation_status']='META_ATINGIDA' if change().get('target_reached') else 'SESSAO_PAUSADA'
 except Exception:
  outcome['automation_status']='INTERROMPIDA_CONFIRA_PAINEL_E_IQ'
 finally:
  update(token,active=False);publish()
 outcome['session']={k:change().get(k) for k in ('initial_balance','target','realized','target_reached','active','stop','uncertain')}
 return outcome
