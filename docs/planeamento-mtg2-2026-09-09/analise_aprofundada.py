"""Auditoria offline dos extratos MTG2 de 09/09/2026, sem escrita nas fontes.

Uso: python3 analise_aprofundada.py --dados /tmp/mtg2-planning-20260909
Requer plan.json, plan_previous.json, aux.json, production.json,
snapshots.json e factory_sheets.json, exportados em leitura apenas.
Os resultados são evidência de análise, não ordens de produção.
"""

import argparse
import collections as C
import csv
import hashlib
import json
import math
import re
from pathlib import Path


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def norm(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def context(r):
    return r.get("order_context") or {}


def pending(r):
    return r["remaining_valid"] and (r["canonical_remaining"] or 0) > 0 and not r["closed_x"]


def active(r):
    return context(r).get("cpis_status") in {"Em Produção", "Em Aberto"}


def geometry(r):
    return r["material_type"], r["profile_type"]


def identity(r):
    return norm(r["production_order_no"]).removeprefix("OF"), norm(r["component_ref"])


def basic(r):
    d = r["row_data"]
    return bool(d.get("Máquina Corte") and d.get("Qual.")
                and (num(d.get("Área de Seção de Corte [mm2]")) or 0) > 0
                and d.get("_profile_fully_dimensioned")
                and context(r).get("cpis_delivery_date"))


def source_area(r):
    """Reconstituição independente das onze funções VBA; sem imputar dimensões."""
    d = r["row_data"]
    t = d.get("Tipo de Material")
    g = lambda k: float(d[k])
    if t == "Tubo redondo":
        D, w = g("Ø Externo [mm]"), g("Espessura (t) [mm]")
        unit = math.pi / 4 * (D * D - (D - 2 * w) ** 2)
    elif t == "Tubo retangular":
        w, h, s = g("Largura (w) [mm]"), g("Altura (h) [mm]"), g("Espessura (t) [mm]")
        unit = w * h - (w - 2 * s) * (h - 2 * s)
    elif t == "Tubo quadrado":
        w, s = g("Largura (w) [mm]"), g("Espessura (t) [mm]")
        unit = w * w - (w - 2 * s) ** 2
    elif t in {"Varão redondo", "Varão nervurado"}:
        unit = math.pi / 4 * g("Ø Externo [mm]") ** 2
    elif t in {"Varão retangular", "Barra"}:
        unit = g("Largura (w) [mm]") * g("Altura (h) [mm]")
    elif t == "Varão quadrado":
        unit = g("Largura (w) [mm]") ** 2
    elif t in {"Calha", "Cantoneira"}:
        w, h, s = g("Largura (w) [mm]"), g("Altura (h) [mm]"), g("Espessura (t) [mm]")
        unit = h * s + 2 * w * s - 2 * s * s if t == "Calha" else h * s + w * s - s * s
    elif t == "Chapa":
        unit = g("Largura (w) [mm]") * g("Espessura (t) [mm]")
    else:
        return None
    # AP usa AH, e não N. N e AH diferem em doze linhas.
    return unit * g("QTD [un,]")


def describe(r):
    return {"linha_excel": r["excel_row"], "of": r["production_order_no"],
            "referencia": r["component_ref"], "perfil": r["profile_type"],
            "comprimento_mm": r["length_mm"], "saldo_corte": r["canonical_remaining"]}


def export_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dados", type=Path, required=True)
    ap.add_argument("--saida", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    input_names = ["plan", "plan_previous", "aux", "production", "snapshots", "factory_sheets"]
    inputs = {n: json.loads((args.dados / (n + ".json")).read_text()) for n in input_names}
    plan, previous = inputs["plan"], inputs["plan_previous"]
    backlog = [r for r in plan if pending(r)]
    jobs = [r for r in backlog if active(r)]
    subset = [r for r in jobs if basic(r)]
    result = {"snapshot": plan[0]["snapshot_id"], "snapshot_anterior": previous[0]["snapshot_id"],
              "data_referencia": "2026-09-09", "escrita_nas_fontes": False,
              "sha256_extratos": {n: hashlib.sha256((args.dados / (n + ".json")).read_bytes()).hexdigest()
                                  for n in input_names}}
    by_order = C.defaultdict(list)
    for r in jobs:
        by_order[r["production_order_no"]].append(r)
    complete = {of: rs for of, rs in by_order.items() if all(basic(r) for r in rs)}
    result["universos"] = {
        "linhas_fonte": len(plan), "saldo_positivo_nao_fechadas": len(backlog),
        "linhas_of_ativas": len(jobs), "of_ativas_com_saldo_corte": len(by_order),
        "pecas_saldo_corte_of_ativas": sum(r["canonical_remaining"] for r in jobs),
        "linhas_campos_basicos": len(subset), "of_com_alguma_linha_basica": len({r["production_order_no"] for r in subset}),
        "of_todas_linhas_corte_basicas": len(complete),
        "linhas_dessas_of": sum(map(len, complete.values())),
        "sem_maquina": sum(not r["row_data"].get("Máquina Corte") for r in jobs),
        "sem_qualidade": sum(not r["row_data"].get("Qual.") for r in jobs),
        "sem_area_positiva": sum((num(r["row_data"].get("Área de Seção de Corte [mm2]")) or 0) <= 0 for r in jobs),
        "sem_entrega": sum(not context(r).get("cpis_delivery_date") for r in jobs),
        "linhas_com_data_material": sum(bool(r["row_data"].get("Data Material")) for r in jobs),
        "linhas_com_lote": sum(bool(r["row_data"].get("Nº lote")) for r in jobs),
        "nota": "Campos básicos não comprovam stock, calendário, tempos ou elegibilidade."
    }

    # A unidade de confirmação pode ser um conjunto OF + perfil, sem inventar o aço.
    grade_groups = C.defaultdict(list)
    for r in jobs:
        if not r["row_data"].get("Qual."):
            grade_groups[(r["production_order_no"], *geometry(r))].append(r)
    grade_csv = [{"of": k[0], "tipo": k[1], "perfil": k[2], "linhas": len(rs),
                  "quantidade_por_cortar": sum(r["canonical_remaining"] for r in rs),
                  "linhas_excel": " ".join(str(r["excel_row"]) for r in rs),
                  "qualidade_confirmada": ""}
                 for k, rs in sorted(grade_groups.items(), key=lambda kv: -len(kv[1]))]
    export_csv(args.saida / "confirmacoes-qualidade.csv", grade_csv)
    result["qualidade"] = {"grupos_of_tipo_perfil": len(grade_csv), "grupos": grade_csv}

    recalculated = C.Counter()
    for r in plan:
        try:
            value = source_area(r)
            if value is None:
                recalculated["catalogo"] += 1
            else:
                cached = float(r["row_data"]["Área de Seção de Corte [mm2]"])
                recalculated["recalculadas"] += 1
                recalculated["coincidem" if math.isclose(value, cached, rel_tol=1e-7, abs_tol=.01) else "divergem"] += 1
        except (ValueError, TypeError, KeyError):
            recalculated["entradas_insuficientes"] += 1
    result["validacao_geometria_com_AH"] = dict(recalculated)
    result["N_diferente_AH"] = [describe(r) | {"N": r["quantity_planned"], "AH": r["row_data"].get("QTD [un,]")}
                                    for r in plan if num(r["quantity_planned"]) is not None
                                    and num(r["row_data"].get("QTD [un,]")) is not None
                                    and num(r["quantity_planned"]) != num(r["row_data"].get("QTD [un,]"))]
    result["angulos_fora_360"] = [describe(r) | {"angulo": r["row_data"].get("Ang,")}
                                      for r in jobs if abs(num(r["row_data"].get("Ang,")) or 0) > 360]

    # Estas correspondências são propostas explícitas, não correções aplicadas.
    aliases = {"HEA240": "HEA240A", "HEB300": "HEB300B", "UPN80": "UPN80x45",
               "UPN65": "UPN65x42", "UPN100": "UPN100x50"}
    catalogue = {r["row_data"]["values"][1]: r["row_data"]["values"][2]
                 for r in inputs["aux"] if r["sheet_name"] == "AreaSecaoCorte"}
    result["area_zero_propostas"] = [describe(r) | {"nome_catalogo_proposto": aliases.get(r["profile_type"]),
                                                      "area_unitaria_proposta_mm2": catalogue.get(aliases.get(r["profile_type"])),
                                                      "confirmado": False}
                                        for r in jobs if (num(r["row_data"].get("Área de Seção de Corte [mm2]")) or 0) <= 0]

    # Precedentes do plano só geram sugestões; não constituem capacidades físicas.
    machine_history = C.defaultdict(lambda: C.defaultdict(set))
    for r in plan:
        d = r["row_data"]
        if r["closed_x"] and d.get("Máquina Corte") and d.get("Qual."):
            machine_history[(*geometry(r), d["Qual."])][d["Máquina Corte"]].add(r["production_order_no"])
    suggestions = []
    for r in jobs:
        d = r["row_data"]
        if d.get("Máquina Corte") or not d.get("Qual."):
            continue
        options = machine_history[(*geometry(r), d["Qual."])]
        if len(options) == 1 and len(next(iter(options.values()))) >= 3:
            machine, orders = next(iter(options.items()))
            suggestions.append(describe(r) | {"maquina_sugerida": machine, "of_precedentes": len(orders),
                                               "origem": "maquina_indicada_em_linhas_fechadas", "autorizada": False})
    export_csv(args.saida / "sugestoes-maquinas.csv", suggestions)
    result["sugestoes_maquinas"] = {"linhas": len(suggestions), "criterio": "Mesmo tipo, perfil e qualidade conhecida; uma única máquina em pelo menos três OF fechadas. Não valida dimensões máximas, comprimento, ângulo ou dispositivo de aperto."}

    # Operações separadas: não se infere zero de um contador de abocardar vazio.
    aboc = []
    for r in plan:
        d = r["row_data"]
        if not r["closed_x"] and active(r) and d.get("Aborc.") == "X":
            cut, made, qty = num(d.get("Ser.")), num(d.get("Aboc.")), num(r["quantity_planned"])
            aboc.append(describe(r) | {"quantidade": qty, "contador_corte": cut, "contador_abocardar": made,
                                       "saldo_abocardar_se_contador_valido": max(qty - made, 0) if qty is not None and made is not None else None,
                                       "ja_cortado_nao_abocardado_se_contadores_validos": max(min(cut, qty) - made, 0) if None not in (cut, made, qty) else None})
    result["abocardar"] = aboc

    # Comparação temporal com identificação estável e exclusão de IDs repetidos.
    old_index, new_index = C.defaultdict(list), C.defaultdict(list)
    for r in previous:
        old_index[r["external_row_number"]].append(r)
    for r in plan:
        new_index[r["external_row_number"]].append(r)
    delta, delta_counts = [], C.Counter()
    for k, rows in new_index.items():
        if len(rows) != 1 or len(old_index[k]) != 1:
            delta_counts["linhas_ids_ambiguos"] += len(rows)
            continue
        r, old = rows[0], old_index[k][0]
        if identity(r) != identity(old):
            delta_counts["identidade_alterada"] += 1
            continue
        delta_counts["identidade_estavel"] += 1
        for field in ["quantity_planned", "quantity_remaining_source", "closed_x"]:
            if r[field] != old[field]:
                delta_counts["alterado_" + field] += 1
        if r["quantity_remaining_source"] != old["quantity_remaining_source"]:
            delta.append(describe(r) | {"saldo_fonte_anterior": old["quantity_remaining_source"],
                                       "saldo_fonte_atual": r["quantity_remaining_source"]})
    result["alteracoes_snapshots"] = {"contagens": dict(delta_counts), "linhas": delta,
                                       "nota": "Data da alteração do ficheiro não é data física de produção."}

    idx, by_row = C.defaultdict(list), {r["excel_row"]: r for r in plan}
    for r in plan:
        idx[identity(r)].append(r)
    prod = [r for r in inputs["production"] if r["source_app"] == "kanban-mes-mtg2"]
    production_counts, by_sheet = C.Counter(), C.defaultdict(list)
    retained_snapshots = {r["snapshot_id"] for r in inputs["snapshots"]}
    machine_alias = {"VANGUARD": "Vanguard", "MEBA": "Serrote MEBA IS381 Pav 3"}
    transitions = C.Counter()
    for r in prod:
        pid = norm(r["production_order"]).removeprefix("OF"), norm(r["model_ref"])
        production_counts["candidatos_por_of_referencia_" + str(len(idx[pid]))] += 1
        origin = (r["matched_plan_key"] or "").rsplit(":plan:", 1)[0]
        production_counts["snapshot_origem_retido" if origin in retained_snapshots else "snapshot_origem_nao_retido"] += 1
        p = by_row.get(int(r["matched_plan_key"].rsplit(":", 1)[-1])) if r["matched_plan_key"] else None
        if p and identity(p) == pid:
            production_counts["linha_mesmo_numero_mesma_identidade"] += 1
            actual = machine_alias.get(r["machine"], r["machine"])
            transitions[(p["row_data"].get("Máquina Corte"), actual)] += 1
        by_sheet[r["sheet_uid"]].append(r)
    result["producao"] = {"registos": len(prod), "folhas": len(by_sheet), "contagens": dict(production_counts),
                            "maquina_atual_vs_registo": [{"maquina_corte_fonte": k[0], "maquina_registada": k[1], "registos": v}
                                                        for k, v in transitions.items()]}
    sheets_hours = []
    for uid, rows in by_sheet.items():
        hours = {r["hours_worked"] for r in rows if r["hours_worked"] is not None}
        if not hours:
            continue
        area, missing = 0., 0
        for r in rows:
            hits = idx[(norm(r["production_order"]).removeprefix("OF"), norm(r["model_ref"]))]
            if len(hits) != 1:
                missing += 1
                continue
            d = hits[0]["row_data"]
            total, qty = num(d.get("Área de Seção de Corte [mm2]")), num(d.get("QTD [un,]"))
            if total is None or total <= 0 or qty is None or qty <= 0:
                missing += 1
                continue
            area += total / qty * r["quantity"]
        sheets_hours.append({"folha": uid, "data": rows[0]["sheet_date"], "maquina": rows[0]["machine"],
                             "horas_uma_vez_por_folha": sorted(hours), "linhas": len(rows),
                             "linhas_sem_area_valida": missing,
                             "horas_modelo_vanguard_9200": area / 9200 if not missing else None,
                             "nota": "Horas de folha; não são tempos medidos por referência."})
    result["folhas_com_horas"] = sheets_hours
    result["folhas_backup_por_estado"] = dict(C.Counter(r["status"] for r in inputs["factory_sheets"]))

    # Carga teórica sem datas atribuídas nem disponibilidade presumida.
    rates = {r["row_data"]["values"][1]: r["row_data"]["values"][2]
             for r in inputs["aux"] if r["sheet_name"] == "CapacidadeMáquinas" and 2 <= r["excel_row"] <= 12}
    hours_by_scope = {}
    detail = []
    for scope, rows in [("ativas_com_maquina_e_area", jobs), ("campos_basicos", subset)]:
        grouped = C.defaultdict(list)
        for r in rows:
            d = r["row_data"]
            m, total, qty = d.get("Máquina Corte"), num(d.get("Área de Seção de Corte [mm2]")), num(d.get("QTD [un,]"))
            rate = num(rates.get(m))
            if not m or not rate or total is None or total <= 0 or not qty:
                continue
            factor = 3 if m == "Serrote Fita Thomas IS639 Pav.1" and qty > 50 else 1
            h = total / qty * r["canonical_remaining"] / rate / factor
            grouped[m].append((r, h))
            if scope == "ativas_com_maquina_e_area":
                detail.append(describe(r) | {"maquina": m, "horas_historicas_sem_preparacao": round(h, 5),
                                             "qualidade": d.get("Qual."), "entrega_cpis": context(r).get("cpis_delivery_date"),
                                             "data_corte": r["cut_date"], "material_confirmado": False})
        hours_by_scope[scope] = [{"maquina": m, "linhas": len(rs), "horas": sum(h for r, h in rs),
                                  "linhas_acima_8h": sum(h > 8 for r, h in rs), "maior_linha_horas": max(h for r, h in rs),
                                  "horas_entrega_ate_18_set": sum(h for r, h in rs if (context(r).get("cpis_delivery_date") or "9999")[:10] <= "2026-09-18"),
                                  "horas_se_velocidade_metade": sum(h * 2 for r, h in rs),
                                  "horas_se_velocidade_dobro": sum(h / 2 for r, h in rs)}
                                 for m, rs in grouped.items()]
    export_csv(args.saida / "carga-teorica-nao-calendarizada.csv", sorted(detail, key=lambda r: -r["horas_historicas_sem_preparacao"]))
    result["carga_teorica"] = hours_by_scope
    result["carga_teorica_nota"] = "Capacidades 11/11/2024 e fator Thomas do Excel. Sem preparação, stock, turnos ou tempos medidos. Cenários de velocidade não são intervalos de confiança."
    (args.saida / "resultados-aprofundamento.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"universos": result["universos"], "geometria": result["validacao_geometria_com_AH"],
                      "grupos_qualidade": len(grade_csv), "sugestoes_maquina": len(suggestions),
                      "operacoes_abocardar": len(aboc), "alteracoes": dict(delta_counts)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
