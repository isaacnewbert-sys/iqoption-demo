# IQ Demo — teste de execução demonstrativa

Conector não oficial, restrito à conta PRACTICE. Não é um robô de estratégia operacional.

O painel permite diagnóstico sem ordens e uma solicitação explícita de teste CALL de
1 unidade do saldo virtual, em contrato disponível na grade de 5 minutos. O envio só
ocorre com conta tipo 4 confirmada, nenhuma posição digital aberta, instrumento do
catálogo e cotações Call/Put recentes e válidas. A conta real não é suportada.

O botão de teste não usa sinal de estratégia. Saída antecipada em +8% ainda NÃO foi
implementada nem validada; a operação de teste, se aceita, permanece até o vencimento.
Uma assinatura aceita, um teste local ou um deploy saudável não comprovam execução.

Variáveis no Render Dashboard: PANEL_PASSWORD (usuário do painel: isaac), IQ_EMAIL e
IQ_PASSWORD. Nunca coloque credenciais no GitHub ou em mensagens.

No início do servidor roda apenas um diagnóstico de leitura. Ordens não são enviadas
em reinícios. POST /demo-order exige autenticação e X-Demo-Panel: 1. Cada solicitação
fica bloqueada contra repetição por 11 minutos, inclusive se houver falha de transporte.
A trava local pode ser perdida em novo deploy; a consulta de posições na IQ continua
obrigatória antes de enviar. Confira PRACTICE no app oficial se o envio ficar incerto.
Não existe reenvio automático. Um timeout após a solicitação não comprova ausência de ordem.

Hospedagem gratuita pode suspender; não é adequada à operação contínua. Um worker
Gunicorn é obrigatório para o bloqueio de concorrência deste protótipo.

Testes: python -m unittest test_demo_order.py
Start: gunicorn --workers 1 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app
