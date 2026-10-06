"""Sugestões do registo manual (app/planning_suggestions.py) e datas dd/mm/aaaa (06/10/2026). Sem base de dados."""
from app import planning_suggestions as S
from app.raw.registration import iso_date


def row(of, ref, profile, *, team="", pav="", machine="", cut="", material="Tubo redondo", length=1000.0, op1="", op2="",
        grade="", customer="Cliente", work_type="3", designation="COLUNAS 8M"):
    return S.Row(of=of, ref=ref, profile=S.profile_key(profile), profile_text=profile, material=material, team=team, pav=S.pavilion(pav),
                 machine=machine, cut_date=cut, length=length, op1=op1, op2=op2, grade=grade, description="", customer=customer,
                 work_type=work_type, designation=designation)


PERFIS = S.Index("perfis", [
    row("OF1", "A1", "76x3", team="Colunas", pav=6, machine="Serrote Disco pav 1", cut="2026-10-23", grade="S275JR"),
    row("OF1", "A2", "76x3", team="Colunas", pav=6, machine="Serrote Disco pav 1", cut="2026-10-23"),
    row("OF1", "A3", "60.3x2.9", team="Colunas", pav=6, machine="Vanguard", cut="2026-10-23"),
    row("OF10", "A1", "76x3", team="Colunas", pav=6, customer="Terceiro", work_type="5", designation="MASTROS"),
    row("OF2", "A1", "76x3", team="Equipa 5", pav=1, length=3050.0, grade="S275JR", customer="Outro", work_type="9", designation="BRAÇOS"),
    row("OF3", "B1", "30x30x3", team="Equipa 5", pav=1.0, material="Tubo quadrado", customer="Outro", work_type="9", designation="BRAÇOS"),
    row("OF4", "C1", "40x20", team="VFerreira", pav="", material="Varão retangular", customer="VF", work_type="1", designation="PÓRTICO"),
    row("OF5", "C2", "40x20", team="VFerreira", pav="", material="Varão retangular", customer="VF", work_type="1", designation="PÓRTICO"),
    row("OF6", "C3", "40x20", team="VFerreira", pav="2", material="Varão retangular", customer="VF", work_type="1", designation="PÓRTICO"),
], cpis={"OF9": ("Outro", "9", "BRAÇOS SIMPLES")})

CANT = S.Index("cantoneiras", [
    row("OF7", "D13F195", "L40X40X3", team="Postes MTG3", pav="mtg3", machine="Ficep XP T4", cut="2026-09-02", material="Cantoneira",
        length=909.0, op1="119", op2="111"),
    row("OF7", "D13F196", "L50X50X5", team="Postes MTG3", pav="MTG3", machine="Peddi 8", cut="2026-09-02", material="Cantoneira"),
    row("OF8", "D13F195", "L40X40X3", team="Postes MTG3", pav="MTG3", machine="Ficep XP T4", material="Cantoneira", length=909.0,
        op1="119", op2="111"),
])


def values(result):
    return {k: v["value"] for k, v in result.items()}


def test_existing_order_fills_team_pavilion_cut_date_and_machine_from_its_other_lines():
    out = S.suggest("perfis", "OF1", "NEW", "60.3x2.9", {"material_type": "Tubo redondo"}, idx=PERFIS, learned=False)
    v = values(out)
    assert v["team"] == "Colunas" and out["team"]["source_pt"] == "outras linhas da OF"
    assert v["pavilion"] == "6" and v["cut_date"] == "2026-10-23"
    assert v["machine"] == "Vanguard" and out["machine"]["source_pt"] == "mesma OF e mesmo perfil"
    assert S.suggest("perfis", "OF1", "NEW", "100x5", idx=PERFIS, learned=False)["machine"]["value"] == "Serrote Disco pav 1"
    assert v["outer_diameter_mm"] == 60.3 and v["thickness_mm"] == 2.9


