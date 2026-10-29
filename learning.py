"""Persistent, PRACTICE-only trade memory and causal shadow evaluation.
No broker writes, credential storage, stake changes, or strategy gate overrides.
"""
import os,json,time,hashlib,statistics,math,sqlite3,threading
from collections import defaultdict
from contextlib import contextmanager
from profit_exit import number
VERSION='memory-v1-shadow'
_lock=threading.RLock();_cache={}
class Memory:
 def __init__(self,url=None,local=None):
  self.url=os.environ.get('LEARNING_DATABASE_URL','') if url is None else url
  self.local=local
 @contextmanager
 def db(self):
  if self.local:
   with sqlite3.connect(self.local,timeout=2) as db:yield db,'?'
  elif self.url:
   import psycopg
   with psycopg.connect(self.url,connect_timeout=8) as db:
    db.execute('SET LOCAL statement_timeout=2000')
    db.execute('SET LOCAL lock_timeout=1000')
    yield db,'%s'
  else:raise RuntimeError('Persistent learning database is not configured')
 def schema(self,db):
  db.execute('CREATE TABLE IF NOT EXISTS iq_memory (wallet TEXT NOT NULL, order_id TEXT NOT NULL, entry_data TEXT, outcome_data TEXT, PRIMARY KEY(wallet,order_id))')
 def entry(self,r,context=None,at=None):
  if r.get('account')!='PRACTICE' or r.get('order_status')!='ORDEM_DEMO_CONFIRMADA' or not r.get('order_id') or not r.get('balance_id'):return False
  stake=number(r.get('amount'))
  if stake is None or stake<=0:return False
  a=context or {};fields=('strategy_version','regime','setup','direction','signal_id','trigger','support','resistance','atr','ema9','ema21','macro_fast','macro_slow','efficiency','checks','invalidation_reference')
  row={k:r.get(k) for k in ('pair','direction','amount','asset_id','expiration_timestamp')}
  row.update(recorded_at=time.time() if at is None else at,analysis={k:a[k] for k in fields if k in a},provenance='bot_entry',model_version=VERSION,selection=r.get('selection_snapshot'))
  return self.write(str(r['balance_id']),str(r['order_id']),'entry_data',row)
 def outcome(self,r):
  if r.get('account')!='PRACTICE' or not r.get('balance_id') or not r.get('order_id'):return False
  if r.get('monitor_status') not in ('POSICAO_ENCERRADA','FECHAMENTO_ANTECIPADO_CONFIRMADO'):return False
  pnl=number(r.get('broker_pnl_realized'))
  if pnl is None:return False
  row={'pnl':str(pnl),'recorded_at':time.time(),'exit_status':r['monitor_status'],'source':'broker_confirmed','close_reason':r.get('close_reason')}
  return self.write(str(r['balance_id']),str(r['order_id']),'outcome_data',row)
 def write(self,wallet,oid,column,row):
  assert column in ('entry_data','outcome_data')
  data=json.dumps(row,allow_nan=False)
  with self.db() as (db,p):
   self.schema(db)
   # First confirmed entry/outcome is immutable. Duplicate events never multiply P/L.
   db.execute(f'INSERT INTO iq_memory(wallet,order_id,{column}) VALUES({p},{p},{p}) ON CONFLICT(wallet,order_id) DO UPDATE SET {column}=COALESCE(iq_memory.{column},excluded.{column})',(wallet,oid,data))
  return True
 def rows(self,wallet):
  with self.db() as (db,p):
   self.schema(db)
   values=db.execute(f'SELECT order_id,entry_data,outcome_data FROM iq_memory WHERE wallet={p}',(str(wallet),)).fetchall()
  return [{'order_id':oid,'entry':json.loads(e) if e else None,'outcome':json.loads(o) if o else None} for oid,e,o in values]

