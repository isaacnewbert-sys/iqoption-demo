import os,queue,json,sys,argparse
from probe import worker
from streaming import ProgressQueue
q=ProgressQueue()
parser=argparse.ArgumentParser()
parser.add_argument('--automation-token')
parser.add_argument('--pair',choices=('EURUSD','EURUSD-OTC'),default='EURUSD')
parser.add_argument('--direction',choices=('call','put'),default='call')
parser.add_argument('--demo-test-order',action='store_true')
parser.add_argument('--take-profit-8',action='store_true')
args=parser.parse_args()
if args.take_profit_8 and not args.demo_test_order:parser.error("Take-profit requires explicit demo order mode")
test_order=args.demo_test_order
worker(q,os.environ['IQ_EMAIL'],os.environ['IQ_PASSWORD'],args.pair,test_order=test_order,take_profit_8=args.take_profit_8,direction=args.direction,automation_token=args.automation_token)
messages=[]
while not q.empty():messages.append(q.get())
print(json.dumps({'steps':list(q.steps),'result':next((m for m in reversed(messages) if 'progress' not in m),{'error':'Sem resultado'}),'demo_test_orders_enabled':True,'real_orders_enabled':False},ensure_ascii=False),flush=True)
os._exit(0)
