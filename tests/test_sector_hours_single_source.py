"""Horas de uma só fonte (plano de 08/10/2026, Etapa 1: F01, F02, F25, S01 e eficiência por máquina).

- As horas da Tabela (motor de capacidade) só valem na máquina para que foram calculadas; noutra máquina
  (Carteira, sugerida, alternativa) usa-se a velocidade do Excel dessa máquina e operação (F01).
- Uma só política de taxas: Confirmada > Excel; o ×3 da Thomas aplica-se uma vez, em todo o lado (F02).
- Carteira/Carga (estimates.hours_on) e Gantt técnico (integrated._duration) dão as mesmas horas.
- As linhas excluídas na Carteira não pesam nas sugestões (F25).
- A eficiência da máquina é o único fator sobre as horas; gravar o horário não a apaga (S01).
Sem base de dados.
"""
from datetime import date

import pytest

from app.gantt import integrated
from app.raw import capacity, capacity_revision as calc, productivity as p
from app.sector import estimates, occurrences

TODAY = date.today().isoformat()
NOW = f"{TODAY}T08:00:00+00:00"
P8, XP4, FITA = "p8", "xp4", "fita"
BY_ID = {P8: {"id": P8, "code": "PEDDI8", "name": "Peddi 8", "aliases": [{"area": "cantoneiras", "name": "Peddi 8"}]},
         XP4: {"id": XP4, "code": "XPT4", "name": "Ficep XP T4", "aliases": [{"area": "cantoneiras", "name": "Ficep XP T4"}]},
         FITA: {"id": FITA, "code": "POSTO_FITA", "name": "Serrote Fita pav.1",
                "aliases": [{"area": "perfis", "name": "Serrote Fita Thomas IS639 Pav.1"}, {"area": "perfis", "name": "FITA PAV1"}]}}
ALIASES = {("cantoneiras", "Peddi 8"): "PEDDI8", ("cantoneiras", "Ficep XP T4"): "XPT4",
           ("perfis", "Serrote Fita Thomas IS639 Pav.1"): "POSTO_FITA", ("perfis", "Serrote Fita pav.1"): "POSTO_FITA"}
CODES = {r["code"]: r for r in BY_ID.values()}


def resolve(area, name):
    return (CODES.get(ALIASES.get((area, name))) or {}).get("id")


def record(area, machine, operation, value, *, source="Excel provisório", factor=1, method="metres_hour", hours=None, quantity=None):
    estimate = {"operation": operation, "machine": machine, "source": source, "factor": factor, "hours": hours, "quantity": quantity,
                "rate": {"method": method, "value": value, "unit": "m/h" if method == "metres_hour" else "mm²/h"}}
    return {"area": area, "row_key": f"{machine}:{operation}:{value}", "values_json": {},
            "detail": {"calculation": {"operation_estimates": [estimate]}}}


# Velocidades do Excel que o motor publicou (OF264095: a Peddi 8 estava pelo Histórico a 85,49 m/h).
RECORDS = [record("cantoneiras", "Peddi 8", "119", 120), record("cantoneiras", "Ficep XP T4", "119", 120),
           record("cantoneiras", "Peddi 8", "112", 85.49, source="Histórico"),
           record("perfis", "Serrote Fita Thomas IS639 Pav.1", "corte", 55434, factor=3, method="area_hour"),
           record("perfis", "Serrote Fita pav.1", "corte", 18478, method="area_hour")]


def fact(**kw):
    base = {"key": "v2:a", "area": "cantoneiras", "phase": "principal", "operation": "CPIS:119", "remaining": 100, "length_mm": 6000,
            "profile": "L100X100X10", "designation": "", "material_type": "Sem tipo", "section_unit": None, "quantity_required": 100,
            "hours": None, "hours_origin": None, "resource_id": XP4, "documentary_resource_id": P8, "of": "OF264095",
            "reference": "R", "occurrence": 1, "selection": None}
    return {**base, **kw}


