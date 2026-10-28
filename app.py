import os,secrets,threading,subprocess,sys,json,time,queue,sqlite3,uuid
from flask import Flask,request,Response,jsonify
from pathlib import Path
from probe import VERSION
from auto_session import MAX_OPEN_POSITIONS
app=Flask(__name__)
state={'stage':'Aguardando teste','started_at':None,'running':False,'result':None,'demo_test_orders_enabled':True,'real_orders_enabled':False}
HOLD_FILE='/tmp/iq-demo-test-hold.json'
STATE_DB='/tmp/iq-demo-state-v19.sqlite3'
lock=threading.Lock()
def state_transaction(change=None):
 # One authoritative state for HTTP and background tasks, even after module reload.
 with sqlite3.connect(STATE_DB,timeout=2) as db:
  db.execute('CREATE TABLE IF NOT EXISTS panel (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
  db.execute('BEGIN IMMEDIATE')
  row=db.execute('SELECT payload FROM panel WHERE id=1').fetchone()
  current=json.loads(row[0]) if row else dict(state)
  if change is not None:change(current)
  db.execute('INSERT OR REPLACE INTO panel VALUES(1,?)',(json.dumps(current),))
 return current

def snapshot():
 def reap(current):
  # Only read-only diagnostics can be released by a stale-state watchdog.
  # Demo submissions keep their uncertainty lock and never retry automatically.
  if current.get('running') and not current.get('test_order') and time.time()-current.get('started_at',time.time())>40:
   current.update(running=False,job_id=None,stage='Tempo limite',result={'error':'O diagnóstico excedeu 35 segundos. Atualize o teste de conexão; nenhuma ordem foi solicitada.'})
 current=state_transaction(reap)
 current['elapsed_seconds']=max(0,int(time.time()-current['started_at'])) if current.get('started_at') and current.get('running') else 0
 return current

def begin_job(test_order=False):
 token=uuid.uuid4().hex
 def claim(current):
  if current.get('running'):raise RuntimeError('busy')
  current.update(running=True,result=None,stage='Iniciando conexão',started_at=time.time(),test_order=test_order,job_id=token)
 state_transaction(claim)
 return token

def update_job(token,**values):
 def change(current):
  if current.get('job_id')==token:current.update(values)
 state_transaction(change)

@app.before_request
def protect():
 if request.path=='/health':return
 if request.path=='/release-demo-test' and request.method=='POST':
  # Temporary capability: one fixed-size PRACTICE test, expires and cannot change scope.
  cap=os.environ.get('DEMO_RELEASE_TEST_TOKEN','')
  try:remaining=float(os.environ.get('DEMO_RELEASE_TEST_EXPIRES','0'))-time.time()
  except ValueError:remaining=0
  if not cap or not 0<remaining<=600 or not secrets.compare_digest(request.headers.get('X-Demo-Release-Test',''),cap):return Response('Unauthorized',401)
  return
 key=os.environ.get('PANEL_PASSWORD','')
 if not key:return Response('Configure PANEL_PASSWORD no Render. Painel bloqueado.',503)
 auth=request.authorization
 if not auth or auth.username!='isaac' or not secrets.compare_digest(auth.password or '',key):return Response('Autenticação necessária',401,{'WWW-Authenticate':'Basic realm="IQ Demo"'})
 if request.method=='POST' and request.headers.get('X-Demo-Panel')!='1':return Response('Forbidden',403)
@app.after_request
def headers(r):
 r.headers['Cache-Control']='no-store';r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY';r.headers['Referrer-Policy']='no-referrer';return r
@app.get('/health')
def health():
 current=snapshot()
 return {'ok':True,'orders_enabled':True,'orders_scope':'PRACTICE_DEMO_ONLY','automatic_demo_available':True,'max_positions':MAX_OPEN_POSITIONS,'demo_test_orders_enabled':True,'real_orders_enabled':False,'probe_version':VERSION,'panel_version':'v27-dashboard','diagnostic_running':current['running'],'diagnostic_completed':current['result'] is not None}
@app.get('/')
def index():
 return Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8').replace('__MAX_POSITIONS__',str(MAX_OPEN_POSITIONS))
@app.get('/status')
def status():
 current=snapshot()
 from auto_session import change
 session=change()
 current['session']={k:session.get(k) for k in ('initial_balance','target','realized','target_reached','active','stop','uncertain','submission_pending','max_positions','pair')}
 current['journal']=[{k:r.get(k) for k in ('order_id','direction','pnl','setup','regime')} for r in session.get('ledger',[])[-20:]]
 current['trades_completed']=len(session.get('ledger',[]))
 return jsonify(current)
def run_process(args,timeout,job_id=None):
 """Stream only structured progress; kill the SDK child on the wall-clock deadline."""
 p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
 lines=queue.Queue()
 def read_lines():
  try:
   for line in p.stdout:lines.put(line)
  finally:lines.put(None)
 threading.Thread(target=read_lines,daemon=True).start()
 deadline=time.monotonic()+timeout
 result=None
 last_trade_log=0
 last_message=time.monotonic()
 try:
  while True:
   remaining=deadline-time.monotonic()
   if '--automation-token' in args and time.monotonic()-last_message>45:raise subprocess.TimeoutExpired(args,45)
   if remaining<=0:raise subprocess.TimeoutExpired(args,timeout)
   try:line=lines.get(timeout=min(remaining,.25))
   except queue.Empty:continue
   if line is None:break
   try:message=json.loads(line)
   except (ValueError,TypeError):continue
   if isinstance(message,dict) and ('progress' in message or 'trade_update' in message):last_message=time.monotonic()
   if isinstance(message,dict) and isinstance(message.get('progress'),str):
    if job_id:update_job(job_id,stage=message['progress'][:200])
    else:state['stage']=message['progress'][:200]
   elif isinstance(message,dict) and isinstance(message.get('trade_update'),dict):
    trade=message['trade_update']
    if job_id:update_job(job_id,result={'result':trade,'demo_test_orders_enabled':True,'real_orders_enabled':False})
    if time.monotonic()-last_trade_log>=10:
     print('IQ_TP8_UPDATE '+json.dumps({k:trade.get(k) for k in ('order_id','order_status','monitor_status','broker_sell_profit','broker_pnl_net','broker_pnl','net_profit','profit_pct','trigger_profit_pct','close_attempts','early_sell_verified')}),flush=True)
     if isinstance(trade.get('positions'),list):print('IQ_MULTI_POSITION_UPDATE '+json.dumps({'open_positions':trade.get('open_positions'),'positions':[{k:p.get(k) for k in ('order_id','direction','monitor_status','profit_pct','broker_pnl_realized','monitor_finished')} for p in trade['positions'][-20:]],'session':{k:trade.get('session',{}).get(k) for k in ('realized','target_reached','uncertain')}}),flush=True)
     if trade.get('automatic_demo'):print('IQ_ANALYSIS '+json.dumps({k:trade.get(k) for k in ('requested_pair','pair','asset_id','analysis','feed','execution_checks','last_entry','blocking_reason','open_positions')}),flush=True)
     last_trade_log=time.monotonic()
   elif isinstance(message,dict) and 'result' in message:result=message
  p.wait(timeout=max(.01,deadline-time.monotonic()))
  if p.returncode!=0 or result is None:return {'error':'Processo interrompido; resultado não confirmado.'}
  return result
 finally:
  if p.poll() is None:p.kill()
  try:p.wait(timeout=2)
  except subprocess.TimeoutExpired:pass
  if p.stdout:p.stdout.close()

def job(test_order=False,job_id=None,pair="EURUSD",take_profit_8=False,direction="call",automation_token=None):
 try:
  args=[sys.executable,'runner.py','--pair',pair,'--direction',direction]+(['--demo-test-order'] if test_order else [])+(['--take-profit-8'] if take_profit_8 else [])
  if automation_token:args+=['--automation-token',automation_token]
  result=run_process(args,22300 if automation_token else 700 if take_profit_8 else (65 if test_order else 35),job_id)
 except subprocess.TimeoutExpired:
  last_stage=snapshot()['stage']
  result={'error':'Tempo limite de '+str(700 if take_profit_8 else (65 if test_order else 35))+' segundos na etapa: '+last_stage+'. Processo encerrado.'}
 except Exception:result={'error':'Falha no diagnóstico; detalhes omitidos para preservar credenciais.'}
 if automation_token and 'error' in result:
  from auto_session import update
  update(automation_token,active=False,uncertain=True)
 if test_order and 'error' in result:
  partial=snapshot().get('result')
  if isinstance(partial,dict) and isinstance(partial.get('result'),dict) and (partial['result'].get('order_id') or partial['result'].get('positions')):
   partial['result'].update(monitor_status='MONITORAMENTO_INTERROMPIDO_CONFIRA_A_IQ',monitor_error=result['error'])
   result=partial
 if test_order and 'error' in result:
  result.update(error='Não foi possível confirmar o resultado. Confira a conta PRACTICE antes de repetir.',order_status='ENVIO_INCERTO_NAO_REPETIR',orders_sent=None)
 # Publish completion BEFORE writing logs, which may be slow or unavailable.
 if job_id:update_job(job_id,running=False,result=result,stage='Concluído')
 else:state.update(running=False,result=result,stage='Concluído')
 # Emit fixed diagnostic fields only; never credentials, auth payloads or raw errors.
 inner=result.get('result',{}) if isinstance(result,dict) else {}
 ws=inner.get('websocket',{})
 print('IQ_DEMO_DIAGNOSTIC '+json.dumps({
  'probe_version':inner.get('probe_version',VERSION),
  'status':inner.get('status','DIAGNOSTICO_INTERROMPIDO'),
  'login_confirmed':inner.get('login_confirmed',False),
  'contracts_verified':inner.get('contracts_verified',False),
  'underlying_price_received':inner.get('underlying_price_received',False),
  'catalog_received':ws.get('catalog_received',False),
  'catalog_match':ws.get('catalog_match'),
  'catalog_asset_count':len(ws.get('catalog_assets',[])),
  'eurusd_catalog_assets':[a for a in ws.get('catalog_assets',[]) if a['name'].startswith('EURUSD')],
  'pair':inner.get('pair'),
  'instruments_received':ws.get('instruments_received',False),
  'instruments_raw_count':ws.get('instruments_raw_count',0),
  'instrument_schema':ws.get('instrument_schema',[]),
  'instruments':ws.get('instruments',[]),
  'received_frames':ws.get('received_frames',0),
  'market_packet_count':len(ws.get('price_splitter_packets',[])),
  'event_counts':ws.get('event_counts',{}),
  'market_request_responses':ws.get('subscription_responses',[]),
  'orders_sent':inner.get('orders_sent'),
  'order_status':inner.get('order_status',result.get('order_status')),
  'order_id':inner.get('order_id'),
  'monitor_status':inner.get('monitor_status'),
  'early_sell_verified':inner.get('early_sell_verified'),
  'profit_pct':inner.get('profit_pct'),
  'trigger_profit_pct':inner.get('trigger_profit_pct'),
  'broker_pnl_realized':inner.get('broker_pnl_realized')}),flush=True)

@app.post('/run')
def run():
 pair=(request.get_json(silent=True) or {}).get('pair','EURUSD')
 if pair not in ('EURUSD','EURUSD-OTC'):return Response('Ativo inválido.',400)
 if not os.environ.get('IQ_EMAIL') or not os.environ.get('IQ_PASSWORD'):return Response('Configure IQ_EMAIL e IQ_PASSWORD no Render.',409)
 with lock:
  snapshot()
  try:token=begin_job(False)
  except RuntimeError:return Response('Já existe um teste em andamento.',409)
 threading.Thread(target=job,args=(False,token,pair),daemon=True).start();return {'started':True,'orders_enabled':False},202

@app.post('/demo-order')
def demo_order():
 pair=(request.get_json(silent=True) or {}).get('pair','EURUSD')
 if pair not in ('EURUSD','EURUSD-OTC'):return Response('Ativo inválido.',400)
 direction=(request.get_json(silent=True) or {}).get('direction','call')
 if direction not in ('call','put'):return Response('Direção inválida.',400)
 return schedule_demo_order(pair,direction)

def schedule_demo_order(pair,direction="call"):
 from auto_session import change
 session=change()
 if session.get('target_reached') or session.get('uncertain') or session.get('active'):return Response('Sessão ativa, incerta ou meta de 1% atingida. Novas entradas manuais bloqueadas.',409)
 if direction not in ('call','put'):return Response('Direção inválida.',400)
 if not all(os.environ.get(k) for k in ('IQ_EMAIL','IQ_PASSWORD')):return Response('Configure as credenciais no Render.',409)
 with lock:
  if snapshot()['running']:return Response('Aguarde a conclusão do teste em andamento.',409)
  try:
   with open(HOLD_FILE) as f:hold=json.load(f).get('until',0)
  except FileNotFoundError:hold=0
  except Exception:return Response('Trava de repetição indisponível. Envio bloqueado.',409)
  if time.time()<hold:return Response('Teste já solicitado. Confira a IQ antes de repetir; aguarde 11 minutos.',409)
  # Hold is committed BEFORE launching, including for transport errors and lost acknowledgements.
  with open(HOLD_FILE+'.new','w') as f:json.dump({'until':time.time()+660},f)
  os.replace(HOLD_FILE+'.new',HOLD_FILE)
  try:token=begin_job(True)
  except RuntimeError:return Response('Já existe um teste em andamento.',409)
 threading.Thread(target=job,args=(True,token,pair,True,direction),daemon=True).start()
 return {'started':True,'account':'PRACTICE','amount':1,'direction':direction,'real_orders_enabled':False},202

@app.post('/automation/start')
def automation_start():
 from auto_session import claim
 pair=(request.get_json(silent=True) or {}).get('pair','EURUSD')
 if pair not in ('EURUSD','EURUSD-OTC'):return Response('Ativo inválido.',400)
 if not all(os.environ.get(k) for k in ('IQ_EMAIL','IQ_PASSWORD')):return Response('Configure credenciais.',409)
 with lock:
  if snapshot()['running']:return Response('Já existe operação ou diagnóstico em andamento.',409)
  try:
   with open(HOLD_FILE) as f:hold=json.load(f).get('until',0)
  except FileNotFoundError:hold=0
  except Exception:return Response('Trava indisponível.',409)
  if time.time()<hold:return Response('Aguarde a trava do último teste manual.',409)
  try:session_token=claim(pair)
  except RuntimeError:return Response('Sessão bloqueada: ativa, incerta, meta atingida ou ativo diferente.',409)
  token=begin_job(True)
 threading.Thread(target=job,args=(True,token,pair,True,'call',session_token),daemon=True).start()
 return {'started':True,'scope':'PRACTICE_AUTOMATIC','amount':1,'target_session_pct':1,'target_trade_pct':8,'max_positions':MAX_OPEN_POSITIONS},202

@app.post('/automation/new')
def automation_new():
 from auto_session import change
 with lock:
  if snapshot()['running']:return Response('Aguarde a operação terminar.',409)
  def clear(s):
   if s.get('active') or s.get('uncertain') or s.get('submission_pending'):raise RuntimeError('busy')
   s.clear()
  try:change(clear)
  except RuntimeError:return Response('Sessão ativa ou incerta: confira a IQ.',409)
 return {'new_session_ready':True,'initial_balance':'Será registrado ao iniciar'},200

@app.post('/automation/stop')
def automation_stop():
 from auto_session import change
 change(lambda s:s.update(stop=True))
 return {'stop_requested':True,'open_position':'Continua até +8% ou vencimento'},202

@app.post('/release-demo-test')
def release_demo_test():
 def consume(current):
  if current.get('release_test_consumed') or current.get('running'):raise RuntimeError('consumed_or_busy')
  current['release_test_consumed']=True
 try:state_transaction(consume)
 except RuntimeError:return Response('Teste já consumido ou outro teste em andamento.',409)
 return schedule_demo_order('EURUSD-OTC')

# Opening the panel never starts a connection or an order.


def market_preflight():
 """Read-only release check; never invokes a demo order or changes panel job state."""
 for pair in ('EURUSD','EURUSD-OTC'):
  try:
   data=run_process([sys.executable,'runner.py','--pair',pair],35,job_id='release-preflight')
   result=data.get('result',{})
   ws=result.get('websocket',{})
   summary={'pair':result.get('pair',pair),'contracts_verified':result.get('contracts_verified',False),'instrument_count':ws.get('instruments_raw_count',0),'order_sent':False,'contracts':result.get('contracts',[]),'parser_errors':ws.get('parser_exceptions',{}),'analysis':result.get('analysis')}
  except Exception:summary={'pair':pair,'status':'READ_ONLY_CHECK_FAILED','order_sent':False}
  print('IQ_MARKET_PREFLIGHT '+json.dumps(summary),flush=True)

# Market discovery is read-only and independent of the manual order endpoint.
try:release_cap_active=bool(os.environ.get('DEMO_RELEASE_TEST_TOKEN')) and float(os.environ.get('DEMO_RELEASE_TEST_EXPIRES','0'))>time.time()
except ValueError:release_cap_active=False
if __name__=='app' and not release_cap_active and all(os.environ.get(k) for k in ('IQ_EMAIL','IQ_PASSWORD')):
 threading.Thread(target=market_preflight,daemon=True).start()
