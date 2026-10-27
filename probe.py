"""PRACTICE-only connector. One explicit demo test order after market validation."""
import argparse
import getpass
import logging
import threading
import queue as queue_module
import sys
import re
import time

VERSION = 'server-v20-market-instruments'

PIN = '8a903cc094a74af1ed935a56a2d6b5a9ed3319d7'

class WireTrace:
    # Keep only public-market packets and fixed diagnostic counters.
    # Never store profile, account balances, auth packets, tokens or error text.
    def __init__(self):
        self.catalog_received=False; self.catalog_match=None; self.catalog_assets=[]; self.instruments_received=False; self.instruments=[]; self.instrument_schema=[]; self.instruments_raw_count=0; self.subscription_acks={}
        self.asset_id=None; self.pair=None; self.candles=[]; self.event_counts={}; self.started_at=0
        self.order_request_id=None; self.order_reply=None; self.order_attempted=False
        self.frames=0; self.quotes=[]; self.parser_errors={}; self.errors=0
        self.responses=0; self.rejections=0; self.received_at=0
        self.new_packets=[]; self.secrets=[]; self.subscription_responses=[]; self.request_id="spotlab-readonly-digital-5m"
    def receive(self, payload):
        import json
        self.frames+=1
        try:
            event=json.loads(payload) if isinstance(payload,(str,bytes,bytearray)) else payload
            if not isinstance(event,dict): return
            name=event.get('name'); body=event.get('msg')
            # Fixed vocabulary only; unknown event names and arbitrary payloads stay private.
            known=('timeSync','heartbeat','result','error','subscription-result','candle-generated','candles-generated','client-price-generated','price-splitter.client-price-generated','instrument-quotes-generated','digital-option-client-price-generated','trading-settings.digital-option-client-price-generated','digital-option-instruments.underlying-list','digital-option-instruments.instruments','digital-option-instruments.instrument-generated','instrument-generated')
            label=name if name in known else 'other'
            self.event_counts[label]=self.event_counts.get(label,0)+1
            rid=str(event.get('request_id',''))
            if self.order_request_id and rid==self.order_request_id and isinstance(body,dict):
                if name in ('digital-option-placed','digital-options.digital-option-placed') and isinstance(body.get('id'),int) and not isinstance(body['id'],bool) and body['id']>0:
                    self.order_reply={'status':'ORDEM_DEMO_CONFIRMADA','order_id':body['id']}
                elif body.get('success') is False:
                    self.order_reply={'status':'ORDEM_DEMO_RECUSADA'}
            if rid==self.request_id+'-catalog' and isinstance(body,dict) and isinstance(body.get('underlying'),list):
                self.catalog_received=True
                self.catalog_assets=[{'active_id':r['active_id'],'name':r['name'],'is_suspended':r.get('is_suspended') if isinstance(r.get('is_suspended'),bool) else None} for r in body['underlying'] if isinstance(r,dict) and isinstance(r.get('active_id'),int) and isinstance(r.get('name'),str) and re.fullmatch(r'[A-Za-z0-9_/. -]{1,50}',r['name'])][:1000]
                for row in body['underlying']:
                    if isinstance(row,dict) and row.get('active_id')==self.asset_id:
                        self.catalog_match={'active_id':self.asset_id,'is_suspended':row.get('is_suspended') if isinstance(row.get('is_suspended'),bool) else None}
            if isinstance(body,dict) and isinstance(body.get('success'),bool) and rid.startswith(self.request_id):
                self.subscription_acks[rid]=body['success']
            generated=name in ('digital-option-instruments.instrument-generated','instrument-generated') and isinstance(body,dict) and body.get('asset_id')==self.asset_id
            if (rid==self.request_id+'-instruments' and isinstance(body,dict) and isinstance(body.get('instruments'),list)) or generated:
                if generated:body={'instruments':[body]}
                self.instruments_received=True
                self.instruments_raw_count=len(body['instruments'])
                self.instrument_schema=[{k:r[k] for k in ('asset_id','active_id','index','instrument_index','period','expiration','deadtime') if isinstance(r.get(k),(int,float)) and not isinstance(r.get(k),bool)} | {'fields_present':[k for k in ('asset_id','active_id','index','instrument_index','period','expiration','deadtime','instrument_type','data') if k in r],'type_is_digital':r.get('instrument_type')=='digital-option'} for r in body['instruments'][:6] if isinstance(r,dict)]
                for row in body['instruments']:
                    if not isinstance(row,dict) or row.get('asset_id')!=self.asset_id or row.get('instrument_type')!='digital-option':continue
                    fields=('asset_id','index','period','expiration','deadtime')
                    if not all(isinstance(row.get(k),(int,float)) and not isinstance(row.get(k),bool) for k in fields):continue
                    safe={k:row[k] for k in fields}
                    safe['symbols']=[{'direction':d['direction'],'symbol':d['symbol']} for d in row.get('data',[]) if isinstance(d,dict) and d.get('strike')=='SPT' and d.get('direction') in ('call','put') and isinstance(d.get('symbol'),str) and re.fullmatch(r'do[A-Za-z0-9_.-]+',d['symbol'])]
                    self.instruments.append(safe)
                self.instruments=self.instruments[-30:]
            if name=='candle-generated' and isinstance(body,dict) and body.get('active_id')==self.asset_id:
                import math
                close=body.get('close')
                if isinstance(close,(int,float)) and not isinstance(close,bool) and math.isfinite(close) and close>0:
                    self.candles.append({'close':close,'received_at':time.monotonic()})
                    self.candles=self.candles[-5:]

            if name in ('price-splitter.client-price-generated','client-price-generated','trading-settings.digital-option-client-price-generated','digital-option-client-price-generated') and isinstance(body,dict) and body.get('asset_id')==self.asset_id:
                # Public market event metadata only; no raw account payloads.
                row={k:body[k] for k in ('asset_id','active_id','expiration_period','instrument_index','timestamp','quote_time') if isinstance(body.get(k),(int,float))}
                row['fields']=[k for k in ('asset_id','active_id','expiration_period','instrument_index','timestamp','price','prices','quotes','symbols','expiration','instrument_type') if k in body]
                contracts=[]
                import math
                for strike in body.get('prices',[]):
                    if not isinstance(strike,dict) or strike.get('strike')!='SPT':continue
                    for direction in ('call','put'):
                        side=strike.get(direction,{})
                        if not isinstance(side,dict):continue
                        symbol=side.get('symbol','')
                        if not isinstance(symbol,str) or not re.fullmatch(r'do[A-Za-z0-9_.-]+',symbol) or not re.search(r'T5M[CP]',symbol):continue
                        contract={'direction':direction,'symbol':symbol}
                        for field in ('ask','bid'):
                            value=side.get(field)
                            try:
                                value=float(value)
                                if math.isfinite(value) and value>=0:contract[field]=value
                            except (ValueError,TypeError):pass
                        contracts.append(contract)
                row['spot_contracts_5m']=contracts
                row['received_at_monotonic']=time.monotonic()
                self.new_packets.append(row);self.new_packets=self.new_packets[-5:]


            # Correlate ONLY our market-data request. Never dump server payloads.
            if str(event.get('request_id','')) in (self.request_id,self.request_id+'-candles',self.request_id+'-catalog',self.request_id+'-instruments',self.request_id+'-prices'):
                info={'channel':'candles' if str(event.get('request_id','')).endswith('-candles') else 'digital', 'event':name if name in ('result','error','subscription-result') else 'other'}
                if isinstance(body,dict):
                    info['success']=body.get('success') if isinstance(body.get('success'),bool) else None
                    status=body.get('status')
                    info['status']=status if status in ('error','failed','rejected','success','ok') or isinstance(status,(int,float)) else 'omitted'
                    code=body.get('code')
                    info['numeric_code']=code if isinstance(code,(int,float)) else None
                    # Categorize free text; retain no arbitrary strings or credentials.
                    import json
                    text=json.dumps(body).lower()
                    categories=[]
                    for label,pattern in [('unsupported_version',r'unsupported.{0,30}version|version.{0,30}(unsupported|not supported|invalid)'),('unknown_event',r'(unknown|unsupported|invalid).{0,30}(event|message|subscription|name)'),('invalid_parameters',r'(invalid|missing|incorrect).{0,30}(param|filter|active|period)'),('permission',r'forbidden|permission|not allowed|unauthorized|access denied'),('unavailable',r'unavailable|not available|market.{0,15}closed')]:
                        if re.search(pattern,text):categories.append(label)
                    info['reason_categories']=categories or ['unclassified']
                    # Only our correlated failed response, never an account packet.
                    if body.get('success') is False:
                        detail={key:body[key] for key in ('message','reason','error','code','status') if key in body}
                        cleaned=json.dumps(detail,ensure_ascii=False,default=lambda _: '[omitted]')
                        for secret in self.secrets:
                            if secret: cleaned=cleaned.replace(secret,'[removed]')
                        cleaned=re.sub(r'[\w.+-]+@[\w.-]+','[email removed]',cleaned)
                        cleaned=re.sub(r'(?i)(token|password|passwd|ssid|cookie|authorization|session)[\s\"\':=]+[^,}\s]+',r'\1:[removed]',cleaned)
                        cleaned=re.sub(r'[A-Za-z0-9_+/=-]{24,}','[identifier removed]',cleaned)
                        info['server_reason_redacted']=cleaned[:800]
                else: info['body_type']=type(body).__name__
                self.subscription_responses.append(info)
                self.subscription_responses=self.subscription_responses[-5:]

            if name in ('result','error','subscription-result'):
                self.responses+=1
                if isinstance(body,dict) and (body.get('success') is False or body.get('status') in ('error','failed','rejected')):
                    self.rejections+=1
            if name!='instrument-quotes-generated' or not isinstance(body,dict): return
            expiration=body.get('expiration')
            if not isinstance(expiration,dict) or expiration.get('period')!=300: return
            # EURUSD active ID checked by the caller against SDK constants.
            active=body.get('active')
            public=[]
            for quote in body.get('quotes',[]):
                if not isinstance(quote,dict): continue
                symbols=[v for v in quote.get('symbols',[]) if isinstance(v,str) and re.fullmatch(r'do[A-Za-z0-9_-]+[0-9]{12}PT5M[CP][A-Za-z0-9.]*',v)]
                if symbols: public.append({'symbols':symbols})
            if public:
                self.quotes.append({'msg':{'active':active,'expiration':{'period':300,'timestamp':expiration.get('timestamp')},'quotes':public}})
                self.quotes=self.quotes[-10:];self.received_at=time.monotonic()
        except Exception:
            self.errors+=1
    def summary(self):
        return {'catalog_received':self.catalog_received,'catalog_assets':self.catalog_assets,'catalog_match':self.catalog_match,'instruments_received':self.instruments_received,'instruments_raw_count':self.instruments_raw_count,'instrument_schema':self.instrument_schema,'instruments':self.instruments,'event_counts':dict(self.event_counts),'underlying_updates':len(self.candles),'subscription_responses':self.subscription_responses,'price_splitter_packets':self.new_packets,'received_frames':self.frames,'market_packets_5m':len(self.quotes),'parser_exceptions':self.parser_errors,'websocket_errors':self.errors,'responses_seen':self.responses,'rejections_seen':self.rejections}