def hours_on(f, rid, **kw):
    return estimates.hours_on(f, rid, by_id=BY_ID, names={}, study={"recent_speeds": {}}, rates={},
                              published=estimates.published_rates(RECORDS, resolve), **kw)


def test_published_rates_keep_the_excel_base_rate_per_machine_and_operation():
    published = estimates.published_rates(RECORDS, resolve, excel_area={"Serrote Fita Thomas IS639 Pav.1": {"value": 18846, "cell": "F4"}})
    rates = published["rates"]
    assert rates[f"{P8}|119"]["value"] == 120 and rates[f"{XP4}|119"]["value"] == 120
    assert f"{P8}|112" not in rates  # o Histórico já não é a taxa publicada do Excel
    # A Thomas publica 55434 = 18478 × 3 (QTD > 50) e 18478 nas outras linhas: a base é a mesma, sem o fator.
    assert rates[f"{FITA}|corte"]["value"] == pytest.approx(18478) and rates[f"{FITA}|corte"]["lines"] == 2
    # Duas bases diferentes no mesmo par (ex.: intervalos da tabela) não são «a» taxa publicada.
    mixed = estimates.published_rates(RECORDS + [record("cantoneiras", "Ficep XP T4", "119", 100)], resolve)["rates"]
    assert f"{XP4}|119" not in mixed and mixed[f"{P8}|119"]["value"] == 120
    assert published["area"][FITA] == {"value": 18846.0, "cell": "F4", "machine": "Serrote Fita Thomas IS639 Pav.1"}


def test_table_hours_never_move_to_another_machine():
    """F01: a OF264095 tinha as horas da Peddi 8 (Histórico 85,49 m/h) na XP T4 escolhida na Carteira."""
    values = {"theoretical_hours": 600 / 85.49, "remaining": 100, "machine": "Peddi 8", "rate_source": "Histórico"}
    row = {"fase": "principal", "operacao_codigo": "CPIS:119"}
    hours, origin, reason, machine, documentary = occurrences._hours(row, values, {}, "cantoneiras", 100, effective_id=XP4,
                                                                     effective_machine="Ficep XP T4",
                                                                     resolve=lambda n: resolve("cantoneiras", n))
    assert hours is None and machine == "Peddi 8" and documentary == P8 and "Peddi 8" in reason
    # Na própria máquina valem.
    same = occurrences._hours(row, values, {}, "cantoneiras", 100, effective_id=P8, effective_machine="Peddi 8",
                              resolve=lambda n: resolve("cantoneiras", n))
    assert same[0] == pytest.approx(600 / 85.49) and same[4] == P8
    # Máquina fora do catálogo: compara-se o nome.
    other = occurrences._hours(row, {**values, "machine": "Ficep XP T7"}, {}, "cantoneiras", 100, effective_id=None,
                               effective_machine="Ficep XP T7", resolve=lambda n: resolve("cantoneiras", n))
    assert other[0] is not None
    # Na XP T4 a Carteira estima com a velocidade do Excel da XP T4 (120 m/h): 600 m ÷ 120 = 5 h.
    f = fact()
    assert hours_on(f, XP4)[:2] == (pytest.approx(5.0), "estimada")
    # Horas documentais só na máquina documental; noutra, a estimativa dessa máquina.
    documented = fact(hours=7.0, hours_origin="Excel provisório", resource_id=P8)
    assert hours_on(documented, P8)[:2] == (7.0, "documental")
    assert hours_on(documented, XP4)[:2] == (pytest.approx(5.0), "estimada")


