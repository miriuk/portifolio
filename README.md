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
  branch `forecast-bench`.
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
| `crypto` | velas horárias, 24 moedas principais (BTC, ETH, SOL, XRP, ADA, DOGE, …) | 24 velas, 7 dias por semana | 7 dias | Kraken (pública) | branch `colony-live` |
| `stocks` (**pausado**) | barras diárias, SPY/QQQ/AAPL/MSFT/NVDA/AMZN | 1 barra, um pregão | 5 pregões | API da Nasdaq no GitHub; Stooq de uma conexão doméstica | branch `colony-live-stocks` |

```bash
cryptoarena live --floor stocks --once --db live/stocks.db   # um pregão (andar pausado; à mão)
cryptoarena backtest --floor stocks                          # janelas de 60 pregões sobre 6 anos
cryptoarena dashboard --live --floor stocks                  # o andar de ações; um seletor troca de andar
```

No andar de ações os especialistas são os mesmos oito, com os parâmetros
em escala diária (momentum de 20 e 60 pregões, rompimento da máxima de
20 pregões, médias de 10 e 50), mais um nono, **`index-1`**, que compra
SPY e QQQ no primeiro pregão e nunca vende — o investidor passivo dentro
da colônia, para os outros terem com quem se comparar. Meta de 0,2% por
pregão, taxa de 0,05% por lado (corretagem zero mais spread). O workflow
`live-colony-stocks.yml` está **pausado** (o cron fica comentado no
workflow; "Run workflow" ainda dá um tick à mão). Quando voltar: a API
da Nasdaq só publica a barra do dia algumas horas depois do fechamento
de Nova York (às 23:50 UTC ainda não está lá; à 01:30 está), por isso o
horário é terça a sábado à 01:30 UTC, com uma passada às 05:30 de retry.

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
