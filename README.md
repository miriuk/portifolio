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

## Roadmap (ideias colhidas do estado da arte¹)

- **Debate bull vs. bear** antes de cada decisão do agente LLM — TradingAgents.
- **Contrafactuais**: "quanto teria rendido só segurar?" anexado a cada lição.
- **Sim → paper → live**: mesma interface de agente rodando contra o simulador,
  depois CCXT dry-run, e só então (opcional, com limites de gasto rígidos)
  uma carteira real.

¹ Levantamento de agosto/2026: freqtrade (FreqAI-RL), Hummingbot, Jesse,
TradingAgents (Tauric), ai-hedge-fund (virattt), eliza, FinMem, FinCon,
llm_trading_sim (Lopez-Lira), StockBench/InvestorBench, Alpha Arena (nof1.ai).

## Aviso

Isto é um **simulador educacional**. Nada aqui é conselho financeiro; nenhum
código deste repositório conecta a uma carteira ou exchange real. Se um dia
plugar dinheiro de verdade: limites de gasto fora do agente, chaves só-trade
sem saque, e aprovação humana para ordens grandes.