def test_suggested_machine_uses_the_published_rate_of_that_machine():
    f = fact(resource_id=None, documentary_resource_id=None)
    study = {"recent_speeds": {"Ficep XP T4": {"value": 100, "lines": 3}}}  # o estudo diria 100; o motor publicou 120
    hours, why = estimates.estimate(f, BY_ID[XP4], {"Ficep XP T4"}, study, {}, published=estimates.published_rates(RECORDS, resolve))
    assert hours == pytest.approx(5.0) and "Ficep XP T4" in why and "120" in why
    # Sem taxa publicada nessa máquina: a velocidade mais recente do Excel.
    assert estimates.estimate(f, BY_ID[XP4], {"Ficep XP T4"}, study, {}, published={})[0] == pytest.approx(6.0)
    # Uma taxa confirmada da tabela ganha a tudo.
    table = [{"id": "c", "definition": {"resource_id": XP4, "area": "cantoneiras", "operation": "119", "method": "metres_hour",
                                        "value": 150, "valid_from": "2026-01-01", "confirmed": True, "source": "Confirmada"}}]
    assert estimates.estimate(f, BY_ID[XP4], set(), study, {}, table=table, published=estimates.published_rates(RECORDS, resolve))[0] == pytest.approx(4.0)


def test_thomas_factor_is_applied_once_everywhere():
    """F02: ×3 da Thomas (QTD > 50) no motor, nas sugestões/Carteira e no Gantt técnico, uma só vez."""
    assert p.thomas_factor("perfis", "corte", "Serrote Fita Thomas IS639 Pav.1", 51) == 3
    assert p.thomas_factor("perfis", "LOCAL:PRINCIPAL", ["FITA PAV1", "Serrote Fita Thomas IS639 Pav.1"], 51) == 3
    assert p.thomas_factor("perfis", "corte", "Serrote Fita Thomas IS639 Pav.1", 50) == 1
    assert p.thomas_factor("perfis", "corte", "Vanguard", 500) == 1
    assert p.thomas_factor("perfis", "abocardar", "Serrote Fita Thomas IS639 Pav.1", 500) == 1
    assert p.thomas_factor("cantoneiras", "119", "Serrote Fita Thomas IS639 Pav.1", 500) == 1
    volume = 60 * 471.3  # peças × área unitária (OF266133)
    expected = volume / (18478 * 3)
    # Motor de capacidade.
    chosen = p.select_rate({"machine": "Serrote Fita Thomas IS639 Pav.1", "quantity_required": 210}, area="perfis", operation="corte",
                           resource_id=FITA, manual=[], historical_rate={"value": None},
                           excel={"method": "area_hour", "value": 18478}, when=TODAY)
    engine, _ = capacity.estimate({"quantity_to_plan": 60, "section_unit": 471.3}, p.timed(chosen["rate"], chosen["source"], {}, FITA), "corte")
    assert chosen["factor"] == 3 and engine == pytest.approx(expected)
    # Carteira (máquina sugerida ou escolhida): taxa publicada base × 3, uma vez.
    f = fact(area="perfis", operation="LOCAL:PRINCIPAL", remaining=60, length_mm=None, section_unit=471.3, quantity_required=210,
             resource_id=None, documentary_resource_id=None)
    published = estimates.published_rates(RECORDS[:4], resolve)
    carteira, why = estimates.estimate(f, BY_ID[FITA], set(), None, {}, published=published)
    assert carteira == pytest.approx(expected) and "Thomas" in why
    assert estimates.estimate({**f, "quantity_required": 50}, BY_ID[FITA], set(), None, {}, published=published)[0] == pytest.approx(volume / 18478)
    # Sem linha publicada: a taxa E/F da folha, também × 3.
    sheet = {"rates": {}, "area": {FITA: {"value": 18478, "cell": "F4"}}}
    assert estimates.estimate(f, BY_ID[FITA], set(), None, {}, published=sheet)[0] == pytest.approx(expected)
    # Gantt técnico: a estimativa publicada traz 55434 (= × 3); retira-se e aplica-se uma vez.
    row = {"setor": "MTG2", "ordem_codigo": "OF266133", "referencia_original": "P", "item_id": "i", "operacao_id": "o", "linha_origem": "l",
           "ocorrencia": 1, "operacao_codigo": "LOCAL:PRINCIPAL", "fase": "principal", "perfil": "IPE", "qualidade": None,
           "quantidade_base": 210, "saldo_confirmado": None, "saldo_documental": 60, "estado_quantidade": "coerente",
           "comprimento_mm": 1000, "section_unit": 471.3, "recurso_atual": "POSTO_FITA", "maquina_original": "Serrote Fita Thomas IS639 Pav.1",
           "documentary_rate": RECORDS[3]["detail"]["calculation"]["operation_estimates"][0], "documentary_rate_resource": "POSTO_FITA", "raw": {}}
    gantt = integrated._duration(row, {"resource_code": "POSTO_FITA", "proposed_code": "LOCAL:PRINCIPAL", "eligibility": "admissible"},
                                 {"id": FITA, "confirmed": True, "aliases": BY_ID[FITA]["aliases"]}, [], {}, NOW)
    assert gantt["duration_hours"] == pytest.approx(expected, abs=1 / 60)
    # «Horas segundo o Excel» (referência) com a mesma função.
    reference, _, factor = calc.reference_estimate({"machine": "Serrote Fita Thomas IS639 Pav.1", "quantity_required": 210, "section_unit": 471.3},
                                                   "perfis", 60, {"value": 18478})
    assert factor == 3 and reference == pytest.approx(expected)


