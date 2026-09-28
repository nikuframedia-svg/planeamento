"""Referência mestre (o modelo) a partir do código da peça.

Regra aprovada a 28/09/2026 e testada nos planos de 25/09: MTG3 dá 342 modelos (0,3% das
linhas por confirmar) e MTG2 dá 808 (2,9%). As exceções corrigidas pelo planeador têm
prioridade sobre a regra.
"""
import re

_LETTERS_NUMBER_LETTER = re.compile(r"^([A-Z]+\d+)[A-Z]+\d")   # ED4T40 -> ED4, CI7812A4046 -> CI7812
_NUMBER_LETTER = re.compile(r"^(\d+)[A-Z]+\d")                  # 1283V053 -> 1283
_LETTERS_NUMBER = re.compile(r"^([A-Z]+)-?\d")                  # DLT319 -> DLT, ZE-626 -> ZE

UNRESOLVED = "Modelo por confirmar"


def normalise(ref) -> str:
    return re.sub(r"\s+", "", str(ref or "")).upper()


def master_reference(ref, overrides: dict[str, str] | None = None) -> str | None:
    """Model code of a part reference, or None when the rule cannot tell."""
    code = normalise(ref)
    if not code:
        return None
    if overrides and code in overrides:
        return overrides[code]
    for rule in (_LETTERS_NUMBER_LETTER, _NUMBER_LETTER, _LETTERS_NUMBER):
        match = rule.match(code)
        if match:
            return match.group(1)
    return None
