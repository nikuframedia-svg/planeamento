import pytest

from app.sector.references import master_reference


@pytest.mark.parametrize("ref,expected", [
    ("ED4T40", "ED4"), ("CI7812A4046", "CI7812"), ("1283V053", "1283"), ("DLT319", "DLT"),
    ("DLR9312D", "DLR"), ("ZE-626", "ZE"), ("AT1T162", "AT1"), ("5877T169", "5877"),
    (" dlt 319 ", "DLT"), ("CDPTM001", "CDPTM"),
])
def test_rule_examples_approved_on_28_09(ref, expected):
    assert master_reference(ref) == expected


@pytest.mark.parametrize("ref", ["ACS", "ESP.BR.", "DLTBCGE", "", None, "L CORTE"])
def test_unresolved_codes_stay_unknown(ref):
    assert master_reference(ref) is None


def test_planner_override_wins_over_the_rule():
    assert master_reference("DLTBCGE", {"DLTBCGE": "DLT"}) == "DLT"
    assert master_reference("DLT319", {"DLT319": "DLT-ESPECIAL"}) == "DLT-ESPECIAL"
