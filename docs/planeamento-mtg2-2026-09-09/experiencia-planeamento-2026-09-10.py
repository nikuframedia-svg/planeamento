"""Cenário offline de planeamento MEBA; não publica ordens nem altera fontes.

Dados: plan.json do snapshot mtg2_aa2d59af81541c37.
Hipóteses para testar o mecanismo, não parâmetros operacionais confirmados:
37,5 h/semana (5 x 7,5), arranque 14/09, 20 min por mudança de família,
capacidade histórica de 48 024 mm²/h, sem verificação de matéria-prima.
Família = tipo/perfil/qualidade; compatibilidade técnica não é demonstrada.
"""

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path


def family(row):
    return (row["material_type"], row["profile_type"], row["row_data"]["Qual."])


def cut_date(row):
    return (row.get("cut_date") or "9999")[:10]


def date_after_work(hours, day_hours=7.5, lost_first_day=False):
    day = dt.date(2026, 9, 14)
    if lost_first_day:
        day += dt.timedelta(days=1)
    # Inteiros exatos terminam no dia anterior, não às 00h do seguinte.
    days = max(0, math.ceil((hours - 1e-9) / day_hours) - 1)
    while days:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            days -= 1
    return day.isoformat()


def schedule(rows, setup_minutes=20, speed=1.0, lost_first_day=False):
    time = 0.0
    previous = None
    result = []
    for r in rows:
        d = r["row_data"]
        group = family(r)
        setup = setup_minutes / 60 if group != previous else 0
        process = (d["Área de Seção de Corte [mm2]"] / d["QTD [un,]"]
                   * r["canonical_remaining"] / 48024 / speed)
        finish = time + setup + process
        result.append({
            "linha_excel": r["excel_row"], "of": r["production_order_no"],
            "referencia": r["component_ref"], "perfil": r["profile_type"],
            "comprimento_mm": r["length_mm"], "qualidade": d["Qual."],
            "data_corte_importada": cut_date(r), "picking_importado": d.get("Picking"),
            "data_cpis": r["order_context"].get("cpis_delivery_date"),
            "quantidade_pendente": r["canonical_remaining"],
            "preparacao_h_hipotese": setup, "execucao_h_historica": process,
            "inicio_h_util": time, "fim_h_util": finish,
            "dia_conclusao_cenario": date_after_work(finish, lost_first_day=lost_first_day),
        })
        time = finish
        previous = group
    # Verificações do mecanismo: conservação e sequência sem sobreposição.
    assert len(result) == len(rows)
    assert len({r["linha_excel"] for r in result}) == len(rows)
    assert sum(r["quantidade_pendente"] for r in result) == sum(r["canonical_remaining"] for r in rows)
    assert all(r["fim_h_util"] > r["inicio_h_util"] for r in result)
    assert all(math.isclose(a["fim_h_util"], b["inicio_h_util"]) for a, b in zip(result, result[1:]))
    return result


