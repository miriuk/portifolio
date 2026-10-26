# CryptoArena

Um mercado de criptomoedas **simulado** onde múltiplos agentes de trading competem,
erram, acertam — e **aprendem com o próprio histórico**, episódio após episódio.

Inspirado nos agentes autônomos com carteira real que viralizaram (Alpha Arena da
Nof1, bots do ecossistema eliza), mas construído em torno do que nenhum projeto
open-source combina hoje¹: mercado multi-agente + memória persistente entre
episódios + reflexão sobre resultados + evolução populacional.

## O ciclo de aprendizado

```
┌──────────── episódio N ────────────┐
│ mercado sintético (regimes ocultos:│
│ bull/bear/chop/mania/crash + jumps)│
│   agentes observam → decidem →     │
│   risk manager corta excessos →    │
│   exchange cobra taxa + slippage   │
└────────────────┬───────────────────┘
                 ▼
   diário de trades (SQLite, persistente)
                 ▼
   reflexão pós-episódio → lições explícitas
   ("3 stop-losses: entradas agressivas demais",
    "perdeu no regime crash: reduza atividade lá",
    "0 trades: passivo demais, afrouxe entradas")
                 ▼
   agente.learn(lições) → parâmetros mudam
   agente LLM: lições entram no prompt + auto-reflexão escrita pelo Claude
                 ▼
   evolução: o pior agente herda parâmetros
   mutados do melhor (seleção por torneio)
                 ▼
        episódio N+1 (memória preservada)
```

A memória sobrevive a reinícios: pare o programa, rode de novo, e os agentes
continuam de onde pararam — com os parâmetros evoluídos e as lições acumuladas.

## Uso

```bash
pip install -e .

# torneio de aprendizado: 5 episódios de um mês (barras horárias)
cryptoarena run --episodes 5

# incluir o agente Claude (precisa de ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
cryptoarena run --episodes 5 --llm

# ver o que um agente aprendeu
cryptoarena lessons meanrev-1

# zerar a memória e começar do zero
cryptoarena reset
```

## Os agentes

| Agente | Estratégia | Como aprende |
|---|---|---|
| `momentum-*` | compra força de 7 a 14 dias, vende fraqueza | lições → ajuste de parâmetros + evolução |
| `meanrev-*` | compra quedas fundas abaixo da média semanal, com stop | idem |
| `breakout-1` | compra máximas de 7 dias, trailing stop de 8% | idem |
| `regime-1` | surfa tendência, senta no chop, zera em pânico | idem |
| `voltarget-1` | tendência com posição dimensionada pela vol | idem |
| `trend-1` | média de 3 dias acima da de 10 dias: comprado; senão, caixa | idem |
| `claude-trader` | decide via LLM (saída estruturada) | lições injetadas no prompt + auto-reflexão pós-episódio escrita pelo próprio modelo |

### Quem é quem

Cada agente tem nome, cargo e um superpoder (`world/personas.py`). Eles
aparecem no escritório, no feed da mesa, no dashboard, no `status.json` e na
nota do chefe de gabinete. Os ids continuam os mesmos no diário e no estado
salvo. Um estagiário herda o nome de quem o contratou, com "Jr." e o número:
`momentum-3`, contratado pela Rita, aparece como **Rita Jr. 3**.

| | Nome | Cargo | Superpoder | id |
|---|---|---|---|---|
| 🏃 | Rita Rush | Trader de momentum (tiro curto) | Embarca na arrancada curta de um papel antes da multidão | `momentum-1` |
| 🏔️ | Marco Maratona | Trader de momentum (fôlego longo) | Segue a tendência longa e ignora o barulho do dia a dia | `momentum-2` |
| 🪃 | Bea Bounce | Caçadora de quedas | Compra quando um papel cai bem abaixo da média recente e vende no repique | `meanrev-1` |
| 🧘 | Theo Paciência | Contrarian profundo | Espera um tombo fundo abaixo da média longa e compra o que todos vendem | `meanrev-2` |
| ⚡ | Nina Faísca | Caçadora de rompimentos | Compra a máxima nova e protege o ganho com um stop móvel de 8% | `breakout-1` |
| 🌦️ | Otto Clima | Estrategista de regime | Lê se o mercado está em tendência ou de lado e troca de manual | `regime-1` |
| 🎚️ | Vera Calma | Gestora de volatilidade | Dosa cada aposta pelo quanto o papel balança e sai quando fica bravo demais | `voltarget-1` |
| 🧭 | Tomás Bússola | Seguidor de tendência | Fica comprado enquanto a média curta está acima da longa | `trend-1` |
| 🗿 | Inês Índice | Investidora passiva (só ações) | Compra SPY e QQQ uma vez e nunca vende | `index-1` |
| 🐻 | Bruno Urso | Vendedor a descoberto (contratável) | Ganha quando os preços caem | `bear-*` |
| 🔄 | Rosa Rotação | Rotadora de setores (contratável) | Move o dinheiro para o que está mais forte agora | `rotation-*` |
| 🎯 | Paulo Recuo | Comprador de recuos (contratável) | Compra quedas, só dentro de uma tendência de alta | `pullback-*` |
| 📊 | Walter Volume | Leitor de Wyckoff (contratável) | Compra o spring e o sinal de força, sai no upthrust e no sinal de fraqueza | `wyckoff-*` |
| 〽️ | Maria MACD | Cruzadora de médias (formada no curso 2) | Compra no cruzamento da média curta para cima, vende no cruzamento para baixo | `macd-*` |
| 📏 | Bento Bollinger | Caçador de extremos (formado no curso 2) | Compra abaixo da banda inferior de Bollinger, vende acima da superior | `bollinger-*` |
| 💧 | Chica Chaikin | Leitora do fluxo de dinheiro (formada no curso 2) | Compra quando o fluxo de dinheiro de Chaikin entra, vende quando sai | `chaikin-*` |
| 🤖 | Clara IA | Analista de IA | Lê o mercado e escreve o próprio plano com um modelo de linguagem | `claude-trader` |

A mesa acima deles: 🚧 **Rick Guarda**, oficial de risco (diz não quando
a colônia inteira corre para o mesmo papel); 📒 **Pam Livro**, gestora do
livro do PM (junta os votos num livro só e economiza taxas); 🗂️ **Cleo
Pauta**, chefe de gabinete (escreve a nota do dia e só chama o dono quando
há decisão). Para trocar um nome, edite `FOUNDERS`, `BY_STRATEGY` ou `DESK`
em `world/personas.py`.

Todos os agentes de regra compartilham duas disciplinas, ajustáveis por
parâmetro: um **portão de tendência** (`trend_filter`, 28 dias por padrão:
só compram um ativo que está acima de onde estava 4 semanas atrás) e um
**trailing stop** opcional (`stop_trail`). Os horizontes são semanais de
propósito: em backtest com um ano de velas reais, os parâmetros horários
originais giravam demais e as taxas comiam o resultado (veja
*Backtests com dados reais*).

Todos passam pelo mesmo funil de risco (posição máx. 35% do capital, ordem máx.
25%, stop-loss forçado a -12%, kill switch a -50% de drawdown) e pagam taxas e
slippage proporcional ao tamanho da ordem — negociar demais ou grande demais
custa caro, e essas dores viram lições.

## Dados reais em vez de mercado sintético

```bash
pip install ccxt
python scripts/download_data.py --symbol BTC/USDT --days 365 --out data/BTCUSDT.csv
```

E use `ReplayMarket(["data/BTCUSDT.csv"])` como `market_factory` no torneio
(o mercado sintético continua sendo o default — regimes controláveis e
episódios infinitos são melhores para treinar).

## Arquitetura

```
src/cryptoarena/
├── market/      candle, mercado sintético com regimes, replay de CSV,
│                exchange simulada (taxas, slippage, impacto de mercado)
├── portfolio/   carteira paper + risk manager (limites fora do controle do agente)
├── agents/      base observe→decide→learn, agentes de regra, agente Claude
├── learning/    diário SQLite (trades, lições, parâmetros), reflexão, evolução
└── arena/       episódio, torneio com loop de aprendizado, leaderboard
```

## Mercado endógeno (order book)

```bash
cryptoarena run --episodes 5 --endogenous
```

Em vez de preços vindos de um gerador, os agentes negociam contra um **order
book compartilhado**: noise traders cotam liquidez em torno de um valor
fundamental oculto, e as ordens dos agentes consomem essa liquidez — uma compra
grande paga preço médio pior, deixa o book mais fino para o próximo agente no
mesmo passo, e o candle seguinte abre onde o fluxo empurrou o preço. Erros de
tamanho de ordem viram perdas reais de execução (padrão do `llm_trading_sim`).

## Memória em camadas

As lições têm **importância**: uma lição repetida é reforçada (importância sobe,
decai mais devagar) em vez de duplicada; a cada episódio todas decaem 15% e as
que caem abaixo do limiar são esquecidas. A recuperação é **por condição**: o
agente Claude classifica o regime percebido (via momentum/volatilidade públicos)
e recebe as lições aprendidas em condições parecidas, não apenas as mais
recentes — o desenho do FinMem/FinAgent.

## Dashboard ao vivo

```bash
pip install -e ".[ui]"
cryptoarena dashboard          # abre em http://localhost:8501
```

Em outro terminal, rode o torneio apontando para o mesmo `--db`:

```bash
cryptoarena run --episodes 5
```

O dashboard lê o banco SQLite direto (modo WAL, leitura segura enquanto o
torneio escreve) e atualiza sozinho a cada 5 segundos: leaderboard
cumulativo, curvas de patrimônio por agente, trades recentes e as lições
que cada agente está aprendendo, ordenadas por importância. Funciona com
qualquer `--db` customizado: `cryptoarena dashboard --db meu_arena.db`.

Também dá para **iniciar o torneio pela própria página**: a barra lateral
tem episódios, dias por episódio, mercado endógeno e o agente Claude (se
houver chave), e roda tudo numa thread em background enquanto a página
acompanha o progresso.

## Publicar na web (Streamlit Community Cloud)

O repositório já vem pronto para deploy: `streamlit_app.py` na raiz,
`requirements.txt`, `.streamlit/config.toml`.

1. Suba o código para o GitHub e entre em <https://share.streamlit.io>
   com a conta do GitHub.
2. **New app** → escolha o repositório e a branch, e em *Main file path*
   coloque `streamlit_app.py`. Em *Advanced settings*, Python 3.11.
3. (Opcional, só para o agente Claude) em *Secrets* cole
   `ANTHROPIC_API_KEY = "sk-ant-..."` — veja
   `.streamlit/secrets.toml.example`. A chave fica no servidor, nunca no
   código nem no navegador dos visitantes.
4. **Deploy**. Em ~2 minutos a URL pública fica no ar; qualquer visitante
   aperta **Start** na barra lateral e assiste ao torneio.

Vale saber: o plano gratuito hiberna o app após alguns dias sem acesso
(acorda no próximo clique) e o disco é efêmero — o `arena.db` recomeça a
cada reinício, o que para uma demo é até desejável. Hugging Face Spaces
funciona com os mesmos arquivos (SDK *streamlit*, arquivo
`streamlit_app.py`).

## Colônia de sobrevivência (meta diária ou morte)

```bash
cryptoarena survive --days 60 --budget 1000 --target 0.005
```

O esquema viral dos agentes auto-replicantes, feito de forma honesta: cada
agente recebe um **orçamento** e uma **meta diária**; a carteira **não
zera** entre os dias e um **custo de vida** (compute/API) é cobrado todo
dia. Quem fecha o dia abaixo da linha de morte — ou dispara o kill switch —
é desligado para sempre. Quem bate a meta ganha o direito de **clonar**: o
filho é pago com o **lucro do próprio pai, em dinheiro**, nasce com
parâmetros mutados e herda as lições do pai. Ou seja, a colônia só cresce
quando alguém de fato ganhou dinheiro, e cada morte fica registrada — sem
viés de sobrevivência.

| Parâmetro | Default | O que faz |
|---|---|---|
| `--budget` | 5 | uma "nota de cinco" por agente (unidades de cotação) |
| `--clone-at` | 1.1 | contrata um clone quando o patrimônio atinge esse múltiplo do orçamento (1.1 = +10%); o filho **nasce com o excedente** (pai a £5,60 → filho com £0,60, pai volta a £5) |
| `--min-child` | 0.2 | excedente mínimo para virar filho; abaixo disso fica com o pai |
| `--target` | 0.5%/dia | meta diária: define sequências, festas e imunidade |
| `--death` | 60% | estagiário é dispensado abaixo dessa fração do próprio orçamento |
| `--cost` | 0.02%/dia | aluguel: sai do caixa todo dia, operando ou não (0,1%/dia custava 3% ao mês, mais que qualquer estratégia rende) |
| `--pressure` | 0 | após cada meta perdida, ordens × (1+pressão): a ruína do jogador que o esquema induz, desligada por padrão |
| `--max-pop` | 12 | teto da população |

Oito estratégias competem: momentum ×2, reversão à média ×2, breakout,
**regime-switch** (surfa tendência só quando o regime é de tendência, fica
de fora no chop e zera em pânico de volatilidade), **vol-target**
(seguidor de tendência que dimensiona a posição pela volatilidade
realizada — maior em mercado calmo, menor em mercado selvagem, fora
quando a vol explode) e **trend** (cruzamento de médias de 3 e 10 dias).

Um filho de £0,60 vive pelas mesmas regras na escala dele: meta diária
sobre o próprio patrimônio, dispensa abaixo de 60% dos seus £0,60 (£0,36),
aluguel proporcional, e só contrata o próprio filho quando tiver £0,20 de
excedente sobre os £0,60 — o pai paga o que tem em caixa, sem vender
posição.

O experimento das £5 no mercado endógeno (90–180 dias) dava vol-target
+13% a +28%; em velas reais o quadro é bem mais duro — veja *Backtests
com dados reais*. A colônia só cresce com lucro real — que é exatamente o
ponto. É por isso que a trilha é **simulador → dry-run → testnet → real
com limites mínimos**, nessa ordem.

## Backtests com dados reais

O mercado sintético é bom para treinar, mas só velas reais dizem se uma
regra sobrevive a taxas e a um ano de verdade. O workflow `market-data`
baixa ~13 meses de velas horárias de BTC, ETH e SOL da Coinbase (API
pública, sem conta) para a branch `market-data`, e `cryptoarena backtest`
roda colônias novas em janelas deslizantes sobre elas:

```bash
git show origin/market-data:BTCUSD.csv > data/BTCUSD.csv   # idem ETHUSD, SOLUSD
cryptoarena backtest --data data --days 30 --stride 10      # 30 dias, uma colônia a cada 10
cryptoarena backtest --data data --days 60 --stride 15 --learn 0
```

Cada janela é uma colônia nova (fundadores novos, journal em memória)
que aquece os indicadores com 720 velas e vive `--days` dias reais. O
relatório compara com **comprar e segurar** nas mesmas horas — a
pergunta honesta não é "deu lucro", é "bateu segurar as moedas, líquido
de taxas".

Um ano (ago/2025 a set/2026, um período de queda: segurar as três moedas
deu −4% por janela de 30 dias em média, −10% por janela de 60) com taxa
de 0,26% por lado e aluguel de 0,02%/dia:

