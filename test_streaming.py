import json,threading,unittest
from unittest.mock import patch
from streaming import ProgressQueue
class Tests(unittest.TestCase):
 def test_long_session_retains_only_recent_steps_and_final_result(self):
  q=ProgressQueue()
  with patch('streaming.os.write',side_effect=lambda fd,b:len(b)):
   for n in range(5000):q.put({'progress':str(n)});q.put({'trade_update':{'positions':['x'*1000]}})
  self.assertEqual(q.qsize(),0);self.assertEqual(len(q.steps),30);self.assertEqual(q.steps[-1],'4999')
  q.put({'result':{'done':True}});self.assertEqual(q.qsize(),1);self.assertTrue(q.get()['result']['done'])
 def test_concurrent_partial_writes_keep_complete_json_lines(self):
  q=ProgressQueue();chunks=[]
  def write(fd,data):
   n=min(len(data),117);chunks.append(data[:n]);return n
  with patch('streaming.os.write',side_effect=write):
   threads=[threading.Thread(target=q.put,args=({'trade_update':{'order':n,'payload':'x'*5000}},)) for n in range(4)]
   for t in threads:t.start()
   for t in threads:t.join()
  rows=[json.loads(line) for line in b''.join(chunks).splitlines()]
  self.assertEqual({r['trade_update']['order'] for r in rows},set(range(4)));self.assertEqual(q.qsize(),0)
if __name__=='__main__':unittest.main()
