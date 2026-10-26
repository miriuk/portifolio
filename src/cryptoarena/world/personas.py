"""Who is who on the floor: a name, a job title and a superpower for each
agent, so the feed, the office and the chief's note read like a team.

The agent ids (momentum-1, index-1, …) stay what they are: the journal,
the saved colony and the backtests key everything on them. A persona is
only how an id is shown. A founder has its own; an intern takes its
founder's name with "Jr." and its number (momentum-3, hired by Rita, is
"Rita Jr. 3"). The superpower says, in one line, what the strategy
really does: the title is fun, the power is the rule.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    name: str
    emoji: str
    title: str          # the job title
    power: str          # the superpower: the strategy's actual rule, in one line
    founder: bool = True

    @property
    def first(self) -> str:
        return self.name.split()[0]

    @property
    def tag(self) -> str:
        """Emoji and first name: short enough for a feed column."""
        return f"{self.emoji} {self.first}"

    def to_dict(self) -> dict:
        return {"name": self.name, "emoji": self.emoji, "title": self.title,
                "power": self.power, "founder": self.founder}


FOUNDERS: dict[str, Persona] = {
    "momentum-1": Persona("Rita Rush", "🏃", "Trader de momentum (tiro curto)",
                          "Embarca na arrancada curta de um papel antes da multidão."),
    "momentum-2": Persona("Marco Maratona", "🏔️", "Trader de momentum (fôlego longo)",
                          "Segue a tendência longa e ignora o barulho do dia a dia."),
    "meanrev-1": Persona("Bea Bounce", "🪃", "Caçadora de quedas",
                         "Compra quando um papel cai bem abaixo da média recente e vende no repique."),
    "meanrev-2": Persona("Theo Paciência", "🧘", "Contrarian profundo",
                         "Espera um tombo fundo abaixo da média longa e compra o que todos vendem."),
    "breakout-1": Persona("Nina Faísca", "⚡", "Caçadora de rompimentos",
                          "Compra a máxima nova e protege o ganho com um stop móvel de 8%."),
    "regime-1": Persona("Otto Clima", "🌦️", "Estrategista de regime",
                        "Lê se o mercado está em tendência ou de lado e troca de manual."),
    "voltarget-1": Persona("Vera Calma", "🎚️", "Gestora de volatilidade",
                           "Dosa cada aposta pelo quanto o papel balança e sai quando fica bravo demais."),
    "trend-1": Persona("Tomás Bússola", "🧭", "Seguidor de tendência",
                       "Fica comprado enquanto a média curta está acima da longa e nunca briga com o mercado."),
    "index-1": Persona("Inês Índice", "🗿", "Investidora passiva",
                       "Compra SPY e QQQ uma vez e nunca vende: o índice com uma mesa."),
}

# strategies that can be hired but are not founders today
BY_STRATEGY: dict[str, Persona] = {
    "bear": Persona("Bruno Urso", "🐻", "Vendedor a descoberto",
                    "Ganha quando os preços caem."),
    "rotation": Persona("Rosa Rotação", "🔄", "Rotadora de setores",
                        "Move o dinheiro para o que está mais forte agora."),
    "pullback": Persona("Paulo Recuo", "🎯", "Comprador de recuos",
                        "Compra quedas, mas só dentro de uma tendência de alta."),
    "wyckoff": Persona("Walter Volume", "📊", "Leitor de Wyckoff",
                       "Lê o rastro do grande operador: compra o spring e o sinal de força, "
                       "sai no upthrust e no sinal de fraqueza."),
    "macd": Persona("Maria MACD", "〽️", "Cruzadora de médias (formada no curso 2)",
                    "Compra quando a média curta cruza a longa para cima e vende no cruzamento para baixo."),
    "bollinger": Persona("Bento Bollinger", "📏", "Caçador de extremos (formado no curso 2)",
                         "Compra abaixo da banda inferior de Bollinger e vende acima da superior."),
    "chaikin": Persona("Chica Chaikin", "💧", "Leitora do fluxo de dinheiro (formada no curso 2)",
                       "Compra quando o fluxo de dinheiro de Chaikin entra e vende quando ele sai."),
    "claude-trader": Persona("Clara IA", "🤖", "Analista de IA",
                             "Lê o mercado e escreve o próprio plano de trade com um modelo de linguagem."),
}

# the desk above the agents (arena/desk.py, arena/chief.py)
DESK: dict[str, Persona] = {
    "risk": Persona("Rick Guarda", "🚧", "Oficial de risco",
                    "Diz não quando a colônia inteira corre para o mesmo papel."),
    "pm": Persona("Pam Livro", "📒", "Gestora de portfólio",
                  "Junta os votos de todos num livro só e economiza as taxas."),
    "chief": Persona("Cleo Pauta", "🗂️", "Chefe de gabinete",
                     "Escreve a nota do dia e só chama o dono quando há uma decisão."),
}


def strategy_of(agent_id: str) -> str:
    head, _, tail = agent_id.rpartition("-")
    return head if tail.isdigit() and head else agent_id


def persona(agent_id: str, parent_id: str | None = None) -> Persona:
    """The persona an id is shown as. An intern is its founder's "Jr."
    (the parent when known, else the strategy's first founder)."""
    if agent_id in FOUNDERS:
        return FOUNDERS[agent_id]
    if agent_id in DESK:
        return DESK[agent_id]
    if agent_id in BY_STRATEGY:
        return BY_STRATEGY[agent_id]
    strategy = strategy_of(agent_id)
    base = None
    if parent_id:
        base = persona(parent_id)
    if base is None or not base.founder:
        base = FOUNDERS.get(f"{strategy}-1") or BY_STRATEGY.get(strategy)
    if base is None:
        return Persona(agent_id, "👤", "Especialista", "—")
    if strategy in BY_STRATEGY and f"{strategy}-1" == agent_id:
        return base
    number = agent_id.rpartition("-")[2]
    return Persona(f"{base.first} Jr. {number}", base.emoji, f"Estagiário · {base.title}",
                   base.power, founder=False)


def display(agent_id: str, parent_id: str | None = None) -> str:
    """'🏃 Rita Rush' — what a table or a note shows for an id."""
    p = persona(agent_id, parent_id)
    return f"{p.emoji} {p.name}"


def roster(agent_ids) -> list[dict]:
    """Ids with their personas, for the status JSON and the dashboard."""
    return [{"id": a, **persona(a).to_dict()} for a in agent_ids]