def test_new_order_uses_reference_then_customer_and_work_type_then_designation():
    out = S.suggest("perfis", "OF99", "A1", None, idx=PERFIS, learned=False)
    v = values(out)
    # A1 aparece na OF1 e na OF10 (Colunas) e na OF2 (Equipa 5): 2 contra 1
    assert v["team"] == "Colunas" and out["team"]["source_pt"] == "mesma referência noutras OF" and out["team"]["confidence"] == 0.67
    assert v["material_type"] == "Tubo redondo" and v["profile"] == "76x3" and v["grade"] == "S275JR"
    assert "machine" not in v and "cut_date" not in v
    by_cpis = S.suggest("perfis", "OF9", "SEM-REF", None, idx=PERFIS, learned=False)
    assert by_cpis["team"] == {"value": "Equipa 5", "source_pt": "cliente e tipo de obra", "confidence": 1.0}
    assert by_cpis["pavilion"]["value"] == "1"
    by_word = S.suggest("perfis", "OF98", "SEM-REF", None, {"designation": "Braços duplos"}, idx=PERFIS, learned=False)
    assert by_word["team"]["value"] == "Equipa 5" and by_word["team"]["source_pt"] == "designação da obra"
    assert "team" not in S.suggest("perfis", "OF97", "SEM-REF", None, idx=PERFIS, learned=False)  # perfis: vazio


def test_pavilion_follows_the_typed_team_and_stays_empty_for_vferreira():
    assert values(S.suggest("perfis", "OF1", None, None, {"team": "Equipa 5"}, idx=PERFIS, learned=False))["pavilion"] == "1"
    assert "pavilion" not in S.suggest("perfis", "OF1", None, None, {"team": "VFerreira"}, idx=PERFIS, learned=False)


def test_cantoneiras_default_team_uppercase_pavilion_dimensions_and_grade():
    out = S.suggest("cantoneiras", "OF50", "NOVA", "L60X60X6 S355J2", idx=CANT, learned=False)
    v = values(out)
    assert v["team"] == "Postes MTG3" and v["pavilion"] == "MTG3"
    assert (v["width_mm"], v["height_mm"], v["thickness_mm"]) == (60.0, 60.0, 6.0) and v["grade"] == "S355J2"
    ref = values(S.suggest("cantoneiras", "OF50", "D13F195", None, idx=CANT, learned=False))
    assert ref["operation"] == "119" and ref["operation_detail"] == "111" and ref["length_mm"] == 909.0 and ref["profile"] == "L40X40X3"
    same = S.suggest("cantoneiras", "OF7", None, "L50X50X5", idx=CANT, learned=False)
    assert same["machine"]["value"] == "Peddi 8" and same["cut_date"]["value"] == "2026-09-02"


def test_exclude_of_measures_a_new_order_without_its_own_lines():
    out = S.suggest("perfis", "OF2", "A1", None, idx=PERFIS, exclude_of="OF2", learned=False)
    assert out["team"]["value"] == "Colunas" and out["team"]["confidence"] == 1.0  # só a OF1 fica para votar
    assert "cut_date" not in out


def test_dimensions_follow_the_excel_columns_per_material():
    assert S.dimensions("perfis", "Tubo redondo", "60.3x2.9") == {"outer_diameter_mm": 60.3, "thickness_mm": 2.9}
    assert S.dimensions("perfis", "Tubo quadrado", "30x30x3") == {"width_mm": 30.0, "thickness_mm": 3.0}
    assert S.dimensions("perfis", "Tubo retangular", "80x40x3") == {"width_mm": 80.0, "height_mm": 40.0, "thickness_mm": 3.0}
    assert S.dimensions("perfis", "Varão redondo", "16") == {"outer_diameter_mm": 16.0}
    assert S.dimensions("perfis", "Varão nervurado", "20") == {"outer_diameter_mm": 20.0}
    assert S.dimensions("perfis", "Varão quadrado", "12x12") == {"width_mm": 12.0}
    assert S.dimensions("perfis", "Chapa", "75x45") == {"width_mm": 75.0, "thickness_mm": 45.0}
    assert S.dimensions("perfis", "Calha", "40x22x2") == {"width_mm": 40.0, "height_mm": 22.0, "thickness_mm": 2.0}
    assert S.dimensions("perfis", "Perfil U", "UPN100") == {}
    assert S.dimensions("cantoneiras", "Cantoneira", "L40X40X3 S355J2 EN10025") == {"width_mm": 40.0, "height_mm": 40.0, "thickness_mm": 3.0}
    assert S.pavilion("mtg3") == "MTG3" and S.pavilion(1.0) == "1"


def test_registration_dates_accept_day_month_year():
    assert iso_date("10/10/2026") == "2026-10-10"
    assert iso_date("1-2-2026") == "2026-02-01"
    assert iso_date("2026-10-23T00:00:00") == "2026-10-23"
    assert iso_date("31/02/2026") is None and iso_date("sem data") is None and iso_date("") is None
