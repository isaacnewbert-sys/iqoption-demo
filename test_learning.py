import unittest,tempfile,os
from learning import Memory,summarize,check_storage
from unittest.mock import patch
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=Memory(url='',local=self.tmp.name+'/memory.db')
  self.e={'account':'PRACTICE','order_status':'ORDEM_DEMO_CONFIRMADA','balance_id':4,'order_id':1,'pair':'EURUSD-OTC','direction':'call','amount':100,'asset_id':76}
  self.a={'strategy_version':'regime-v2','setup':'REJEICAO_SUPORTE','regime':'LATERAL','direction':'call','atr':.001}
  self.o=dict(self.e,monitor_status='POSICAO_ENCERRADA',broker_pnl_realized=8)
 def tearDown(self):self.tmp.cleanup()
 def test_memory_survives_new_connection_and_deduplicates(self):
  self.db.entry(self.e,self.a,at=1);self.db.entry(dict(self.e,amount=900),self.a);self.db.outcome(self.o);self.db.outcome(dict(self.o,broker_pnl_realized=99))
  rows=Memory(url='',local=self.db.local).rows(4)
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['entry']['amount'],100);self.assertEqual(rows[0]['outcome']['pnl'],'8')
 def test_wallet_isolation_and_real_rejected(self):
  self.assertFalse(self.db.entry(dict(self.e,account='REAL'),self.a));self.db.entry(self.e,self.a)
  self.assertEqual(self.db.rows(99),[])
 def test_unknown_result_is_not_training(self):
  self.db.entry(self.e,self.a,at=1)
  self.assertFalse(self.db.outcome(dict(self.o,monitor_status='ENCERRAMENTO_INCERTO_CONFIRA_IQ')))
  self.assertEqual(summarize(self.db.rows(4))['pending_trades'],1)
 def test_history_only_result_has_no_fabricated_context(self):
  self.db.outcome(self.o);summary=summarize(self.db.rows(4))
  self.assertEqual(summary['unattributed_records'],1);self.assertEqual(summary['matched_closed_trades'],0)
 def test_out_of_order_outcome_can_join_later_entry(self):
  self.db.outcome(self.o);self.db.entry(self.e,self.a,at=1)
  self.assertEqual(summarize(self.db.rows(4))['matched_closed_trades'],1)
 def test_manual_without_context_does_not_train(self):
  self.db.entry(self.e,at=1);self.db.outcome(self.o)
  self.assertEqual(summarize(self.db.rows(4))['matched_closed_trades'],0)
 def examples(self,n=60,roi=.08):
  return [{'order_id':str(i),'entry':{'pair':'EURUSD-OTC','amount':100,'provenance':'bot_entry','recorded_at':i*10,'analysis':self.a},'outcome':{'recorded_at':i*10+5,'pnl':str(roi*100)}} for i in range(1,n+1)]
 def test_minimum_sample_and_shadow_mode(self):
  s=summarize(self.examples(59),asof=1000);self.assertEqual(s['contexts'][0]['shadow_priority_delta'],0)
  s=summarize(self.examples(),asof=1000);self.assertGreater(s['contexts'][0]['shadow_priority_delta'],0);self.assertEqual(s['mode'],'SHADOW_NO_EXECUTION_CHANGES');self.assertEqual(s['contexts'][0]['validation_trades'],20)
 def test_validation_rejects_regime_reversal(self):
  rows=self.examples()
  for r in rows[-20:]:r['outcome']['pnl']='-100'
  self.assertEqual(summarize(rows,asof=1000)['contexts'][0]['shadow_priority_delta'],0)
 def test_future_outcomes_cannot_leak(self):
  self.assertEqual(summarize(self.examples(),asof=15)['matched_closed_trades'],0)
 def test_overlapping_train_validation_does_not_promote(self):
  rows=self.examples();rows[0]['outcome']['recorded_at']=1000
  self.assertEqual(summarize(rows,asof=2000)['contexts'][0]['shadow_priority_delta'],0)
 def test_probe_commits_across_connections_without_fake_trade(self):
  with patch.dict(os.environ,{'LEARNING_DATABASE_URL':'postgresql://placeholder'}),patch('learning.Memory',return_value=self.db):r=check_storage()
  self.assertEqual(r['status'],'WRITE_READ_VERIFIED');self.assertEqual(r['records'],0)
  self.assertEqual(self.db.rows(4),[])
 def test_pasted_shell_command_is_rejected_without_exposing_secret(self):
  with patch.dict(os.environ,{'LEARNING_DATABASE_URL':"psql 'postgresql://user:SECRET@host/db'"}):r=check_storage()
  self.assertEqual(r['status'],'INVALID_CONNECTION_URL');self.assertNotIn('SECRET',str(r))
 def test_secrets_not_saved(self):
  self.db.entry(dict(self.e,password='SECRET'),dict(self.a,password='SECRET'),at=1)
  self.assertNotIn('SECRET',str(self.db.rows(4)))
if __name__=='__main__':unittest.main()