def summary(rows):
    return {
        "linhas": len(rows), "of": len({r["of"] for r in rows}),
        "quantidade_pendente": sum(r["quantidade_pendente"] for r in rows),
        "preparacoes": sum(r["preparacao_h_hipotese"] > 0 for r in rows),
        "horas_preparacao_hipotese": sum(r["preparacao_h_hipotese"] for r in rows),
        "horas_execucao_historica": sum(r["execucao_h_historica"] for r in rows),
        "horas_total_cenario": rows[-1]["fim_h_util"],
        "semanas_equivalentes_37_5h": rows[-1]["fim_h_util"] / 37.5,
        "dia_fim_cenario": rows[-1]["dia_conclusao_cenario"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", type=Path, required=True)
    parser.add_argument("--saida", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    plan = json.loads(args.dados.read_text())
    active = [r for r in plan if r["remaining_valid"]
              and (r["canonical_remaining"] or 0) > 0 and not r["closed_x"]
              and (r.get("order_context") or {}).get("cpis_status") in {"Em Produção", "Em Aberto"}]
    meba = [r for r in active if r["row_data"].get("Máquina Corte") == "Serrote MEBA IS381 Pav 3"]
    calculable = [r for r in meba if r["row_data"].get("Qual.")
                  and (r["row_data"].get("Área de Seção de Corte [mm2]") or 0) > 0
                  and (r["row_data"].get("QTD [un,]") or 0) > 0
                  and r["row_data"].get("_profile_fully_dimensioned")]
    # A: datas de corte importadas; ordem estável por OF e linha dentro da data.
    by_order = sorted(calculable, key=lambda r: (cut_date(r), r["production_order_no"], r["excel_row"]))
    # B: a mesma prioridade de data, com famílias contíguas dentro dessa data.
    grouped = sorted(calculable, key=lambda r: (cut_date(r), family(r), r["production_order_no"], r["excel_row"]))
    assert {r["excel_row"] for r in by_order} == {r["excel_row"] for r in grouped}
    assert [cut_date(r) for r in by_order] == [cut_date(r) for r in grouped]
    scenarios = {
        "por_data_corte_e_of": schedule(by_order),
        "familias_dentro_da_mesma_data_corte": schedule(grouped),
        "familias_sem_preparacao": schedule(grouped, setup_minutes=0),
        "familias_velocidade_25pc_inferior": schedule(grouped, speed=.75),
        "familias_velocidade_25pc_superior": schedule(grouped, speed=1.25),
        "familias_perda_primeiro_turno": schedule(grouped, lost_first_day=True),
    }
    baseline = {r["linha_excel"]: r for r in scenarios["por_data_corte_e_of"]}
    line_effects = []
    order_ends = collections.defaultdict(lambda: [0.0, 0.0])
    for r in scenarios["familias_dentro_da_mesma_data_corte"]:
        old = baseline[r["linha_excel"]]
        delta = r["fim_h_util"] - old["fim_h_util"]
        line_effects.append({"linha": r["linha_excel"], "of": r["of"], "diferenca_fim_h_uteis": delta})
        order_ends[r["of"]][0] = max(order_ends[r["of"]][0], old["fim_h_util"])
        order_ends[r["of"]][1] = max(order_ends[r["of"]][1], r["fim_h_util"])
    def effect(delta):
        return "igual" if abs(delta) < 1e-7 else ("mais_tarde" if delta > 0 else "mais_cedo")
    aux_path = args.dados.parent / "aux-workbook.json"
    aux = json.loads(aux_path.read_text())
    picking = {str(int(values[1])): values[2] for _, values in aux["Picking"][1:]}
    assert len(picking) == len(aux["Picking"]) - 1
    positive = lambda value: isinstance(value, (float, int)) and value > 0
    source_week = lambda r: picking.get(r["production_order_no"].removeprefix("OF"))
    recovered = [r for r in active if not positive(r["row_data"].get("Picking")) and positive(source_week(r))]
    conflicts = [r for r in active if positive(r["row_data"].get("Picking"))
                 and positive(source_week(r)) and r["row_data"]["Picking"] != source_week(r)]
    counts = collections.Counter((r["row_data"].get("Máquina Corte") or "Sem máquina") for r in active)
    result = {
        "snapshot": plan[0]["snapshot_id"],
        "sha256_extrato": hashlib.sha256(args.dados.read_bytes()).hexdigest(),
        "sha256_folhas_auxiliares": hashlib.sha256(aux_path.read_bytes()).hexdigest(),
        "sha256_ficheiro_drive_verificado": "aa2d59af81541c37165b4d611ed698dad97bcbc9b7cf74ca3db8ace7cf572968",
        "natureza": "Experiência offline, sem validade de ordem de produção ou promessa de prazo.",
        "hipoteses": {
            "inicio": "2026-09-14", "dias": "segunda a sexta", "horas_uteis_dia": 7.5,
            "feriados_e_operadores": "não modelados", "mm2_h": 48024,
            "origem_taxa": "CapacidadeMáquinas!C3, cabeçalho 11/11/2024",
            "minutos_preparacao_por_familia": 20, "familia": "tipo + perfil + qualidade",
            "restricao_prioridade": "conservar grupos de Data Corte; datas não revalidadas",
            "materia_prima": "não verificada; stock/SAP fora da primeira fase",
            "abocardar": "excluído; nenhuma passagem de parcelas inferida",
            "quantidades": "saldos importados; não são novos registos",
            "maquinas": "manter atribuição MEBA existente; não testar substituições",
            "conclusao": "das linhas MEBA incluídas; não de toda a obra nem da Produção",
        },
        "universo": {"linhas_ativas": len(active), "of_ativas": len({r["production_order_no"] for r in active}),
                     "pecas_pendentes": sum(r["canonical_remaining"] for r in active),
                     "maquinas": dict(counts), "meba_linhas": len(meba), "meba_calculaveis": len(calculable)},
        "excluidas_meba": [{"linha": r["excel_row"], "of": r["production_order_no"], "ref": r["component_ref"]}
                           for r in meba if r not in calculable],
        "cenarios": {name: summary(rows) for name, rows in scenarios.items()},
        "efeitos_agrupamento": {
            "linhas": dict(collections.Counter(effect(r["diferenca_fim_h_uteis"]) for r in line_effects)),
            "ultima_linha_meba_incluida_por_of": dict(collections.Counter(effect(v[1] - v[0]) for v in order_ends.values())),
            "of_com_ultima_linha_meba_incluida_mais_tarde": [{"of": of, "diferenca_h": v[1] - v[0]}
                                                            for of, v in order_ends.items() if effect(v[1] - v[0]) == "mais_tarde"],
            "nota": "Reduzir preparações não melhora todas as entregas. Picking não foi otimizado.",
        },
        "picking": {
            "of_unicas_na_fonte": len(picking),
            "linhas_ativas_com_semana_no_plano": sum(positive(r["row_data"].get("Picking")) for r in active),
            "linhas_ativas_com_semana_na_fonte": sum(positive(source_week(r)) for r in active),
            "linhas_recuperadas": len(recovered), "of_recuperadas": len({r["production_order_no"] for r in recovered}),
            "conflitos_entre_semanas_positivas": len(conflicts),
            "distribuicao_semanas_fonte": dict(collections.Counter(source_week(r) for r in active if positive(source_week(r)))),
            "nota": "Ano e dia limite não definidos pela simples semana. Join OF reproduz relação existente na folha.",
        },
        "verificacoes": ["mesmas linhas e quantidades", "sem sobreposição em tempo útil",
                         "grupos de Data Corte preservados", "perda de turno desloca calendário, não aumenta trabalho"],
    }
    args.saida.mkdir(parents=True, exist_ok=True)
    (args.saida / "experiencia-planeamento-2026-09-10.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for name in ["por_data_corte_e_of", "familias_dentro_da_mesma_data_corte"]:
        with (args.saida / ("cenario-meba-" + name + ".csv")).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(scenarios[name][0]))
            writer.writeheader()
            writer.writerows(scenarios[name])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
