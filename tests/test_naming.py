"""Um nome por conceito, coerente com o CPIS (pedido do Luís, 06/10/2026)."""
import re
from pathlib import Path

from app import naming

ROOT = Path(__file__).resolve().parents[1]
SCANNED = [*sorted((ROOT / "app/web/templates").glob("*.html")), *sorted((ROOT / "app/web/static").glob("*.js")),
           *sorted((ROOT / "app/sector").glob("*.py")), ROOT / "app/planning_raw.py", ROOT / "app/raw/contracts.py"]
# Ecrãs antigos que o MES ainda serve (ficheiros partilhados): ficam como estavam.
LEGACY = {"capacity.js", "capacity.html"}


def test_every_name_has_a_label_a_source_and_an_explanation():
    for key, f in naming.fields()["campos"].items():
        assert f["nome"] and f["explicacao"], key
        assert "cpis" in f and "excel" in f, key
    assert naming.label("delivery_date") == "Data de entrega"
    assert naming.label("work_type") == "Família de Produto"


def test_old_synonyms_are_not_used_as_labels():
    found = []
    for path in SCANNED:
        if path.name in LEGACY or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for key, words in naming.synonyms().items():
            for word in words:
                # Só o rótulo inteiro entre aspas ou etiquetas (não «Descrição do perfil», nem o histórico dos documentos).
                pattern = r"""(?<=['"`>])\s*""" + re.escape(word) + r"""\s*(?=['"`<:])"""
                for m in re.finditer(pattern, text):
                    line = text[:m.start()].count("\n") + 1
                    found.append(f"{path.relative_to(ROOT)}:{line} «{word}» → «{naming.label(key)}»")
    assert not found, "\n".join(found)


def test_python_labels_match_the_glossary():
    from app.sector import portfolio, priority, tree
    assert portfolio.LEVELS["family"] == naming.label("work_type")
    assert portfolio.LEVELS["work"] == naming.label("ov") and tree.DIMENSIONS["work"] == naming.label("ov")
    assert tree.DIMENSIONS["cpis_family"] == naming.label("work_type")
    assert priority.FIELDS["delivery_date"] == naming.label("delivery_date")
    assert priority.FIELDS["planned_finish_date"] == naming.label("planned_finish_date")


def test_data_nome_keys_exist_and_the_menu_loads_the_explanations():
    keys = set(naming.fields()["campos"])
    for path in SCANNED:
        if path.suffix == ".html" and path.is_file():
            for key in re.findall(r'data-nome="([^"]+)"', path.read_text(encoding="utf-8")):
                assert key in keys, f"{path.name}: {key}"
    assert "/static/nomes.js" in (ROOT / "app/web/templates/_app_nav.html").read_text(encoding="utf-8")
