"""Causal, experimental demo setups selected by regime. No profitability claim."""
import math
VERSION='regime-v2'

def candle(row):
 try:
  r={k:float(row[k]) for k in ('from','to','open','close','min','max')}
  if not all(math.isfinite(v) for v in r.values()):return None
  if r['to']-r['from']!=60 or min(r['open'],r['close'],r['min'])<=0:return None
  if r['min']>min(r['open'],r['close']) or r['max']<max(r['open'],r['close']):return None
  return r
 except (KeyError,ValueError,TypeError):return None

def ema(values,period):
 # Seed from the first observation; require long warm-up in analyze().
 result=[values[0]];alpha=2/(period+1)
 for v in values[1:]:result.append(result[-1]+alpha*(v-result[-1]))
 return result

def atr14(bars):
 ranges=[max(b['max']-b['min'],abs(b['max']-a['close']),abs(b['min']-a['close'])) for a,b in zip(bars,bars[1:])]
 if len(ranges)<14:return 0
 atr=sum(ranges[:14])/14
 for value in ranges[14:]:atr=(13*atr+value)/14
 return atr

def evaluate(closed,current):
 prices=[b['close'] for b in closed];fast=ema(prices,9);slow=ema(prices,21);atr=atr14(closed)
 if atr<=0:return {'direction':None,'reason':'ATR sem amplitude válida','checks':{'atr':False}}
 groups={}
 for c in closed:groups.setdefault(int(c['from']//300),[]).append(c)
 macro=[v[-1]['close'] for k,v in sorted(groups.items()) if len(v)==5 and v[0]['from']==k*300 and v[-1]['to']==(k+1)*300]
 if len(macro)<10:return {'direction':None,'reason':'Contexto de 5 minutos incompleto','checks':{'macro':False}}
 mf=ema(macro,3)[-1];ms=ema(macro,8)[-1]
 path=sum(abs(b-a) for a,b in zip(prices[-15:],prices[-14:]))
 efficiency=abs(prices[-1]-prices[-15])/path if path else 0
 slope=(fast[-1]-fast[-4])/atr;gap=(fast[-1]-slow[-1])/atr
 up=gap>.12 and slope>.10 and efficiency>=.30 and (mf>=ms or gap>.6)
 down=gap<-.12 and slope<-.10 and efficiency>=.30 and (mf<=ms or gap<-.6)
 regime='TENDENCIA_ALTA' if up else 'TENDENCIA_BAIXA' if down else ('LATERAL' if efficiency<.30 and abs(gap)<.6 else 'TRANSICAO')
 prev=closed[-1];before=closed[-21:-1];support=min(c['min'] for c in before);resistance=max(c['max'] for c in before)
 width=prev['max']-prev['min'];body=abs(prev['close']-prev['open']);price=current['close']
 base=dict(strategy_version=VERSION,regime=regime,support=support,resistance=resistance,atr=atr,ema9=fast[-1],ema21=slow[-1],macro_fast=mf,macro_slow=ms,efficiency=efficiency)
 if width<=0:return dict(base,direction=None,reason='Vela anterior sem amplitude',checks={'signal_bar':False})
 lower=min(prev['open'],prev['close'])-prev['min'];upper=prev['max']-max(prev['open'],prev['close'])
 bullish=prev['close']>prev['open'] and prev['close']>=prev['min']+.6*width
 bearish=prev['close']<prev['open'] and prev['close']<=prev['min']+.4*width
 def trigger(direction):
  level=prev['max'] if direction=='call' else prev['min']
  move=price-level if direction=='call' else level-price
  return 0<move<=atr*.5
 def signal(direction,setup,reason,level):
  return dict(base,direction=direction,setup=setup,reason=reason,signal_id=str(int(prev['from']))+':'+direction,trigger=prev['max'] if direction=='call' else prev['min'],invalidation_reference=level,checks={'context':True,'location':True,'confirmation':True,'trigger':True,'not_chasing':True})
 checks={'context':True,'location':False,'confirmation':False,'trigger':False,'not_chasing':abs(price-fast[-1])<=2.5*atr}
 if up or down:
  direction='call' if up else 'put';confirmed=bullish if up else bearish
  # Breakout followed by retest. Every breakout level uses bars preceding that breakout.
  for index in range(len(closed)-4,len(closed)-1):
   br=closed[index];prior=closed[index-20:index]
   level=max(c['max'] for c in prior) if up else min(c['min'] for c in prior)
   br_body=br['close']-br['open'] if up else br['open']-br['close']
   broke=br['close']>level if up else br['close']<level
   touched=prev['min']<=level+.35*atr and prev['close']>level if up else prev['max']>=level-.35*atr and prev['close']<level
   held=min(c['close'] for c in closed[index+1:])>=level-.2*atr if up else max(c['close'] for c in closed[index+1:])<=level+.2*atr
   location=broke and br_body>=.45*atr and touched and held and abs(price-level)<=1.8*atr
   if location:
    checks.update(location=True,confirmation=confirmed,trigger=trigger(direction))
    if confirmed and trigger(direction):return signal(direction,'ROMPIMENTO_RETESTE','Rompimento confirmado, reteste sustentado e retomada intravela',level)
  # Trend continuation: a genuine retracement into the EMA9 area, then resumption.
  recent=closed[-4:]
  retraced=any(c['close']<c['open'] for c in recent[:-1]) if up else any(c['close']>c['open'] for c in recent[:-1])
  touched=any(c['min']<=e+.35*atr and c['max']>=e-.35*atr for c,e in zip(recent,fast[-4:]))
  holds=prev['close']>=slow[-1]-.2*atr if up else prev['close']<=slow[-1]+.2*atr
  location=retraced and touched and holds
  room=not (0<resistance-price<.15*atr) if up else not (0<price-support<.15*atr)
  checks.update(location=checks['location'] or location,confirmation=confirmed,trigger=trigger(direction),room_to_barrier=room)
  if location and confirmed and trigger(direction) and checks['not_chasing'] and room:return signal(direction,'PULLBACK_TENDENCIA','Recuo até a EMA9, confirmação de retomada e rompimento intravela',min(c['min'] for c in recent) if up else max(c['max'] for c in recent))
  labels={'location':'recuo/reteste em região válida','confirmation':'vela de retomada','trigger':'rompimento do gatilho','not_chasing':'preço sem esticamento','room_to_barrier':'espaço antes da barreira'}
  missing=[labels[k] for k in labels if not checks.get(k,True)]
  return dict(base,direction=None,setup='CONTINUACAO',reason='Tendência identificada; aguardando '+', '.join(missing),checks=checks)
 # Reversals belong to range/transition; never fight a classified trend.
 buy=prev['min']<=support+.25*atr and lower>=max(body*1.5,width*.35) and prev['close']>=prev['min']+.6*width
 sell=prev['max']>=resistance-.25*atr and upper>=max(body*1.5,width*.35) and prev['close']<=prev['min']+.4*width
 if buy and sell:return dict(base,direction=None,reason='Rejeições conflitantes',checks=checks)
 if buy and trigger('call'):return signal('call','REJEICAO_SUPORTE','Rejeição no suporte e retomada intravela confirmada',prev['min'])
 if sell and trigger('put'):return signal('put','REJEICAO_RESISTENCIA','Rejeição na resistência e retomada intravela confirmada',prev['max'])
 # Failed break and reclaim permits reversal without requiring a single hammer candle.
 last=closed[-3:];prior=closed[-23:-3];floor=min(c['min'] for c in prior);ceiling=max(c['max'] for c in prior)
 reclaimed_low=min(c['min'] for c in last[:-1])<floor-.1*atr and prev['close']>floor and prev['min']>min(c['min'] for c in last[:-1])
 reclaimed_high=max(c['max'] for c in last[:-1])>ceiling+.1*atr and prev['close']<ceiling and prev['max']<max(c['max'] for c in last[:-1])
 if reclaimed_low and bullish and trigger('call'):return signal('call','FALSO_ROMPIMENTO','Perda do suporte falhou; recuperação e fundo mais alto confirmados',min(c['min'] for c in last))
 if reclaimed_high and bearish and trigger('put'):return signal('put','FALSO_ROMPIMENTO','Rompimento da resistência falhou; devolução e topo mais baixo confirmados',max(c['max'] for c in last))
 checks.update(location=buy or sell or reclaimed_low or reclaimed_high,confirmation=bullish or bearish,trigger=trigger('call') if buy or reclaimed_low else trigger('put') if sell or reclaimed_high else False)
 return dict(base,direction=None,setup='REVERSAO',reason='Faixa/transição: aguardando região, rejeição ou recuperação e gatilho',checks=checks)

def analyze(rows,now):
 def out(reason,**kw):return dict(strategy_version=VERSION,direction=None,reason=reason,**kw)
 clean={}
 for row in rows:
  c=candle(row)
  if c and c['from']<=now:clean[c['from']]=c
 bars=sorted(clean.values(),key=lambda c:c['from']);closed=[c for c in bars if c['to']<=now];live=[c for c in bars if c['from']<=now<c['to']]
 if len(closed)<65 or not live:return out('Aguardando 65 velas completas e vela atual de 1 minuto',closed_bars=len(closed),live_bars=len(live),checks={'history':len(closed)>=65,'live_candle':bool(live)})
 closed=closed[-120:];current=live[-1]
 if any(b['from']-a['from']!=60 for a,b in zip(closed,closed[1:])) or current['from']!=closed[-1]['to']:return out('Histórico com lacunas',checks={'continuous_history':False})
 return evaluate(closed,current)
