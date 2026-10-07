"""capacity.counted() (08/10, F18): capacidade de máquinas e postos sem contar a dobrar. Sem base de dados."""
from app.sector import capacity

RESOURCES = {
    "fita": {"id": "fita", "code": "POSTO_FITA", "name": "Serrote Fita pav.1", "type": "posto"},
    "doall": {"id": "doall", "code": "DOALL", "name": "Serrote Doall Pav.1", "type": "maquina"},
    "thomas": {"id": "thomas", "code": "THOMAS", "name": "Serrote Thomas", "type": "maquina"},
    "meba": {"id": "meba", "code": "MEBA", "name": "Serrote MEBA", "type": "maquina"},
    "ops": {"id": "ops", "code": "OPERADORES_PAV1", "name": "Operadores pav.1", "type": "grupo_operadores"},
}
RELATIONS = [{"pai": "POSTO_FITA", "filho": "DOALL", "relacao": "compoe"},
             {"pai": "POSTO_FITA", "filho": "THOMAS", "relacao": "compoe"}]


def test_a_post_with_its_own_capacity_replaces_its_machines():
    """O Fita pav.1 (60 h) contém o Doall (30 h) e a Thomas: o total do setor soma o posto, não o Doall."""
    caps = {"fita": 60.0, "doall": 30.0, "thomas": None, "meba": 30.0, "ops": 80.0}
    chosen = capacity.counted(RESOURCES, caps, RELATIONS)
    assert chosen == {"fita", "meba"}
    assert sum(caps[r] for r in chosen) == 90.0  # e não 120 h


def test_without_its_own_capacity_the_machines_count_and_the_post_does_not():
    assert capacity.counted(RESOURCES, {"fita": None, "doall": 30.0, "thomas": 20.0, "meba": 30.0}, RELATIONS) == {"doall", "thomas", "meba"}
    # Um posto fechado (0 h) tem capacidade própria: continua a substituir as máquinas.
    assert capacity.counted(RESOURCES, {"fita": 0.0, "doall": 30.0}, RELATIONS) == {"fita", "meba"}


def test_cells_and_a_precomputed_shape_give_the_same_answer_and_operators_never_count():
    cells = {"fita": {"hours": 60.0}, "doall": {"hours": 30.0}, "thomas": {"hours": None}, "meba": {"hours": None}, "ops": {"hours": 80.0}}
    shape = capacity.physical(RESOURCES, RELATIONS)
    assert capacity.counted(RESOURCES, cells, shape=shape) == capacity.counted(RESOURCES, cells, RELATIONS) == {"fita", "meba"}
    assert "ops" not in capacity.counted(RESOURCES, cells, RELATIONS)


def test_counted_does_not_depend_on_the_family_views_switch(monkeypatch):
    monkeypatch.delenv("MES_PLANNING_FAMILY_VIEWS_ENABLED", raising=False)
    assert capacity.counted(RESOURCES, {"fita": 60.0}, RELATIONS) == {"fita", "meba"}
