"""PRACTICE-only take-profit based on the broker's position valuation, not asset candles."""
import time,math,uuid
from decimal import Decimal,InvalidOperation

def number(value):
    if isinstance(value,bool):return None
    try:
        n=Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation,ValueError,TypeError):return None

class ProfitTracker:
    def __init__(self,balance_id,asset_id):
        self.balance_id=balance_id;self.asset_id=asset_id;self.order_id=None
        self.position=None;self.pending=[];self.metrics=None
        self.close_request_id=None;self.close_ack=None;self.close_attempts=0
    def bind(self,order_id):
        self.order_id=order_id
        for row in list(self.pending):self.ingest_position(row)
        self.pending=[]
    def ingest_position(self,row):
        if not isinstance(row,dict) or row.get('instrument_type')!='digital-option':return
        if row.get('user_balance_id')!=self.balance_id or row.get('active_id')!=self.asset_id:return
        if self.order_id is None:
            self.pending=(self.pending+[row])[-5:];return
        raw=row.get('raw_event',{})
        raw=raw.get('digital_options_position_changed1',raw) if isinstance(raw,dict) else {}
        ids=raw.get('order_ids',row.get('order_ids',[])) if isinstance(raw,dict) else row.get('order_ids',[])
        # Do not assume order_id is the external position ID.
        if not isinstance(ids,list) or self.order_id not in ids:return
        if not isinstance(row.get('external_id'),int) or isinstance(row['external_id'],bool) or row['external_id']<=0:return
        if not isinstance(row.get('id'),str) or len(row['id'])>128:return
        invest=number(row.get('invest'))
        if invest is None or invest!=Decimal('1'):return
        status=row.get('status')
        if status not in ('open','closed'):return
        safe={k:row.get(k) for k in ('external_id','id','active_id','user_balance_id','status','invest','close_profit','close_reason','pnl_realized','pnl_net')}
        for key in ('close_profit','pnl_realized','pnl_net'):
            value=number(safe[key]);safe[key]=float(value) if value is not None else None
        safe['received_at']=time.monotonic()
        if self.position and self.position['status']=='closed' and status=='open':return
        self.position=safe
    def receive(self,event):
        if not isinstance(event,dict):return
        name=event.get('name');body=event.get('msg');rid=str(event.get('request_id',''))
        if not isinstance(body,dict):return
        if self.close_request_id and rid==self.close_request_id and isinstance(body.get('success'),bool):self.close_ack=body['success']
        if name in ('position-changed','portfolio.position-changed'):self.ingest_position(body)
        if rid.startswith('tp8-positions-'):
            for row in body.get('positions',[]):self.ingest_position(row)
        if name in ('positions-state','portfolio.positions-state') and self.position:
            for row in body.get('positions',[]):
                if not isinstance(row,dict) or row.get('instrument_type')!='digital-option' or row.get('id')!=self.position['id']:continue
                self.metrics={k:row.get(k) for k in ('sell_profit','pnl_net','pnl','quote_timestamp')}
                self.metrics['received_at']=time.monotonic()
    def valuation(self,server_now,monotonic_now=None):
        if not self.position or self.position['status']!='open' or not self.metrics:return None
        now=time.monotonic() if monotonic_now is None else monotonic_now
        if now-self.metrics['received_at']>3:return None
        qt=number(self.metrics.get('quote_timestamp'))
        if qt is not None:
            if qt>Decimal('1e12'):qt/=1000
            if abs(Decimal(str(server_now))-qt)>5:return None
        sell=number(self.metrics.get('sell_profit'));net=number(self.metrics.get('pnl_net'));stake=number(self.position['invest'])
        if sell is None or net is None or stake is None or stake<=0:return None
        # Validate the broker's sell valuation against its net P/L. Some protocol
        # versions expose gross proceeds; others expose net profit. Never guess.
        tolerance=Decimal('0.00001')
        if abs((sell-stake)-net)<=tolerance:profit=sell-stake;mode='gross_proceeds'
        elif abs(sell-net)<=tolerance:profit=sell;mode='net_profit'
        else:return None
        return {'net_profit':float(profit),'profit_pct':float(profit/stake*100),'valuation_mode':mode,'target_reached':profit>=stake*Decimal('0.08')}

def prepare_tracking(client):
    if client.get_balance_mode()!='PRACTICE':return False
    profile=client.get_profile_ansyc();user_id=profile.get('user_id',profile.get('id'))
    if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id<=0:return False
    trace=client.trace
    trace.profit_tracker=ProfitTracker(client.get_balance_id(),trace.asset_id)
    specs=[('tp8-changed','portfolio.position-changed','3.0',{'routingFilters':{'user_id':user_id}}),('tp8-state','portfolio.positions-state','1.0',None)]
    for suffix,name,version,params in specs:
        msg={'name':name,'version':version}
        if params:msg['params']=params
        client.api.send_websocket_request('subscribeMessage',msg,request_id=trace.request_id+'-'+suffix)
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        if all(trace.subscription_acks.get(trace.request_id+'-'+s[0]) is True for s in specs):return True
        time.sleep(.05)
    return False