def install_compatibility(trace):
    from iqoptionapi.ws.client import WebsocketClient
    import iqoptionapi.global_value as flags
    original=WebsocketClient.on_message
    def on_message(self,*args):
        payload=args[-1] if args else ''
        trace.receive(payload)
        try: return original(self,payload)
        except Exception as error:
            name=type(error).__name__
            trace.parser_errors[name]=trace.parser_errors.get(name,0)+1
        finally:
            # The legacy handler leaves this flag locked when a parser fails.
            flags.ssl_Mutual_exclusion=False
    def on_error(*args):
        trace.errors+=1
        flags.check_websocket_if_error=True
        flags.websocket_error_reason='WebSocket error (details omitted)'
    def on_close(*args): flags.check_websocket_if_connect=0
    WebsocketClient.on_message=on_message
    WebsocketClient.on_error=staticmethod(on_error)
    WebsocketClient.on_close=staticmethod(on_close)

def verified_contracts(trace, server_time):
    """Require both current 5m directions, correct asset, finite executable quotes.

    This validates market data only; never authorizes or sends an order.
    """
    import math
    from datetime import datetime, timezone
    if not isinstance(server_time,(int,float)) or not math.isfinite(server_time): return []
    for packet in reversed(trace.new_packets):
        if packet.get('asset_id')!=trace.asset_id: continue
        if time.monotonic()-packet.get('received_at_monotonic',0)>5: continue
        metadata=None
        if 'instrument_index' in packet:
            metadata=next((i for i in trace.instruments if i['index']==packet['instrument_index'] and i['period']==300),None)
            if metadata is None or not metadata['expiration']-metadata['deadtime']>server_time:continue
        if 'quote_time' in packet:
            qt=packet['quote_time'];qt=qt/1000 if qt>1e12 else qt
            if abs(server_time-qt)>5:continue
        valid=[]
        for contract in packet.get('spot_contracts_5m',[]):
            symbol=contract.get('symbol','')
            direction=contract.get('direction')
            letter={'call':'C','put':'P'}.get(direction)
            # Formats observed in the community SDK: numeric asset and legacy pair.
            modern=re.fullmatch(r'do(\d+)A(\d{8})D(\d{6})T5M([CP])SPT',symbol)
            legacy=re.fullmatch(r'do([A-Za-z0-9_-]+?)(\d{12})PT5M([CP])SPT',symbol)
            try:
                if modern and int(modern[1])==trace.asset_id and modern[4]==letter:
                    expiry=datetime.strptime(modern[2]+modern[3],'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).timestamp()
                elif legacy and legacy[1]==trace.pair and legacy[3]==letter:
                    expiry=datetime.strptime(legacy[2],'%Y%m%d%H%M').replace(tzinfo=timezone.utc).timestamp()
                else: continue
            except ValueError: continue
            # Use IQ server time, not the phone clock. Do not fabricate expiry IDs.
            if not 0<expiry-server_time<=600: continue
            if metadata and (expiry!=metadata['expiration'] or not any(d['symbol']==symbol and d['direction']==direction for d in metadata['symbols'])):continue
            ask=contract.get('ask'); bid=contract.get('bid')
            if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (ask,bid)):continue
            if not 0<ask<=100 or not 0<=bid<=ask:continue
            valid.append(dict(contract,expiration_timestamp=expiry))
        if {c['direction'] for c in valid}=={'call','put'} and len({c['expiration_timestamp'] for c in valid})==1:
            return valid
    return []