| Fundadores | 30 dias: colônia / segurar / bate segurar | 60 dias: colônia / segurar / bate segurar | taxas (34 janelas de 30 d) |
|---|---|---|---|
| horários (antigos), 3 moedas | −3,4% / −4,0% / 47% | −7,2% / −9,8% / 67% | 15,9 |
| semanais + portão de tendência, 3 moedas | −1,2% / −4,0% / 53% | −2,6% / −9,8% / 67% | 3,8 |
| idem, 24 moedas, sem disciplinas | −3,9% / −6,3% / 50% | — | 13,9 |
| idem, 24 moedas, com disciplinas | −2,0% / −6,3% / 56% | — | 6,2 |
| + o urso (`bear-1`), 24 moedas | −1,5% / −6,3% / 53% | −3,3% / −13,1% / 69% | 8,2 |

(Com a configuração antiga — aluguel de 0,1%/dia, taxa de 0,1% — a mesma
colônia antiga dava −6,9% por janela de 30 dias.)

O que o backtest ensinou, e virou default: horizontes de 7 a 14 dias em
vez de 1 a 2; um portão de 28 dias que corta as compras em tendência de
baixa (perda média por janela cai um terço, taxas caem pela metade);
exposição maior nos seguidores de tendência (30% por ordem), que escapam
das quedas e por isso podem carregar mais; stop de 6% só na reversão à
média, que é quem segura faca caindo; a lição "operou pouco, afrouxe as
entradas" só quando o mercado subiu mais de 3% sem o agente (ficar em
caixa numa queda é acerto, não passividade); e o custo de vida de
0,02%/dia (0,1% custava 3% ao mês, mais do que qualquer regra rende).
Stops apertados em todos os agentes (5–8%) pioraram: chicoteiam no
horário. Com 24 moedas os agentes compravam demais, e entraram as
**disciplinas**: uma compra por vela (a de momentum mais forte), no
máximo 60% investido, um portão de "clima" pelo BTC e só as 6 moedas
mais fortes. Num ano de queda, uma colônia só-comprada que fica perto
de zero está ganhando de segurar — e é isso que os números mostram, nem
mais nem menos.

### Cinco anos: o que um ano de queda não ensina

Tudo acima foi calibrado num único ano de queda. O workflow `market-data`
puxa agora **cinco anos** de velas horárias das 24 moedas (jul/2021 a
hoje, cada moeda a partir da listagem: 16 em 2021, 24 desde 2023) e o
backtest usa um **universo que cresce com o tempo** (`load_tape(align=False)`:
cada janela negocia as moedas que existiam nela inteira, para não
testar só as sobreviventes de hoje). São 184 janelas de 30 dias cobrindo a
alta de 2021, o colapso de 2022, a recuperação de 2023, a alta de 2024
e a queda de 2025-26. `cryptoarena backtest` imprime a tabela por ano.

| Configuração (5 anos, 184 janelas) | média/janela | positivo | bate segurar | taxas |
|---|---|---|---|---|
| sem disciplinas, sem urso, sem portão de ganância (a de agosto) | −1,25% | 32% | 41% | 94 |
| com disciplinas, com urso, portão de ganância 60 | −0,39% | 26% | 53% | 34 |
| com disciplinas, com urso, portão 80 | +0,11% | 35% | 50% | 52 |
| com disciplinas, com urso, sem portão | +0,24% | 35% | 49% | 53 |
| **com disciplinas, sem urso, sem portão — atual** | **+0,44%** | 34% | 49% | 41 |
| comprar e segurar as moedas | +0,94% | | | |

Por ano, com a configuração atual: 2021 +0,6% (segurar −2,8%), 2022
−0,7% (−5,0%), 2023 +4,5% (+7,6%), 2024 +1,9% (+9,8%), 2025 −2,4%
(−4,4%), 2026 −2,1% (−3,4%). Nos anos de queda a colônia perde bem
menos que segurar; nos de alta fica para trás. O momentum-1 sozinho fez
+10% por janela em 2023 e +7% em 2024.

O que os cinco anos decidiram:

- **Disciplinas ficam.** De −1,25% para +0,44% por janela, taxas de 94
  para 41. Uma compra por vela, 60% investido no máximo, portão de clima
  pelo BTC e só as 6 mais fortes valem em todo regime.
- **O urso sai dos fundadores.** `BearAgent`, o vendedor a descoberto
  (posição negativa na carteira de papel, funding de 0,12% por dia, os
  mesmos limites do lado vendido no funil de risco), foi o único fundador
  no azul nos 13 meses de queda (+1,8% por janela). Em cinco anos perdeu
  em 5 dos 6 anos, −3,9% em 2024, e nenhuma variante (BTC 10% ou 15%
  abaixo do nível de 28 dias, horizontes mais longos, só em medo) fica
  positiva: taxas mais funding comem o que a queda rende. A classe fica
  disponível para contratar; não é mais fundador.
- **O portão de ganância sai (fica desligado).** O Crypto Fear & Greed
  (alternative.me, publicado em `sentiment/fng.csv`) é contrarian na fita
  de 13 meses e o portão em 60 ajudava ali; em cinco anos ele custa os
  anos de alta (2024: −0,8% com portão, +1,9% sem). `greed_gate` continua
  em todo agente (0 = desligado) e a colônia ao vivo segue lendo o índice
  a cada tick e mostrando no dashboard, mas ninguém deixa de comprar por
  ele.
- **Contratar e aposentar sem refundar.** O que está na lista de
  fundadores do andar é a verdade: quem entra na lista é contratado na
  colônia que já roda (£ novas, fita compartilhada, "nascido hoje"); quem
  sai é aposentado (evento `retired`, posições avaliadas no último preço).

### A linha que a colônia precisa bater: segurar com saída pela tendência

Uma colônia que rende +0,44% por mês contra +0,94% de segurar não é
investimento. A pergunta seguinte foi se o que ela tem de bom (perder
menos nos anos de queda) vale sozinho, sem a colônia: **segurar as
moedas e ir para caixa quando a tendência vira**
(`arena/trend_hold.py`). Uma vez por dia cada moeda é checada; compra
quando o sinal liga, vende tudo quando desliga, deixa correr no meio,
0,26% de taxa em cada lado. As regras foram fixadas antes de olhar o
resultado; os prazos de 14, 56 e 100 dias servem só de teste de
robustez.

Mesmas 184 janelas de 30 dias da colônia:

| Estratégia | média | mediana | pior janela | 2022 | 2024 |
|---|---|---|---|---|---|
| colônia (fundadores atuais) | +0,44% | −1,33% | | −0,7% | +1,9% |
| segurar as moedas, sem taxa | +0,94% | −2,74% | −43,5% | −5,0% | +9,8% |
| moeda em alta de 28 dias | +1,27% | −3,01% | −22,8% | −1,6% | +6,7% |
| BTC em alta de 28 dias → todas | +1,71% | −0,33% | −34,4% | −2,1% | +6,3% |
| **as duas condições** | **+2,07%** | −0,76% | −23,9% | −0,2% | +5,9% |
| segurar só BTC | +2,04% | +0,76% | −30,1% | | |
| só BTC, em alta de 28 dias | +1,51% | −0,33% | −25,2% | −3,3% | +4,0% |

Cinco anos seguidos, começando em datas diferentes (retorno ao ano /
pior queda do pico):

| Início | segurar BTC | segurar as moedas | BTC + tendência | moedas + as duas condições |
|---|---|---|---|---|
| out/2021 | +5,8% / 77% | −14,7% / 83% | +11,2% / 49% | +16,0% / 58% |
| out/2022 | +44,8% / 54% | +8,8% / 75% | +27,2% / 42% | +18,9% / 63% |
| out/2023 | +46,7% / 54% | +14,6% / 80% | +22,7% / 42% | +23,5% / 62% |
| abr/2024 | +7,2% / 54% | −19,8% / 76% | −7,7% / 42% | −12,0% / 62% |
| abr/2025 | +1,6% / 54% | −16,2% / 73% | −1,0% / 29% | −7,9% / 48% |

O que isso diz:

- **A saída pela tendência faz o que promete: corta as quedas.** Pior
  janela de −43% para −24%; queda máxima do BTC de 54–77% para 29–49%.
- **Ela não acrescenta retorno de forma confiável.** Nas janelas que
  não se sobrepõem, a diferença para segurar tem estatística t abaixo
  de 1 em todas as variantes: indistinguível de sorte. Num começo perto
  do topo (2021) ela brilha; num começo antes de uma alta (2022–2023)
  ela entrega metade do BTC puro.
- **O que mais pesa é o quê, não o quando.** A cesta de 24 moedas
  perdeu dinheiro na maioria dos começos; só BTC ganhou de tudo na
  maior parte deles, inclusive da colônia. O universo largo da colônia
  é um peso, não uma vantagem.
- **Nenhuma variante é suave.** Mesmo com a saída, quedas de 40–60%
  continuam acontecendo. É cripto.

Ressalvas: as 24 moedas são as grandes de hoje (quem morreu no caminho,
como LUNA e FTT, não está na fita, o que favorece "segurar as moedas");
a taxa é a da Kraken e não inclui spread; no Reino Unido cada venda é
um evento de imposto sobre ganho de capital, e a saída pela tendência
vende muito mais que segurar.

### Modelos de previsão do GitHub contra segurar BTC

Muitos repositórios prometem prever o preço de cripto. Quatro famílias
foram instaladas e postas no mesmo teste (`cryptoarena forecast`,
`forecast/`): a cada dia, no fechamento, o modelo vê **só os fechamentos
até aquele dia** e prevê o retorno do BTC nos próximos 7 dias; com a
previsão positiva segura BTC, senão fica em caixa, com o simulador e as
taxas de `trend_hold`. Um teste garante que nenhum modelo recebe um
preço do futuro.

