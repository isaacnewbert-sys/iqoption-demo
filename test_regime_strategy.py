import unittest
from strategy import analyze,atr14,ema
START=1793142000//300*300

def bar(i,o,c,lo=None,hi=None):return {'from':START+i*60,'to':START+(i+1)*60,'open':o,'close':c,'min':min(o,c)-.1 if lo is None else lo,'max':max(o,c)+.1 if hi is None else hi}
def flat():return [bar(i,100,100,99.8,100.2) for i in range(120)]
def live(close):return bar(120,close,close)
def flip(rows):return [dict(r,open=200-r['open'],close=200-r['close'],min=200-r['max'],max=200-r['min']) for r in rows]
def pullback():
 rows=flat()
 for i in range(80,117):rows[i]=bar(i,100+(i-80)*.15,100+(i-79)*.15)
 rows[117]=bar(117,105.55,105.05,104.95,105.6)
 rows[118]=bar(118,105.05,104.95,104.85,105.1)
 rows[119]=bar(119,104.95,105.3,104.9,105.35)
 return rows,live(105.39)
def retest():
 rows=flat();rows[117]=bar(117,100,100.9,99.95,101)
 rows[118]=bar(118,100.9,100.5,100.35,100.92)
 rows[119]=bar(119,100.4,100.65,100.15,100.68)
 return rows,live(100.72)

class Tests(unittest.TestCase):
 def test_pullback_continuation_both_directions(self):
  rows,current=pullback()
  result=analyze(rows+[current],START+7201)
  self.assertEqual(result['direction'],'call',result);self.assertEqual(result['setup'],'PULLBACK_TENDENCIA',result)
  result=analyze(flip(rows+[current]),START+7201)
  self.assertEqual(result['direction'],'put',result);self.assertEqual(result['setup'],'PULLBACK_TENDENCIA',result)
 def test_breakout_retest_both_directions(self):
  rows,current=retest();r=analyze(rows+[current],START+7201)
  self.assertEqual(r['direction'],'call',r);self.assertEqual(r['setup'],'ROMPIMENTO_RETESTE',r)
  r=analyze(flip(rows+[current]),START+7201);self.assertEqual(r['direction'],'put',r);self.assertEqual(r['setup'],'ROMPIMENTO_RETESTE',r)
 def test_failed_break_recovers_without_hammer(self):
  rows=flat();rows[117]=bar(117,100,99.6,99.45,100.05);rows[118]=bar(118,99.6,99.78,99.5,99.82);rows[119]=bar(119,99.78,100.02,99.75,100.05)
  r=analyze(rows+[live(100.09)],START+7201);self.assertEqual(r['direction'],'call',r);self.assertEqual(r['setup'],'FALSO_ROMPIMENTO',r)
 def test_chasing_candle_does_not_enter(self):
  rows,current=pullback();current['close']=107;current['max']=107
  self.assertIsNone(analyze(rows+[current],START+7201)['direction'])
 def test_no_trade_before_intrabar_trigger(self):
  rows,current=pullback();current.update(close=105.3,min=105.29,max=105.4)
  self.assertIsNone(analyze(rows+[current],START+7201)['direction'])
 def test_future_price_and_unfinished_macro_bar_do_not_change_context(self):
  rows,current=pullback();r=analyze(rows+[current],START+7201)
  later=bar(121,1,1000,1,1000)
  self.assertEqual(r,analyze(rows+[current,later],START+7201))
  other=dict(current,close=105.4,max=106,min=104)
  r2=analyze(rows+[other],START+7201)
  for key in ('ema9','ema21','macro_fast','macro_slow','atr','regime'):self.assertEqual(r[key],r2[key])
 def test_outside_market_clock_or_history_gap_blocks(self):
  rows,current=pullback();self.assertIsNone(analyze(rows,START+7261)['direction'])
  rows.pop(-15);self.assertEqual(analyze(rows+[current],START+7201)['reason'],'Histórico com lacunas')
 def test_warmup_diagnostic_and_true_range(self):
  r=analyze(flat()[-50:]+[live(100)],START+7201)
  self.assertFalse(r['checks']['history']);self.assertEqual(r['closed_bars'],50)
  rows=[bar(i,100,100,99.9,100.1) for i in range(15)];rows[-1]=bar(14,110,110,109.9,110.1)
  self.assertGreater(atr14(rows),.8)
 def test_ema_is_recursive(self):self.assertEqual(ema([1,3,5],3),[1,2,3.5])
 def test_every_signal_explains_context_and_trigger(self):
  rows,current=pullback();r=analyze(rows+[current],START+7201)
  self.assertTrue(r['checks']['trigger']);self.assertIn('invalidation_reference',r);self.assertIn('signal_id',r)
if __name__=='__main__':unittest.main()
