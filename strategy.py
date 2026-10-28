"""Deterministic demo hypothesis; no look-ahead, no institutional-flow claims."""
import math

def candle(row):
 try:
  r={k:float(row[k]) for k in ('from','to','open','close','min','max')}
  if not all(math.isfinite(v) for v in r.values()):return None
  if r['to']-r['from']!=60 or min(r['open'],r['close'],r['min'])<=0:return None
  if r['min']>min(r['open'],r['close']) or r['max']<max(r['open'],r['close']):return None
  return r
 except (KeyError,ValueError,TypeError):return None

def analyze(rows,now):
 def out(reason,**kw):return dict(direction=None,reason=reason,**kw)
 clean={}
 for row in rows:
  c=candle(row)
  if c and c['from']<=now:clean[c['from']]=c
 bars=sorted(clean.values(),key=lambda c:c['from'])
 closed=[c for c in bars if c['to']<=now]
 live=[c for c in bars if c['from']<=now<c['to']]
 if len(closed)<100 or not live:return out('Aguardando 100 velas completas e vela atual de 1 minuto')
 closed=closed[-100:];current=live[-1]
 if any(b['from']-a['from']!=60 for a,b in zip(closed,closed[1:])) or current['from']!=closed[-1]['to']:return out('Histórico com lacunas')
 # Complete aligned 5-minute bars, formed exclusively from past candles.
 groups={}
 for c in closed:groups.setdefault(int(c['from']//300),[]).append(c)
 macro=[(k,sum(c['close'] for c in v)/5,v[-1]['close']) for k,v in sorted(groups.items()) if len(v)==5 and v[0]['from']==k*300 and v[-1]['to']==(k+1)*300]
 if len(macro)<12:return out('Aguardando contexto de 5 minutos')
 closes=[v[2] for v in macro];fast=sum(closes[-4:])/4;slow=sum(closes[-10:])/10
 prev=closed[-1];before=closed[-21:-1]
 atr=sum(c['max']-c['min'] for c in closed[-15:-1])/14
 if atr<=0:return out('Sem amplitude válida')
 support=min(c['min'] for c in before);resistance=max(c['max'] for c in before)
 width=prev['max']-prev['min'];body=abs(prev['close']-prev['open'])
 if width<=0:return out('Vela de rejeição sem amplitude')
 lower=min(prev['open'],prev['close'])-prev['min'];upper=prev['max']-max(prev['open'],prev['close'])
 strong_down=slow-fast>atr*.6;strong_up=fast-slow>atr*.6
 base=dict(support=support,resistance=resistance,atr=atr,macro_fast=fast,macro_slow=slow)
 buy=prev['min']<=support+atr*.25 and lower>=max(body*1.5,width*.35) and prev['close']>=prev['min']+width*.6
 sell=prev['max']>=resistance-atr*.25 and upper>=max(body*1.5,width*.35) and prev['close']<=prev['min']+width*.4
 if buy and sell:return out('Rejeições conflitantes',**base)
 if buy and not strong_down and prev['max']<current['close']<=prev['max']+atr*.5:return dict(direction='call',reason='Rejeição no suporte e rompimento intravela da máxima',signal_id=str(int(prev['from']))+':call',**base)
 if sell and not strong_up and prev['min']>current['close']>=prev['min']-atr*.5:return dict(direction='put',reason='Rejeição na resistência e rompimento intravela da mínima',signal_id=str(int(prev['from']))+':put',**base)
 return out('Sem confluência: região, rejeição, gatilho ou tendência não confirmados',**base)
