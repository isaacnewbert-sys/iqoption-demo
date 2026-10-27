import os,queue,json,sys
from probe import worker
class ProgressQueue(queue.Queue):
 def put(self,message,*args,**kwargs):
  if 'progress' in message:
   os.write(1,(json.dumps({'progress':message['progress']},ensure_ascii=False)+'\n').encode('utf-8'))
  return super().put(message,*args,**kwargs)
q=ProgressQueue()
test_order=len(sys.argv)==2 and sys.argv[1]=='--demo-test-order'
worker(q,os.environ['IQ_EMAIL'],os.environ['IQ_PASSWORD'],'EURUSD',test_order=test_order)
messages=[]
while not q.empty():messages.append(q.get())
print(json.dumps({'steps':[m['progress'] for m in messages if 'progress' in m],'result':next((m for m in reversed(messages) if 'progress' not in m),{'error':'Sem resultado'}),'demo_test_orders_enabled':True,'real_orders_enabled':False},ensure_ascii=False),flush=True)
os._exit(0)
