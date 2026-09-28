"""Resolução determinística entre a designação literal e o catálogo da macro."""
from __future__ import annotations

import re
import unicodedata

from .models import fingerprint

VERSION = "material-catalog-v2-section-geometry"


def _plain(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold().strip()


def _key(value) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper().replace(",", "."))


def _family_kind(value) -> str:
    text = _plain(value)
    if "tubo" in text and "redond" in text: return "round_tube"
    if "tubo" in text and ("retang" in text or "quadr" in text): return "rect_tube"
    if ("varao" in text or "barra" in text or "maci" in text) and "redond" in text: return "round_bar"
    if "perfil u" in text or text.startswith("upn"): return "profile_u"
    if "perfil h" in text or re.match(r"he[abm]", text): return "profile_h"
    if "perfil i" in text or text.startswith("ipe") or text.startswith("ipn"): return "profile_i"
    if text.startswith("perfil ") or "roscado" in text: return "standard_other"
    return "other"


def _canonical_family(raw: str, catalog: list[dict]) -> str:
    kind = _family_kind(raw)
    candidates = sorted({str(e.get("family") or "").strip() for e in catalog
                         if _family_kind(e.get("family")) == kind and e.get("family")})
    if len(candidates) == 1:
        return candidates[0]
    defaults = {"round_tube": "Tubo redondo", "rect_tube": "Tubo retangular",
                "round_bar": "Varão redondo", "profile_u": "Perfil U",
                "profile_h": "Perfil H", "profile_i": "Perfil I"}
    return defaults.get(kind, str(raw or "").strip())


def resolve(values: dict, context: dict) -> dict:
    """Return export values plus auditable catalogue/derivation metadata.

    The extracted values are never changed. Only this result is consumed by the
    macro adapter after reconciliation has accepted it.
    """
    catalog = list(context.get("material_catalog") or [])
    raw_family = str(values.get("material_type") or "").strip()
    raw_profile = str(values.get("profile") or "").strip()
    family_kind = _family_kind(raw_family)
    profile_kind = _family_kind(raw_profile)
    # Descrições genéricas como «Viga» não podem esconder uma série explícita
    # HEB/IPE/UPN presente no perfil. Uma família técnica reconhecida continua
    # a prevalecer, para não resolver silenciosamente dados contraditórios.
    use_profile_family = family_kind == "other" and profile_kind != "other"
    kind = profile_kind if use_profile_family else family_kind
    family_source = raw_profile if use_profile_family else (raw_family or raw_profile)
    export = {"material_type": _canonical_family(family_source, catalog),
              "profile": raw_profile}
    derived, candidates = {}, []

    numbers = [float(x.replace(",", ".")) for x in
               re.findall(r"\d+(?:[.,]\d+)?", raw_profile)]
    if kind == "round_tube" and len(numbers) >= 2:
        derived = {"outer_diameter_mm": numbers[0], "thickness_mm": numbers[1]}
    elif kind == "rect_tube" and len(numbers) >= 3:
        derived = {"width_mm": numbers[0], "height_mm": numbers[1], "thickness_mm": numbers[2]}
    elif kind == "round_bar" and len(numbers) == 1 and re.fullmatch(r"\s*(?:R|D|[Øø⌀])?\s*\d+(?:[.,]\d+)?\s*", raw_profile, re.I):
        # Rxx is treated as a diameter only after the material was independently
        # classified as a round solid section.
        derived = {"outer_diameter_mm": numbers[0]}
    for field, value in list(derived.items()):
        if values.get(field) is not None:
            derived.pop(field)
        else:
            export[field] = value

    if kind in {"profile_u", "profile_h", "profile_i", "standard_other"}:
        exact = [e for e in catalog if _key(e.get("profile")) == _key(raw_profile)]
        if exact:
            candidates = exact
        else:
            nominal = _key(raw_profile)
            if kind == "profile_u":
                # U50 is a common drawing designation; the second number can
                # even be the cut length (U50x200). The explicit section
                # dimensions decide between catalogue entries such as
                # UPN50x25 and UPN50x38.
                match = re.fullmatch(r"(?:UPN|U)(\d+)(?:X\d+(?:[.]\d+)?)?", nominal)
                candidates = [e for e in catalog if match and _family_kind(e.get("family")) == kind
                              and re.fullmatch(rf"UPN{match[1]}(?:X\d+(?:[.]\d+)?)?", _key(e.get("profile")))]
                width, height = values.get("width_mm"), values.get("height_mm")
                if candidates and (width is not None or height is not None):
                    compatible = []
                    for entry in candidates:
                        section = re.fullmatch(r"UPN(\d+(?:[.]\d+)?)(?:X(\d+(?:[.]\d+)?))?",
                                               _key(entry.get("profile")))
                        if not section:
                            continue
                        nominal_height = float(section[1])
                        nominal_width = float(section[2]) if section[2] else None
                        if height is not None and float(height) != nominal_height:
                            continue
                        if width is not None and (nominal_width is None or float(width) != nominal_width):
                            continue
                        compatible.append(entry)
                    candidates = compatible
            elif kind == "profile_h":
                match = re.fullmatch(r"(HE[ABM])(\d+)", nominal)
                candidates = [e for e in catalog if match and _family_kind(e.get("family")) == kind
                              and re.fullmatch(rf"{match[1]}{match[2]}[A-Z]?", _key(e.get("profile")))]
            elif kind == "profile_i":
                match = re.fullmatch(r"(IP[EN])(\d+)", nominal)
                candidates = [e for e in catalog if match and _family_kind(e.get("family")) == kind
                              and re.fullmatch(rf"{match[1]}{match[2]}[A-Z]?", _key(e.get("profile")))]
        unique = {(str(e.get("family") or ""), str(e.get("profile") or "")) for e in candidates}
        if len(unique) == 1:
            family, profile = unique.pop()
            export.update(material_type=family, profile=profile)
            status = "catalog_exact" if _key(profile) == _key(raw_profile) else "catalog_alias"
        elif len(unique) > 1:
            status = "ambiguous"
        else:
            status = "catalog_unavailable" if not catalog else "unresolved"
    else:
        status = "dimensional"

    return {"version": VERSION, "catalog_version": context.get("material_catalog_version"),
            "status": status, "raw": {"material_type": raw_family, "profile": raw_profile},
            "export": export, "derived": derived,
            "candidates": [{"family": e.get("family"), "profile": e.get("profile"),
                            "area": e.get("area"), "rule": e.get("rule")}
                           for e in candidates[:20]],
            "fingerprint": fingerprint([VERSION, context.get("material_catalog_version"), raw_family,
                                        raw_profile, export, derived])}
