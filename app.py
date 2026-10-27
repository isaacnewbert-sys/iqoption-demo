import os,secrets,threading,subprocess,sys,json,time
from flask import Flask,request,Response,jsonify
app=Flask(__name__)
state={'running':False,'result':None}
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
def health():return {'ok':True,'orders_enabled':False}
@app.get('/')
def index():return '''<!doctype html><html lang="pt-BR"><meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8"><title>IQ Demo</title><style>body{font:16px system-ui;background:#0a1524;color:#e5edf7;max-width:750px;margin:auto;padding:24px}button{padding:16px;background:#27c89c;border:0;border-radius:10px;font:inherit}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#15263d;padding:18px;border-radius:12px}</style><h1>IQ Demo · servidor</h1><p>Conta demonstrativa. Ordens desativadas. Conexão e preços ainda em validação.</p><p>EUR/USD Digital · grade de vencimentos de 5 minutos · objetivo futuro de saída +8%, sem stop por perda.</p><button onclick="run()">Testar conexão e contratos</button><p id="status"></p><pre id="out">Aguardando teste.</pre><p>Credenciais IQ Option somente nas variáveis protegidas do Render. Não são solicitadas nesta página. Resultados temporários são perdidos ao reiniciar. Hospedagem gratuita pode suspender por inatividade; não serve para operação contínua.</p><script>async function refresh(){try{let r=await fetch('/status');if(!r.ok)return;let s=await r.json();document.getElementById('status').textContent=s.running?'Teste em andamento…':'Teste parado';document.getElementById('out').textContent=JSON.stringify(s.result,null,2)}catch{}}async function run(){let r=await fetch('/run',{method:'POST',headers:{'X-Demo-Panel':'1'}});if(!r.ok)document.getElementById('status').textContent=await r.text();refresh()}setInterval(refresh,3000);refresh()</script></html>'''
@app.get('/status')
def status():
 with lock:return jsonify(dict(state))
def job():
 try:
  p=subprocess.run([sys.executable,'runner.py'],capture_output=True,text=True,timeout=65)
  result=json.loads(p.stdout) if p.returncode==0 else {'error':'Processo interrompido. Nenhuma ordem enviada.'}
 except subprocess.TimeoutExpired:result={'error':'Tempo limite de 65 segundos. Processo encerrado. Nenhuma ordem enviada.'}
 except Exception:result={'error':'Falha no diagnóstico; detalhes omitidos para preservar credenciais.'}
 with lock:state.update(running=False,result=result)
@app.post('/run')
def run():
 if not os.environ.get('IQ_EMAIL') or not os.environ.get('IQ_PASSWORD'):return Response('Configure IQ_EMAIL e IQ_PASSWORD no Render.',409)
 with lock:
  if state['running']:return Response('Já existe um teste em andamento.',409)
  state.update(running=True,result=None)
 threading.Thread(target=job,daemon=True).start();return {'started':True,'orders_enabled':False},202