def inspect_client(client, pair, progress=lambda stage: None):
    progress("Selecionando conta PRACTICE")
    client.change_balance('PRACTICE')
    progress("Confirmando conta PRACTICE")
    if client.get_balance_mode() != 'PRACTICE':
        raise RuntimeError('Conta demonstrativa não confirmada; interrompido.')
    import iqoptionapi.constants as constants
    trace=client.trace
    trace.asset_id=int(constants.ACTIVES[pair]);trace.pair=pair
    trace.event_counts={};trace.started_at=time.monotonic()
    progress('Consultando catálogo e instrumentos digitais versão 3')
    # Protocol source: TradeCodeHub/client-sdk-js src/index.ts, v3 instruments.
    client.api.send_websocket_request('sendMessage',{
        'name':'digital-option-instruments.get-underlying-list','version':'3.0',
        'body':{'filter_suspended':True}},request_id=trace.request_id+'-catalog')
    catalogue_deadline=time.monotonic()+5
    while not trace.catalog_received and time.monotonic()<catalogue_deadline:time.sleep(.1)
    # Resolve by exact requested name as well as ID; do not substitute OTC or another pair.
    named=next((a for a in trace.catalog_assets if a['name'].replace('/','')==pair),None)
    if named is None:
        named=next((a for a in trace.catalog_assets if a['name'].replace('/','')==pair+'-op'),None)
    if named:
        trace.asset_id=named['active_id'];trace.pair=named['name'];trace.catalog_match=named
        # The pinned SDK constants predate -op assets; synchronize its parser with public catalogue IDs.
        for asset in trace.catalog_assets:constants.ACTIVES[asset['name']]=asset['active_id']
    if not trace.catalog_received or trace.catalog_match:
        # SDK v3 subscribes instrument generation BEFORE requesting current state.
        progress('Assinando geração dos instrumentos digitais do ativo selecionado')
        client.api.send_websocket_request('subscribeMessage',{
            'name':'digital-option-instruments.instrument-generated','version':'3.0',
            'params':{'routingFilters':{'asset_id':trace.asset_id}}},request_id=trace.request_id+'-generated')
        ack_deadline=time.monotonic()+2
        while trace.request_id+'-generated' not in trace.subscription_acks and time.monotonic()<ack_deadline:time.sleep(.05)
        client.api.send_websocket_request('sendMessage',{
            'name':'digital-option-instruments.get-instruments','version':'3.0',
            'body':{'asset_id':trace.asset_id}},request_id=trace.request_id+'-instruments')
    client.api.send_websocket_request('subscribeMessage',{
        'name':'candle-generated',
        'params':{'routingFilters':{'active_id':str(trace.asset_id),'size':60}}},
        request_id=trace.request_id+'-candles')
    lookup_deadline=time.monotonic()+8
    while (not trace.catalog_received or trace.catalog_match) and not trace.instruments_received and time.monotonic()<lookup_deadline:time.sleep(.1)
    if trace.catalog_match and not trace.instruments_received:
        progress('Consultando formato compatível de instrumentos digitais versão 1')
        # Legacy primary source: ViniciosPsidonik/iq metatrader.js get-instruments v1.
        client.api.send_websocket_request('sendMessage',{
            'name':'digital-option-instruments.get-instruments','version':'1.0',
            'body':{'instrument_type':'digital-option','asset_id':trace.asset_id}},
            request_id=trace.request_id+'-instruments')
        fallback_deadline=time.monotonic()+5
        while not trace.instruments_received and time.monotonic()<fallback_deadline:time.sleep(.1)
    server_time=client.api.timesync.server_timestamp
    candidates=sorted([i for i in trace.instruments if i['period']==300 and 0<i['expiration']-server_time<=600 and i['expiration']-i['deadtime']>server_time],key=lambda i:i['expiration'])
    progress('Assinando preços dos contratos de 5 minutos' if candidates else 'A IQ não retornou instrumento disponível de 5 minutos')
    for instrument in candidates[:2]:
        client.api.send_websocket_request('subscribeMessage',{
            'name':'trading-settings.digital-option-client-price-generated','version':'1.0',
            'params':{'routingFilters':{'instrument_type':'digital-option','asset_id':trace.asset_id,'instrument_index':int(instrument['index'])}}},
            request_id=trace.request_id+'-prices')
    deadline=time.monotonic()+(8 if candidates else 0)
    contracts=[]
    while time.monotonic()<deadline:
        contracts=verified_contracts(trace,client.api.timesync.server_timestamp)
        if contracts and len(trace.candles)>=2:break
        time.sleep(.1)
    contracts=verified_contracts(trace,client.api.timesync.server_timestamp)
    return {'probe_version':VERSION,'account':'PRACTICE','login_confirmed':True,'requested_pair':pair,'pair':trace.pair,
            'requested_duration_minutes':5,'orders_sent':0,'early_sell_verified':False,
            'contracts_verified':bool(contracts),'contracts':contracts,
            'underlying_price_received':bool(trace.candles),
            'status':'CONTRATOS_5M_RECEBIDOS_EXECUCAO_PENDENTE' if contracts else ('ATIVO_NAO_LISTADO_NO_CATALOGO_DIGITAL' if trace.catalog_received and not trace.catalog_match else 'CONTRATOS_5M_NAO_CONFIRMADOS'),
            'websocket':trace.summary()}

