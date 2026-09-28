"""Normalização e semelhança por campo.

Três tipos de campo:
- código (OF, OV, lote, nesting): comparação compacta alfanumérica com variantes 0↔O;
- texto (cliente, modelo): tokens normalizados sem sufixos societários;
- numérico (dimensões): dentro de tolerância = 1.0, decaimento linear fora.
"""

from __future__ import annotations

import re
import math
import unicodedata
from functools import lru_cache

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_WS = re.compile(r"\s+")

# Sufixos/palavras sem poder identificativo em nomes de clientes.
_CLIENT_STOPWORDS = frozenset(
    "SA LDA SL SAS GMBH AG BV SRL SPA LTD LTDA INC CO SOCIEDADE UNIPESSOAL E DE DO DA".split()
)


def compact(value: str | None) -> str:
    """Maiúsculas, só alfanumérico ASCII. 'of 250002' → 'OF250002'.

    Acentos decompõem-se primeiro (NFKD) para a letra base sobreviver:
    'CONCEIÇÃO' → 'CONCEICAO', não 'CONCEIO' — senão um nome corretamente
    lido pelo OCR ficava a 2 de distância da lista de colaboradores.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    return _NON_ALNUM.sub("", text.upper())


_YEAR_PREFIX = re.compile(r"^\s*\d{2}_")


def normalize_code(value: str | None) -> str:
    """O plano prefixa nestings com o ano ('26_S07.CH5_1'); os operadores nunca
    o escrevem ('S07.CH5_1'). O prefixo é formatação, não identidade — cai dos
    dois lados antes do lookup. Medido nos kanbans reais: cobertura exata sobe
    de 24,7% para 56,7%. OF/OV/referências não têm o padrão '\\d\\d_'."""
    if value is None:
        return ""
    return compact(_YEAR_PREFIX.sub("", str(value)))


def zero_o_variants(code: str) -> set[str]:
    """Variantes do código trocando O↔0 (a confusão mais comum de todas).
    Limitado a códigos curtos para não explodir combinatoriamente."""
    code = normalize_code(code)
    if not code or len(code) > 12:
        return {code} if code else set()
    variants = {code}
    for i, ch in enumerate(code):
        swap = {"O": "0", "0": "O"}.get(ch)
        if swap:
            variants |= {v[:i] + swap + v[i + 1 :] for v in list(variants)}
        if len(variants) > 64:
            break
    return variants


def code_variants(value: str | None, prefix: str = "") -> set[str]:
    """Formas sob as quais um código escrito à mão pode aparecer no plano.

    O plano guarda `OF263323`/`OV2504650` (todas as 64 mil linhas com prefixo)
    e o operador escreve `263323` — a folha já diz «OF» no cabeçalho da coluna,
    ninguém repete o prefixo. A variante prefixada é **adicional**: nem tudo o
    que está na coluna OV começa por OV, portanto a forma sem prefixo continua
    a valer.
    """
    base = normalize_code(value)
    if not base:
        return set()
    out = zero_o_variants(base)
    if prefix:
        pfx = compact(prefix)
        if pfx and not base.startswith(pfx):
            out = out | {pfx + v for v in out}
    return out


# Perfis deste setor: tubos «Ø ext x espessura». O plano Met2 guarda
# «60.3x2.9» (composto pelo loader a partir de Ø Ext e Esp.); o operador
# escreve «60.3x2.9», «60,3 x 2,9» ou «Ø60.3x2.9». O compact() iguala as três
# formas (pontuação e Ø caem): todas ficam «603X29» — a forma canónica é essa.
# A expansão de cantoneira (2 medidas → abas iguais, «60x5» = L60X60X5) NÃO
# se aplica a tubos e foi removida neste repo.


# Abaixo disto é medida do perfil (aba, espessura, Ø); acima é o COMPRIMENTO
# da peça, que o operador escreve a seguir ao tubo («Ø20 x 455», «UPN65 x
# 3940» — casos reais da folha 1fb333b28059) mas que o plano guarda à parte
# (length_mm), nunca no profile_type.
_COMPRIMENTO_MIN = 250


def normalize_profile(value: str | None, known: object = None) -> str:
    """Forma textual canónica de um perfil, sem interpretar a geometria.

    Distingue ``60x300`` de ``60``. A hipótese de que um último eixo é o
    comprimento da peça vive no cross e só é aplicada após confirmação forte
    contra o plano.

    `known` (conjunto de perfis válidos do plano) mantém-se na assinatura por
    compatibilidade com os call-sites do motor.
    """
    # Decimal marks are identity: 60.3x2.9 and 60.3x29 are different tubes.
    # Import locally to keep the legacy helpers independent of the V3 engine.
    from .geometry import profile_key

    return profile_key(value)


def profile_similarity(written_norm: str, truth_norm: str) -> float:
    """Semelhança entre perfis JÁ normalizados.

    Além da igualdade, aceita o sufixo dimensional a mais num dos lados:
    o operador escreve «UPN65» e o plano guarda «UPN65x42» (Designação
    Perfil completa), ou escreve só o Ø «76.1» de um tubo «76.1x3.2» —
    é o mesmo perfil, não uma parecença.
    """
    if not written_norm or not truth_norm:
        return 0.0
    if written_norm == truth_norm:
        return 1.0
    # Só a referência do plano pode ter detalhe dimensional omitido no papel.
    # Se o escrito tem mais detalhe, ele distingue «42.4x2.65» de «42.4».
    suffix = truth_norm[len(written_norm) + 1:]
    if (truth_norm.startswith(written_norm + "X")
            and re.fullmatch(r"\d+(?:\.\d+)?(?:X\d+(?:\.\d+)?)*", suffix)):
        return 1.0
    return code_similarity(written_norm, truth_norm)


def client_tokens(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    tokens = [compact(t) for t in _WS.split(str(value).upper())]
    return tuple(t for t in tokens if t and t not in _CLIENT_STOPWORDS)


@lru_cache(maxsize=65536)
def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def ratio(a: str, b: str) -> float:
    """Semelhança em [0,1] baseada em distância de edição."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))


