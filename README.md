# Live colony

Updated 2026-11-14 05:36 UTC by the nightly job.
Paper trading on Nasdaq's daily bars, mirrored to a Trading 212 practice account.
Read `colony.db` with the dashboard:

```
CRYPTOARENA_DB_URL=https://raw.githubusercontent.com/miriuk/portifolio/colony-live-stocks/colony.db
```

```json
{
  "day": 38,
  "hour": 0,
  "started_at": "2026-09-24T00:00:00+00:00",
  "last_candle": "2026-11-13T00:00:00+00:00",
  "alive": 9,
  "population": 9,
  "interns": 0,
  "colony_equity": 1287.9309,
  "invested": 889.2219,
  "senior": "momentum-2",
  "prices": {
    "SPY": 754.37,
    "QQQ": 679.89,
    "AAPL": 356.27,
    "MSFT": 523.88,
    "NVDA": 162.85,
    "AMZN": 266.66
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
      "AAPL": 0.2409,
      "MSFT": 0.1818,
      "AMZN": 0.1406,
      "SPY": 0.0553,
      "QQQ": 0.052,
      "NVDA": 0.0198
    },
    "holders": {
      "AAPL": 6,
      "AMZN": 4,
      "MSFT": 5,
      "NVDA": 1,
      "SPY": 1,
      "QQQ": 1
    },
    "pm": {
      "since_day": 6,
      "capital": 1322.01,
      "equity": 1287.0763,
      "return": -0.026425,
      "colony_return": -0.025046,
      "consensus": 0.0,
      "band": 0.02,
      "fees": 1.0064,
      "weights": {
        "AAPL": 0.241,
        "MSFT": 0.1817,
        "NVDA": 0.0245,
        "QQQ": 0.0696,
        "SPY": 0.0554,
        "AMZN": 0.1341
      },
      "targets": {
        "AAPL": 0.2409,
        "AMZN": 0.1406,
        "MSFT": 0.1818,
        "NVDA": 0.0198,
        "SPY": 0.0553,
        "QQQ": 0.052
      },
      "fills": [
        {
          "ts": 1792713600,
          "symbol": "AAPL",
          "side": "buy",
          "quantity": 0.20031124239520148,
          "price": 348.05766707796147,
          "fee": 0.03487737054405297
        },
        {
          "ts": 1793145600,
          "symbol": "AAPL",
          "side": "buy",
          "quantity": 0.26690824541333596,
          "price": 344.1012113913217,
          "fee": 0.04594469763734922
        },
        {
          "ts": 1793232000,
          "symbol": "AMZN",
          "side": "sell",
          "quantity": 0.14024486606592784,
          "price": 243.48670967412883,
          "fee": 0.017073880493540826
        },
        {
          "ts": 1793577600,
          "symbol": "MSFT",
          "side": "sell",
          "quantity": 0.13176994386541696,
          "price": 506.8630975321963,
          "fee": 0.03339466095463444
        },
        {
          "ts": 1793664000,
          "symbol": "AAPL",
          "side": "sell",
          "quantity": 0.2005161735984552,
          "price": 331.72770230685023,
          "fee": 0.033258384771588524
        },
        {
          "ts": 1793664000,
          "symbol": "MSFT",
          "side": "sell",
          "quantity": 0.07105622924168678,
          "price": 520.3706262567807,
          "fee": 0.018487787254970963
        },
        {
          "ts": 1793664000,
          "symbol": "SPY",
          "side": "sell",
          "quantity": 0.04650415369401171,
          "price": 753.365246175423,
          "fee": 0.017517306597934417
        },
        {
          "ts": 1793923200,
          "symbol": "MSFT",
          "side": "buy",
          "quantity": 0.1291844866256528,
          "price": 531.0846036524252,
          "fee": 0.03432110649205945
        },
        {
          "ts": 1794182400,
          "symbol": "AMZN",
          "side": "buy",
          "quantity": 0.50467353214223,
          "price": 267.084461732861,
          "fee": 0.06742894381342131
        },
        {
          "ts": 1794355200,
          "symbol": "AAPL",
          "side": "buy",
          "quantity": 0.19105306557487728,
          "price": 356.2394362738078,
          "fee": 0.03404734186031872
        }
      ]
    }
  },
  "go_live": {
    "since": 1791936000,
    "days": 23,
    "criteria": [
      {
        "key": "time",
        "label": "tempo sob as mesmas regras",
        "met": false,
        "value": "23 de 126 preg\u00f5es (ideal 252)"
      },
      {
        "key": "return",
        "label": "\u00e0 frente de segurar SPY",
        "met": false,
        "value": "col\u00f4nia -3.07% contra SPY -3.04%"
      },
      {
        "key": "fall",
        "label": "queda m\u00e1xima n\u00e3o pior que a de SPY",
        "met": true,
        "value": "col\u00f4nia 4.0% contra SPY 5.8%"
      },
      {
        "key": "mirror",
        "label": "conta Practice acompanhando, sem incidente",
        "met": true,
        "value": "23 noites do espelho (23 medidas), 0 com ordem falhada ou sem resposta, 1.1% do que a noite anterior mirou faltando em m\u00e9dia, 16% da carteira s\u00f3 no papel (fora da lista da corretora)"
      }
    ],
    "met": 2,
    "of": 4,
    "ready": false,
    "colony_return": -0.03067211265614478,
    "benchmark_return": -0.030385213557666324,
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
      "equity": 142.4978,
      "streak": 0,
      "misses": 29,
      "immune_until": 40
    },
    {
      "id": "momentum-2",
      "name": "Marco Maratona",
      "title": "Trader de momentum (f\u00f4lego longo)",
      "gen": 0,
      "budget": 146.89,
      "equity": 150.7094,
      "streak": 8,
      "misses": 0,
      "immune_until": 35
    },
    {
      "id": "meanrev-1",
      "name": "Bea Bounce",
      "title": "Ca\u00e7adora de quedas",
      "gen": 0,
      "budget": 146.89,
      "equity": 148.949,
      "streak": 18,
      "misses": 0,
      "immune_until": 25
    },
    {
      "id": "meanrev-2",
      "name": "Theo Paci\u00eancia",
      "title": "Contrarian profundo",
      "gen": 0,
      "budget": 146.89,
      "equity": 146.5081,
      "streak": 0,
      "misses": 37,
      "immune_until": 0
    },
    {
      "id": "breakout-1",
      "name": "Nina Fa\u00edsca",
      "title": "Ca\u00e7adora de rompimentos",
      "gen": 0,
      "budget": 146.89,
      "equity": 137.548,
      "streak": 0,
      "misses": 25,
      "immune_until": 35
    },
    {
      "id": "regime-1",
      "name": "Otto Clima",
      "title": "Estrategista de regime",
      "gen": 0,
      "budget": 146.89,
      "equity": 137.1114,
      "streak": 0,
      "misses": 23,
      "immune_until": 15
    },
    {
      "id": "voltarget-1",
      "name": "Vera Calma",
      "title": "Gestora de volatilidade",
      "gen": 0,
      "budget": 146.89,
      "equity": 143.6104,
      "streak": 0,
      "misses": 23,
      "immune_until": 25
    },
    {
      "id": "trend-1",
      "name": "Tom\u00e1s B\u00fassola",
      "title": "Seguidor de tend\u00eancia",
      "gen": 0,
      "budget": 146.89,
      "equity": 142.5746,
      "streak": 0,
      "misses": 23,
      "immune_until": 35
    },
    {
      "id": "index-1",
      "name": "In\u00eas \u00cdndice",
      "title": "Investidora passiva",
      "gen": 0,
      "budget": 146.89,
      "equity": 138.4222,
      "streak": 0,
      "misses": 25,
      "immune_until": 0
    }
  ],
  "chief": {
    "day": 37,
    "headline": "Col\u00f4nia $1,287.93 (-2.58% desde a funda\u00e7\u00e3o, 37 dias); segurar SPY no mesmo per\u00edodo: -1.67%.",
    "lines": [
      "Col\u00f4nia $1,287.93 (-2.58% desde a funda\u00e7\u00e3o, 37 dias); segurar SPY no mesmo per\u00edodo: -1.67%.",
      "Hoje ningu\u00e9m operou.",
      "O livro do PM (desde o dia 6): -2.64%, a col\u00f4nia no mesmo per\u00edodo -2.50%.",
      "Prontid\u00e3o para dinheiro real: 2 de 4 crit\u00e9rios. \u274c tempo sob as mesmas regras: 23 de 126 preg\u00f5es (ideal 252); \u274c \u00e0 frente de segurar SPY: col\u00f4nia -3.07% contra SPY -3.04%; \u2705 queda m\u00e1xima n\u00e3o pior que a de SPY: col\u00f4nia 4.0% contra SPY 5.8%; \u2705 conta Practice acompanhando, sem incidente: 23 noites do espelho (23 medidas), 0 com ordem falhada ou sem resposta, 1.1% do que a noite anterior mirou faltando em m\u00e9dia, 16% da carteira s\u00f3 no papel (fora da lista da corretora)."
    ],
    "decisions": [],
    "colony_return": -0.025778246760614243,
    "hold_return": -0.01669751557652699,
    "benchmark": "SPY",
    "bench_start": {
      "symbol": "SPY",
      "ts": 1790208000,
      "price": 767.18
    },
    "readiness": {
      "since": 1791936000,
      "days": 23,
      "criteria": [
        {
          "key": "time",
          "label": "tempo sob as mesmas regras",
          "met": false,
          "value": "23 de 126 preg\u00f5es (ideal 252)"
        },
        {
          "key": "return",
          "label": "\u00e0 frente de segurar SPY",
          "met": false,
          "value": "col\u00f4nia -3.07% contra SPY -3.04%"
        },
        {
          "key": "fall",
          "label": "queda m\u00e1xima n\u00e3o pior que a de SPY",
          "met": true,
          "value": "col\u00f4nia 4.0% contra SPY 5.8%"
        },
        {
          "key": "mirror",
          "label": "conta Practice acompanhando, sem incidente",
          "met": true,
          "value": "23 noites do espelho (23 medidas), 0 com ordem falhada ou sem resposta, 1.1% do que a noite anterior mirou faltando em m\u00e9dia, 16% da carteira s\u00f3 no papel (fora da lista da corretora)"
        }
      ],
      "met": 2,
      "of": 4,
      "ready": false,
      "colony_return": -0.03067211265614478,
      "benchmark_return": -0.030385213557666324,
      "fingerprint": "4f7f979807693a81",
      "rules_day": 15
    }
  }
}
```