def send_demo_test(client):
    """One fixed-size demo CALL. Never retry an uncertain submission."""
    trace=client.trace
    blocked=lambda reason:{'order_status':reason,'orders_sent':0,'order_attempted':False}
    if trace.order_attempted:return blocked('BLOQUEADO_TENTATIVA_JA_REALIZADA')
    if client.get_balance_mode()!='PRACTICE':return blocked('BLOQUEADO_CONTA_NAO_DEMO')
    balance_id=client.get_balance_id()
    profile=client.get_profile_ansyc()
    balance=next((b for b in profile.get('balances',[]) if b.get('id')==balance_id and b.get('type')==4),None)
    if not balance:return blocked('BLOQUEADO_SALDO_DEMO_NAO_CONFIRMADO')
    # Bound the SDK's normally unbounded position lookup. Unknown schema blocks sending.
    client.api.positions=None
    client.api.get_positions('digital-option')
    deadline=time.monotonic()+5
    while client.api.positions is None and time.monotonic()<deadline:time.sleep(.05)
    response=client.api.positions
    if not isinstance(response,dict) or response.get('status')!=2000:return blocked('BLOQUEADO_POSICOES_NAO_CONFIRMADAS')
    body=response.get('msg',{})
    positions=body.get('positions') if isinstance(body,dict) else None
    if not isinstance(positions,list):return blocked('BLOQUEADO_FORMATO_POSICOES')
    if positions:return blocked('BLOQUEADO_POSICAO_DIGITAL_EXISTENTE')
    contracts=verified_contracts(trace,client.api.timesync.server_timestamp)
    contract=next((c for c in contracts if c['direction']=='call'),None)
    if not contract:return blocked('BLOQUEADO_SEM_CONTRATO_5M_VALIDO')
    instrument=next((i for i in trace.instruments if i['period']==300 and i['expiration']==contract['expiration_timestamp'] and any(d['symbol']==contract['symbol'] and d['direction']=='call' for d in i['symbols'])),None)
    if not instrument:return blocked('BLOQUEADO_INSTRUMENTO_NAO_CONFIRMADO')
    if instrument['expiration']-instrument['deadtime']-client.api.timesync.server_timestamp<15:return blocked('BLOQUEADO_VENCIMENTO_PROXIMO')
    # Recheck account immediately before the only write; never construct a contract ID.
    if client.get_balance_mode()!='PRACTICE' or client.get_balance_id()!=balance_id:return blocked('BLOQUEADO_CONTA_ALTERADA')
    import uuid
    trace.order_request_id='demo-test-'+uuid.uuid4().hex
    trace.order_attempted=True
    payload={'name':'digital-options.place-digital-option','version':'3.0','body':{
        'amount':'1','asset_id':trace.asset_id,'instrument_id':contract['symbol'],
        'instrument_index':int(instrument['index']),'user_balance_id':int(balance_id)}}
    result={'order_status':'ENVIO_INCERTO_NAO_REPETIR','orders_sent':None,'order_attempted':True,'amount':1,'direction':'call','account':'PRACTICE','expiration_timestamp':instrument['expiration'],'early_sell_verified':False}
    try:
        client.api.send_websocket_request('sendMessage',payload,request_id=trace.order_request_id)
        deadline=time.monotonic()+8
        while trace.order_reply is None and time.monotonic()<deadline:time.sleep(.05)
        if trace.order_reply:
            result.update(order_status=trace.order_reply['status'],orders_sent=1 if trace.order_reply['status']=='ORDEM_DEMO_CONFIRMADA' else 0)
            if 'order_id' in trace.order_reply:result['order_id']=trace.order_reply['order_id']
    except Exception:
        # Transport errors after calling send may still mean the server received the order.
        pass
    return result