class _Context:
    """O que o Gantt lê do contexto do motor: velocidade recente do Excel por máquina e as Definições."""
    def __init__(self, recent, timing=None):
        self.recent_excel, self.timing, self.aliases, self.excel_area = recent, {"cantoneiras": timing or {}, "perfis": timing or {}}, {}, {}

    def rate(self, *a, **k):
        raise AssertionError("O Gantt já não pede o histórico.")


@pytest.mark.parametrize("machine", [P8, XP4])
def test_planned_fact_has_the_same_hours_in_carteira_and_gantt(machine):
    """Para um facto Planeado: horas de estimates.hours_on = duração do Gantt técnico (± 1 min), na máquina documental
    (Peddi 8) e noutra escolhida na Carteira (XP T4), com eficiência e tempo fixo do setor."""
    timing = {"piece_minutes": 0.1, "efficiency": {P8: 90, XP4: 80}}
    excel = {"method": "metres_hour", "value": 120, "unit": "m/h", "source": "Velocidade mais recente do Excel"}
    # Horas da Tabela calculadas pelo motor para a Peddi 8 (documentais).
    chosen = p.select_rate({"machine": "Peddi 8"}, area="cantoneiras", operation="119", resource_id=P8, manual=[],
                           historical_rate={"value": 85.49, "method": "metres_hour"}, excel=excel, when=TODAY)
    assert chosen["source"] == "Excel provisório"  # o histórico de 85,49 m/h já não ganha
    documentary, _ = capacity.estimate({"quantity_to_plan": 100, "length_mm": 6000}, p.timed(chosen["rate"], chosen["source"], timing, P8), "119")
    f = fact(hours=documentary if machine == P8 else None, hours_origin="Excel provisório", resource_id=machine, documentary_resource_id=P8)
    carteira, basis, _ = estimates.hours_on(f, machine, by_id=BY_ID, names={}, study={"recent_speeds": {}}, rates={}, timing=timing,
                                            published=estimates.published_rates(RECORDS, resolve))
    assert basis == ("documental" if machine == P8 else "estimada")
    row = {"setor": "MTG3", "ordem_codigo": "OF264095", "referencia_original": "R", "item_id": "i", "operacao_id": "o", "linha_origem": "l",
           "ocorrencia": 1, "operacao_codigo": "CPIS:119", "fase": "principal", "perfil": "L100X100X10", "qualidade": None,
           "quantidade_base": 100, "saldo_confirmado": None, "saldo_documental": 100, "estado_quantidade": "coerente",
           "comprimento_mm": 6000, "recurso_atual": "PEDDI8", "maquina_original": "Peddi 8", "raw": {},
           "documentary_rate": {"operation": "119", "machine": "Peddi 8", "source": "Excel provisório", "factor": 1, "rate": excel},
           "documentary_rate_resource": "PEDDI8"}
    resource = {**BY_ID[machine], "confirmed": True}
    gantt = integrated._duration(row, {"resource_code": BY_ID[machine]["code"], "proposed_code": "CPIS:119", "eligibility": "admissible"},
                                 resource, [], {}, NOW, _Context({"Peddi 8": {"value": 120}, "Ficep XP T4": {"value": 120}}, timing))
    assert gantt["duration_hours"] == pytest.approx(carteira, abs=1 / 60)
    # 600 m ÷ 120 m/h + 100 peças × 6 s, ÷ eficiência.
    assert carteira == pytest.approx((5 + 100 * 6 / 3600) * 100 / timing["efficiency"][machine])


