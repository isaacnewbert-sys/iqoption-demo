"""Serialize multi-monitor NDJSON and bound retained progress for long sessions."""
import os,json,queue,threading
from collections import deque
class ProgressQueue(queue.Queue):
 def __init__(self):
  super().__init__();self.steps=deque(maxlen=30);self.stream_lock=threading.RLock()
 def put(self,message,*args,**kwargs):
  if 'progress' in message or 'trade_update' in message:
   data=(json.dumps(message,ensure_ascii=False)+'\n').encode('utf-8')
   with self.stream_lock:
    if 'progress' in message:self.steps.append(message['progress'])
    while data:
     written=os.write(1,data)
     if written<=0:raise BrokenPipeError('Progress stream closed')
     data=data[written:]
   return None
  return super().put(message,*args,**kwargs)