def worker(queue, email, password, pair, test_order=False):
    # The old SDK may write authentication details on errors; suppress its logs.
    logging.disable(logging.CRITICAL)
    import contextlib
    import os
    client = None
    progress=lambda stage: queue.put({"progress":stage})
    try:
        with open(os.devnull,'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            progress("Carregando biblioteca")
            from iqoptionapi.stable_api import IQ_Option
            trace=WireTrace()
            trace.secrets=[email,password]
            install_compatibility(trace)
            client = IQ_Option(email,password)
            client.trace=trace
            progress("Autenticando e abrindo conexão IQ Option")
            ok, _reason = client.connect()
            if not ok:
                queue.put({'error':('Autenticação em duas etapas solicitada. Este diagnóstico não implementa a etapa de 2FA.' if _reason=='2FA' else 'Login não concluído; causa não confirmada. Confira acesso no aplicativo oficial. Nenhuma ordem enviada.')})
                return
            progress("Conexão inicial aceita; verificando conta")
            result = inspect_client(client,pair,progress)
            if test_order:
                progress('Validando conta e condições para uma ordem demonstrativa de 1 unidade')
                result.update(send_demo_test(client))
        queue.put(result)
    except Exception as error:
        # Do not print exception contents: SDK may embed credentials or account IDs.
        queue.put({'error':('Dependência ausente: instale a biblioteca iqoptionapi no mesmo Pydroid.' if isinstance(error, ModuleNotFoundError) else 'Diagnóstico interrompido ('+type(error).__name__+'). Nenhuma ordem enviada.')})
    finally:
        if client:
            try: client.api.close()
            except Exception: pass

def main():
    parser = argparse.ArgumentParser(description='Testar conexão não oficial IQ Option, somente demonstrativa e sem ordens.')
    parser.add_argument('--par',default='EURUSD',help='Identificador exato do par; padrão EURUSD. Não troca para OTC automaticamente.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{2,30}',args.par):
        parser.error('Identificador de par inválido.')
    print('Versão: '+VERSION)
    print('Teste de compatibilidade não oficial. Não envia compras ou vendas.')
    print('Informe as credenciais somente neste terminal local. Elas não serão salvas.')
    email = input('E-mail IQ Option: ').strip()
    password = getpass.getpass('Senha IQ Option (oculta): ')
    # Pydroid executes the file through exec(), without an importable __main__.
    # A daemon thread avoids spawn/pickle/__spec__ requirements entirely.
    console = sys.stdout
    queue = queue_module.Queue()
    process = threading.Thread(target=worker,args=(queue,email,password,args.par),daemon=True)
    process.start()
    del password
    try:
        import json
        stage='Iniciando diagnóstico'
        deadline=time.monotonic()+45
        total_deadline=time.monotonic()+120
        while True:
            try: message=queue.get(timeout=max(.01,min(deadline,total_deadline)-time.monotonic()))
            except queue_module.Empty:
                result={'error':'Tempo limite na etapa: '+stage+'. Nenhuma ordem enviada.',
                        'login_confirmed':False if 'Autenticando' in stage else 'Não concluir por este campo; confira as etapas acima.'}
                break
            if 'progress' in message:
                stage=message['progress']
                print('Etapa: '+stage,file=console,flush=True)
                deadline=time.monotonic()+45
                continue
            result=message
            break
        print(json.dumps(result,ensure_ascii=False,indent=2),file=console,flush=True)
        print('Automação de ordens permanece desligada. Recompra +8% ainda precisa ser validada na plataforma.',file=console,flush=True)
    finally:
        if process.is_alive():
            print('Diagnóstico ainda em encerramento. Se não finalizar, use Parar no Pydroid antes de executar novamente.',file=console,flush=True)

if __name__ == '__main__': main()