- [Nixtla/statsforecast](https://github.com/Nixtla/statsforecast):
  AutoARIMA, AutoETS e AutoTheta sobre o log do preço.
- [StephanAkkerman/crypto-forecasting-benchmark](https://github.com/StephanAkkerman/crypto-forecasting-benchmark):
  o setup de aprendizado de máquina do artigo (gradient boosting sobre
  retornos defasados), com LightGBM, retreinado a cada 30 dias só com o
  passado. O repositório fixa Python 3.9 e bibliotecas de 2023, então o
  método foi reproduzido com as versões atuais.
- [amazon-science/chronos-forecasting](https://github.com/amazon-science/chronos-forecasting):
  Chronos-Bolt, modelo pré-treinado em milhões de séries, sem treino
  nenhum aqui. Precisa de PyTorch e do Hugging Face, então roda no
  workflow **Forecast bench** (Actions), que publica o relatório na
  branch `forecast-bench-crypto` (ou `forecast-bench-world`).
- `drift`: a linha sem habilidade nenhuma, a média do retorno diário do
  último ano vezes 7.

Jul/2022 a set/2026, 1.535 previsões. "Acerto" é a direção certa nos
dias em que o modelo tomou lado; a "base" é quantas vezes o BTC
simplesmente subiu em 7 dias (quem sempre diz "sobe" acerta isso). IC é
a correlação de postos entre previsto e realizado:

| Modelo | acerto (base 53%) | IC | ao ano | pior queda | operações |
|---|---|---|---|---|---|
| segurar BTC | | | +42,2% | 54% | 0 |
| BTC com saída pela tendência de 28 dias | | | +25,6% | 42% | 141 |
| drift (sem habilidade) | 53% | +0,01 | +34,7% | 32% | 4 |
| AutoARIMA (tomou lado em 48% dos dias) | 54% | +0,01 | +12,3% | 44% | 52 |
| AutoTheta | 50% | −0,01 | +8,1% | 58% | 95 |
| LightGBM sobre retornos defasados | 48% | −0,06 | +4,6% | 57% | 290 |
| Chronos-Bolt small | 51% | −0,03 | +4,0% | 54% | 148 |
| AutoETS | 52% | −0,05 | −14,8% | 62% | 619 |

Com horizonte de 1 dia, o que a maioria desses repositórios usa, fica
pior: acerto de 48% a 52% contra base de 50%, e as taxas de quem gira
muito pesam (LightGBM −42,5% ao ano com 730 operações; Chronos −2,0%).

- **Nenhum modelo prevê melhor que a moeda ao ar.** Todo acerto fica a
  até 5 pontos da base, e todo IC fica entre −0,06 e +0,02, dentro do
  ruído (com ~220 semanas independentes, o erro padrão do IC é ~0,07).
- **Todos perdem para segurar BTC e para a saída pela tendência.** Os
  que operam mais perdem mais: a taxa é o único efeito que aparece com
  clareza.
- **O modelo mais moderno não ajuda.** O Chronos, pré-treinado e
  premiado em benchmarks de previsão genérica, faz o mesmo que os
  outros no BTC: o que ele sabe prever (sazonalidade, tendência suave)
  não existe numa série que se comporta como passeio aleatório.
- **O único que "funcionou" não prevê nada.** O drift fica comprado
  enquanto o último ano foi positivo; operou 4 vezes e teve a menor
  queda. É a saída pela tendência com um prazo longo, a mesma lição da
  seção anterior, e com 4 decisões ninguém distingue isso de sorte.

O quinto repositório lido,
[SC4RECOIN/LSTM-Crypto-Price-Prediction](https://github.com/SC4RECOIN/LSTM-Crypto-Price-Prediction),
anuncia quase 80% de acerto numa LSTM. O `lstm.py` embaralha as amostras
antes de separar treino e validação, então a validação vê dias vizinhos
dos de treino e os 80% não medem previsão. O próprio README mostra o
teste honesto, em dados que o modelo não viu: carteira −11,26% contra
+6,51% de segurar. Por isso ele não entrou no teste.

```bash
pip install -e ".[forecast]"
cryptoarena forecast --data data --models drift,arima,ets,theta,lgbm --horizon 7
# o Chronos: Actions → Forecast bench → Run workflow (models: chronos)
```

### Ações do mundo: os projetos mais completos, instalados e testados

Previsão falhou no cripto; a pergunta seguinte foi se ações são
diferentes. O universo (`market/universe.py`, workflow **Global data**,
branch `global-data`) tem dez anos de barras diárias da API pública da
Nasdaq: **27 ETFs de índices** (mundo, regiões, 20 países, títulos do
Tesouro americano e ouro) e **as 100 maiores empresas americanas** (uma
lista recente do S&P 100). Os preços vêm ajustados por desdobramento,
mas não por dividendos nem por cisões: a cisão da Honeywell em
29/06/2026 aparecia como uma queda de 51% e está registrada e corrigida
em `universe.py`.

**1. Prever o índice (séries temporais).** O mesmo banco de testes do
BTC, agora em barras diárias (`cryptoarena forecast --symbol all`), com
uma previsão por semana para a semana seguinte (sem sobreposição: cada
previsão é uma observação independente), set/2017 a set/2026, 0,05% por
lado:

| Modelo, nos 27 índices | acerto − base | IC médio | ganha de segurar |
|---|---|---|---|
| drift (sem habilidade) | −1,6 pts | −0,020 | 6 de 27 |
| AutoARIMA (statsforecast) | −2,3 pts | −0,004 | 8 de 27 |
| AutoTheta | −3,0 pts | −0,024 | 4 de 27 |
| AutoETS | −3,8 pts | −0,013 | 3 de 27 |
| LightGBM sobre retornos defasados | −4,5 pts | −0,029 | 3 de 27 |
| Chronos-Bolt small | −1,4 pts | +0,002 | 5 de 27 |
| [Kronos](https://github.com/shiyu-coder/Kronos) small, 8 índices principais | −8,8 pts | +0,058 | 0 de 8 |

O índice sobe em ~59% das semanas; nenhum modelo acerta mais do que
quem sempre diz "sobe".

O Kronos é o único com IC positivo em todos os índices, e merece um
olhar mais de perto. Ele foi pré-treinado com velas de 45 bolsas até
junho de 2024, então só o período depois disso é um teste limpo; nele
o IC médio sobe para +0,15 (112 semanas por índice, t entre 1,0 e 2,2,
com índices que andam quase juntos). Mas as previsões dele têm
correlação de 0,83 com uma regra de uma linha, "quanto mais o preço
está acima da média do último ano, mais cai na semana seguinte", e
essa regra tem IC ainda maior no mesmo período (+0,17) e quase nenhum
antes (+0,04). O Kronos aprendeu a apostar em volta à média, o que deu
certo no vaivém de 2024–2026; operando pelo sinal ele perde de segurar
nos 8 índices, porque num mercado que sobe ele passa a maior parte do
tempo prevendo queda. A saída pela tendência de 20 pregões repete o
cripto: queda máxima menor em 25 dos 27 índices (mediana 42% → 30%),
retorno menor em 22 (mediana 4,7% → 1,7% ao ano).

**Instalar o Kronos.** O código do modelo não está no PyPI; ele vem do
repositório num commit fixo (13/04/2026), e os pesos vêm do Hugging Face
na primeira vez que o modelo carrega. Os três tamanhos abertos estão no
banco, com o mesmo contexto (256 dias) e 3 caminhos sorteados:
`kronos-mini` (4,1M de parâmetros, tokenizador próprio de 2k), `kronos`
(o small, 24,7M) e `kronos-base` (102,3M). O large (499M) não foi
liberado.

```bash
pip install -e ".[forecast,kronos]"      # PyTorch, einops, huggingface_hub, safetensors
bash scripts/install_kronos.sh           # o código do Kronos em ./Kronos (fora do git)
KRONOS_PATH="$PWD/Kronos" cryptoarena forecast --data data/global/etf --symbol SPY,QQQ \
  --models drift,kronos-mini,kronos,kronos-base --every 5
```

No GitHub Actions: **Forecast bench → Run workflow**, `tape: world`,
`models: drift,kronos-mini,kronos,kronos-base`, com um `label` para não
sobrescrever resultados anteriores.

**Os três tamanhos, SPY e QQQ (14/10/2026).** Uma previsão por semana
para a semana seguinte, out/2017 a out/2026, 0,05% por lado (branch
`forecast-bench-world-kronos-sizes`). No período inteiro o mini parecia
ganhar de segurar nos dois (SPY +15,4% ao ano contra +13,2%; QQQ +23,4%
contra +19,8%, com metade da queda). Separando o que o modelo pode ter
visto no pré-treino (até junho de 2024) do que veio depois:

| IC semanal (t) | SPY até jun/2024 | SPY depois | QQQ até jun/2024 | QQQ depois |
|---|---|---|---|---|
| Kronos mini | **+0,244 (4,6)** | −0,037 (−0,4) | **+0,173 (3,2)** | +0,021 (0,2) |
| Kronos small | +0,130 (2,4) | +0,194 (2,1) | +0,079 (1,5) | +0,205 (2,2) |
| Kronos base | +0,109 (2,0) | +0,142 (1,5) | +0,051 (0,9) | +0,166 (1,8) |
| volta à média de 1 ano (uma linha) | +0,068 | **+0,284** | +0,031 | **+0,234** |

| Depois de jun/2024, ao ano (queda máx.) | SPY | QQQ |
|---|---|---|
| segurar | **+17,0% (19%)** | **+21,6% (23%)** |
| Kronos mini | +11,4% (19%) | +20,8% (17%) |
| Kronos small | +5,7% (7%) | +9,5% (16%) |
| Kronos base | +6,3% (12%) | +13,2% (7%) |

- **O mais provável é memória, não previsão**: o acerto forte do mini se
  concentra nos anos que ele pode ter visto no pré-treino (de 2020 a 2023,
  o IC semestral chega a +0,62 no SPY) e não aparece no período depois do
  corte. A queda, porém, não tem data exata: no SPY o IC já foi −0,28 no
  1º semestre de 2024, ainda dentro do treino, e no QQQ ainda foi +0,22 no
  2º semestre de 2024, depois dele. Com só dois anos depois do corte não dá
  para separar memória de mudança de mercado (a volta à média passou a
  funcionar no mesmo período). É por isso que só o período depois do corte
  conta.
- **O small e o base** repetem o que já sabíamos: o pouco de acerto que
  têm depois do corte anda junto (correlação 0,6 a 0,9) com a regra de
  volta à média de uma linha, que acerta mais que eles. Como passam a
  maior parte do tempo prevendo queda num mercado que sobe, ficam de fora
  e rendem muito menos que segurar.
- **Veredito**: nenhum tamanho do Kronos ganha de segurar o índice no
  período que ele não viu. Fica no banco de previsões, fora do andar.

### TradingAgents: o artigo, as réplicas e o que veio de lá (14/10/2026)

O [TradingAgents](https://github.com/TauricResearch/TradingAgents)
(v0.6.0, Apache-2.0) é um gerador de recomendação: para cada ação e cada
dia, cerca de 20 chamadas de LLM (quatro analistas, debate bull/bear,
gerente de pesquisa, trader, debate de risco em três vozes e gerente de
carteira) produzem uma nota de cinco níveis. Ele não executa, não dimensiona
e não conta custos. O nosso debate bull/bear (`agents/debate.py`) já veio
de lá.

- **O artigo** (arXiv 2412.20138) relata Sharpe de 5,6 a 8,2 e queda
  abaixo de 2% em **uma rodada, três ações, cerca de um trimestre de
  2024**, sem custos, sem comparar com o índice e sem publicar o código da
  avaliação; a janela de teste muda entre versões do artigo. O próprio
  CHANGELOG lista vazamentos de dados do futuro corrigidos só em 2026.
- **Nas réplicas depois do corte de treino dos modelos** a vantagem some:
  um estudo de reprodutibilidade (ACM ICAIF 2026, GOOGL, mai–jul/2025) não
  bateu segurar a GOOGL nem o QQQ; o *Profit Mirage* (2025) mede o Sharpe
  caindo cerca de 56% depois do corte; nas arenas com dinheiro de verdade
  a maioria dos modelos perdeu. Vários desses só foram lidos por trechos
  de busca.
- **O que ele tem de bom** é a higiene de dados na data da decisão
  (notícias cortadas no dia, balanços da SEC como foram entregues, dados
  macro na versão da época), útil se um dia usarmos texto ou balanços.
- **A comparação achou dois defeitos nossos**, corrigidos antes do
  relógio do placar começar: lições que empurravam o parâmetro para o lado
  errado no andar de ações, e a fonte da SEC calada sem que a impressão
  digital das regras soubesse.
- Um teste honesto do TradingAgents só pode ser para frente, num andar de
  laboratório, com as notas julgadas pelo placar das fontes (cerca de
  US$7–11 por mês com Haiku 5.5 e Sonnet 5.5). Não ligado; decisão do dono.

**2. Ranquear ações (a abordagem do [Microsoft Qlib](https://github.com/microsoft/qlib)).**
O Qlib, a plataforma aberta mais completa de investimento quantitativo,
não tenta adivinhar se o mercado sobe: todo dia ele ranqueia as ações
umas contra as outras com 158 indicadores técnicos (Alpha158) e a
carteira segura as melhores colocadas, trocando poucas por dia
(TopkDropout). `forecast/qlib_bench.py` (`cryptoarena qlib`) escreve os
nossos dados no formato binário do Qlib e roda quatro modelos **com os
parâmetros exatos dos arquivos de benchmark publicados pelo Qlib**,
retreinados todo ano só com o passado (teste 2020 a set/2026), mais o
momentum de 12 meses (o sinal mais forte da literatura) sem
aprendizado de máquina nenhum:

| | IC | ao ano | vs índice | pior queda |
|---|---|---|---|---|
| *Publicado pelo Qlib, China CSI300, 2017–2020* | *0,040 a 0,052* | | *+6,9 a +11,6 pts* | |
| **100 maiores empresas dos EUA, top 10** | | | | |
| LightGBM | −0,003 | +5,6% | −7,2 pts | 39% |
| DoubleEnsemble | +0,003 | +11,5% | −1,3 pts | 43% |
| XGBoost | −0,002 | +12,7% | +0,1 pts | 41% |
| Linear | +0,006 | +14,6% | +2,1 pts | 37% |
| momentum 12-1 | +0,024 | +32,2% | +17,6 pts | 34% |
| segurar SPY | | +13,8% | | 34% |
| **27 índices do mundo, top 5** | | | | |
| LightGBM | +0,011 | +6,9% | −3,7 pts | 35% |
| DoubleEnsemble | +0,007 | +5,7% | −5,0 pts | 31% |
| XGBoost | +0,002 | +1,0% | −8,9 pts | 42% |
| Linear | +0,011 | +8,9% | −1,8 pts | 29% |
| momentum 12-1 | +0,024 | +12,0% | +0,9 pts | 31% |
| segurar ACWI (mundo) | | +11,1% | | 34% |

- **Os modelos do Qlib não acham nada aqui.** O IC que na China chega a
  0,04–0,05 fica entre −0,003 e +0,011: o ranking dos modelos quase não
  se relaciona com o que as ações fizeram depois. Os retornos ficam
  espalhados em volta do índice, para os dois lados. Trocar duas ações
  por dia custa sozinho ~5 pontos por ano a 0,05% por lado.
- **O momentum nas 100 empresas não deve ser levado ao pé da letra.** A
  lista é a de hoje: ela já contém quem subiu até o topo (Nvidia,
  Palantir, Broadcom, Eli Lilly…) e nenhuma empresa que caiu dele, e o
  momentum é exatamente o sinal que mais lucra com esse viés (+92% em
  2020, +62% em 2024). Nos índices do mundo, que existem desde antes do
  teste e não têm esse viés, o mesmo momentum rendeu +0,9 ponto por ano.
- **O mercado chinês é outro mercado.** Onde o Qlib foi publicado, o
  pregão é dominado por pessoas físicas; as maiores empresas americanas
  e os índices mundiais estão entre os preços mais disputados do
  planeta.

**3. O que já se sabe (e reforça).**

- [Gu, Kelly e Xiu (2020)](https://academic.oup.com/rfs/article/33/5/2223/5758276):
  aprendizado de máquina acha previsibilidade entre ações americanas,
  com momentum, liquidez e volatilidade como sinais dominantes.
- [Avramov, Cheng e Metzker (2023)](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.4449):
  esse lucro vem de ações difíceis de negociar; tirando as muito
  pequenas, as em dificuldade e os períodos de alta volatilidade ele
  cai bastante, e piora com custos, porque esses modelos giram muito.
- [McLean e Pontiff (2016)](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365):
  97 anomalias publicadas rendem 26% menos fora da amostra e 58% menos
  depois de publicadas.
- [FinRL](https://github.com/AI4Finance-Foundation/FinRL) (aprendizado
  por reforço): lido, não rodado. O exemplo oficial treina cinco agentes
  em 2014–2025 e testa em onze semanas (jan–mar/2026), sem semente fixa;
  um resultado assim não distingue habilidade de sorte.
- [Stock-Prediction-Models](https://github.com/huseinzol05/Stock-Prediction-Models)
  (30 modelos, parado desde 2021): anuncia "LSTM com 95,7% de
  acurácia". A métrica é 1 − o erro percentual sobre o nível do preço
  em 30 dias; uma linha reta que repete o último fechamento marca 95,1%
  (mediana) na mesma Alphabet dos notebooks.
- [Machine Learning for Trading](https://github.com/stefan-jansen/machine-learning-for-trading)
  (Stefan Jansen, atualizado em 2026): o livro-referência trata o
  backtest como tentativa de falsificação e dedica capítulos a
  sobreajuste e testes múltiplos (Deflated Sharpe Ratio, White's Reality
  Check), que é o que este projeto vem fazendo à mão.

```bash
pip install -e ".[qlib,forecast]"
# com a branch global-data em data/global (stocks/ e etf/):
cryptoarena qlib --data data/global --universe stocks --benchmark SPY
cryptoarena qlib --data data/global --universe etf --benchmark ACWI --topk 5 --n-drop 1
cryptoarena forecast --data data/global/etf --symbol all --every 5
```

### O andar de ações na conta de prática da Trading 212

Desde 25/09/2026 o andar que roda é o de **ações**: um depósito simulado
de **£1.000**, convertido em dólares pelo câmbio do dia da fundação
(Banco Central Europeu) e dividido pelos 9 especialistas
(`live --floor stocks --deposit-gbp 1000`). Toda noite, depois do
fechamento em Nova York, o workflow **Live colony (stocks)** alimenta o
pregão que fechou e, com uma chave configurada, **espelha a carteira dos
agentes na conta de prática da Trading 212** (dinheiro virtual, preços e
execuções reais da corretora).

- `broker/trading212.py` fala **só** com `demo.trading212.com`: não
  existe opção, variável ou argumento que aponte para uma conta real.
- `broker/mirror.py` é uma **reconciliação**, não uma cópia de ordens:
  lê as posições e as ordens ainda pendentes e manda só a diferença para
  a conta ter as mesmas ações que os agentes. Rodar duas vezes, ou depois
  de um dia perdido, nunca dobra uma compra (a ordem a mercado da
  Trading 212 não é idempotente). Vende antes de comprar, nunca mais do
  que a conta pode vender, só mexe nos símbolos do andar, e para de
  mandar ordens se a resposta de uma for incerta.
- SPY e QQQ são fundos americanos que a Trading 212 não vende a contas
  do Reino Unido: o que os agentes têm deles fica só no papel, e o
  espelho avisa.
- As ordens são mandadas de madrugada e executam na abertura seguinte,
  então a conta de prática compra um pregão depois do papel.

Para conectar: no app da Trading 212, mude para a conta **Practice**,
crie uma chave de API (com permissão de conta, portfólio, metadados e
ordens) e guarde-a em **Settings → Secrets and variables → Actions**
do repositório como `T212_API_KEY` e `T212_API_SECRET`. Nunca num
arquivo nem no chat. A variável `T212_PAUSE=true` para o espelho. Sem
a chave, a colônia segue só no papel. À mão:

```bash
export T212_API_KEY=... T212_API_SECRET=...     # chave da conta Practice
cryptoarena t212 status                         # confere a conexão
cryptoarena t212 mirror --db live/stocks.db     # lista o que mandaria
cryptoarena t212 mirror --db live/stocks.db --execute
```

### A mesa: risco, PM, chefe de gabinete e o feed

Cada agente tem o seu cinto (no máximo 35% do *seu* patrimônio num
nome, stop, kill switch), mas ninguém olhava a colônia inteira. No
quarto pregão do andar de ações, quatro agentes compraram Nvidia na
mesma barra: nove carteiras, uma aposta só. Acima dos agentes agora há
uma **mesa** (`arena/desk.py`, `arena/chief.py`):

- **Risco da mesa**: vê cada ordem depois do risco do próprio agente e
  corta ou recusa a que levaria a colônia além de uma fatia do patrimônio
  num nome (`desk_symbol_cap`) ou investida no total (`desk_gross_cap`).
  Fechar posição nunca é recusado. Os agentes revezam o primeiro lugar
  da fila, então a folga sob o teto não vai sempre para o mesmo. Cada
  "não" fica no journal (`vetoed` ou `clipped`) e aparece no feed.
- **PM**: mantém um livro próprio com o mesmo capital dos fundadores,
  montado com os votos dos agentes. Depois de cada barra, ele segura o
  peso líquido da colônia em cada nome (o peso de cada agente, ponderado
  pelo patrimônio dele), pode ignorar o que poucos agentes têm
  (`pm_consensus`) e só opera quando um peso sai mais de `pm_band` do
  alvo. Se o agente A vende o que o B compra, isso se anula dentro do
  livro em vez de pagar taxa duas vezes. O livro é uma **sombra**: não
  mexe nas carteiras dos agentes, então os dois se comparam nas mesmas
  barras.
- **Chefe de gabinete**: a cada fechamento escreve uma nota com a
  colônia contra segurar o índice desde a fundação (SPY nas ações, BTC
  no cripto), o que foi comprado e vendido, e o que a mesa barrou. Só
  **chama o dono** quando há uma decisão:
  - a colônia está mais de 3 pontos atrás do SPY depois de 10 pregões;
  - caiu mais de 5% desde a fundação;
  - o livro do PM está mais de 2 pontos à frente da colônia;
  - o andar está sem barra nova há 5 dias.

  Nesses casos, o workflow abre uma **issue no GitHub** com o rótulo
  `mesa`, e o app do GitHub avisa no celular. A issue é atualizada
  enquanto a situação dura e fechada com uma nota quando ela some. Sem
  decisão, nada é postado. À mão: `cryptoarena chief --floor stocks`.
- **Feed da mesa**: nova aba **📟 Desk feed** no dashboard. Mostra uma
  linha por evento, do mais novo ao mais antigo: compras e vendas por
  agente, `RISK`, `PM`, contratações e dispensas (`HR`), prêmios e a
  nota do `CHIEF`. O painel ao vivo ganhou "The desk", com o maior nome
  contra o teto, as ordens recusadas e o livro do PM.

O que o backtest disse antes de ligar qualquer coisa:

| Ações: 60 janelas de 60 pregões, 2020–2026 | média/janela | desvio | barradas / cortadas |
|---|---|---|---|
| sem mesa | +0,52% | 5,35% | |
| teto de 20% por nome | +0,52% | 5,35% | 0 / 2 |
| teto de 15% por nome | +0,43% | 5,12% | 241 / 111 |
| teto de 10% por nome | +0,07% | 4,24% | 1.216 / 326 |
| no máximo 50% investido | +0,27% | 4,81% | 596 / 152 |
| livro do PM (banda de 2%) | +0,49% | | taxas 1,48 contra 1,68 |
| segurar as 6 | +5,08% | | |

| Cripto: 184 janelas de 30 dias, 2021–2026 | média/janela | desvio | barradas / cortadas |
|---|---|---|---|
| sem mesa | +0,55% | 9,03% | |
| teto de 20% por nome | +0,52% | 8,90% | 154 / 59 |
| teto de 15% por nome | +0,47% | 8,58% | 785 / 448 |
| no máximo 50% investido | +0,51% | 8,90% | 165 / 171 |
| livro do PM (banda de 2%) | +0,67% | | taxas 33 contra 41 |
| segurar as moedas | +0,99% | | |

- **Tetos que mordem custam mais retorno do que tiram de risco.** O
  retorno por unidade de desvio piora em todos. O andar de ações tem 6
  nomes; o que pesa é estar fora do mercado na alta, não a concentração.
  O teto de **20%** fica ligado nas ações como cinto de segurança: em
  seis anos nunca mordeu (2 cortes) e existe para o dia em que muitos
  agentes correrem para o mesmo papel. Aqueles quatro Nvidias eram 9%
  da colônia, abaixo de qualquer teto razoável.
- **O PM não ganha da colônia nas ações**: −0,02 ponto por janela, t
  −0,8, um empate. **No cripto ganha +0,11 ponto por janela** (t 1,9,
  0,3 e 2,5 nos três conjuntos de janelas que não se sobrepõem), e isso
  é quase exatamente a taxa que ele deixa de pagar (33 contra 41): com
  24 moedas e 8 agentes, um vende o que o outro compra o tempo todo, e o
  livro compensa isso por dentro. É uma vantagem mecânica, não de
  previsão, e ainda perde de segurar (+0,67% contra +0,99%). O PM fica
  ligado como **livro-sombra** nos dois andares (`pm_band` 0,02): o
  status mostra os dois lado a lado, e o chefe chama se o PM abrir 2
  pontos de vantagem. O espelho da Trading 212 já faz essa
  reconciliação líquida sobre a soma das carteiras; seguir o PM só
  mudaria a banda.
- Nada disso fecha a distância para segurar o índice.

```bash
cryptoarena backtest --floor stocks --desk-cap 0.15 --pm 1 --pm-band 0.02   # a mesa no backtest
cryptoarena live --floor stocks --status | jq .desk,.chief                  # a mesa ao vivo
cryptoarena chief --floor stocks                                            # a nota do dia
```

### Três ideias de projetos abertos: futuro espiado, boletim dos sinais e HRP

O REA (engenharia reversa de programas fechados) não serve aqui: os
projetos que valem a pena estudar já são abertos. Por isso as ideias
foram reescritas a partir do código e dos artigos, sem copiar código.

**1. O backteste espiou o futuro? (a ideia do `lookahead-analysis` do
[freqtrade](https://github.com/freqtrade/freqtrade))** —
`arena/lookahead.py`, `cryptoarena lookahead --floor stocks|crypto`.

- **Futuro embaralhado.** Cada janela roda duas vezes. Na segunda, tudo
  depois de um corte vira outro futuro: os mesmos movimentos embaralhados
  e com sinal trocado ao acaso, volumes e dias do Fear & Greed também
  embaralhados. Todo trade e todo evento da colônia até o corte
  (contratação, dispensa, prêmio, veto) tem de sair idêntico. Uma decisão
  que muda quando só o futuro mudou estava lendo o futuro. Um teste
  planta um vazamento de propósito (o volume da barra carregando o
  fechamento seguinte) para provar que o auditor o pega.
- **Execução atrasada.** O simulador executa a ordem no fechamento da
  barra que o agente acabou de ver. Na vida real ela só chega ao mercado
  na abertura seguinte: uma hora depois no cripto, no pregão seguinte
  nas ações, depois do gap da noite. `--fill next_open` roda as mesmas
  janelas executando na próxima abertura, para o agente e para o PM.
- **Universo.** Conta as vezes em que uma janela deixa de fora um nome
  que existia no início dela e sumiu antes do fim.

| Resultado | Ações (60 janelas) | Cripto (184 janelas) |
|---|---|---|
| Futuro embaralhado, colônia (3 janelas × 3 cortes) | limpo: 308 trades, 3.989 eventos | limpo: 762 trades, 2.044 eventos |
| Futuro embaralhado, saída por tendência e previsões (drift, LightGBM) | limpo | limpo |
| Colônia, fechamento → próxima abertura | +0,52% → +0,48% por janela | +0,55% → +0,54% |
| Livro do PM, idem | +0,50% → +0,44% | +0,67% → +0,67% |
| Saída por tendência de 20/28 dias, idem | +1,88% → +1,81% | +1,49% → +1,49% |
| Nomes deixados de fora por sumirem no meio da janela | 0 | 0 |

- **Nada vazou.** Os números que este README mostra não dependem de
  informação do futuro.
- **A execução no mesmo fechamento quase não pesa**: nas ações custa
  0,04 ponto em 60 pregões; no cripto, 0,01 ponto em 30 dias, porque uma
  hora depois o preço é quase o mesmo. A colônia ao vivo, que executa no
  papel ao último fechamento, está otimista nessa mesma ordem de
  grandeza.
- **O viés que nenhum código remove é a escolha dos nomes.** As 6 ações
  do andar foram escolhidas hoje. Segurar só a Nvidia rendeu +14,3% por
  janela de 60 pregões, o SPY +2,7%, e as 6 juntas +5,1%: o "segurar"
  que a colônia não alcança já carrega o vencedor que só se conhecia
  depois. No cripto, os CSVs têm só moedas ainda listadas: as que
  morreram não estão lá.

**2. Boletim dos sinais (a ideia do
[alphalens](https://github.com/quantopian/alphalens))** —
`arena/signals.py`, `cryptoarena signals --floor stocks|crypto`.

Os agentes não publicam notas, eles seguram posições: o que cada
estratégia segura a cada fechamento (o fundador mais os estagiários que
contratou) é o sinal dela. Em janelas que não se sobrepõem, o boletim
mede:

- **IC**: a correlação de postos, entre os nomes, entre o peso e o
  retorno que veio depois (1, 5 e 20 pregões; no cripto, 1, 7 e 28
  dias). O *t* conta horizontes sobrepostos uma vez só.
- **escolha**: o que os nomes segurados fizeram depois, menos o
  universo com pesos iguais.
- **timing**: se ela estava mais investida antes das altas.
- **giro**: a fração da carteira negociada por dia.

| Ações, 20 janelas de 60 pregões | IC 20d | t | escolha 20d | t | timing | giro/dia |
|---|---|---|---|---|---|---|
| breakout | +0,057 | +0,8 | +0,19% | +0,4 | +0,04 | 1,4% |
| index | −0,040 | −0,8 | −0,67% | −1,9 | −0,06 | 0,3% |
| meanrev | −0,026 | −0,2 | +0,09% | +0,0 | −0,02 | 0,5% |
| momentum | +0,059 | +0,8 | +1,14% | +1,2 | +0,03 | 1,2% |
| regime | −0,017 | −0,2 | −0,31% | −0,5 | +0,01 | 2,2% |
| trend | +0,014 | +0,2 | +0,23% | +0,4 | −0,05 | 1,8% |
| voltarget | −0,148 | −2,2 | −0,54% | −1,0 | +0,01 | 0,8% |
| colônia | −0,035 | −0,6 | −0,20% | −1,1 | +0,00 | 1,0% |

| Cripto, 62 janelas de 30 dias | IC 28d | t | escolha 1d | t | escolha 7d | t | timing | giro/dia |
|---|---|---|---|---|---|---|---|---|
| breakout | +0,033 | +0,7 | +0,10% | +0,7 | +0,85% | +0,8 | +0,09 | 4,0% |
| meanrev | −0,013 | −0,2 | +0,27% | +1,5 | +0,45% | +0,3 | −0,11 | 1,5% |
| momentum | −0,001 | −0,0 | +0,17% | +1,5 | +1,05% | +1,4 | +0,09 | 3,1% |
| regime | +0,011 | +0,2 | +0,43% | +2,9 | +1,71% | +1,5 | +0,09 | 4,9% |
| trend | +0,021 | +0,5 | +0,17% | +1,6 | +1,23% | +1,6 | +0,10 | 4,6% |
| voltarget | +0,026 | +0,7 | +0,15% | +1,7 | +0,99% | +1,6 | +0,11 | 3,8% |
| colônia | +0,022 | +0,6 | +0,13% | +1,8 | +0,78% | +1,6 | +0,09 | 3,0% |

- **Nas ações, nenhuma estratégia escolhe.** Os ICs ficam em torno de
  zero, e o único *t* acima de 2 em valor absoluto é negativo (voltarget,
  −2,2). Entre 42 medidas, isso é o que o acaso entrega. O que separa as
  estratégias no placar é **quanto** elas ficam investidas numa alta,
  não **o que** escolhem.
- **No cripto, os nomes escolhidos rendem um pouco mais que a média no
  dia seguinte e na semana**, todas as estratégias na mesma direção
  (regime +0,43% num dia, *t* 2,9). Mas o IC de 1 dia é levemente
  negativo (momentum *t* −2,7), e é o mesmo efeito visto pelo outro lado:
  o retorno vem de **segurar** o que está subindo, não de **dosar** pelo
  tamanho da aposta. O ganho é pequeno diante dos 0,26% de taxa por lado
  e de um giro de 3% a 5% ao dia.
- O boletim é o que faltava para julgar uma fonte nova (FMP, Quiver) do
  mesmo jeito: ela entraria aqui antes de ganhar peso na colônia.

**3. HRP e paridade de risco no PM (as ideias do
[PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt) e do
[skfolio](https://github.com/skfolio/skfolio))** —
`portfolio/allocation.py`, `--pm-weighting votes|equal|inverse_vol|hrp`.

O PM continua usando os votos para decidir **quais** nomes segurar e
**quanto** investir no total. A diferença está em como esse total é
dividido entre os nomes:

- **votes**: na proporção dos votos (o atual);
- **equal**: fatias iguais (o controle);
- **inverse_vol**: inverso da volatilidade;
- **hrp**: Hierarchical Risk Parity (López de Prado, 2016). Agrupa os
  nomes por como andam juntos e divide a árvore de cima para baixo,
  galho contra galho, pelo inverso da variância de cada galho. Dois
  nomes que são a mesma aposta (QQQ e Nvidia, BTC e ETH) dividem uma
  fatia em vez de levar duas. Usa só numpy.

| Ações, 60 janelas | média/janela | desvio entre janelas | queda média na janela | vol. diária | contra os votos |
|---|---|---|---|---|---|
| votes (atual) | +0,50% | 5,25% | 3,99% | 0,50% | |
| equal | +0,29% | 4,59% | 3,75% | 0,46% | −0,21 pt (t −0,8) |
| inverse_vol | −0,06% | 3,71% | 3,35% | 0,39% | −0,55 pt (t −1,2) |
| hrp | −0,04% | 3,98% | 3,52% | 0,41% | −0,54 pt (t −1,3) |

| Cripto, 184 janelas | média/janela | pior janela | queda média na janela | vol. diária | taxas |
|---|---|---|---|---|---|
| votes (atual) | +0,67% | −10,5% | 5,08% | 0,98% | 33 |
| equal | +0,22% | −12,6% | 5,03% | 0,91% | 43 |
| inverse_vol | +0,13% | −11,8% | 4,82% | 0,87% | 44 |
| hrp | −0,12% | −12,1% | 4,90% | 0,87% | 57 |

- **O HRP faz o que promete: tira risco.** A volatilidade cai de 0,50%
  para 0,41% ao dia e a queda média na janela de 4,0% para 3,5%. Só que
  o retorno cai mais do que o risco (por unidade de desvio, +0,095
  contra −0,011). Nas ações, a divisão por risco tira peso justamente
  da Nvidia, a mais volátil e a maior vencedora.
  No cripto o corte de risco é pequeno (0,98% para 0,87% ao dia), a
  pior janela fica até pior, e o retorno cai 0,79 ponto por janela.
  Parte disso são taxas: reequilibrar por risco todo dia gira a
  carteira (57 contra 33). A vantagem do PM no cripto vinha de
  **compensar** as ordens dos agentes, e qualquer divisão que se afasta
  dos votos desfaz isso.
- **O PM segue com os votos.** O HRP fica disponível para o backteste, e
  o boletim do item 2 é o juiz se um dia o universo mudar.

```bash
cryptoarena lookahead --floor stocks                       # o auditor completo
cryptoarena backtest --floor stocks --fill next_open       # execução na abertura seguinte
cryptoarena signals --floor crypto                         # o boletim das estratégias
cryptoarena backtest --floor crypto --pm-weighting hrp     # o PM dividindo por risco
```

### O teste justo: universo escolhido na época, contra o SPY

As 6 ações do andar foram escolhidas hoje, então o histórico delas já
carrega o vencedor. Para tirar essa vantagem, a mesma colônia (mesmos 9
agentes, mesmos parâmetros, janelas de 60 pregões a cada 20) rodou em
mais três universos. Todos são comparados com **segurar o SPY nas mesmas
janelas** (`--benchmark SPY`):

- **27 ETFs de índices do mundo** (2017–2026, branch `global-data`):
  nenhuma ação escolhida com o benefício de hoje.
- **As 100 maiores empresas dos EUA, escolhidas na época**
  (`--top N --always SPY,QQQ`). Em cada janela entram só as N que mais
  movimentaram dinheiro (preço × volume) nos 250 pregões anteriores, ou
  seja, com o que se sabia antes da janela, mais SPY e QQQ para a Inês.

| Universo (janelas) | colônia/janela | segurar o universo | SPY | colônia − SPY | t | colônia bate SPY |
|---|---|---|---|---|---|---|
| as 6 de hoje (60) | +0,52% | +5,08% | +2,70% | −2,19 pt | −1,9 | 35% |
| 27 ETFs do mundo (111) | −0,68% | +1,82% | +3,30% | −3,98 pt | −4,1 | 17% |
| top 6 da época + SPY/QQQ (111) | +1,42% | +6,69% | +3,30% | −1,88 pt | −1,9 | 31% |
| top 20 da época + SPY/QQQ (111) | +1,81% | +5,06% | +3,30% | −1,49 pt | −1,6 | 37% |

Em ritmo anual aproximado: a colônia faz de −2,8% (ETFs) a +7,8% (top
20) ao ano; o SPY, +14,6% no mesmo período.

- **Em nenhum universo a colônia bate o SPY.** Nos ETFs, onde não há
  vencedor escolhido de antemão, ela perde 4 pontos a cada 60 pregões
  (*t* −4,1): é o resultado mais limpo, e o pior.
- **A melhor estratégia isolada também não se sustenta.** O Marco
  Maratona (`momentum-2`) faz +1,37 pt contra o SPY no top 20 (*t* 0,7),
  empata no top 6 e perde 4,3 pt nos ETFs. O Tomás Bússola (`trend-1`)
  repete o padrão. Nenhuma diferença positiva passa perto de
  significativa.
- **O top 100 ainda tem um viés**: a lista é a das maiores de hoje, e
  as que caíram ou sumiram desde 2016 não estão nela. Por isso segurar o
  top 20 rende mais que o SPY (+5,06% contra +3,30%), e a colônia, mesmo
  assim, fica abaixo dos dois. Sem esse viés, o resultado só pioraria.
- **Os parâmetros do andar foram ajustados nas 6 ações de hoje.** Fora
  delas, eles rendem menos, que é o sinal clássico de ajuste ao passado.

**Veredito**: com as regras de hoje, os agentes não têm vantagem sobre
segurar o índice, e o teste justo deixa isso mais claro, não menos. O
andar de ações continua como laboratório no papel e na conta Practice;
dinheiro de verdade vai para o índice.

```bash
cryptoarena backtest --floor stocks --data data/global/etf --benchmark SPY --quiet
cryptoarena backtest --floor stocks --data <stocks + SPY + QQQ> --top 20 --always SPY,QQQ --benchmark SPY --quiet
```

### Wyckoff: todos os agentes aprenderam, e o teste mandou desligar

O método de Richard Wyckoff lê o rastro do "grande operador" no preço e
no volume. Ele **acumula** numa faixa de negociação depois de uma queda e
**distribui** numa faixa depois de uma alta, deixando eventos no caminho.
`agents/wyckoff.py` lê esses eventos de forma mecânica:

- **spring**: fura o suporte da faixa e fecha de volta dentro;
- **sinal de força (SOS)**: fecha acima da resistência com volume 1,5×
  a média da faixa;
- **último ponto de suporte (LPS)**: recuo calmo que segura acima da
  antiga resistência;
- **upthrust**: passa da resistência e fecha de volta dentro, com volume;
- **sinal de fraqueza (SOW)**: fecha abaixo do suporte com volume.

Cada leitura vira uma nota de +1 (acumulação concluída) a −1
(distribuição concluída). Os agentes usam isso de dois jeitos:

- **A lente, em todos os agentes de regra** (`wyckoff`, 0 = desligada;
  `wyckoff_range` em barras, 40 pregões nas ações e 240 horas no
  cripto). Ela vende no upthrust e no sinal de fraqueza, nunca compra
  dentro de um, e põe na frente da fila o nome com spring, SOS ou LPS.
  Sobrevive a salvar e restaurar a colônia, e os estagiários a herdam.
- **📊 Walter Volume** (`WyckoffAgent`), um especialista que só opera os
  eventos.

| Contra a colônia sem Wyckoff | 6 ações (60) | 27 ETFs (111) | top 20 da época (111) | cripto (184) |
|---|---|---|---|---|
| colônia sem Wyckoff | +0,52% | −0,68% | +1,81% | +0,55% |
| todos com a lente | +0,17% (−0,35 pt, t −1,7) | −1,02% (−0,34 pt, t −1,8) | +1,67% (−0,14 pt, t −0,6) | +0,15% (−0,39 pt, t −1,2) |
| Walter sozinho | +0,32% | −1,16% | +1,52% | **−5,60%** |
| segurar o índice (SPY / BTC) | +2,70% | +3,30% | +3,30% | +1,98% |

Por janela: 60 pregões nas ações e 30 dias no cripto.

- **A lente piorou a colônia nos quatro universos.** Ela vende em
  "sinais de fraqueza" que, na maioria das vezes, não continuam, e
  aumenta as taxas (no cripto, 48 contra 33 no livro do PM).
- **O Walter sozinho perde do índice em todos**, e no cripto perde feio:
  em velas de hora aparecem muitos springs e rompimentos falsos.
- **Não é falta de ajuste.** Faixas de 20, 60 e 100 pregões nas ações e
  de 120 a 320 horas no cripto dão o mesmo veredito: nenhuma combinação
  bate o SPY ou o BTC, e a melhor (lente com 60 pregões no top 20, +1,82%)
  só empata com a colônia sem Wyckoff (+1,81%).

**Veredito**: os agentes sabem Wyckoff, mas a lente fica **desligada**
(`wyckoff` 0) e o Walter fica **contratável**, não fundador. Ligar é uma
linha, se um dia o boletim das estratégias mostrar que os eventos
predizem alguma coisa:

```bash
cryptoarena backtest --floor stocks --wyckoff 1 --benchmark SPY --quiet    # a lente em todos
```

### A academia: cursos do livro *Algorithmic Trading with Python*

Os agentes fizeram os cursos de *Algorithmic Trading with Python* (Chris
Conlan, 2020; código em
[chrisconlan/algorithmic-trading-with-python](https://github.com/chrisconlan/algorithmic-trading-with-python)).
O objetivo não é fortuna: é que cada agente saiba dizer como está indo,
conheça as ferramentas clássicas e saiba separar habilidade de sorte.

**Sobre a licença.** O código do livro é "freeware" para uso pessoal e
proíbe redistribuição em material educativo sem permissão do autor.
Como este repositório é público, **nenhuma linha dele foi copiada**:
cada curso é a ideia do capítulo escrita de novo aqui, com crédito, e
os dados do livro também não vêm junto.

| Curso | Capítulo | O que os agentes aprendem | Onde mora |
|---|---|---|---|
| 1 · Medir desempenho | 2 | CAGR, volatilidade, Sharpe, Sortino, queda máxima, Calmar, *pure profit score*, beta e alfa de Jensen | `portfolio/metrics.py` |
| 2 · Indicadores e sinais | 3 | MACD, Bandas de Bollinger, Chaikin Money Flow: três especialistas formados | `agents/rules.py` |
| 3 · Simular uma carteira | 4 | vagas limitadas, preferência entre candidatos, slippage e taxa fixa | `arena/booksim.py` |
| 4 · Não se enganar | 5 | testes de ruído branco e de bootstrap | `arena/booksim.py` |
| 5 · Aprendizado de máquina financeiro | 6 e 7 | filtro CUSUM, barreira tripla, peso por exclusividade, walk-forward com purga | `forecast/events.py` |

`cryptoarena academy` lista o currículo; `cryptoarena academy --course N
[--data DIR]` aplica a prova.

**Prova do curso 1: o boletim de cada um** (andar de ações, uma colônia
contínua de 2021 a 2026, contra segurar o SPY):

| | CAGR | vol. | Sharpe | Sortino | queda máx. | beta | alfa/ano |
|---|---|---|---|---|---|---|---|
| 🏔️ Marco Maratona | +10,2% | 20,2% | +0,50 | +0,76 | 42,4% | 0,51 | +5,4% |
| ⚡ Nina Faísca | +6,5% | 14,6% | +0,45 | +0,67 | 21,0% | 0,40 | +2,4% |
| 🧭 Tomás Bússola | +5,8% | 16,8% | +0,34 | +0,52 | 31,3% | 0,46 | +1,3% |
| 🏃 Rita Rush | +5,5% | 15,9% | +0,35 | +0,51 | 26,4% | 0,35 | +2,2% |
| 🗿 Inês Índice | +4,2% | 12,4% | +0,34 | +0,48 | 20,4% | 0,69 | −3,8% |
| 🎚️ Vera Calma | +1,7% | 8,7% | +0,19 | +0,27 | 19,0% | 0,29 | −1,6% |
| 🌦️ Otto Clima | 0,0% | 12,6% | 0,00 | 0,00 | 28,3% | 0,29 | −2,8% |
| 🧘 Theo Paciência | −5,1% | 3,7% | −1,39 | −2,05 | 24,2% | 0,05 | −5,8% |
| 🪃 Bea Bounce | −6,5% | 5,5% | −1,18 | −1,50 | 30,9% | 0,10 | −7,8% |
| 🏢 colônia | +3,5% | 10,2% | +0,35 | +0,51 | 20,5% | 0,35 | −0,4% |
| segurar SPY | +11,6% | 17,2% | +0,68 | +0,98 | 25,4% | 1,00 | 0 |

O boletim mostrou duas coisas que o placar escondia:

- **O custo de vida pesa.** Cada agente paga 0,02% do orçamento por dia,
  cerca de 5% ao ano. Sem esse custo, a colônia sobe +1,2 ponto por
  janela de 60 pregões: nas 6 ações vai de +0,52% para +1,72%, nos ETFs
  de −0,68% para +0,55% e no top 20 da época de +1,81% para +3,04%,
  quase o SPY (+3,30%). Na conta Practice não existe aluguel. O custo é
  uma regra do jogo de sobrevivência, não do mercado.
- **O cinto de cada agente limita o investimento.** O funil de risco
  permite no máximo 35% do patrimônio num nome. A Inês, que só segura SPY
  e QQQ, fica com no máximo 70% investido: daí o beta de 0,69 e o alfa
  negativo, que são só a parte parada em caixa.
- Os alfas positivos (Marco +5,4%/ano) vêm de uma única fita de 5 anos
  nas 6 ações escolhidas hoje. O teste justo mostra que eles não
  sobrevivem fora delas.

**Prova do curso 2: os formandos** (sozinhos, janelas de 60 pregões,
contra o SPY):

| | 6 de hoje | 27 ETFs | top 20 da época |
|---|---|---|---|
| 〽️ Maria MACD | −4,02 pt (t −3,4) | −3,89 pt (t −3,9) | −2,12 pt (t −1,8) |
| 📏 Bento Bollinger | −2,21 pt (t −1,9) | −4,15 pt (t −4,5) | −3,39 pt (t −3,1) |
| 💧 Chica Chaikin | −1,94 pt (t −1,5) | −3,66 pt (t −3,9) | −0,18 pt (t −0,1) |

Nenhum bate o índice. A Chica Chaikin empata no top 20, num universo que
ainda favorece quem compra as maiores de hoje.

**Provas dos cursos 3 e 4: habilidade ou sorte?** É o simulador do
livro: 5 vagas, sinal de Bollinger ou MACD, preferência pelo Sharpe dos
últimos 20 dias. Cada carteira roda de novo com uma preferência que não
sabe nada: ruído branco (200 vezes) ou Sharpe de retornos reamostrados
(100 vezes).

| | contra o SPY, ao ano | supera, das que não sabem nada |
|---|---|---|
| 27 ETFs · Bollinger | −7,75% | 12% (ruído) · 11% (bootstrap) |
| 27 ETFs · MACD | −8,56% | 78% · 75% |
| 100 maiores · Bollinger | +0,18% | 71% · 66% |
| 100 maiores · MACD | +0,44% | 60% · 60% |

Para contar como habilidade, a preferência teria de superar uns 95%
delas. Nenhuma passa disso: **escolher pelo Sharpe recente não é
diferente de escolher ao acaso**. Nas 100 maiores, as carteiras ao acaso
já ficam perto do SPY, porque a lista é a das sobreviventes de hoje.

**Prova do curso 5: aprendizado de máquina com cuidado.** Eventos pelo
filtro CUSUM, rótulos de barreira tripla (±1 volatilidade × √20, ou 20
pregões), pesos por exclusividade, floresta aleatória com 10
características de preço e volume. Treino só com o que já tinha
terminado antes de cada ano:

- **100 maiores, 2018–2026 (63 mil eventos):** acerto de 43% a 54% por
  ano. Sempre chutar o rótulo mais comum acerta de 47% a 66%, e o modelo
  só empata ou perde. Os eventos que o modelo escolheu rendem o mesmo que
  todos (em 2026, +1,07% contra +0,75%; em 2024, +1,09% contra +1,23%).
- **27 ETFs (18 mil eventos):** mesmo quadro, com acerto de 40% a 54%.

**Veredito da academia**: os agentes agora medem, simulam e testam como
o livro ensina, e as provas confirmam o que o resto deste README já
dizia. Nenhuma técnica do livro dá vantagem sobre segurar o índice
nestes dados. O que a academia ganhou foi método: o boletim do curso 1
achou o custo de vida e o cinto de 35%, que já explicam boa parte da
distância.

### Curso 6: 21 técnicas de análise técnica, e a confiança que cada uma ganhou

Os agentes aprenderam as técnicas que mais se ouve no mercado
(`agents/technical.py`). Cada uma virou uma regra mecânica que, no
fechamento de cada barra, diz compra (+1), venda (−1) ou nada, usando só
o passado. Os topos e fundos (pivôs) só contam a partir da barra que os
confirma, e são montados um dia de cada vez. A primeira versão juntava
fundos seguidos olhando o futuro, o que apagava justamente os padrões
que falhavam; foi corrigida antes da prova. O auditor de futuro
embaralhado (`arena/lookahead.py`) passa limpo nas 21, em ações e em
cripto.

A prova (`learning/ta_exam.py`, `cryptoarena academy --course 6`):

- **Entrada e medida.** Em cada sinal, a operação entra na abertura
  seguinte e é medida 5 e 20 barras depois, contra o retorno *normal*
  daquele papel no mesmo prazo. Uma alta geral não faz todo sinal de
  compra parecer bom, e um sinal de venda pontua quando o papel rende
  menos que o normal.
- **Universos.** 4 universos: as 6 ações, 27 ETFs de índices, as 100
  maiores (2016–2026) e 24 moedas em barras diárias (2021–2026). São
  cerca de 367 mil barras e 355 mil sinais.
- **Contagem honesta.** Os sinais vêm em grupos (uma queda geral dispara
  a mesma compra em muitos nomes), então o *t* conta blocos de *h*
  barras, não operações. Com 332 testes de uma vez, alguns "significativos"
  aparecem por acaso, e a correção de Benjamini–Hochberg (*q*) mede quantos
  sobrevivem.
- **Notas.**
  - **A**: a vantagem resiste à correção e aparece na maioria dos
    universos. Só a nota A dá confiança acima de zero.
  - **B**: positiva na maioria dos universos, mas não resiste à
    correção.
  - **C**: sem direção.
  - **D**: aponta para o lado errado.

| Técnica | Nota | vantagem média em 20 barras | universos a favor | menor *q* | confiança |
|---|---|---|---|---|---|
| Fibonacci (retração 50–61,8%) | C | +0,29% | 2 de 4 | 0,76 | 0 |
| Padrões de rompimento | D | -1,52% | 0 de 4 | 0,46 | 0 |
| Padrões de reversão (fundo/topo duplo, OCO) | D | -0,13% | 1 de 4 | 0,33 | 0 |
| Ondas de Elliott (entrada na onda 3) | D | -0,58% | 1 de 4 | 0,23 | 0 |
| Fair value gap | D | -0,58% | 0 de 4 | 0,65 | 0 |
| Padrões de candle | C | +0,04% | 2 de 4 | 0,47 | 0 |
| Heikin-Ashi | D | -0,33% | 0 de 4 | 0,65 | 0 |
| Fases da lua | C | -0,30% | 2 de 4 | 0,53 | 0 |
| Renko | D | -0,72% | 0 de 4 | 0,06 | 0 |
| Padrões harmônicos | B | +0,03% | 2 de 3 | 0,54 | 0 |
| Suporte e resistência | B | +0,07% | 3 de 4 | 0,62 | 0 |
| Suporte dinâmico (média de 20) | D | -0,45% | 0 de 4 | 0,46 | 0 |
| Linhas de tendência | D | -0,92% | 1 de 4 | 0,39 | 0 |
| Leque de Gann (1×1) | B | +0,12% | 3 de 4 | 0,40 | 0 |
| Osciladores (IFR 30/70) | B | +0,98% | 4 de 4 | 0,46 | 0 |
| Divergência preço × IFR | B | +0,21% | 3 de 4 | 0,78 | 0 |
| Indicador de volume (OBV) | D | -0,40% | 0 de 4 | 0,34 | 0 |
| Oferta e demanda | B | +0,16% | 3 de 4 | 0,47 | 0 |
| Estrutura de mercado | D | -0,46% | 0 de 4 | 0,46 | 0 |
| BOS | D | -1,54% | 0 de 4 | 0,23 | 0 |
| CHoCH | D | -1,12% | 0 de 4 | 0,39 | 0 |

- **Nenhuma técnica tirou A, e a confiança de todas é zero.** O menor
  *q* de todo o exame (0,06) é de um sinal que funciona *ao contrário*:
  a compra do Renko nas 100 maiores rende 0,34% *menos* que o normal em
  5 pregões.
- **As entradas "a favor da tendência" tendem a render menos que o
  normal**: rompimento, BOS, CHoCH, onda 3 de Elliott, estrutura e Renko
  nas compras. Nas ações, o curto prazo costuma devolver parte do
  movimento, o que é conhecido na literatura. Nenhum desses resultados
  passa da correção, então não há base para operar o contrário deles.
- **As de nota B** (IFR, divergência, suporte e resistência, Gann,
  harmônicos, oferta e demanda) apontam para o lado certo em 3 ou 4
  universos, mas com vantagem pequena e sem passar na correção. É o que
  se espera do acaso entre 21 técnicas.
- **A lua não move nada**: −0,30% em 20 barras, dentro do ruído, a
  favor em 2 de 4 universos.

**O conselho técnico.** Todo agente de regra pode consultar as 21 técnicas
(`ta` > 0): cada uma vota com o peso da confiança que ganhou
(`agents/ta_confidence.json`). Voto negativo veta a compra e voto positivo
põe o nome na frente da fila. Hoje todos os pesos são zero, então o
conselho não muda nada. A confiança dos agentes nessas técnicas está
**calibrada**: é exatamente o que a prova mostrou. Se uma nova prova (mais
anos, outro mercado) der nota A a alguma técnica, ela ganha voz sozinha,
sem mudar código.

### Curso 7: os grandes traders, da série *Market Wizards* a Kotegawa

Os agentes estudaram a trajetória de quem fez algo raro por muito tempo
(`learning/wizards.py`). As fontes são a série de Jack Schwager (*Market
Wizards* 1989, *The New Market Wizards* 1992, *Stock Market Wizards* 2001,
*Hedge Fund Market Wizards* 2012, *Unknown Market Wizards* 2020) e os
resumos públicos dela, *Pit Bull* (Marty Schwartz, 1998) e a imprensa
japonesa sobre Takashi Kotegawa. Números que os traders nunca auditaram
estão marcados como divulgados.

| Mestre | Trajetória | Lições |
|---|---|---|
| Michael Marcus | Começou em 1972 com ~US$7 mil e quebrou mais de uma vez; aprendeu risco com Seykota; teria feito US$30 mil virarem US$80 milhões na Commodities Corporation (divulgado); formou Bruce Kovner | corte as perdas cedo; só os melhores setups; o trade forte é quando fundamento, gráfico e mercado concordam |
| Ed Seykota | Pioneiro dos sistemas de tendência por computador, ~1970 | quem segue tendência perde na maioria dos trades e vive de cortar perdas e deixar os ganhos correrem |
| Paul Tudor Jones | Tudor Investment (1980); ganhou no crash de 1987 | defesa antes de ataque; fora de tudo que estiver abaixo da média de 200 dias (dito a Tony Robbins) |
| Richard Dennis e as Tartarugas | Ensinou novatos com regras fechadas em 1983 | rompimento de 20/55 dias, saída de 10/20, tamanho pela volatilidade |
| Larry Hite | Mint Investment | nunca arrisque mais de 1% num trade |
| Marty Schwartz | Só ficou lucrativo ao trocar fundamentos por técnica; campeão do U.S. Investing Championship | a média exponencial de 10 dias é sinal verde ou vermelho |
| Bruce Kovner | Aprendiz de Marcus; Caxton | stop onde o mercado provaria o erro; risco pequeno |
| Linda Raschke | Trader de curto prazo; o *Holy Grail* (*Street Smarts*, 1995) | poucos padrões, bem conhecidos |
| Stanley Druckenmiller | Duquesne, Quantum | concentre com convicção; importa quanto ganha quando acerta |
| William O'Neil e David Ryan | CAN SLIM; Ryan venceu o campeonato três vezes | compre força em máxima nova; corte a perda em 7–8% |
| Mark Minervini | Campeão de 1997 | só ações no *trend template*; stop curto |
| Takashi Kotegawa (BNF) | Comprava papéis 20–35% abaixo da média de 25 dias e vendia na volta (limite que ele disse ter mudado); o erro da Mizuho com a J-Com em 2005; nunca confirmou nome nem números | compre o pânico, venda a volta ao normal; segure pouco |

As lições aparecem nas conversas do escritório ("As Michael Marcus put it:
…"). As regras mecânicas o bastante para virar código foram testadas assim:

- **Entrada e custo.** A entrada é na abertura seguinte, com custo de
  negociação.
- **Contra o quê.** A regra é comparada com segurar o ativo ou o índice e
  com a mesma regra com as **entradas sorteadas**: mesmo número de
  entradas, nos dias em que a posição poderia viver, e as mesmas saídas.
  Se a regra não supera o próprio sorteio, o mérito não está no momento
  de entrar.
- **Sobre o sorteio.** As duas primeiras versões dele favoreciam as
  regras: uma embaralhava também as saídas, a outra punha entradas em
  dias em que a saída já mandava sair. As duas foram corrigidas antes do
  veredito.

**Regras de tempo num ativo só** (ETFs 2017–2026, BTC e ETH diários
2021–2026; CAGR da regra / de segurar · queda máxima · supera quantas
entradas sorteadas):

| | SPY | QQQ | ACWI | GLD | BTC | ETH |
|---|---|---|---|---|---|---|
| **Paul Tudor Jones, média de 200** | +7,9% / +13,2% · 22% (34%) · 76% | +15,3% / +19,8% · 23% (36%) · 92% | +6,6% / +9,8% · 21% (34%) · 78% | +9,8% / +13,9% · 30% (26%) · 46% | **+30,6% / +14,6%** · 33% (66%) · 92% | **+22,7% / −5,4%** · 36% (72%) · 84% |
| Tartarugas, 20/10 | +8,4% · **9%** (34%) · 14% | +11,7% · 15% (36%) · 12% | +3,0% · 15% · 14% | +3,6% · 22% · 26% | +11,1% · 35% · 64% | −13,5% · 65% · 26% |
| Tartarugas, 55/20 | +2,3% · 26% · 0% | +8,5% · 18% · 4% | +2,0% · 19% · 2% | +7,8% · 19% · 32% | +8,1% · 33% · 42% | +18,1% · 34% · 66% |
| Marty Schwartz, exponencial de 10 | +1,8% · 38% · 24% | +4,2% · 42% · 40% | +1,9% · 31% · 18% | +4,6% · 26% · 28% | −1,8% · 45% · 44% | −16,4% · 65% · 18% |

- **A regra dos 200 dias de Tudor Jones é a lição que melhor se
  sustenta**: a queda máxima é menor em 8 dos 9 ativos testados (só o
  ouro piora), o Sharpe melhora em 5 dos 9 (QQQ, ACWI, TLT, BTC e ETH), e
  as entradas dela superam de 76% a 92% das sorteadas em SPY, QQQ, ACWI,
  EFA e BTC (nos emergentes, só 46%).
  Nas ações ela custa retorno (SPY +7,9% contra +13,2% ao ano). No cripto
  rende mais que segurar, mas isso vem de um único ciclo de 5 anos, com
  uma única grande queda (2022). É "defesa antes de ataque", não uma
  fonte de retorno.
- **As Tartarugas no SPY têm o melhor Sharpe (0,85 contra 0,70) e a menor
  queda (9% contra 34%)**, mas as entradas delas superam só 14% das
  sorteadas. O que protege é a **saída** (o mínimo de 10 dias), ou seja,
  "corte as perdas", não o rompimento.
- **A exponencial de 10 dias de Schwartz perde para segurar em todos os
  9 ativos**: entra e sai demais, e o custo come o resto. Ela fazia sentido
  como filtro para um trader de curto prazo que lê o pregão, não como
  sistema sozinho.

**Regras de escolha de ações** (até 10 posições; CAGR contra o SPY, que
fez +13,2% ao ano):

| | 100 maiores (o universo fez +13,9%) | 27 ETFs (o universo fez +6,5%) |
|---|---|---|
| Kotegawa, 10% abaixo da média de 25 | +12,4% · supera 100% dos sorteios | +0,1% · 20% |
| Kotegawa, 15% / 20% | +4,5% / +1,8% · 88% / 66% | −1,4% / −0,7% · 0% / 2% |
| Minervini, *trend template* e stop de 8% | +8,3% · 26% | +1,6% · 98% (quase sempre fora) |
| O'Neil/Ryan, máxima de 52 semanas com volume | +0,1% · 16% (quase sempre fora) | −0,6% · 18% |
| Raschke, *Holy Grail* | −0,6% · 4% | 0,0% · 74% (quase nunca entra) |
| Tartarugas 20/10 | +13,5% · 78% | +2,6% · 2% |
| Tudor Jones, 200 dias (líderes de 12 meses) | **+19,9%** · 90% | +4,4% · 10% |

- **Duas regras parecem boas nas 100 maiores**: comprar a queda forte
  (Kotegawa, 10%) e voltar aos líderes acima da média de 200. As duas
  apostam em empresas que *sobreviveram* até hoje: uma lista escolhida
  em 2026 garante que cada queda comprada foi recuperada e que cada líder
  continuou líder. Nos 27 ETFs, sem esse viés, as duas somem.
- O limite original de Kotegawa (20% ou mais) quase não ocorre em grandes
  empresas americanas e rende +1,8% ao ano. Ele mesmo disse que o número
  era de um regime específico.

**As regras de risco de Marcus, Seykota e Hite sozinhas**: entradas
sorteadas nas 100 maiores, 20 vezes cada (contra o SPY, ao ano):

| | média | pior | melhor |
|---|---|---|---|
| segurar 20 dias | −2,0% | −10,0% | +3,5% |
| stop de 8% + *trailing* de 15% | −4,0% | −8,1% | +2,2% |
| só stop de 8%, até 60 dias | −2,3% | −6,3% | +3,2% |

Cortar perdas sem uma entrada boa não cria retorno. Ele **estreita os
resultados**: o pior caso melhora de −10% para −6% a −8% ao ano, e a
dispersão cai. É exatamente o que Marcus e Seykota dizem que ele faz: dá
sobrevivência para que uma entrada boa tenha tempo de aparecer.

**A regra dos 200 dias na Inês.** A Inês (`index-1`) é o índice do
andar: compra SPY e QQQ e não vende. O teste mostrou que ela nunca foi o
índice inteiro, por causa de três limites:
- cada ordem vai a no máximo 25% do patrimônio, e ela só compra quando
  está zerada;
- o limite de 35% por nome;
- o stop de 12% do risco, que a vendia em toda queda maior que isso.

Agora um agente pode ter os próprios limites (`risk_position`,
`risk_order`, `risk_stop`), e a Inês ganhou a regra de Tudor Jones
(`exit_ma`: fora enquanto fecha abaixo da média de 200, de volta acima
dela). Ela sozinha, de forma contínua, sem a mesa:

| | SPY+QQQ 2017–2026: CAGR · Sharpe · queda máx. | andar de ações 2021–2026 |
|---|---|---|
| A · hoje (cerca de 60% investida) | +11,0% · 0,82 · 21,9% | +8,4% · 0,75 · 16,4% |
| B · hoje + 200 dias | +6,7% · 0,83 · 12,9% | +6,0% · 0,82 · 11,6% |
| C · carteira cheia (sem os três limites) | **+17,0%** · 0,81 · 31,2% | **+13,3%** · 0,67 · 30,2% |
| D · cheia + 200 dias | +12,2% · **0,85** · 21,9% | +11,1% · **0,83** · 21,7% |
| segurar 50/50 SPY+QQQ | +17,1% · 0,81 · 31,2% | +13,3% · 0,67 · 30,2% |

Os números acima são sem o custo de vida; com ele, todas perdem de 1,5 a
5,4 pontos ao ano, e mais as que ficam parte do tempo em caixa.

- **C é o índice de verdade**: rende o mesmo que segurar, dentro de 0,1
  ponto. Era o que a Inês deveria ter sido desde o começo.
- **D troca retorno por defesa**: 5 pontos a menos por ano em 2017–2026
  (2 pontos em 2021–2026), um terço a menos de queda máxima e o melhor
  Sharpe das cinco linhas.
- A colônia ao vivo continua com a Inês de hoje até o dono escolher.

**Veredito do curso 7**: o que os mestres têm em comum, e o que os testes
confirmam, é **gestão de risco**, não um sinal mágico. A média de 200
dias e a saída das Tartarugas reduzem quedas de verdade; nenhuma regra
bate segurar o índice em retorno sem depender de um universo com viés ou
de um único ciclo. `cryptoarena academy --course 7 --data DIR` mostra as
trajetórias e refaz as regras de tempo.

### Aprender em vez de sobreviver (13/10/2026)

Decisão do dono: por enquanto, **ninguém é mandado embora**, e a meta deixa
de ser diária e passa a ser anual. Nos dois andares (`floors.py`):

- **`dismissals` desligado**: nem o estagiário abaixo da linha, nem o que
  acionou o kill switch é dispensado. O kill switch ainda o tira do resto
  do dia. Os erros continuam virando lições todas as noites.
- **`annual_target` 8% ao ano**, julgado pelo **ritmo**: no dia *d*, a
  meta do agente é o orçamento × 1,08^(*d*/252) nas ações (365 no cripto).
  Quem está abaixo do ritmo conta como "perdeu a meta", pede dica ao
  mentor e, depois de 3 dias seguidos, ao sênior. O happy hour semanal
  usa a mesma régua: o ritmo anual de uma semana, não 0,2% ao dia.
- **Custo de vida zero** (`daily_cost` 0): o aluguel diário só fazia
  sentido como pressão de sobrevivência e tirava cerca de 1,2 ponto a
  cada 60 pregões.
  - *Corrigido em 26/10/2026*: o livro do PM guarda a própria taxa e
    continuou pagando aluguel por 9 pregões depois disso ($2,38 no andar de
    ações). Agora ele segue o aluguel do andar a cada tick, e os $2,38
    foram devolvidos uma vez no estado salvo, com uma linha no feed da
    mesa. Desde 30/09, PM e colônia empatam (−1,73% cada). Os agentes, o
    espelho e o placar não mudam.
- A colônia ao vivo guarda a própria configuração, mas estes campos
  (`POLICY_FIELDS`), como os da mesa, passam a valer no próximo tick real.

O mesmo backtest das 6 ações, com as regras novas:

- **Em janelas de 60 pregões**: +1,72% contra +0,52% antes, e o SPY fez
  +2,70%.
- **Em janelas de um ano** (16 janelas, 2021–2026): a colônia fez **+9,95%
  em média** (mediana +7,6%; 75% das janelas positivas) contra +13,2% do
  SPY. Chegou aos 8% em 8 das 16 janelas, e o SPY em 12.
- **Nos anos de queda** a colônia perdeu bem menos: −3,5%, −12,6% e −2,1%
  contra −17,7%, −18,9% e −12,5% do SPY. Nas altas ela fica para trás.

### Mais agressividade, as mesmas regras de gráfico (13/10/2026)

Decisão do dono: a Inês passa a ser o **índice inteiro** (versão C), e o
resto da colônia fica **mais agressivo** sem mudar o que cada um lê no
gráfico. No andar de ações:

- **A Inês**: metade em SPY, metade em QQQ, sem stop, e completa a posição
  quando o cinto cortou uma ordem. Antes ela só comprava zerada.
- **Os outros 8 agentes**: até 50% do patrimônio num nome e numa ordem
  (eram 35% e 25%) e **sem o stop de 12% do risco**. Cada estratégia mantém
  as próprias saídas, e o kill switch de 50% continua.
- **A mesa**: teto de 35% por nome na colônia (era 20%).
- **Na colônia ao vivo**: os cintos de cada agente (`POLICY_PARAMS`) passam
  a valer no próximo tick, por cima do estado salvo. O que cada agente
  aprendeu sozinho (tamanho de ordem, limiares) continua dele.

Testado antes de ligar, com a Inês C em todos (por janela; pior janela;
quantas vezes bate o SPY):

| | 6 ações, 1 ano | 6 ações, 60 pregões | top 20 da época, 60 | 27 ETFs, 60 |
|---|---|---|---|---|
| só a Inês C | +10,7% · −13,7% · 38% | +1,86% · −4,9% | +3,24% · −8,3% | +0,73% · −7,3% |
| + posições e ordens até 50% | +11,5% · −18,5% · 50% | +2,11% · −7,2% | +3,86% · −12,5% | +0,68% · −10,4% |
| + teto da mesa 35% | +12,3% · −19,0% · 44% | +2,32% · −7,3% | +4,04% · −13,7% | +0,67% · −10,4% |
| **+ sem stop de 12% (o escolhido)** | **+12,4% · −19,5% · 44%** | **+2,36% · −7,5%** | **+4,32% · −13,7%** | +0,69% · −10,8% |
| segurar o SPY | +13,2% · −18,9% | +2,70% | +3,30% | +3,30% |

- **A agressividade aproxima a colônia do índice nas ações**: +12,4% ao
  ano contra +13,2% do SPY, com uma pior janela (−19,5%) praticamente igual
  à pior do SPY (−18,9%). No top 20 da época ela passa o SPY por janela
  (+4,32% contra +3,30%), num universo que ainda favorece as sobreviventes.
- **Nos ETFs não muda nada** (+0,7%): mais tamanho não cria vantagem onde
  as regras não têm.
- A Inês C rende como o índice que ela segura: +13,9% por ano e +2,76% por
  janela de 60 pregões.

### O placar para dinheiro real, combinado antes dos resultados (13/10/2026)

Antes de ver um único dia de resultado sob as regras novas, o dono e a
colônia combinaram o que precisa ser verdade para **sequer discutir**
dinheiro real (`arena/readiness.py`). Escrever a linha antes é o ponto:
uma linha traçada depois dos resultados cai onde eles estão.

| Critério | O que pede (andar de ações) |
|---|---|
| **tempo** | 126 pregões (seis meses; o ideal é 252, um ano) **sob as mesmas regras** |
| **retorno** | a colônia à frente de segurar o SPY no mesmo período, já descontadas as próprias taxas |
| **queda** | a pior queda da colônia, de um pico ao fundo, não mais funda que a do SPY no período |
| **espelho** | a conta Practice da Trading 212 acompanhando, noite a noite: 20 noites medidas no mínimo, nenhuma ordem falhada ou sem resposta, a conta ilegível em no máximo 10% das noites, e em média no máximo 5% do que a noite anterior mirou faltando na conta |

- **O relógio zera sozinho** quando as regras mudam: a configuração do
  andar (comparada com o retrato tirado quando o relógio começou), quem
  são os fundadores, o cinto que o andar dá a cada um, o **código** das
  estratégias (sem comentários nem docstrings), as fontes que eles escutam
  e o próprio placar viram uma impressão digital. Mudou, a contagem
  recomeça do fechamento seguinte, e a mudança aparece no feed da mesa.
  Mexer num critério também zera: a linha não se move depois de traçada.
  O que a impressão não enxerga (como as ordens são executadas, a mesa, o
  gerente de risco) se declara à mão, subindo `REVISION`.
- **O espelho deixa um registro por execução** no diário da colônia:
  ordens enviadas, ordens com problema, se a conta não pôde ser lida
  (nada enviado: conta como noite perdida, não como incidente), quanto do
  que a execução anterior mirou a conta não tinha (pega ordem recusada na
  abertura, preenchimento parcial, mão na conta; não se mede enquanto uma
  ordem ainda espera a abertura) e quanto da carteira fica só no papel
  porque a corretora não lista o papel (SPY e QQQ não são vendidos a
  contas do Reino Unido). Uma noite vai de uma abertura do mercado à
  seguinte: a nova tentativa das 05:30 e qualquer reexecução contam dentro
  dela, e vale a pior medida da noite. **Só contagens e proporções**:
  nenhum saldo da conta vai para o banco público.
- **A Cleo** (chefe de gabinete) põe uma linha do placar em toda nota do
  dia e abre uma issue **só quando os quatro critérios forem atingidos**;
  se um deixar de valer, a issue fecha sozinha.
- **Nada aqui opera dinheiro real.** A colônia continua no papel e o
  espelho na conta de prática. Atingir o placar é o começo de uma conversa,
  e a decisão é do dono, à mão, na corretora. Para a parte do índice, a
  conta real precisaria de um ETF UCITS equivalente (por exemplo um S&P 500
  domiciliado na Irlanda) no lugar do SPY.

`cryptoarena live --floor stocks --status` mostra o placar em `go_live`.

**Reinícios do relógio.** 14/10/2026, decisão do dono: na primeira noite o
espelho tentou comprar QQQ, que a Trading 212 lista mas recusa a contas do
Reino Unido (HTTP 400, na rodada da 01:30 e na das 05:30). Era um defeito
nosso: fundo americano precisa de versão UCITS. O espelho passou a deixar
fundos listados nos EUA só no papel, e `REVISION` subiu para 2 para o
relógio recomeçar com o espelho corrigido. Custou um pregão (13/10), o
único contado até ali; nenhum resultado favorável foi descartado.

#### O próximo passo, também combinado antes: automático com aprovação

Decisão do dono (13/10/2026): o dinheiro real entra **no modo automático
com aprovação, e só depois que o placar for atingido**. Até a Cleo abrir a
issue dos quatro critérios, não há dinheiro real e nenhum código de conta
real no repositório: o cliente da Trading 212 só conhece a conta Practice.
No dia em que o placar for atingido, o modo é construído assim:

1. **Ensaio primeiro**: algumas semanas do fluxo de aprovação inteiro na
   conta Practice, antes de qualquer libra real.
2. **Uma aprovação por noite**: depois do tick, a Cleo abre uma issue com
   as ordens da noite, já no tamanho do valor real escolhido pelo dono.
   Nada sai sem a aprovação daquela noite; sem aprovação, as ordens da
   noite caducam.
3. **O que a conta do Reino Unido pode comprar**: SPY e QQQ trocados por
   ETFs UCITS (S&P 500 e Nasdaq-100, de preferência cotados em libras e
   dentro do ISA). O custo de câmbio das ações americanas (cerca de 0,15%
   por lado) entra no cálculo.
4. **Tetos e freio**: limite por ordem, por dia e no total investido, um
   valor pequeno no começo, e uma variável que pausa tudo na hora.
5. **Pausa automática**: se as regras mudarem (o relógio zera) ou se a
   issue do placar fechar porque um critério deixou de valer, as ordens
   reais param até o placar ser atingido de novo.
6. **Chaves** só nos secrets do repositório, com o mínimo de permissão que
   a corretora oferecer; nunca no chat nem no código.

Pelo calendário da bolsa, o mais cedo é 15/04/2027 (o 126º pregão contado
a partir de 14/10/2026, depois do reinício do relógio), se os quatro
critérios estiverem atingidos nesse dia e as regras não tiverem mudado; o
ideal (252 pregões) cai em 14/10/2027.

### Pronto para dinheiro de verdade?

Cada tick a colônia pergunta à Kraken o **menor pedido aceito** por
moeda (`readiness` no `status.json`: mínimos por moeda, fração das
últimas compras que a bolsa aceitaria, e o orçamento por agente que
faria todas passarem). Com £5 por agente as ordens de £0,3 a £1,5 ficam
quase todas abaixo do mínimo; é o número que diz quanto capital o andar
precisa antes de a camada `LiveExchange` (dry-run por padrão, limites
por ordem e por dia, aprovação humana acima de um teto) receber chaves.

### O medo e a ganância

O workflow `market-data` publica também o **Crypto Fear & Greed** da
alternative.me (`sentiment/fng.csv`, diário desde 2018, sem chave). Na
nossa fita ele é contrarian: quanto mais ganância, pior o mês seguinte
(correlação de postos −0,33 com o retorno de 30 dias do BTC; acima de 45
os retornos médios de 30 dias foram de −4% a −11%). Todo agente de regra
tem um `greed_gate` que veta compras novas acima desse nível (0 =
desligado); a colônia ao vivo lê o índice a cada tick e o backtest lê o
CSV. Na fita, quanto mais apertado o portão, menos a colônia perde
(sem portão −1,5% por janela; 60 → −1,4%; 45 → −1,1%; 30 → −0,8%), mas
30 ou 45 significam "quase nunca compre" num ano de queda, e numa alta
o índice passa meses acima de 60. Em 13 meses o default foi **60**; os
cinco anos (acima) o desligaram: hoje o portão vem em **0**, a leitura
continua no dashboard.

### As fontes: quem a colônia escuta

Uma **fonte** é uma conta no X cujos posts às vezes cravam uma moeda
("$SOL pronta pra subir", "shortando ETH aqui"). A colônia não acredita
em ninguém pelo número de seguidores: ela **anota cada chamada** (moeda,
direção, hora, preço naquele momento), espera o horizonte da fonte
(7 dias por padrão) e **julga** — a moeda andou para o lado que a fonte
disse? O placar fica no journal (`source_calls`) e a **confiança** da
fonte sai só dele:

```
confiança = prior (0,25)            enquanto menos de 10 chamadas foram julgadas
confiança = 2 × acertos − 1         depois, misturada aos poucos conforme o placar cresce
```

Quem acerta 70% puxa a colônia com confiança 0,4; quem acerta 50% é
ruído (0); quem costuma errar fica **negativo** e a colônia passa a fazer
o contrário. A soma das chamadas abertas por moeda, pesada pela
confiança, chega aos agentes como `MarketView.signals` (−1 … 1). Todo
agente de regra tem `signal_bias` (1 = ouve, 0 = surdo): uma moeda que
uma fonte confiável cravou comprada sobe na fila do `rank_top` (sinal 1
vale 10 pontos de momento), uma que ela cravou vendida **não é comprada**
enquanto a chamada estiver de pé (sinal abaixo de −0,5). Com o prior de
0,25 a inclinação é leve — a fonte precisa provar antes de mandar.

A primeira fonte do andar cripto é
[@leshka_eth](https://x.com/leshka_eth) (`floors.py`, `CRYPTO_SOURCES`).
Os posts chegam de dois jeitos:

- **Pela API do X** — pagamento por uso, cerca de meio centavo de dólar
  por post lido. Um *Bearer token* de app do X no secret `X_BEARER_TOKEN`
  do repositório faz o job de hora em hora ler os posts novos da conta
  (só os novos: a colônia guarda o último id lido).
- **À mão** — sem token, em **Actions → Live colony → Run workflow**
  preencha `post_text`, `post_url` e `post_source`; ou localmente
  `cryptoarena call --source leshka_eth --url https://x.com/… --text "…"`.
  O id do link impede que o mesmo post conte duas vezes.

O parser é de palavras: reconhece as 24 moedas por ticker (`$SOL`,
`SOL` em maiúsculas — `near` em minúsculas não é NEAR) ou nome
(bitcoin, solana) e a direção pelo vocabulário (long/buy/bottom/🚀 contra
short/sell/top/📉). Um post que não nomeia moeda, ou não pende para lado
nenhum, não vira chamada — só se julga o que dá para julgar. O
`status.json` e o dashboard mostram, por fonte, chamadas, julgadas,
taxa de acerto, resultado médio e confiança, e a inclinação atual por
moeda.

**No andar de ações, a fonte são os próprios diretores das empresas**
(`market/sec.py`, `STOCK_SOURCES`). Quando um diretor ou executivo
negocia ações da própria empresa, ele entrega um **Form 4** à SEC em até
dois dias úteis, e o EDGAR publica de graça. Vendas dizem pouco
(salário, impostos, planos 10b5-1 marcados com antecedência). A
**compra no mercado aberto** (código P) é o executivo pondo o próprio
dinheiro no preço do dia. A literatura dá algum poder de previsão a essas
compras (Lakonishok & Lee, 2001; Cohen, Malloy & Pomorski, 2012), menor
nas maiores empresas. Cada compra de um diretor da Apple, Microsoft,
Nvidia ou Amazon vira uma chamada comprada no mesmo placar das fontes do
X: anotada ao preço do dia, julgada **30 dias** depois, com a confiança
tirada só do acerto. ETFs não entregam Form 4. Nessas gigantes, compras
de diretores são raras: a fonte pode passar meses calada, e isso também
é informação.

O EDGAR exige que cada cliente se identifique com nome e um e-mail de
contato real. De um servidor do GitHub ele respondeu 403 ("Undeclared
Automated Tool") a qualquer outra coisa, inclusive aos endereços noreply
do GitHub. Por isso a fonte **fica calada até o repositório ter a
o secret `SEC_USER_AGENT`** (Settings → Secrets and variables →
Actions), por exemplo `Seu Nome seu@email.com`. É um secret e não uma
variável porque o repositório e os logs do Actions são públicos: assim o
e-mail aparece mascarado.

## O andar (mundo isométrico)

A aba **The floor** do dashboard mostra os agentes como pessoinhas num
escritório isométrico: cada um tem mesa (monitor verde/vermelho conforme o
dia), há sofá, máquina de café, quadro de estudos, o painel do mercado na
parede e um cemitério no canto para quem morreu.

Cada agente tem três **necessidades derivadas do que aconteceu de verdade
no mercado** (nada é aleatório):

- **energia** (física): cai com volume de trades e drawdown, volta em dias parados;
- **stress** (emocional): sobe com perdas, stop-losses, metas perdidas e proximidade da linha de morte;
- **foco** (mental): sobe com lições aprendidas, taxa de acerto e sequências de meta; o stress corrói.

Delas saem o humor (calmo, confiante, eufórico, ansioso, em pânico,
exausto) e o comportamento (operar na mesa, descansar no sofá, andar de um
lado para o outro, estudar no quadro, comemorar). Os agentes **conversam
entre si sobre o mercado** em balões de fala — comentam o regime, o último
trade, a meta perdida, quem chegou e quem saiu, e respondem uns aos outros
de acordo com a estratégia (momentum provoca meanrev e vice-versa). As
falas são compostas ao vivo a partir do estado real e **não são gravadas
em lugar nenhum**. Passe o mouse (ou clique) num agente para ver suas
vitals.

**Estagiários.** Os clones (geração ≥ 1) são os estagiários: ficam numa
sala própria, com mesas menores, e conhecem os especialistas do andar.
Quem perde a meta **pede uma dica** a um mentor — o pai, se ainda estiver
lá, senão o especialista da mesma estratégia com a melhor sequência — e a
dica é real: a lição mais importante do mentor entra na memória do
estagiário (evento `consulted` no diário). No andar isso aparece
literalmente: o estagiário levanta, atravessa a sala, para ao lado da mesa
do mentor, pergunta, ouve a dica e volta — **um de cada vez**, para não
virar bagunça. Ninguém "morre": o estagiário que fica abaixo da linha é
**dispensado por não bater a meta**, os outros ficam sabendo pelo aviso ao
lado da porta de saída, e é assim que aparece no dashboard e nas
conversas. **Especialistas nunca são dispensados**: o papel deles é
alimentar a base de lições de onde os estagiários aprendem.

**Sentimentos.** Uma dispensa recente pesa em quem fica: o stress dos
estagiários sobe (dos especialistas, pouco — eles estão seguros) e, ao
mesmo tempo, a **motivação** de todos sobe — humor "determined": "worried?
yes. stopping? no." Além de energia, stress e foco, cada agente tem
**motivação** (dispensas, festas e elogios sobem; sequências de meta
perdida desgastam) e **ego** (quadro na parede, elogios, sequências).

**Happy hour.** A cada 7 dias, quem bateu a meta da semana (≈ meta diária
composta por 7 dias) ganha uma festa: todo mundo vai para o sofá e o café,
os vencedores erguem o copo e recebem elogios dos colegas ("cheers to
breakout-1, +7.7% this week — teach me"), a motivação sobe e o stress cai.
O melhor da semana vira **funcionário da semana**: o quadro na parede do
meio da sala mostra o nome, ele ganha um 🏆 sobre a cabeça, o ego sobe
(humor "proud") — e a lição "lean into this setup" entra na memória dele.

**Como os estagiários aprendem.** Um estagiário nasce como **cópia fiel**
do pai — mesmos parâmetros, o livro inteiro de lições e o histórico de
indicadores já aquecido, para poder decidir desde o primeiro dia (a cada
`explore_every`=3 contratações, uma nasce **mutada**, para a colônia
continuar explorando). O limite de caixa para comprar é **proporcional ao
orçamento** do agente, então um estagiário pequeno também opera. E o
aprendizado é numérico, não só uma frase: toda semana cada estagiário move
seus parâmetros metade do caminho (`imitation_rate`) na direção do
especialista da mesma estratégia com a **melhor semana** (evento
`trained`), e cada dica de mentor também puxa 10% (`tip_rate`).

**Especialista sênior.** Toda semana, o especialista que mais fez o
orçamento crescer desde o dia 0 vira o sênior (evento `senior`, 🌟 no
andar) — conquistado, nunca nomeado. O que ele tem de transferível para
qualquer estratégia é a **disciplina**: no treino semanal os estagiários
também movem `order_frac` na direção da **fração efetiva de patrimônio
que o sênior gastou por compra** naquela semana (medida nos trades, não
nos parâmetros) e o `cooldown` na direção do dele. Estagiário com
`escalate_after`=3 metas perdidas seguidas leva a dúvida ao sênior em vez
de ao próprio mentor.

**Imunidade.** O prêmio que importa: quem venceu a semana **não pode ser
dispensado na semana seguinte**, mesmo sem bater a meta. Um estagiário
imune que cai abaixo da linha é "poupado" (evento `spared`) em vez de
dispensado — no andar ele carrega um 🛡️, dorme melhor (menos stress perto
da linha, um pouco de acomodação) e, se a imunidade de fato o salvou, leva
o susto e sai mais motivado: *"the shield held; never again this close"*.

## Debate bull vs. bear

```bash
cryptoarena run --episodes 5 --llm --debate
```

Antes de cada decisão, o agente Claude convoca sua "mesa de research"
(padrão portado do [TradingAgents](https://github.com/TauricResearch/TradingAgents),
Apache-2.0): um analista **bull** monta o melhor caso para comprar, um **bear**
o rebate ponto a ponto, e um juiz converte o debate num rating estruturado
(buy / overweight / hold / underweight / sell) com plano e convicção — que o
trader precisa pesar na decisão final. O debate força o modelo a considerar os
dois lados em vez de ancorar na primeira leitura (custo: 3 chamadas extras por
decisão; por isso é opt-in).

## O prédio: um andar por classe de ativo

A colônia não sabe o que negocia. O que muda de um andar para outro é a
fita, o relógio e os especialistas; as regras (orçamento, meta,
estagiários, dispensa, happy hour, sênior, imitação) são as mesmas.

| Andar | Fita | Um "dia" da colônia | Semana | Fonte | Estado publicado |
|---|---|---|---|---|---|
| `crypto` (**pausado** desde 25/09/2026) | velas horárias, 24 moedas principais (BTC, ETH, SOL, XRP, ADA, DOGE, …) | 24 velas, 7 dias por semana | 7 dias | Kraken (pública) | branch `colony-live` |
| `stocks` (**rodando**, fundado em 25/09/2026) | barras diárias, SPY/QQQ/AAPL/MSFT/NVDA/AMZN | 1 barra, um pregão | 5 pregões | API da Nasdaq no GitHub; Stooq de uma conexão doméstica | branch `colony-live-stocks` |

```bash
cryptoarena live --floor stocks --once --db live/stocks.db   # um pregão à mão (o workflow faz isso toda noite)
cryptoarena backtest --floor stocks                          # janelas de 60 pregões sobre 6 anos
cryptoarena dashboard --live --floor stocks                  # o andar de ações; um seletor troca de andar
```

No andar de ações os especialistas são os mesmos oito, com os parâmetros
em escala diária (momentum de 20 e 60 pregões, rompimento da máxima de
20 pregões, médias de 10 e 50), mais um nono, **`index-1`**, que segura
metade SPY e metade QQQ e nunca vende — o investidor passivo dentro
da colônia, para os outros terem com quem se comparar. Meta de 8% ao
ano, julgada pelo ritmo (era 0,2% por pregão até 13/10/2026), taxa de
0,05% por lado (corretagem zero mais spread). O workflow
`live-colony-stocks.yml` roda toda noite: a API da Nasdaq só publica a
barra do dia algumas horas depois do fechamento de Nova York (às 23:50
UTC ainda não está lá; à 01:30 está), por isso o horário é terça a
sábado à 01:30 UTC, com uma passada às 05:30 de retry. O andar de cripto
está **pausado** (o cron fica comentado em `live-colony.yml`; "Run
workflow" ainda dá um tick à mão).

O que seis anos de barras reais (2020–2026, mercado em alta) disseram:
os portões do andar cripto (portão de mercado, ranking, exposição máxima
de 60%, tendência de 28 dias) só custavam participação aqui. Com eles a
colônia fazia +0,04% por janela de 60 pregões; sem eles (tendência de 3
meses, exposição total, ordens maiores) e com o `index-1`, **+0,5%** por
janela — contra **+5,0%** de comprar e segurar as seis. Regras lentas e
só compradas não acompanham mega-caps num mercado em alta; o andar
existe para ver se a colônia aprende algo que a fita de 6 anos não
ensinou, não porque já venceu.

Sobre os dados: sondados de um runner do GitHub, o Stooq responde com
uma parede de JavaScript, o Yahoo com 429, o FRED e a Cboe estouram o
tempo ou dão 403; a API pública da Nasdaq responde com abertura,
máxima, mínima, fechamento e volume de qualquer ação ou ETF, e é ela que
os workflows usam (`CRYPTOARENA_DAILY_SOURCE=nasdaq`). De um PC comum o
Stooq também responde. `--symbols TSLA=tsla.us,META=meta.us` troca a
lista.

Sobre as moedas: a colônia cripto negocia 24 moedas principais cotadas em
dólar tanto na Kraken (feed real) quanto na Coinbase (fita do backtest),
para que backtest e colônia vejam os mesmos nomes. A lista inteira do
CoinMarketCap são milhares de moedas, quase todas sem par líquido em
dólar em lugar nenhum; `--symbols` troca a lista. A parede do andar mostra
as oito que mais se moveram nas últimas 24 velas.

## A colônia no mundo real (uma semana de dados reais)

`cryptoarena live` é a mesma colônia — meta diária, estagiários, dispensa,
happy hour, sênior, imitação — só que o "dia" dura um dia de verdade e as
velas vêm de uma exchange real. As carteiras continuam de papel (preço
real, execução simulada, nenhuma conta nem chave), então dá para deixar
rodando uma semana sem risco enquanto se observa quem aprende e quem se
reproduz.

Como o processo não fica vivo por uma semana, o estado inteiro é salvo
no próprio journal (`colony_state`): carteiras, posições, histórico de
velas de cada agente, parâmetros, sequências, imunidade, relógio. Cada
execução reabre o journal, processa **só as velas que fecharam** desde a
última visita (o candle em formação nunca é visto) e salva de novo.
Quando o candle das 23:00 UTC fecha, rodam os rituais de fim de dia; a
cada 7 dias, os de fim de semana.

```bash
pip install -e ".[live]"

# uma execução: pega o que fechou desde a última vez, salva, sai (cron)
cryptoarena live --once --db live/colony.db --exchange kraken

# ou fica de pé e bate o ponto a cada hora, por 7 dias
cryptoarena live --days 7 --db live/colony.db

cryptoarena live --status --db live/colony.db     # estado em JSON
cryptoarena dashboard --db live/colony.db         # o andar, ao vivo
```

Os defaults são os do experimento das £5: `--budget 5 --clone-at 1.1
--min-child 0.2 --target 0.005 --death 0.6 --cost 0.0002 --fee 0.0026`
(taxa taker da Kraken, para o papel valer o que vale). A configuração
usada na fundação fica gravada no journal e vale para as execuções
seguintes; para aplicar defaults novos a uma colônia que já existe,
`Run workflow` com `reset` funda outra.
A exchange padrão é a Kraken (BTC/USD, ETH/USD, SOL/USD), que serve velas
públicas do mundo todo sem conta — a Binance recusa endereços dos EUA,
onde rodam os runners do GitHub. `--exchange binance` ou `--symbols
BTCUSDT=BTC/USDT,...` trocam isso.

### Rodando sozinha no GitHub Actions

**Pausada em 25/09/2026.** Os cinco anos de backtest deixam o retorno da colônia
perto de zero contra segurar BTC, e a atenção passou para o andar de ações (abaixo).
O journal continua na branch `colony-live` (a última fundação simulava £1.000,
£125 por fundador); "Run workflow" ainda tica à mão e devolver o `schedule`
religa o relógio.

`.github/workflows/live-colony.yml` faz o ciclo de hora em hora sem
servidor nenhum: restaura o journal da branch `colony-live`, roda
`live --once`, e publica o journal atualizado de volta (um único commit,
substituído a cada hora). O GitHub só agenda workflows que estão na
branch padrão — depois do merge na `main` ela começa a bater o ponto; em
**Actions → Live colony → Run workflow** dá para disparar na hora (`reset`
funda uma colônia nova; `post_text`/`post_url`/`post_source` arquivam
um post de uma fonte à mão). O secret opcional `X_BEARER_TOKEN` deixa o
job ler as fontes sozinho pela API do X.

O dashboard lê esse journal direto do GitHub: no Streamlit Cloud, em
*Secrets*, coloque

```toml
CRYPTOARENA_DB_URL = "https://raw.githubusercontent.com/<usuario>/portifolio/colony-live/colony.db"
```

e o app público passa a mostrar a colônia real (atualiza a cada 2 min;
um seletor na barra lateral volta para o journal local). Localmente,
`cryptoarena dashboard --live` faz o mesmo sem configurar nada, e
`--db-url` aceita qualquer outra URL.

## Trilha sim → paper → live

A camada live (`market/live.py`) usa a mesma interface dos agentes — eles não
sabem se estão no simulador ou numa exchange real. Cinco travas independentes:

| Trava | Default | Efeito |
|---|---|---|
| `dry_run` | **ligado** | ordens são logadas e simuladas, nunca enviadas |
| `testnet` | **ligado** | chamadas reais vão para o sandbox da exchange |
| `max_order_quote` | 50 | qualquer ordem acima é **cortada** para o teto |
| `max_daily_quote` | 200 | compras param quando o gasto do dia (UTC) atinge o teto |
| `approve_above_quote` | 25 | ordem acima disso exige callback de aprovação humana; sem callback, é **recusada** |

```python
from cryptoarena.market import LiveExchange, LiveFeed, LiveLimits

feed = LiveFeed("kraken", {"BTCUSD": "BTC/USD"})      # só velas fechadas
exchange = LiveExchange(
    "kraken", api_key=..., api_secret=...,
    limits=LiveLimits(max_order_quote=25, max_daily_quote=100),
    dry_run=True,          # desligue por último, depois de dias de dry-run limpo
    testnet=True,          # desligue só depois do testnet
    confirm=lambda order, valor: input(f"aprovar {valor:.2f}? [y/N] ") == "y",
)
```

Progressão recomendada: simulador → `dry_run` com feed real → testnet →
real com `LiveLimits` mínimos. E no lado da exchange: **API key só-trade
(sem saque)**, restrição por IP e subconta com o valor que você aceita perder.

## Roadmap (ideias colhidas do estado da arte¹)

- **Contrafactuais**: "quanto teria rendido só segurar?" anexado a cada lição.

¹ Levantamento de agosto/2026: freqtrade (FreqAI-RL), Hummingbot, Jesse,
TradingAgents (Tauric), ai-hedge-fund (virattt), eliza, FinMem, FinCon,
llm_trading_sim (Lopez-Lira), StockBench/InvestorBench, Alpha Arena (nof1.ai).

## Aviso

Isto é um **simulador educacional**. Nada aqui é conselho financeiro; nenhum
código deste repositório conecta a uma carteira ou exchange real. Se um dia
plugar dinheiro de verdade: limites de gasto fora do agente, chaves só-trade
sem saque, e aprovação humana para ordens grandes.
