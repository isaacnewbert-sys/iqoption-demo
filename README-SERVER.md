# IQ Demo — entrada e recompra demonstrativas

Conector não oficial, somente PRACTICE. Conta real não é suportada. Não é um robô de estratégia completo.

O painel oferece diagnóstico sem ordens e um teste CALL de 1 unidade virtual, na grade de 5 minutos.
Selecione EUR/USD Digital ou EUR/USD OTC Digital explicitamente. O envio exige conta tipo 4 confirmada,
nenhuma posição digital aberta, instrumento real do catálogo e cotações atuais válidas.

Depois da confirmação da ordem, o servidor monitora posições da IQ: associa order_id a position_id,
valida a conta, o ativo e o investimento, e assina portfolio.positions-state. A recompra só é solicitada
se sell_profit e pnl_net forem consistentes e indicarem lucro líquido >= 8% do investimento.
Valores ausentes, antigos ou inconsistentes bloqueiam a saída por alvo. Não usa candles para calcular lucro.
Sem stop por prejuízo: se não houver alvo executável, a opção segue até o vencimento.
A confirmação do pedido de fechamento não é confirmação da posição encerrada. O preço final pode variar.
Um fechamento incerto não é repetido; recusas explícitas permitem até 3 tentativas espaçadas.
Apenas a posição vinculada à ordem demonstrativa pode ser fechada. Nunca fecha posições de outros testes.

Limites: leitura 35 s; entrada com acompanhamento +8% até 700 s. O painel mostra andamento e resultado
parcial enquanto monitora. Abrir a página não abre ordens. Uma verificação de mercado na inicialização é
somente de leitura. Estado compartilhado em SQLite temporário; não é armazenamento durável.
Bloqueio local de repetição: 11 minutos, sujeito à perda em novo deploy. A consulta de posições na IQ
é obrigatória para toda entrada. Confira a conta PRACTICE se o resultado ficar incerto.

Variáveis protegidas no Render: PANEL_PASSWORD (usuário do painel isaac), IQ_EMAIL e IQ_PASSWORD.
Nenhuma senha deve ir ao GitHub ou ao chat. O teste de release usa uma capacidade temporária opcional,
expirável e de uso único, limitada a 1 CALL em EURUSD-OTC PRACTICE; desativada sem configuração explícita.

Hospedagem gratuita pode suspender e não é adequada para operação contínua. Monitoramento pode ser
interrompido por reinício, perda de conexão ou deploy; o broker continua sendo a referência da posição.
Um único worker Gunicorn é obrigatório para o bloqueio de concorrência do protótipo.

Testes: python -m unittest discover
Start: gunicorn --workers 1 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app