def monitor_profit(client,entry,progress=lambda _:None,update=lambda _:None):
    tracker=client.trace.profit_tracker
    tracker.bind(entry['order_id'])
    expiry=entry['expiration_timestamp'];started=time.monotonic()
    duration=min(620,max(1,expiry-client.api.timesync.server_timestamp+20))
    deadline=started+duration;last_lookup=0;last_subscription=0;last_update=0;last_close=float('-inf');subscribed_id=None
    result=dict(entry,target_profit_pct=8,early_sell_verified=False,monitor_status='AGUARDANDO_POSICAO')
    close_pending=False
    def request_positions():
        client.api.send_websocket_request('sendMessage',{'name':'portfolio.get-positions','version':'4.0','body':{'instrument_types':['digital-option'],'limit':30,'offset':0}},request_id='tp8-positions-'+uuid.uuid4().hex)
    while time.monotonic()<deadline:
        now=time.monotonic();server_now=client.api.timesync.server_timestamp
        if now-last_lookup>=3:
            request_positions();last_lookup=now
        pos=tracker.position
        if pos and pos['status']=='closed':
            reason=pos.get('close_reason')
            sold=tracker.close_attempts>0 and tracker.close_ack is True and reason in ('default','sold','sell','manual','closed_by_user')
            result.update(monitor_status='FECHAMENTO_ANTECIPADO_CONFIRMADO' if sold else 'POSICAO_ENCERRADA',early_sell_verified=sold,close_reason=reason if isinstance(reason,str) and len(reason)<64 else 'omitted',broker_pnl_realized=pos.get('pnl_realized'),broker_close_profit=pos.get('close_profit'))
            update(result);return result
        if pos and (subscribed_id!=pos['id'] or now-last_subscription>=45):
            client.api.send_websocket_request('sendMessage',{'name':'portfolio.subscribe-positions','version':'1.0','body':{'frequency':'frequent','ids':[pos['id']]}},request_id='tp8-watch-'+uuid.uuid4().hex)
            client.api.send_websocket_request('subscribeMessage',{'name':'portfolio.positions-state','version':'1.0'},request_id=client.trace.request_id+'-tp8-state')
            subscribed_id=pos['id'];last_subscription=now
        if tracker.metrics:
            for field in ('sell_profit','pnl_net','pnl'):
                value=number(tracker.metrics.get(field))
                if value is not None:result['broker_'+field]=float(value)
        valuation=tracker.valuation(server_now)
        if valuation:result.update(valuation,monitor_status='MONITORANDO_LUCRO_RECOMPRA')
        elif pos:
            result['monitor_status']='AGUARDANDO_RECOMPRA_CONSISTENTE'
            for key in ('profit_pct','net_profit','target_reached'):result.pop(key,None)
        if close_pending:
            if tracker.close_ack is False:
                result['monitor_status']='RECOMPRA_RECUSADA';close_pending=False;last_close=now
            elif tracker.close_ack is True:result['monitor_status']='FECHAMENTO_ACEITO_AGUARDANDO_POSICAO'
            else:result['monitor_status']='FECHAMENTO_ENVIADO_SEM_CONFIRMACAO'
        if pos and valuation and valuation['target_reached'] and not close_pending and tracker.close_attempts<3 and now-last_close>=5 and server_now<expiry:
            # Revalidate demo identity and close ONLY the position mapped to this order.
            if client.get_balance_mode()!='PRACTICE' or client.get_balance_id()!=tracker.balance_id:
                result['monitor_status']='MONITOR_INTERROMPIDO_CONTA_ALTERADA';update(result);return result
            tracker.close_attempts+=1;tracker.close_ack=None;tracker.close_request_id='tp8-close-'+uuid.uuid4().hex
            result.update(monitor_status='SOLICITANDO_RECOMPRA_ALVO_8',trigger_profit_pct=valuation['profit_pct'],close_attempts=tracker.close_attempts)
            close_pending=True;last_close=now
            try:client.api.send_websocket_request('sendMessage',{'name':'digital-options.close-position','version':'1.0','body':{'position_id':pos['external_id']}},request_id=tracker.close_request_id)
            except Exception:result['monitor_status']='FECHAMENTO_INCERTO_NAO_REPETIR'
        if now-last_update>=1:
            update(dict(result))
            pct=result.get('profit_pct')
            progress('Ordem '+str(entry['order_id'])+' · '+('lucro recompra '+format(pct,'.2f')+'% · ' if pct is not None else '')+result['monitor_status']+' · alvo +8%')
            last_update=now
        time.sleep(.2)
    result['monitor_status']='MONITOR_FINALIZADO_SEM_CONFIRMACAO_DE_ENCERRAMENTO'
    update(result);return result