def code_similarity(written: str | None, truth: str | None) -> float:
    """1.0 se alguma variante O↔0 bate certo; senão ratio de edição compacta.
    Normaliza o prefixo de ano dos dois lados (ver normalize_code)."""
    w, t = normalize_code(written), normalize_code(truth)
    if not w or not t:
        return 0.0
    if w == t or t in zero_o_variants(w):
        return 1.0
    return ratio(w, t)


def text_similarity(written: str | None, truth: str | None) -> float:
    """Clientes/modelos: igualdade compacta, contenção de tokens, ou fuzzy."""
    w_comp, t_comp = compact(written), compact(truth)
    if not w_comp or not t_comp:
        return 0.0
    if w_comp == t_comp:
        return 1.0
    # o escrito está contido na designação completa (operador abrevia)
    if len(w_comp) >= 4 and (w_comp in t_comp or t_comp in w_comp):
        return 0.97
    w_tokens, t_tokens = client_tokens(written), client_tokens(truth)
    if w_tokens and t_tokens:
        if set(w_tokens) & set(t_tokens):
            common = len(set(w_tokens) & set(t_tokens))
            return min(0.97, 0.6 + 0.2 * common)
        best = max(
            (ratio(a, b) for a in w_tokens for b in t_tokens[:8]),
            default=0.0,
        )
        return max(best, ratio(w_comp, t_comp))
    return ratio(w_comp, t_comp)


def numeric_similarity(written: float | None, truth: float | None, tolerance: float) -> float:
    """1.0 dentro da tolerância; decaimento linear até 0 a 4× tolerância."""
    if written is None or truth is None:
        return 0.0
    diff = abs(float(written) - float(truth))
    if diff <= tolerance:
        return 1.0
    span = max(tolerance * 3.0, 1e-9)
    return max(0.0, 1.0 - (diff - tolerance) / span)


# «1.200» é milhar; «0.125» não (milhares não começam por zero)
_THOUSANDS_DOT = re.compile(r"^-?[1-9]\d{0,2}(\.\d{3})+$")

_REF_PREFIX = re.compile(r"^\s*(OF|OV)\s*(\d+)\s*$", re.IGNORECASE)


def strip_ref_prefix(value: object) -> str:
    """«OF263323» → «263323». No planeamento e na Metalogalva 2 as ordens são
    números puros; o prefixo é convenção interna do Excel do plano. Tudo o que
    se MOSTRA e GRAVA fica nu — o matching continua a usar variantes por
    dentro. Só OF/OV: um modelo «QS122» não pode perder o Q."""
    text = str(value or "").strip()
    m = _REF_PREFIX.match(text)
    return m.group(2) if m else text


def parse_number(value: object) -> float | None:
    """Typed numerics and complete human tokens, preserving legacy mm/h units."""
    from .geometry import parse_decimal

    if isinstance(value, str):
        # Explicit units used by existing exports; never strip arbitrary
        # annotations, mathematical operators or time separators.
        value = re.sub(r"\s*(?:mm|h)$", "", value.strip(), flags=re.IGNORECASE)
    number = parse_decimal(value)
    if number is None:
        return None
    result = float(number)
    return result if math.isfinite(result) else None
