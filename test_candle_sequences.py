import unittest
from strategy import sequence_reversal,analyze
from test_regime_strategy import bar,flat,live,flip,START
class Tests(unittest.TestCase):
 def sample(self,n=3):
  rows=flat();start=120-n
  # Reference range ends at 100.2; sequence advances into that resistance.
  if n==3:
   rows[start]=bar(start,99.4,99.8,99.35,99.85)
   rows[start+1]=bar(start+1,99.8,100.2,99.75,100.25)
  else:rows[start]=bar(start,99.6,100.2,99.55,100.25)
  rows[119]=bar(119,100.2,100.3,100.15,100.7)
  return rows,live(100.1)
 def test_three_up_gives_put_only_after_live_break(self):
  rows,c=self.sample();r=sequence_reversal(rows,c,.4,'LATERAL')
  self.assertEqual(r['count'],3);self.assertEqual(r['direction'],'put')
 def test_two_up_has_separate_variant(self):
  rows,c=self.sample(2);r=sequence_reversal(rows,c,.4,'LATERAL')
  self.assertEqual(r['count'],2);self.assertEqual(r['direction'],'put')
 def test_two_and_three_down_give_call(self):
  for n in (2,3):
   rows,c=self.sample(n);r=sequence_reversal(flip(rows),flip([c])[0],.4,'TRANSICAO')
   self.assertEqual(r['direction'],'call');self.assertEqual(r['count'],n)
 def test_count_does_not_replace_reversal_confirmation(self):
  rows,c=self.sample();c['close']=100.25
  self.assertIsNone(sequence_reversal(rows,c,.4,'LATERAL'))
 def test_no_countertrend_or_four_bar_sequence(self):
  rows,c=self.sample();self.assertIsNone(sequence_reversal(rows,c,.4,'TENDENCIA_ALTA'))
  rows[116]=bar(116,99.2,99.4);self.assertIsNone(sequence_reversal(rows,c,.4,'LATERAL'))
 def test_strong_undiminished_bodies_are_not_exhaustion(self):
  rows,c=self.sample();rows[-1]=bar(119,100.2,100.65,100.19,100.66)
  self.assertIsNone(sequence_reversal(rows,c,.4,'LATERAL'))
 def test_end_to_end_variant_and_future_bar_are_causal(self):
  rows,c=self.sample();now=START+7201;r=analyze(rows+[c],now)
  self.assertEqual(r['setup'],'REVERSAO_SEQUENCIA_3');self.assertEqual(r['direction'],'put')
  future=bar(121,100,120,99,121)
  self.assertEqual(analyze(rows+[c,future],now),r)
if __name__=='__main__':unittest.main()
