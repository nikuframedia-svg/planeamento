"""Estado de planeamento de uma linha da Carteira (filtro «Estado», Resumo e cor verde).

Regra do Luís (02/10/2026), uma partição — cada linha tem um só estado:
1. planeado: decisão Planear efetiva e Máquina preenchida (o trabalho que o Gantt recebe);
2. nesting: tem Máquina (já tem a informação de planeamento) mas ainda não foi planeada;
3. sem_maquina: sem Máquina. Uma decisão antiga sem máquina também fica aqui: sem máquina não se planeia.
A Máquina é a coluna Máquina da Tabela/Excel.
"""
from __future__ import annotations

STATUS = {
    "planeado": "Planeado",
    "nesting": "Planeado para nesting",
    "sem_maquina": "Sem máquina atribuída",
}
ORIGINS = {
    "planeado": "Planear e Máquina preenchida",
    "nesting": "Máquina preenchida, ainda sem Planear",
    "sem_maquina": "Coluna Máquina vazia",
}


def classify(effective: dict, machine: str | None) -> dict:
    """{planeado, nesting, sem_maquina}: exatamente um verdadeiro."""
    planned = bool(machine) and effective.get("decision") == "selected"
    return {"planeado": planned, "nesting": bool(machine) and not planned, "sem_maquina": not machine}


def matches(status: dict, wanted: str) -> bool:
    return bool(status.get(wanted))