def test_excluded_lines_do_not_weigh_on_suggestions(monkeypatch):
    """F25: uma linha excluída na Carteira não conta como «outra linha da OF» nem como carga da máquina."""
    from app.gantt import machines

    class Index:
        def __init__(self, *a):
            pass

        def candidates(self, row, codes):
            return [{"resource_id": rid, "resource_code": BY_ID[rid]["code"], "proposed_code": "CPIS:119", "eligibility": "admissible",
                     "conditions": [], "other_orders": 0} for rid in (P8, XP4)]
    monkeypatch.setattr(machines, "EvidenceIndex", Index)
    package = {"metadata": {"rates": []}, "rows": []}
    excluded = fact(key="v2:x", resource_id=XP4, assigned_resource_id=XP4, assigned_machine="Ficep XP T4", documentary_resource_id=XP4,
                    selection="excluded", late_days=0, priority_day=None)
    pending = fact(key="v2:p", resource_id=None, assigned_resource_id=None, assigned_machine="Sem máquina", documentary_resource_id=None,
                   late_days=0, priority_day=None, occurrence=2)
    rows = {"v2:x": {"linha": "x"}, "v2:p": {"linha": "p"}}
    published = estimates.published_rates(RECORDS, resolve)

    def run(excluded_keys):
        facts = [dict(excluded), dict(pending)]
        info = estimates.apply(facts, rows, codes=CODES, by_id=BY_ID, package=package, study=None, published=published,
                               excluded=excluded_keys)
        return facts[1], info
    counted, info = run(set())
    assert counted["suggestion"]["with_of_peers"] and counted["planning_resource_id"] == XP4
    assert info["loads"][XP4] > counted["load_hours"]
    free, info = run({"v2:x"})
    assert not free["suggestion"]["with_of_peers"] and free["planning_resource_id"] == P8  # código do recurso desempata
    assert info["loads"] == {P8: pytest.approx(free["load_hours"])}
    assert free["load_basis"] == "estimada" and free["load_hours"] == pytest.approx(5.0)