def summarize(rows,asof=None):
 """Strict temporal cutoff; unmatched/manual history is never a training example."""
 asof=time.time() if asof is None else asof;groups=defaultdict(list);unmatched=0;pending=0
 for r in rows:
  e=r.get('entry');o=r.get('outcome')
  if not e:unmatched+=1;continue
  if not o:pending+=1;continue
  a=e.get('analysis',{});stake=number(e.get('amount'));pnl=number(o.get('pnl'))
  if e.get('recorded_at',asof)>=asof or o.get('recorded_at',asof)>=asof:continue
  if e.get('provenance')!='bot_entry' or not all(a.get(k) for k in ('strategy_version','setup','regime','direction')):unmatched+=1;continue
  if stake is None or stake<=0 or pnl is None:continue
  key='|'.join(str(v) for v in (e['pair'],a['strategy_version'],a['setup'],a['regime'],a['direction']))
  groups[key].append((e['recorded_at'],o['recorded_at'],float(pnl/stake),r['order_id']))
 stats=[]
 for key,values in sorted(groups.items()):
  values.sort();roi=[v[2] for v in values];n=len(roi);wins=sum(x>0 for x in roi);gains=sum(max(0,x) for x in roi);loss=-sum(min(0,x) for x in roi)
  train=roi[:-20] if n>=60 else [];validation=roi[-20:] if train else [];proposal=0;phase='AMOSTRA_INSUFICIENTE'
  if train:
   # Completed training outcomes must precede the first held-out entry.
   causal=max(v[1] for v in values[:-20])<values[-20][0]
   def bounds(xs):
    mean=statistics.mean(xs);margin=2*statistics.stdev(xs)/math.sqrt(len(xs)) if len(xs)>1 else float('inf')
    return mean-margin,mean+margin
   tl,tu=bounds(train);vl,vu=bounds(validation)
   if causal and tl>0 and vl>0:proposal=min(5,statistics.mean(train)*10);phase='CANDIDATO_POSITIVO_EM_OBSERVACAO'
   elif causal and tu<0 and vu<0:proposal=max(-5,statistics.mean(train)*10);phase='CANDIDATO_NEGATIVO_EM_OBSERVACAO'
   else:phase='SEM_VALIDACAO_TEMPORAL'
  model=hashlib.sha256(json.dumps(values).encode()).hexdigest()[:16]
  stats.append({'context':key,'trades':n,'win_rate_pct':round(100*wins/n,2),'mean_return_pct':round(100*statistics.mean(roi),3),'profit_factor':round(gains/loss,3) if loss else None,'training_trades':len(train),'validation_trades':len(validation),'shadow_priority_delta':round(proposal,3),'phase':phase,'model_id':model})
 return {'version':VERSION,'mode':'SHADOW_NO_EXECUTION_CHANGES','matched_closed_trades':sum(g['trades'] for g in stats),'pending_trades':pending,'unattributed_records':unmatched,'contexts':stats,'minimum_context_trades':60,'validation_trades_required':20,'asof':asof}

def record_entry(r,context=None):
 try:return Memory().entry(r,context)
 except Exception:return False

def record_outcome(r):
 try:return Memory().outcome(r)
 except Exception:return False

def snapshot(wallet):
 if wallet is None:return {'configured':bool(os.environ.get('LEARNING_DATABASE_URL')),'durable':False,'available':False,'mode':'WAITING_FOR_DEMO_WALLET'}
 if not os.environ.get('LEARNING_DATABASE_URL'):return {'configured':False,'durable':False,'mode':'NOT_CONFIGURED'}
 key=str(wallet)
 with _lock:
  cached=_cache.get(key)
  if cached and time.monotonic()-cached[0]<900:return cached[1]
 try:result=dict(summarize(Memory().rows(wallet)),configured=True,durable=True,available=True)
 except Exception:result={'configured':True,'durable':False,'available':False,'mode':'DATABASE_UNAVAILABLE'}
 with _lock:_cache[key]=(time.monotonic(),result)
 return result


def check_storage():
 """Separate connections prove committed storage; no fake trade or credentials."""
 import uuid
 if not os.environ.get('LEARNING_DATABASE_URL'):return {'configured':False,'available':False,'status':'NOT_CONFIGURED'}
 key=uuid.uuid4().hex
 url=os.environ.get('LEARNING_DATABASE_URL','').strip()
 if not url.startswith(('postgresql://','postgres://')):return {'configured':True,'available':False,'status':'INVALID_CONNECTION_URL'}
 try:
  memory=Memory()
  with memory.db() as (db,p):
   memory.schema(db)
   db.execute('CREATE TABLE IF NOT EXISTS iq_memory_probe (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
   db.execute(f'INSERT INTO iq_memory_probe(id,value) VALUES({p},{p})',(key,'durability-check'))
  with memory.db() as (db,p):
   found=db.execute(f'SELECT value FROM iq_memory_probe WHERE id={p}',(key,)).fetchone()
   db.execute(f'DELETE FROM iq_memory_probe WHERE id={p}',(key,))
   counts=db.execute('SELECT COUNT(*), COUNT(entry_data), COUNT(outcome_data) FROM iq_memory').fetchone()
  ok=bool(found and found[0]=='durability-check')
  return {'configured':True,'available':ok,'status':'WRITE_READ_VERIFIED' if ok else 'READBACK_FAILED','records':counts[0],'entries':counts[1],'outcomes':counts[2],'mode':'SHADOW_NO_EXECUTION_CHANGES'}
 except Exception as error:
  message=str(error).lower()
  categories=[('authentication',('password authentication','authentication failed')),('dns',('could not translate host','name or service not known','nodename nor servname')),('timeout',('timeout','timed out')),('ssl',('ssl','certificate')),('startup_parameter',('startup parameter','unsupported parameter')),('database',('database does not exist','database \"')),('connection_refused',('connection refused',)),('permission',('permission denied',)),('url_format',('invalid conninfo','invalid dsn','invalid connection option'))]
  category=next((name for name,patterns in categories if any(p in message for p in patterns)),'unclassified')
  return {'configured':True,'available':False,'status':'DATABASE_CHECK_FAILED','error_category':type(error).__name__,'reason_category':category}

