"""Local PRACTICE-only compatibility probe. Never submits buy/sell orders."""
import argparse
import getpass
import logging
import threading
import queue as queue_module
import sys
import re
import time

VERSION = 'Pydroid-v11-leitura-call-put'

PIN = '8a903cc094a74af1ed935a56a2d6b5a9ed3319d7'

class WireTrace:
    # Keep only public-market packets and fixed diagnostic counters.
    # Never store profile, account balances, auth packets, tokens or error text.
    def __init__(self):
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
            if name in ('price-splitter.client-price-generated','client-price-generated') and isinstance(body,dict):
                # Public market event metadata only; no raw account payloads.
                row={k:body[k] for k in ('asset_id','active_id','expiration_period','instrument_index','timestamp') if isinstance(body.get(k),(int,float))}
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
                self.new_packets.append(row);self.new_packets=self.new_packets[-5:]


            # Correlate ONLY our market-data request. Never dump server payloads.
            if str(event.get('request_id',''))==self.request_id:
                info={'event':name if name in ('result','error','subscription-result') else 'other'}
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
        return {'subscription_responses':self.subscription_responses,'price_splitter_packets':self.new_packets,'received_frames':self.frames,'market_packets_5m':len(self.quotes),'parser_exceptions':self.parser_errors,'websocket_errors':self.errors,'responses_seen':self.responses,'rejections_seen':self.rejections}

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

def inspect_client(client, pair, progress=lambda stage: None):
    progress("Selecionando conta PRACTICE")
    client.change_balance('PRACTICE')
    progress("Confirmando conta PRACTICE")
    if client.get_balance_mode() != 'PRACTICE':
        raise RuntimeError('Conta demonstrativa não confirmada; interrompido.')
    progress('Assinando canal alternativo price-splitter para digitais de 5 minutos')
    import iqoptionapi.constants as constants
    client.api.send_websocket_request('subscribeMessage',{
        'name':'price-splitter.client-price-generated','version':'1.0',
        'params':{'routingFilters':{'instrument_type':'digital-option',
                  'expiration_period':300,'asset_id':int(constants.ACTIVES[pair])}}},
        request_id=client.trace.request_id)
    deadline=time.monotonic()+20
    while not any(p.get('spot_contracts_5m') for p in client.trace.new_packets) and time.monotonic()<deadline:
        time.sleep(.1)
    return {'account':'PRACTICE','login_confirmed':True,'pair':pair,
            'requested_duration_minutes':5,'orders_sent':0,'early_sell_verified':False,
            'status':'CONTRATOS_5M_RECEBIDOS_EXECUCAO_PENDENTE' if any(p.get('spot_contracts_5m') for p in client.trace.new_packets) else 'CONTRATOS_5M_NAO_CONFIRMADOS',
            'websocket':client.trace.summary()}

def worker(queue, email, password, pair):
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
