import os,queue,json
from probe import worker
q=queue.Queue()
worker(q,os.environ['IQ_EMAIL'],os.environ['IQ_PASSWORD'],'EURUSD')
messages=[]
while not q.empty():messages.append(q.get())
print(json.dumps({'steps':[m['progress'] for m in messages if 'progress' in m],'result':next((m for m in reversed(messages) if 'progress' not in m),{'error':'Sem resultado'}),'orders_enabled':False},ensure_ascii=False),flush=True)
os._exit(0)
