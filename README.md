# Live colony

Updated 2026-10-17 05:39 UTC by the nightly job.
Paper trading on Nasdaq's daily bars, mirrored to a Trading 212 practice account.
Read `colony.db` with the dashboard:

```
CRYPTOARENA_DB_URL=https://raw.githubusercontent.com/miriuk/portifolio/colony-live-stocks/colony.db
```

```json
{
  "day": 18,
  "hour": 0,
  "started_at": "2026-09-24T00:00:00+00:00",
  "last_candle": "2026-10-16T00:00:00+00:00",
  "alive": 9,
  "population": 9,
  "interns": 0,
  "colony_equity": 1301.849,
  "invested": 886.6255,
  "senior": "momentum-2",
  "prices": {
    "SPY": 763.25,
    "QQQ": 709.8,
    "AAPL": 343.46,
    "MSFT": 529.05,
    "NVDA": 214.13,
    "AMZN": 250.0
  },
  "sentiment": null,
  "signals": {},
  "sources": [
    {
      "handle": "sec-form4",
      "label": "SEC Form 4 \u00b7 insider purchases",
      "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4",
      "trust": 0.25,
      "prior": 0.25,
      "horizon_days": 30,
      "calls": 0,
      "resolved": 0,
      "hits": 0,
      "hit_rate": null,
      "avg_outcome": null,
      "active": []
    }
  ],
  "readiness": {},
  "desk": {
    "symbol_cap": 0.35,
    "gross_cap": 0.0,
    "vetoes": 0,
    "clipped": 0,
    "exposure": {
      "MSFT": 0.2113,
      "NVDA": 0.1145,
      "AAPL": 0.1093,
      "QQQ": 0.098,
      "SPY": 0.0827,
      "AMZN": 0.0653
    },
    "holders": {
      "AAPL": 4,
      "MSFT": 6,
      "NVDA": 4,
      "AMZN": 3,
      "QQQ": 3,
      "SPY": 2
    },
    "pm": {
      "since_day": 6,
      "capital": 1322.01,
      "equity": 1302.4264,
      "return": -0.014814,
      "colony_return": -0.01451,
      "consensus": 0.0,
      "band": 0.02,
      "fees": 0.514,
      "weights": {
        "AAPL": 0.1093,
        "MSFT": 0.2113,
        "NVDA": 0.1144,
        "QQQ": 0.098,
        "SPY": 0.0826,
        "AMZN": 0.0543
      },
      "targets": {
        "AAPL": 0.1093,
        "MSFT": 0.2113,
        "NVDA": 0.1145,
        "AMZN": 0.0653,
        "QQQ": 0.098,
        "SPY": 0.0827
      },
      "fills": [
        {
          "ts": 1791331200,
          "symbol": "QQQ",
          "side": "buy",
          "quantity": 0.08112175784809633,
          "price": 758.2593309768592,
          "fee": 0.030771050442003154
        },
        {
          "ts": 1791504000,
          "symbol": "AMZN",
          "side": "buy",
          "quantity": 0.1406317546162906,
          "price": 262.6896784096455,
          "fee": 0.018480495444891228
        },
        {
          "ts": 1791763200,
          "symbol": "MSFT",
          "side": "buy",
          "quantity": 0.06785727951047527,
          "price": 541.7243349606044,
          "fee": 0.01838916438971889
        },
        {
          "ts": 1791763200,
          "symbol": "SPY",
          "side": "buy",
          "quantity": 0.04657270951284629,
          "price": 779.0284496115191,
          "fee": 0.018149807746873584
        },
        {
          "ts": 1791849600,
          "symbol": "QQQ",
          "side": "buy",
          "quantity": 0.0491993774443182,
          "price": 744.0323382284981,
          "fee": 0.01831211997963107
        },
        {
          "ts": 1791849600,
          "symbol": "SPY",
          "side": "buy",
          "quantity": 0.046693297049655434,
          "price": 778.5850243867711,
          "fee": 0.01818644413311892
        },
        {
          "ts": 1792022400,
          "symbol": "NVDA",
          "side": "sell",
          "quantity": 0.3204372909092456,
          "price": 217.00481044515075,
          "fee": 0.034768216786659235
        },
        {
          "ts": 1792022400,
          "symbol": "AAPL",
          "side": "buy",
          "quantity": 0.08725325518160837,
          "price": 342.40824803765304,
          "fee": 0.014945589916116456
        },
        {
          "ts": 1792022400,
          "symbol": "MSFT",
          "side": "buy",
          "quantity": 0.10412366621547246,
          "price": 539.7461213716821,
          "fee": 0.02811422960620356
        },
        {
          "ts": 1792108800,
          "symbol": "NVDA",
          "side": "buy",
          "quantity": 0.34124450604823303,
          "price": 214.38810490598112,
          "fee": 0.03659768032078954
        }
      ]
    }
  },
  "go_live": {
    "since": 1791936000,
    "days": 3,
    "criteria": [
      {
        "key": "time",
        "label": "tempo sob as mesmas regras",
        "met": false,
        "value": "3 de 126 preg\u00f5es (ideal 252)"
      },
      {
        "key": "return",
        "label": "\u00e0 frente de segurar SPY",
        "met": false,
        "value": "col\u00f4nia -2.02% contra SPY -1.90%"
      },
      {
        "key": "fall",
        "label": "queda m\u00e1xima n\u00e3o pior que a de SPY",
        "met": false,
        "value": "col\u00f4nia 2.0% contra SPY 1.9%"
      },
      {
        "key": "mirror",
        "label": "conta Practice acompanhando, sem incidente",
        "met": null,
        "value": "3 noites do espelho (3 medidas), 0 com ordem falhada ou sem resposta, 1.0% do que a noite anterior mirou faltando em m\u00e9dia, 27% da carteira s\u00f3 no papel (fora da lista da corretora) (julga a partir de 20 noites medidas)"
      }
    ],
    "met": 0,
    "of": 4,
    "ready": false,
    "colony_return": -0.020196944238556336,
    "benchmark_return": -0.018971478515700246,
    "fingerprint": "4f7f979807693a81",
    "rules_day": 15
  },
  "agents": [
    {
      "id": "momentum-1",
      "name": "Rita Rush",
      "title": "Trader de momentum (tiro curto)",
      "gen": 0,
      "budget": 146.89,
      "equity": 143.1232,
      "streak": 0,
      "misses": 9,
      "immune_until": 15
    },
    {
      "id": "momentum-2",
      "name": "Marco Maratona",
      "title": "Trader de momentum (f\u00f4lego longo)",
      "gen": 0,
      "budget": 146.89,
      "equity": 148.874,
      "streak": 6,
      "misses": 0,
      "immune_until": 20
    },
    {
      "id": "meanrev-1",
      "name": "Bea Bounce",
      "title": "Ca\u00e7adora de quedas",
      "gen": 0,
      "budget": 146.89,
      "equity": 146.4007,
      "streak": 0,
      "misses": 17,
      "immune_until": 0
    },
    {
      "id": "meanrev-2",
      "name": "Theo Paci\u00eancia",
      "title": "Contrarian profundo",
      "gen": 0,
      "budget": 146.89,
      "equity": 146.5081,
      "streak": 0,
      "misses": 17,
      "immune_until": 0
    },
    {
      "id": "breakout-1",
      "name": "Nina Fa\u00edsca",
      "title": "Ca\u00e7adora de rompimentos",
      "gen": 0,
      "budget": 146.89,
      "equity": 142.7864,
      "streak": 0,
      "misses": 5,
      "immune_until": 15
    },
    {
      "id": "regime-1",
      "name": "Otto Clima",
      "title": "Estrategista de regime",
      "gen": 0,
      "budget": 146.89,
      "equity": 143.1178,
      "streak": 0,
      "misses": 3,
      "immune_until": 15
    },
    {
      "id": "voltarget-1",
      "name": "Vera Calma",
      "title": "Gestora de volatilidade",
      "gen": 0,
      "budget": 146.89,
      "equity": 144.7982,
      "streak": 0,
      "misses": 3,
      "immune_until": 0
    },
    {
      "id": "trend-1",
      "name": "Tom\u00e1s B\u00fassola",
      "title": "Seguidor de tend\u00eancia",
      "gen": 0,
      "budget": 146.89,
      "equity": 144.0327,
      "streak": 0,
      "misses": 3,
      "immune_until": 15
    },
    {
      "id": "index-1",
      "name": "In\u00eas \u00cdndice",
      "title": "Investidora passiva",
      "gen": 0,
      "budget": 146.89,
      "equity": 142.208,
      "streak": 0,
      "misses": 5,
      "immune_until": 0
    }
  ],
  "chief": {
    "day": 17,
    "headline": "Col\u00f4nia $1,301.85 (-1.53% desde a funda\u00e7\u00e3o, 17 dias); segurar SPY no mesmo per\u00edodo: -0.51%.",
    "lines": [
      "Col\u00f4nia $1,301.85 (-1.53% desde a funda\u00e7\u00e3o, 17 dias); segurar SPY no mesmo per\u00edodo: -0.51%.",
      "Hoje a mesa comprou NVDA (1\u00d7 $73.22).",
      "O livro do PM (desde o dia 6): -1.48%, a col\u00f4nia no mesmo per\u00edodo -1.45%.",
      "Prontid\u00e3o para dinheiro real: 0 de 4 crit\u00e9rios. \u274c tempo sob as mesmas regras: 3 de 126 preg\u00f5es (ideal 252); \u274c \u00e0 frente de segurar SPY: col\u00f4nia -2.02% contra SPY -1.90%; \u274c queda m\u00e1xima n\u00e3o pior que a de SPY: col\u00f4nia 2.0% contra SPY 1.9%; \u23f3 conta Practice acompanhando, sem incidente: 3 noites do espelho (3 medidas), 0 com ordem falhada ou sem resposta, 1.0% do que a noite anterior mirou faltando em m\u00e9dia, 27% da carteira s\u00f3 no papel (fora da lista da corretora) (julga a partir de 20 noites medidas)."
    ],
    "decisions": [],
    "colony_return": -0.015250262857315677,
    "hold_return": -0.005122657003571507,
    "benchmark": "SPY",
    "bench_start": {
      "symbol": "SPY",
      "ts": 1790208000,
      "price": 767.18
    },
    "readiness": {
      "since": 1791936000,
      "days": 3,
      "criteria": [
        {
          "key": "time",
          "label": "tempo sob as mesmas regras",
          "met": false,
          "value": "3 de 126 preg\u00f5es (ideal 252)"
        },
        {
          "key": "return",
          "label": "\u00e0 frente de segurar SPY",
          "met": false,
          "value": "col\u00f4nia -2.02% contra SPY -1.90%"
        },
        {
          "key": "fall",
          "label": "queda m\u00e1xima n\u00e3o pior que a de SPY",
          "met": false,
          "value": "col\u00f4nia 2.0% contra SPY 1.9%"
        },
        {
          "key": "mirror",
          "label": "conta Practice acompanhando, sem incidente",
          "met": null,
          "value": "3 noites do espelho (3 medidas), 0 com ordem falhada ou sem resposta, 1.0% do que a noite anterior mirou faltando em m\u00e9dia, 27% da carteira s\u00f3 no papel (fora da lista da corretora) (julga a partir de 20 noites medidas)"
        }
      ],
      "met": 0,
      "of": 4,
      "ready": false,
      "colony_return": -0.020196944238556336,
      "benchmark_return": -0.018971478515700246,
      "fingerprint": "4f7f979807693a81",
      "rules_day": 15
    }
  }
}
```
