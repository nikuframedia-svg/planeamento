"""2.ª operação das cantoneiras fora do plano (decisão do Luís, 08/10/2026, opção A).

Saca bocados, Plasma manual, Fresadora e Prensa só saem das LISTAS (Carga, Definições, Atribuir máquina,
Conjuntos, Gantt); nenhum cálculo de horas muda e a 2.ª Oper. continua na Tabela. Duas regras, uma só fonte:
- máquina da 2.ª operação: setor cantoneiras e processo do catálogo conhecido e fora de {Punção, Broca}
  (hoje Fresadora · Chanfro, Plasma manual e Saca bocados · Corte adicional, Prensa · Forja). Sem processo no
  catálogo não se sabe: fica nas listas, como antes;
- operação da 2.ª operação: setor cantoneiras e ocorrência seguinte (fact["phase"] == "seguinte"). Apanha também
  a Soldadura, a Quinadora e o 221, que caíam em «noutro setor» ou «Sem máquina».
A MTG2 fica igual (o Abocardar continua). Funções puras: sem base de dados, fora do selo do Gantt técnico.
"""
from __future__ import annotations

from collections import Counter

SECTOR = "cantoneiras"
MAIN_PROCESSES = frozenset({"Punção", "Broca"})
NO_MACHINE = "sem máquina"


def machine(sector: str, process: str | None) -> bool:
    """Máquina da 2.ª operação: só nas cantoneiras, com processo do catálogo fora de {Punção, Broca}."""
    return sector == SECTOR and bool(process) and process not in MAIN_PROCESSES


def operation(sector: str, fact: dict) -> bool:
    """Operação da 2.ª operação: uma ocorrência seguinte nas cantoneiras."""
    return sector == SECTOR and fact.get("phase") == "seguinte"


def phase(occurrence) -> str:
    """Fase de uma operação do Gantt técnico pela ocorrência: a 1.ª é a principal (pesquisa e linhas da aplicação)."""
    try:
        return "principal" if int(occurrence or 1) <= 1 else "seguinte"
    except (TypeError, ValueError):
        return "principal"


def summary(facts) -> dict:
    """{operations, hours, unknown, machines: [{name, operations}]} das operações da 2.ª operação dadas.

    As horas conhecidas somam-se e as desconhecidas contam-se à parte (nunca como zero); as máquinas por número de
    operações, a maior primeiro; sem máquina conta como «sem máquina».
    """
    operations, hours, unknown = 0, 0.0, 0
    machines: Counter = Counter()
    for f in facts:
        operations += 1
        value = f.get("load_hours")
        if value is None:
            unknown += 1
        else:
            hours += value
        name = f.get("planning_machine") if f.get("planning_resource_id") else None
        machines[name or NO_MACHINE] += 1
    return {"operations": operations, "hours": round(hours, 1), "unknown": unknown,
            "machines": [{"name": name, "operations": n} for name, n in sorted(machines.items(), key=lambda x: (-x[1], x[0]))]}


def _number(n) -> str:
    return f"{n:,}".replace(",", " ")


def label(summary: dict) -> str:
    """«N operações de 2.ª operação fora do plano (Plasma manual 3 925 · …). Continuam na Tabela.»; vazio sem nenhuma."""
    n = (summary or {}).get("operations") or 0
    if not n:
        return ""
    machines = " · ".join(f"{m['name']} {_number(m['operations'])}" for m in summary.get("machines") or [])
    what = "operação" if n == 1 else "operações"
    return f"{_number(n)} {what} de 2.ª operação fora do plano{f' ({machines})' if machines else ''}. Continuam na Tabela."