def test_capacity_sheet_rate_reads_columns_e_f_like_the_excel_load_table():
    """F02 (MTG2): a taxa é a da coluna F (se houver) ou E da CapacidadeMáquinas (29/11/2024), a que o Excel divide na
    tabela «Carga serrotes total»; a C (11/11/2024) fica nas alternativas. Valores do Excel de 07/10."""
    def cells(**kw):
        return {k: {"value": v} for k, v in kw.items()}
    assert calc.sheet_rate(cells(B="Serrote Disco pav 1", C=12824, E=15409), 2)["value"] == 15409
    thomas = calc.sheet_rate(cells(B="Serrote Fita Thomas IS639 Pav.1", C=18478, E=37692, F=18846), 4)
    assert thomas["value"] == 18846 and thomas["cell"] == "F4" and thomas["alternatives"]["C"]["value"] == 18478
    assert calc.sheet_rate(cells(B="Serrote Doall Pav.1", C=21863.5, F=18846), 10)["value"] == 18846
    assert calc.sheet_rate(cells(B="Vanguard", C=9200, E=13636), 6)["value"] == 13636
    assert calc.sheet_rate(cells(B="Abocardar", E=0), 8)["value"] is None
    sheet = [{"row": r, "cells": c} for r, c in ((2, cells(B="Serrote Disco pav 1", C=12824, E=15409)),
                                                 (3, cells(B="Serrote MEBA IS381 Pav 3", C=48024, E=40323)))]
    _, rates, _ = calc.workbook_index({"perfis": {"snapshot_id": "s", "sheets": {"CapacidadeMáquinas": sheet}}})
    assert rates[("perfis", "Serrote MEBA IS381 Pav 3")]["value"] == 40323
    assert rates[("perfis", "Serrote MEBA IS381 Pav 3")]["source"]["cell"] == "E3"


class _Conn:
    """Ligação falsa: só sector_settings (para provar que gravar não apaga chaves)."""
    def __init__(self, definition):
        self.definition = definition

    def execute(self, sql, params=None):
        conn = self

        class Result:
            def fetchone(self):
                if "to_regclass" in sql:
                    return {"t": "planning_mtg.sector_settings"}
                return {"definition": dict(conn.definition)} if conn.definition is not None else None
        if sql.lstrip().startswith("INSERT INTO planning_mtg.sector_settings"):
            conn.definition = params[1].obj
        return Result()


def test_saving_the_schedule_keeps_every_other_settings_key():
    """S01: antes só ficavam template/workdays/holidays/margem/tempo fixo; a eficiência e as chaves futuras apagavam-se."""
    from app.sector import settings
    stored = {"template": [["06:00", "13:30"]], "workdays": [1, 2, 3, 4, 5], "holidays": [], "piece_minutes": 0,
              "efficiency": {P8: 85}, "folga_dias": 2, "clientes_prioritarios": ["X"]}
    c = _Conn(stored)
    settings._store(c, "cantoneiras", {"template": [["06:00", "14:00"]], "workdays": [1, 2, 3, 4], "holidays": ["2026-12-08"]}, "teste")
    assert c.definition["efficiency"] == {P8: 85} and c.definition["folga_dias"] == 2 and c.definition["clientes_prioritarios"] == ["X"]
    assert c.definition["template"] == [["06:00", "14:00"]] and c.definition["workdays"] == [1, 2, 3, 4]
    settings._store(c, "cantoneiras", {"piece_minutes": 1, "revision": 9}, "teste")
    assert c.definition["efficiency"] == {P8: 85} and c.definition["piece_minutes"] == 1 and "revision" not in c.definition


def test_old_sector_margin_becomes_the_equivalent_efficiency_once():
    from app.sector import settings
    machines = {P8: {}, XP4: {}}
    # Margem 25 % sem eficiências: todas as máquinas passam a 80 %, depois aplica-se a alteração.
    assert settings._efficiency_store({"margin_pct": 25, "efficiency": {}}, {XP4: 90}, machines) == {P8: 80.0, XP4: 90}
    assert settings._efficiency_store({"margin_pct": 0, "efficiency": {P8: 85}}, {P8: 100, XP4: "95,5"}, machines) == {XP4: 95.5}
    with pytest.raises(Exception):
        settings._efficiency_store({}, {"outra": 90}, machines)
    with pytest.raises(Exception):
        settings._efficiency_store({}, {P8: 250}, machines)
    # A margem antiga sem eficiências conta como a eficiência equivalente de todas (uma só vez).
    timing = {"piece_minutes": 0, "efficiency": {"*": 100 / 1.25}}
    assert p.efficiency_of(timing, XP4) == pytest.approx(80) and p.efficiency_of({"efficiency": {P8: 85}}, XP4) == 100
