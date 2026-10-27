import os,queue,json,sys,argparse
from probe import worker
class ProgressQueue(queue.Queue):
 def put(self,message,*args,**kwargs):
  if 'progress' in message:
   os.write(1,(json.dumps({'progress':message['progress']},ensure_ascii=False)+'\n').encode('utf-8'))
  return super().put(message,*args,**kwargs)
q=ProgressQueue()
parser=argparse.ArgumentParser()
parser.add_argument('--pair',choices=('EURUSD','EURUSD-OTC'),default='EURUSD')
parser.add_argument('--demo-test-order',action='store_true')
args=parser.parse_args()
test_order=args.demo_test_order
worker(q,os.environ['IQ_EMAIL'],os.environ['IQ_PASSWORD'],args.pair,test_order=test_order)
messages=[]
while not q.empty():messages.append(q.get())
print(json.dumps({'steps':[m['progress'] for m in messages if 'progress' in m],'result':next((m for m in reversed(messages) if 'progress' not in m),{'error':'Sem resultado'}),'demo_test_orders_enabled':True,'real_orders_enabled':False},ensure_ascii=False),flush=True)
os._exit(0)
