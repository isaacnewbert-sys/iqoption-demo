import os,secrets,threading,subprocess,sys,json,time
from flask import Flask,request,Response,jsonify
from probe import VERSION
app=Flask(__name__)
state={'running':False,'result':None,'demo_test_orders_enabled':True,'real_orders_enabled':False}
HOLD_FILE='/tmp/iq-demo-test-hold.json'
lock=threading.Lock()
@app.before_request
def protect():
 if request.path=='/health':return
 key=os.environ.get('PANEL_PASSWORD','')
 if not key:return Response('Configure PANEL_PASSWORD no Render. Painel bloqueado.',503)
 auth=request.authorization
 if not auth or auth.username!='isaac' or not secrets.compare_digest(auth.password or '',key):return Response('Autenticação necessária',401,{'WWW-Authenticate':'Basic realm="IQ Demo"'})
 if request.method=='POST' and request.headers.get('X-Demo-Panel')!='1':return Response('Forbidden',403)
@app.after_request
def headers(r):
 r.headers['Cache-Control']='no-store';r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY';r.headers['Referrer-Policy']='no-referrer';return r
@app.get('/health')
def health():return {'ok':True,'orders_enabled':True,'orders_scope':'PRACTICE_TEST_ONLY','demo_test_orders_enabled':True,'real_orders_enabled':False,'probe_version':VERSION,'diagnostic_running':state['running'],'diagnostic_completed':state['result'] is not None}
@app.get('/')
def index():return '''<!doctype html><html lang="pt-BR"><meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8"><title>IQ Demo</title><style>body{font:16px system-ui;background:#0a1524;color:#e5edf7;max-width:750px;margin:auto;padding:24px}button{padding:16px;background:#27c89c;border:0;border-radius:10px;font:inherit}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#15263d;padding:18px;border-radius:12px}</style><h1>IQ Demo · servidor</h1><p>Conector catálogo v3 · teste inicial automático ao iniciar o servidor.</p><p>Teste de ordem habilitado somente na conta PRACTICE. Envio depende de contrato e cotações válidas. Conta real desativada.</p><p>EUR/USD Digital · grade de vencimentos de 5 minutos · objetivo futuro de saída +8%, sem stop por perda.</p><button onclick="run()">Testar conexão e contratos</button><p><button onclick="demoOrder()">Enviar 1 CALL de teste · saldo virtual</button></p><p>Teste de execução: 1 unidade do saldo virtual, grade de 5 minutos. Sem sinal de estratégia. A operação permanece até o vencimento; saída +8% ainda indisponível. Não repita se o envio ficar incerto.</p><p id="status"></p><pre id="out">Aguardando teste.</pre><p>Credenciais IQ Option somente nas variáveis protegidas do Render. Não são solicitadas nesta página. Resultados temporários são perdidos ao reiniciar. Hospedagem gratuita pode suspender por inatividade; não serve para operação contínua.</p><script>async function refresh(){try{let r=await fetch('/status');if(!r.ok)return;let s=await r.json();document.getElementById('status').textContent=s.running?'Teste em andamento…':'Teste parado';document.getElementById('out').textContent=JSON.stringify(s.result,null,2)}catch{}}async function demoOrder(){let r=await fetch('/demo-order',{method:'POST',headers:{'X-Demo-Panel':'1'}});if(!r.ok)document.getElementById('status').textContent=await r.text();else refresh()}async function run(){let r=await fetch('/run',{method:'POST',headers:{'X-Demo-Panel':'1'}});if(!r.ok)document.getElementById('status').textContent=await r.text();refresh()}setInterval(refresh,3000);refresh()</script></html>'''
@app.get('/status')
def status():
 with lock:return jsonify(dict(state))
def job(test_order=False):
 print('IQ_DEMO_START '+VERSION,flush=True)
 try:
  args=[sys.executable,'runner.py']+(['--demo-test-order'] if test_order else [])
  p=subprocess.run(args,capture_output=True,text=True,timeout=65)
  result=json.loads(p.stdout) if p.returncode==0 else {'error':'Processo interrompido. Nenhuma ordem enviada.'}
 except subprocess.TimeoutExpired:result={'error':'Tempo limite de 65 segundos. Processo encerrado. Nenhuma ordem enviada.'}
 except Exception:result={'error':'Falha no diagnóstico; detalhes omitidos para preservar credenciais.'}
 if test_order and 'error' in result:
  result.update(error='Não foi possível confirmar o resultado. Confira a conta PRACTICE antes de repetir.',order_status='ENVIO_INCERTO_NAO_REPETIR',orders_sent=None)
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
  'order_id':inner.get('order_id')}),flush=True)
 with lock:state.update(running=False,result=result)
@app.post('/run')
def run():
 if not os.environ.get('IQ_EMAIL') or not os.environ.get('IQ_PASSWORD'):return Response('Configure IQ_EMAIL e IQ_PASSWORD no Render.',409)
 with lock:
  if state['running']:return Response('Já existe um teste em andamento.',409)
  state.update(running=True,result=None)
 threading.Thread(target=job,daemon=True).start();return {'started':True,'orders_enabled':False},202

@app.post('/demo-order')
def demo_order():
 if not all(os.environ.get(k) for k in ('IQ_EMAIL','IQ_PASSWORD')):return Response('Configure as credenciais no Render.',409)
 with lock:
  if state['running']:return Response('Aguarde a conclusão do teste em andamento.',409)
  try:
   with open(HOLD_FILE) as f:hold=json.load(f).get('until',0)
  except FileNotFoundError:hold=0
  except Exception:return Response('Trava de repetição indisponível. Envio bloqueado.',409)
  if time.time()<hold:return Response('Teste já solicitado. Confira a IQ antes de repetir; aguarde 11 minutos.',409)
  # Hold is committed BEFORE launching, including for transport errors and lost acknowledgements.
  with open(HOLD_FILE+'.new','w') as f:json.dump({'until':time.time()+660},f)
  os.replace(HOLD_FILE+'.new',HOLD_FILE)
  state.update(running=True,result=None)
 threading.Thread(target=job,args=(True,),daemon=True).start()
 return {'started':True,'account':'PRACTICE','amount':1,'direction':'call','real_orders_enabled':False},202

# Single-worker deployment: one read-only probe per server start when configured.
if all(os.environ.get(k) for k in ('PANEL_PASSWORD','IQ_EMAIL','IQ_PASSWORD')):
 state.update(running=True,result=None)
 threading.Thread(target=job,daemon=True).start()
else:
 print('IQ_DEMO_SETUP_INCOMPLETE missing_keys='+','.join(k for k in ('PANEL_PASSWORD','IQ_EMAIL','IQ_PASSWORD') if not os.environ.get(k)),flush=True)
