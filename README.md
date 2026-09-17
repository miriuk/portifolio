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
| `momentum-*` | compra força, vende fraqueza | lições → ajuste de parâmetros + evolução |
| `meanrev-*` | compra quedas abaixo da média | idem |
| `breakout-1` | compra rompimentos, trailing stop | idem |
| `claude-trader` | decide via LLM (saída estruturada) | lições injetadas no prompt + auto-reflexão pós-episódio escrita pelo próprio modelo |

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
| `--cost` | 0.1%/dia | aluguel: sai do caixa todo dia, operando ou não |
| `--pressure` | 0 | após cada meta perdida, ordens × (1+pressão): a ruína do jogador que o esquema induz, desligada por padrão |
| `--max-pop` | 12 | teto da população |

Sete estratégias competem: momentum ×2, reversão à média ×2, breakout,
**regime-switch** (surfa tendência só quando o regime é de tendência, fica
de fora no chop e zera em pânico de volatilidade) e **vol-target**
(seguidor de tendência que dimensiona a posição pela volatilidade
realizada — maior em mercado calmo, menor em mercado selvagem, fora
quando a vol explode).

Um filho de £0,60 vive pelas mesmas regras na escala dele: meta diária
sobre o próprio patrimônio, dispensa abaixo de 60% dos seus £0,60 (£0,36),
aluguel proporcional, e só contrata o próprio filho quando tiver £0,20 de
excedente sobre os £0,60 — o pai paga o que tem em caixa, sem vender
posição.

O experimento das £5 (90–180 dias, mercado endógeno): vol-target rende
+13% a +28% em todas as sementes, momentum é alta variância, breakout
fica no zero a zero, reversão à média perde −2% a −4% por semana. A
colônia só cresce com lucro real — que é exatamente o ponto. É por isso
que a trilha é **simulador → dry-run → testnet → real com limites
mínimos**, nessa ordem.

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
--min-child 0.2 --target 0.005 --death 0.6`. A configuração usada na
fundação fica gravada no journal e vale para as execuções seguintes.
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
**Actions → Live colony → Run workflow** dá para disparar na hora (e
`reset` funda uma colônia nova).

O dashboard lê esse journal direto do GitHub: no Streamlit Cloud, em
*Secrets*, coloque

```toml
CRYPTOARENA_DB_URL = "https://raw.githubusercontent.com/<usuario>/portifolio/colony-live/colony.db"
```

e o app público passa a mostrar a colônia real (atualiza a cada 2 min;
um seletor na barra lateral volta para o journal local). Localmente,
`cryptoarena dashboard` aceita `--db-url` com a mesma URL.

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
