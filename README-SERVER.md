# IQ Option Demo — servidor de validação

Painel protegido e diagnóstico não oficial. NÃO envia ordens, não é robô operacional.
A assinatura foi aceita nos testes do usuário, mas preços e contratos não chegaram.
O servidor desloca a execução do Pydroid para um ambiente controlável; não resolve
sozinho o protocolo. Credenciais nunca devem ser commitadas ou enviadas em mensagens.

Variáveis no Dashboard Render:
- PANEL_PASSWORD: senha longa exclusiva do painel; usuário de acesso `isaac`.
- IQ_EMAIL e IQ_PASSWORD: credenciais da IQ Option, inseridas somente pelo dono.

Sem PANEL_PASSWORD, servidor recusa acesso ao painel. Health não revela dados.
Processo separado para SDK, limite de 65 s, uma execução por vez, sem ordens.
Não persiste resultados/credenciais em arquivos. Credenciais permanecem em variáveis
do serviço; dono pode removê-las no Render. Logs do SDK são suprimidos.
Plano gratuito pode dormir e reiniciar; não é adequado a negociações contínuas.
Nenhuma estratégia com vantagem estatística foi demonstrada. Alvo +8% e perda até
100% requerem >92,59% de acerto se todos os resultados forem exatamente esses.

Start: gunicorn --workers 1 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app
Build: pip install -r requirements.txt && pip install --no-deps https://github.com/iqoptionapi/iqoptionapi/archive/8a903cc094a74af1ed935a56a2d6b5a9ed3319d7.zip
