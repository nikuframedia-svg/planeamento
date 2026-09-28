"""Leitura por fases com checkpoints; reconciliação aritmética fora do modelo."""
from __future__ import annotations

import json
import inspect
import logging
import re
import threading

from . import DossierError, cpis, pdf, store, locking
from .models import (Extraction, Inventory, InventoryReading, PageLink, Piece, WorkItemVerification, FIELD_LABELS,
                     difference_decision_fingerprint, filename_order, fingerprint,
                     order_number, reading_decision_fingerprint, ref_key)
from .provider import VisionProvider, configured, read_config, native_schema_supported, structured_tool_supported

log = logging.getLogger(__name__)
PIPELINE_VERSION = "dossier-pipeline-v3-flexible-items"
IMAGE_PREPARATION_VERSION = "table-regions-v4-oriented"
INVENTORY_PROMPT = """Faz o inventário de TODAS as páginas apresentadas, exatamente uma entrada por página.
orientation descreve como o conteúdo deve ser rodado para ficar direito: upright quando
já está direito, clockwise/counterclockwise/upside_down quando a rotação é inequívoca,
e unknown quando não for possível decidir. A forma da página, por si só, não decide.
Identifica OF e OV só quando explícitas. references contém as referências que identificam
o próprio desenho/cartucho ou o seu ficheiro DWG, com aliases literalmente impressos.
sales_orders contém todas as OV explicitamente enumeradas; sales_order pode conservar a
OV principal quando exista. Não escolhas uma OV apenas por ser a primeira da lista.
Não listar todas as referências de uma lista de materiais ou tabela de variantes.
Numa matriz de distribuição, routes contém EXCLUSIVAMENTE as referências cuja linha
tem uma marca na coluna VANGUARD ou SERROTE. Cada cruz tem de ser associada à coluna
e linha certas, incluindo cabeçalhos verticais. Não incluir guilhotina, plasma ou laser.
As linhas de documentos administrativos (por exemplo, a própria lista de distribuição)
não são peças nem desenhos de fabrico: não geram routes, mesmo quando têm cruzes.
Uma referência marcada nas duas colunas gera duas entradas, sem inferir uma sequência.
quantity só se existir uma quantidade de fabrico explícita para essa referência.
Não confundir número de desenho, posição, variante ou prioridade com quantidade.
Se a distribuição não for legível, regista a dúvida em warnings; não adivinhes.
Uma página sem matriz tem routes vazio. kind=distribution quando há matriz e kind=cut_list
quando contém uma lista de corte. Em work_items regista necessidades de fabrico claramente
selecionadas que não dependem de uma matriz: linhas preenchidas de uma lista de corte e
desenhos de peça com quantidade explícita, como A FABRICAR. Não registes linhas de modelo
vazias, todas as variantes de um catálogo, listas de materiais sem seleção, capas sem uma
peça selecionada ou a quantidade do produto final. source_id identifica de forma estável
o bloco/linha/posição no documento e não inclui quantidade nem máquina. reference é a
referência da peça ou desenho quando estiver explícita; usa null quando não estiver, sem
copiar S.L, uma norma, o caminho do ficheiro ou uma posição numérica como referência.
aliases conserva nomes de desenho/DWG relacionados. selection=uncertain apenas quando há
uma marca/linha de fabrico real mas a associação concreta está ilegível.
Não existir uma coluna Vanguard/Serrote, ou não haver quantidade por referência no
índice, não é por si só uma dúvida: omite esse grupo ou usa quantity=null, respetivamente.
A quantidade pode ser lida depois no desenho. warnings contém apenas dúvidas reais
de leitura ou associação, não observações sobre campos opcionais ausentes.
Não extraias ainda todos os campos técnicos. Só inventário, distribuição e seleção dos
itens de trabalho.
"""
EXTRACTION_PROMPT = """Extrai as linhas de trabalho correspondentes APENAS à seleção indicada.
Lê a página do índice e os desenhos fornecidos. Uma tabela com várias variantes não
significa encomendar todas: extrai apenas as linhas selecionadas por quantidade/marca.
Quando a seleção vem de work_item, lê somente a linha preenchida da lista de corte ou a
peça com quantidade A FABRICAR. A quantidade de um produto na capa não substitui nem
multiplica a quantidade da peça. Uma linha vazia do formulário não é uma necessidade.
component_ref é a referência da peça/variante selecionada; drawing_ref é a do cartucho;
drawing_revision é a revisão literal do cartucho; variant descreve a variante quando
aplicável. Preserva diferenças entre estas referências e não juntes revisão ao número.
A referência da seleção serve para localizar o desenho e já fica guardada como index_ref.
Quando a tabela apresenta uma referência de fabrico na linha selecionada, essa é
component_ref; não voltes a copiar a referência do índice nem a posição numérica Ref.
Num desenho de uma peça única, sem tabela de variantes nem referência autónoma de peça,
o número do desenho no cartucho identifica a própria peça: copia-o para component_ref
e drawing_ref, com evidência do cartucho. Não deixes component_ref vazio nesse caso.
material_type classifica a família explicitada pela designação e geometria nominal;
Tubo com símbolo Ø e espessura é Tubo redondo. profile contém a secção nominal,
sem o comprimento de corte; preserva a descrição completa em material_description.
Quantidade por conjunto e total NÃO se somam; dois desenhos com a mesma geometria
podem ser peças distintas. Uma revisão repetida não é outra quantidade de fabrico.
O comprimento em mm vem da cota de corte explicitada, não de escala ou medição da imagem.
Não transformes cotas angulares ou chanfros em ângulo da serra sem indicação inequívoca.
Uma nota 4 × 45° descreve a dimensão e o ângulo de um chanfro; o 4 não é uma
contagem de quatro operações. R80 só representa diâmetro 80 quando a própria
designação/geometria identifica uma secção redonda, nunca por uma regra geral de raio.
Não deduzas dimensões de catálogos de memória. Copia o perfil tal como está escrito.
operations contém indicações expressas (furação, recorte, abocardar, chanfro, etc.).
abocardar, chanfro e ponteira usam X quando a operação é explicitamente pedida,
- só quando a ausência é explícita, e null quando não está indicada. Guarda a evidência.
evidence associa cada campo a {page,text}, com a transcrição curta do valor no documento.
Quando conseguires localizar o valor, region usa [x1,y1,x2,y2] entre 0 e 1 na
página original. source=derived e derivation identificam apenas uma soma ou
decomposição visível (por exemplo 40+40); não apresentes isso como cota direta.
Exige evidência para referência, desenho, material, perfil, qualidade, quantidade e comprimento.
Regista a decomposição que justifica uma quantidade quando seja necessário multiplicar.
Não preenches quantidades realizadas, máquinas concretas de serrote, tempos nem datas.
Se não puderes selecionar uma variante ou confirmar um valor, usa null e warnings.
warnings contém apenas dúvidas reais que precisam de conferência. A caixa geral de
quantidade vazia não é uma dúvida se a quantidade está explícita na linha selecionada.
Não escrevas em warnings uma justificação de leitura que já ficou em evidence ou notes,
nem a ausência normal de ângulo, abocardar, chanfro ou ponteira quando são opcionais.
"""


def _request(provider, uid, run_id, stage, item_key, prompt, schema, images=(), *,
             include_details=True, orientations=None):
    if hasattr(provider, "drain_attempts"):
        provider.drain_attempts()
    try:
        if isinstance(provider, VisionProvider):
            return provider.request(prompt, schema, images, include_details=include_details,
                                    orientations=orientations)
        return provider.request(prompt, schema, images)
    finally:
        if hasattr(provider, "drain_attempts"):
            for number, attempt in enumerate(provider.drain_attempts(), 1):
                store.record_attempt(run_id, uid, stage, item_key,
                    int(attempt.get("attempt") or number), attempt.get("status") or "unknown", attempt)


def _request_inventory(provider, prepared, *, uid, run_id):
    numbers = [number for number, _image, _text in prepared]
    images = [(number, image) for number, image, _text in prepared]
    texts = [f"Texto extraível da página {number} (pode conter erros de ordem):\n{text}"
             for number, _image, text in prepared if text.strip()]
    schema = InventoryReading if isinstance(provider, VisionProvider) else Inventory
    try:
        result = _request(provider, uid, run_id, "inventory", ",".join(map(str, numbers)),
            INVENTORY_PROMPT + "\nPáginas esperadas: " + str(numbers) + "\n" + "\n".join(texts),
            schema,
            images,
        )
        return _normalize_inventory(result)
    except DossierError as exc:
        if len(numbers) == 1 and exc.kind == "model_output_limit":
            compact = ("Lê apenas esta página e devolve uma entrada PageInventory. "
                "Identifica orientação, tipo de página, OF/OV explícitas e referências do cartucho. "
                "Se houver matriz, inclui somente as linhas marcadas em Vanguard ou Serrote. "
                "Sem matriz, inclui em work_items somente linhas de corte preenchidas ou desenhos com "
                "quantidade de fabrico explícita; ignora linhas vazias e quantidades do produto. Não expliques. "
                f"Página esperada: {numbers[0]}. " + " ".join(texts))
            try:
                result = _request(provider, uid, run_id, "inventory_compact_retry", numbers[0],
                                  compact, schema, images, include_details=False)
                return _normalize_inventory(result)
            except DossierError as retry:
                exc = retry
        label = "Página " if len(numbers) == 1 else "Páginas "
        raise DossierError(label + ", ".join(map(str, numbers)) + ": " + str(exc),
                           exc.status, kind=exc.kind) from None


def _normalize_inventory(result):
    pages = []
    for raw in result.get("pages", []):
        references = []
        for entry in raw.get("references", []):
            if isinstance(entry, str):
                references.append(entry)
            elif isinstance(entry, dict):
                references.extend([entry.get("reference"), *entry.get("aliases", [])])
        references = list(dict.fromkeys(str(value).strip() for value in references
                                        if str(value or "").strip()))
        work_items = []
        for index, item in enumerate(raw.get("work_items", []), 1):
            source_type = item.get("source_type")
            if source_type is None:
                source_type = (raw["kind"] if raw["kind"] in ("cut_list", "drawing") else "table")
            source_id = str(item.get("source_id") or item.get("reference")
                            or f"pagina-{raw['page']}-item-{index}")
            evidence = item.get("evidence") or (
                f"Item de fabrico indicado no inventário: {item.get('reference') or source_id}"
                + (f", quantidade {item['quantity']}" if item.get("quantity") is not None else ""))
            work_items.append({"source_type": source_type, "source_id": source_id,
                "reference": item.get("reference"), "aliases": item.get("aliases", []),
                "quantity": item.get("quantity"), "machine_group": item.get("machine_group"),
                "evidence": evidence,
                "selection": item.get("selection") or ("explicit" if item.get("quantity") is not None else "uncertain")})
        pages.append({"page": raw["page"], "kind": raw["kind"],
            "orientation": raw.get("orientation", "unknown"),
            "production_order": raw.get("production_order") or raw.get("of"),
            "sales_order": raw.get("sales_order") or raw.get("ov"),
            "sales_orders": raw.get("sales_orders", []), "references": references,
            "routes": raw.get("routes", []), "work_items": work_items,
            "warnings": raw.get("warnings", [])})
    try:
        return Inventory.model_validate({"pages": pages}).model_dump()
    except ValueError:
        raise DossierError("O inventário não pôde ser normalizado para referências e itens de trabalho válidos.",
                           502, kind="model_output") from None


def _inventory_has_exact_pages(result, numbers):
    return sorted(page["page"] for page in result["pages"]) == numbers


def inventory_document(uid, provider, run_id, checkpoint_signature):
    document = store.get_document(uid)
    path = store.file_path(uid)
    done = store.checkpoints(uid, "inventory", input_fingerprint=checkpoint_signature)
    config = getattr(provider, "config", {})
    batch_size = 1 if config and structured_tool_supported(config) else 2
    failures = []
    for start in range(1, document["page_count"] + 1, batch_size):
        numbers = list(range(start, min(start + batch_size, document["page_count"] + 1)))
        pending = [number for number in numbers if str(number) not in done]
        if not pending:
            continue
        store.update_document(uid, status="indexing", progress=int(50 * (start - 1) / document["page_count"]),
                              progress_label=f"A identificar desenhos · páginas {pending[0]}–{pending[-1]} de {document['page_count']}")
        prepared = []
        for number in pending:
            image, text = pdf.page_data(path, number, size=2400)
            prepared.append((number, image, text))
        result = None
        try:
            result = _request_inventory(provider, prepared, uid=uid, run_id=run_id)
        except DossierError as exc:
            # Um lote maior pode exceder a capacidade de saída estruturada do
            # modelo. Só o decompor quando houve uma resposta concluída mas
            # inválida ou truncada pelo limite de saída; falhas de rede,
            # acesso e quota propagam-se. Nunca aceitar a saída truncada.
            if exc.kind not in ("model_output", "model_output_limit"):
                raise
            if len(pending) == 1:
                failures.append((pending[0], exc))
                continue
            log.warning("Saída estruturada inválida nas páginas %s; a repetir cada página isoladamente", pending)
        if result is None or not _inventory_has_exact_pages(result, pending):
            if len(pending) == 1:
                failures.append((pending[0], DossierError(
                    f"O modelo não identificou corretamente a página {pending[0]}, mesmo na releitura isolada. "
                    "A leitura foi interrompida sem guardar esse resultado.", 502, kind="model_output")))
                continue
            log.warning("Inventário inconsistente nas páginas %s; a repetir cada página isoladamente", pending)
            for item in prepared:
                number = item[0]
                store.update_document(
                    uid,
                    status="indexing",
                    progress=int(50 * (number - 1) / document["page_count"]),
                    progress_label=f"A corrigir inventário · página {number} de {document['page_count']}",
                )
                try:
                    single = _request_inventory(provider, [item], uid=uid, run_id=run_id)
                except DossierError as exc:
                    if exc.kind not in ("model_output", "model_output_limit"):
                        raise
                    failures.append((number, exc))
                    continue
                if not _inventory_has_exact_pages(single, [number]):
                    failures.append((number, DossierError(
                        f"O modelo não identificou corretamente a página {number}, mesmo na releitura isolada. "
                        "A leitura foi interrompida sem guardar esse resultado.", 502, kind="model_output")))
                    continue
                page = single["pages"][0]
                store.checkpoint(uid, "inventory", number, page, run_id=run_id,
                                 input_fingerprint=checkpoint_signature)
                done[str(number)] = page
            continue
        for page in result["pages"]:
            store.checkpoint(uid, "inventory", page["page"], page, run_id=run_id,
                             input_fingerprint=checkpoint_signature)
            done[str(page["page"])] = page
    if failures:
        pages = ", ".join(str(number) for number, _exc in failures)
        first = failures[0][1]
        raise DossierError(
            f"As páginas {pages} ficaram por concluir; as restantes páginas foram guardadas. {first}",
            first.status, kind=first.kind) from None
    return [done[str(p)] for p in range(1, document["page_count"] + 1)]


def collect_routes(inventory):
    routes = {}
    for page in inventory:
        for route in page["routes"]:
            key = fingerprint([ref_key(route["reference"]), route["machine_group"]])
            entry = {**route, "page": page["page"], "key": key}
            if key in routes:
                old = routes[key]
                if old.get("quantity") != route.get("quantity") and route.get("quantity") is not None:
                    old["conflict"] = "A quantidade desta referência difere entre índices/revisões."
            else:
                routes[key] = entry
    return list(routes.values())


def collect_selections(inventory):
    """Prefer an explicit distribution matrix, otherwise use selected work items."""
    routes = collect_routes(inventory)
    if routes:
        return [{**route, "selection": {"source": "distribution", "page": route["page"],
                "evidence": route["evidence"], "reference": route["reference"]}}
                for route in routes]
    selected = {}
    by_reference = {}
    for page in inventory:
        for item in page.get("work_items", []):
            page_references = [str(value).strip() for value in page.get("references", []) if str(value).strip()]
            inferred_reference = (page_references[0] if not item.get("reference")
                                  and len(page.get("work_items", [])) == 1 and page_references else "")
            reference = str(item.get("reference") or inferred_reference).strip()
            source_id = str(item.get("source_id") or "").strip()
            normalized = ref_key(reference)
            existing = by_reference.get(normalized) if normalized else None
            if existing and existing["selection"]["source"] != item.get("source_type"):
                existing.setdefault("related_item_pages", []).append(page["page"])
                existing["related_item_pages"] = list(dict.fromkeys(existing["related_item_pages"]))
                existing["aliases"] = list(dict.fromkeys([*existing.get("aliases", []),
                                                          *item.get("aliases", [])]))
                existing["selection"].setdefault("related", []).append({
                    "source": item.get("source_type"), "page": page["page"],
                    "source_id": source_id, "evidence": item["evidence"]})
                if existing.get("quantity") is None and item.get("quantity") is not None:
                    existing["quantity"] = item["quantity"]
                continue
            key = fingerprint(["work_item", normalized] if normalized and not existing else
                              ["work_item", page["page"], item.get("source_type"),
                               ref_key(source_id), normalized])
            route = {
                "reference": reference or f"item {source_id} (página {page['page']})",
                "machine_group": item.get("machine_group") or "Por atribuir",
                "quantity": item.get("quantity"), "evidence": item["evidence"],
                "page": page["page"], "key": key, "work_item": True,
                "aliases": list(dict.fromkeys([*item.get("aliases", []),
                                               *(page_references[1:] if inferred_reference else [])])),
                "reference_missing": not bool(reference),
                "selection": {"source": item["source_type"], "page": page["page"],
                    "source_id": source_id, "status": item.get("selection", "explicit"),
                    "evidence": item["evidence"], "reference": item.get("reference"),
                    "aliases": item.get("aliases", [])},
            }
            if key not in selected:
                selected[key] = route
                if normalized and normalized not in by_reference:
                    by_reference[normalized] = route
    return list(selected.values())


def resolve_pages(uid, run_id, route, inventory, provider) -> dict:
    allowed_kinds = ("cut_list", "drawing", "assembly")
    lookup = {ref_key(route.get("reference")),
              *(ref_key(value) for value in route.get("aliases", []))} - {""}
    matching = [p for p in inventory if p["kind"] in allowed_kinds
                and any(ref_key(r) in lookup for r in p["references"])]
    if route.get("work_item"):
        own = route["page"]
        support = list(route.get("related_item_pages", []))
        support.extend(p["page"] for p in matching if p["page"] != own)
        if route.get("reference_missing"):
            support.extend(p["page"] for p in inventory
                           if p["kind"] in ("drawing", "assembly") and p["page"] != own)
        support = list(dict.fromkeys(support))[:5]
        return {"pages": [own], "support_pages": support,
                "uncertain": route["selection"].get("status") == "uncertain",
                "explanation": "Item de fabrico selecionado diretamente no documento; páginas relacionadas usadas como apoio."}
    if matching:
        # Uma lista de materiais pode ser classificada como drawing e enumerar
        # dezenas de componentes em references. O desenho da peça é a página
        # mais específica: contém menos referências físicas distintas. Aliases
        # tipográficos da mesma referência contam uma única vez.
        specificity = {
            p["page"]: len({key for value in p["references"] if (key := ref_key(value))})
            for p in matching
        }
        best = min(specificity.values())
        primary = [p["page"] for p in matching if specificity[p["page"]] == best]
        support = [p["page"] for p in matching if p["page"] not in primary]
        if len(primary) == 1:
            return {"pages": primary, "support_pages": support[:5], "uncertain": False,
                    "explanation": "Referência coincidente na página de desenho mais específica; listas de conjunto usadas apenas como apoio."}
        return {"pages": primary[:6], "support_pages": support[:max(0, 6-len(primary))], "uncertain": True,
                "explanation": "A referência aparece em vários desenhos igualmente específicos; confirmar revisões e quantidades."}
    result = _request(provider, uid, run_id, "link", route["key"],
        "Relaciona a referência do índice com as páginas de desenho deste inventário. "
        "Usa apenas referências e aliases presentes. Se não houver correspondência defensável, devolve pages vazio. "
        "Nunca escolhes a página apenas pela proximidade ao índice.\nSeleção: " + json.dumps(route, ensure_ascii=False)
        + "\nInventário: " + json.dumps([{k: p[k] for k in ("page", "kind", "references")} for p in inventory], ensure_ascii=False), PageLink)
    allowed = {p["page"] for p in inventory if p["kind"] in allowed_kinds}
    if len(set(result["pages"])) != len(result["pages"]) or not set(result["pages"]) <= allowed:
        raise DossierError("O modelo associou uma referência a páginas inválidas. A leitura não foi aceite.", 502)
    return {**result, "support_pages": [], "uncertain": True}


def extract_routes(uid, inventory, provider, run_id, checkpoint_signature):
    routes = collect_selections(inventory)
    issues = [cpis.issue(f"inventory_{p['page']}_{i}", f"Página {p['page']}: {w}")
              for p in inventory for i, w in enumerate(p["warnings"])]
    if not routes:
        issues.append(cpis.issue("no_work_items", "A leitura terminou, mas não encontrou linhas de fabrico selecionadas, uma matriz aplicável ou um desenho com quantidade explícita."))
    links = store.checkpoints(uid, "links", input_fingerprint=checkpoint_signature)
    extractions = store.checkpoints(uid, "extractions", input_fingerprint=checkpoint_signature)
    for index, route in enumerate(routes):
        store.update_document(uid, status="extracting", progress=50 + int(40 * index / max(len(routes), 1)),
            progress_label=f"A ler {route['reference']} · {index + 1} de {len(routes)} desenhos")
        link = links.get(route["key"])
        if link is None:
            link = resolve_pages(uid, run_id, route, inventory, provider)
            store.checkpoint(uid, "links", route["key"], link, run_id=run_id,
                             input_fingerprint=checkpoint_signature)
        if not link["pages"]:
            issues.append(cpis.issue("unresolved_" + route["key"], f"Não foi encontrado o desenho de {route['reference']} ({route['machine_group']})."))
            continue
        result = extractions.get(route["key"])
        if result is None:
            numbers = sorted(set([route["page"], *link["pages"], *link.get("support_pages", [])]))
            images = [(number, pdf.page_data(store.file_path(uid), number)[0]) for number in numbers]
            prompt = EXTRACTION_PROMPT + "\nSeleção: " + json.dumps(route, ensure_ascii=False)
            orientations = {p["page"]: p.get("orientation", "unknown") for p in inventory
                            if p["page"] in numbers}
            try:
                result = _request(provider, uid, run_id, "extraction", route["key"], prompt,
                                  Extraction, images, orientations=orientations)
            except DossierError as exc:
                if exc.kind != "model_output_limit":
                    raise
                compact = ("Extrai somente a peça ou variante correspondente a esta seleção. "
                    "Devolve os campos técnicos explícitos e evidência curta por campo; usa null no ilegível. "
                    "Não expliques raciocínio nem repitas dados. Seleção: " + json.dumps(route, ensure_ascii=False))
                result = _request(provider, uid, run_id, "extraction_compact_retry", route["key"],
                                  compact, Extraction, images, include_details=False,
                                  orientations=orientations)
            if (route.get("work_item") and route.get("selection", {}).get("source") == "cut_list"
                    and len(result.get("pieces", [])) == 1):
                checks = store.checkpoints(uid, "verifications", input_fingerprint=checkpoint_signature)
                verification = checks.get(route["key"])
                if verification is None:
                    verification = _request(provider, uid, run_id, "work_item_verification", route["key"],
                        "Relê apenas a linha de corte selecionada. Transcreve os algarismos manuscritos "
                        "de quantidade e comprimento exatamente como aparecem; distingue com atenção 7 de 9. "
                        "Não uses conversões, catálogo, plano ou valores de outras páginas. Usa null no ilegível "
                        "e inclui evidência curta para cada valor. Seleção: " + json.dumps(route, ensure_ascii=False),
                        WorkItemVerification, images, orientations=orientations)
                    initial = {field: result["pieces"][0].get(field)
                               for field in ("quantity_required", "length_mm")}
                    store.checkpoint(uid, "verifications", route["key"],
                        {"result": verification, "initial": initial}, run_id=run_id,
                        input_fingerprint=checkpoint_signature)
                else:
                    verification = verification["result"]
                for field in ("quantity_required", "length_mm"):
                    evidence = verification.get("evidence", {}).get(field)
                    if verification.get(field) is not None and evidence and evidence.get("page") in numbers:
                        result["pieces"][0][field] = verification[field]
                        result["pieces"][0].setdefault("evidence", {})[field] = evidence
            store.checkpoint(uid, "extractions", route["key"], result, run_id=run_id,
                             input_fingerprint=checkpoint_signature)
        if not result["pieces"]:
            issues.append(cpis.issue("empty_" + route["key"], f"A referência {route['reference']} está selecionada mas não produziu nenhuma linha."))
        for n, data in enumerate(result["pieces"]):
            value = dict(data)
            value["warnings"] = list(value.get("warnings", [])) + list(result["warnings"])
            if link["uncertain"]:
                value["warnings"].append(link["explanation"])
            if route.get("conflict"):
                value["warnings"].append(route["conflict"])
            total = sum(p["quantity_required"] or 0 for p in result["pieces"])
            if route["quantity"] is not None and total != route["quantity"]:
                value["warnings"].append(f"O índice indica {route['quantity']} unidades; as variantes extraídas somam {total}.")
            allowed_pages = {route["page"], *link["pages"], *link.get("support_pages", [])}
            for field, evidence in value["evidence"].items():
                if evidence["page"] not in allowed_pages:
                    value["warnings"].append(f"A evidência de {FIELD_LABELS.get(field, field)} aponta para uma página que não foi apresentada nesta leitura.")
            store.add_piece(uid, f"{route['key']}:{n}", route, link["pages"], value,
                            selection=route.get("selection", {}))
    return issues


def resolve_order(document, inventory):
    raw_orders = {str(page.get("production_order") or "").strip() for page in inventory
                  if str(page.get("production_order") or "").strip()}
    read_orders = {of for raw in raw_orders if (of := order_number(raw))}
    compound = {}
    for raw in raw_orders:
        match = re.fullmatch(r"\s*(?:OF[\s._-]*)?(\d{4,10})(/[^\s]+)\s*", raw, re.I)
        if match:
            compound["OF" + match[1]] = raw
    named = filename_order(document["filename"])
    issues = []
    if named:
        candidates = read_orders | set(compound)
        if candidates and candidates != {named}:
            issues.append(cpis.issue("of_disagreement", "A OF do nome do ficheiro difere da OF lida no documento. Confirma o número correto.", blocking=True))
        return named, issues
    if len(compound) == 1 and not read_orders:
        candidate, _raw = next(iter(compound.items()))
        return candidate, []
    if len(read_orders) == 1:
        return read_orders.pop(), issues
    return None, [cpis.issue("of_unresolved", "Não foi possível identificar uma única OF. Confirma o número do dossiê.", blocking=True)]


def route_quantity_state(pieces):
    groups = {}
    for piece in pieces:
        if piece["state"] not in ("excluded", "superseded"):
            groups.setdefault(piece["source_key"].rsplit(":", 1)[0], []).append(piece)
    return {key: {"quantity": sum(p["values"].get("quantity_required") or 0 for p in group),
                  "signature": fingerprint(sorted((p["id"], p["values"].get("quantity_required")) for p in group))}
            for key, group in groups.items()}


@store.guarded
def reconcile(uid, *, context_reader=None, replace_piece=None):
    default_context_reader = context_reader is None
    context_reader = context_reader or cpis.read_context
    document = store.get_document(uid)
    if not document["production_order"]:
        store.update_document(uid, status="review", progress=100, progress_label="Confirma a OF do dossiê")
        return
    references = sorted({value for piece in document["pieces"]
                         for value in (piece["values"].get("component_ref"),
                                       piece["values"].get("drawing_ref"), piece.get("index_ref"))
                         if value})
    accepts_references = "references" in inspect.signature(context_reader).parameters
    context = (context_reader(document["production_order"], references=references)
               if default_context_reader and accepts_references
               else context_reader(document["production_order"]))
    signature = document.get("model", {}).get("processing_signature")
    inventory = list(store.checkpoints(uid, "inventory", input_fingerprint=signature).values()) if signature else list(store.checkpoints(uid, "inventory").values())
    route_expectations = {r["key"]: r["quantity"] for r in collect_selections(inventory)
                          if r["quantity"] is not None}
    quantity_state = route_quantity_state(document["pieces"])
    ovs = set()
    for page in inventory:
        values = [page.get("sales_order"), *page.get("sales_orders", [])]
        for value in values:
            ovs.update("OV" + match for match in re.findall(r"(?:OV[\s._-]*)?(\d{4,10})", str(value or ""), re.I))
    known_ovs = set(context.get('sales_orders') or [context.get('sales_order')])
    if ovs and not ovs.intersection(known_ovs):
        context["issues"].append(cpis.issue("ov_disagreement", "A OV lida no PDF não corresponde à OV desta OF no CPIS.", blocking=True))
    context["document_identifiers"] = {
        "production_orders": sorted({str(p.get("production_order") or "").strip()
                                     for p in inventory if p.get("production_order")}),
        "sales_orders": sorted(ovs),
    }
    document_issues = list(document["issues"])
    observed_orders = context["document_identifiers"]["production_orders"]
    resolved_order, identifier_issues = resolve_order(document, inventory)
    coherent_compound_order = (
        bool(observed_orders)
        and resolved_order == document["production_order"]
        and not identifier_issues
        and context.get("production_order") == document["production_order"]
    )
    if coherent_compound_order:
        # Older contracts treated a harmless suffix (for example OF260221/35)
        # as an unresolved qualifier. Keep the literal identifiers in context,
        # but remove that obsolete question once file, PDF and CPIS agree.
        document_issues = [problem for problem in document_issues if problem.get("code") != "of_qualifier"]
    any_issues = bool(document_issues or context["issues"])
    identities = {}
    for piece in document["pieces"]:
        if piece["state"] in ("superseded", "excluded"):
            continue
        key = (ref_key(piece["values"].get("component_ref")),
               ref_key(piece["values"].get("identity_discriminator")))
        identities.setdefault(key, []).append(piece["id"])
    for piece in document["pieces"]:
        if piece["state"] in ("superseded", "excluded"):
            continue
        problems, match = cpis.assess(piece, context, document["page_count"])
        route_key = piece["source_key"].rsplit(":", 1)[0]
        total = quantity_state.get(route_key)
        if total and route_key in route_expectations and total["quantity"] != route_expectations[route_key]:
            acknowledged = any(p.get("reviewed", {}).get("route_total") == total["signature"]
                               for p in document["pieces"] if p["state"] not in ("excluded", "superseded"))
            if not acknowledged:
                problems.append(cpis.issue("route_total", f"Depois das correções, esta referência soma {total['quantity']} unidades; o índice indica {route_expectations[route_key]}. Confirma o total no desenho.", field="quantity_required"))
        key = (ref_key(piece["values"].get("component_ref")),
               ref_key(piece["values"].get("identity_discriminator")))
        if len(identities[key]) > 1:
            problems.append(cpis.issue("duplicate_piece", "Esta referência foi extraída mais do que uma vez no dossiê. Confirma as variantes.", field="component_ref"))
        same_physical = [other for other in document["pieces"] if other["state"] not in ("superseded", "excluded")
                         and ref_key(other["values"].get("component_ref")) == key[0]
                         and ref_key(other["values"].get("identity_discriminator")) == key[1]]
        concrete_groups = {other["machine_group"] for other in same_physical
                           if other["machine_group"] in ("Vanguard", "Serrote")}
        if len(concrete_groups) > 1:
            problems.append(cpis.issue("dual_distribution", "A mesma peça está marcada para Vanguard e serrote. Confirma a distribuição para evitar duplicar a quantidade.", blocking=True))
        if document_issues:
            problems.append(cpis.issue("document_review", "O dossiê tem dúvidas de distribuição ou identificação por resolver."))
        state = "blocked" if any(p["blocking"] for p in problems) else "review" if problems else "ready"
        if not problems:
            registered = store.register_need(piece, document["production_order"], replace=piece["id"] == replace_piece)
            if registered == "revision_conflict":
                problems.append(cpis.issue("revision_conflict", "Já existe outra versão desta peça preparada a partir de um PDF. Confirma se esta a substitui."))
                state = "review"
            elif registered == "duplicate":
                state = "duplicate"
            elif match["kind"] == "existing":
                state = "existing"
        any_issues |= bool(problems)
        store.save_assessment(piece["id"], problems, match, state)
    store.update_document(uid, context=context, issues=document_issues,
                          status="review" if any_issues else "ready", progress=100,
                          progress_label="Há dados a confirmar" if any_issues else "Linhas preparadas", error=None)


@store.guarded
def process_document(uid, *, provider=None, context_reader=None):
    provider = provider or VisionProvider()
    config = getattr(provider, "config", {})
    document = store.get_document(uid)
    public_config = {k: config.get(k) for k in (
        "base_url", "model", "api_format", "reasoning_effort", "max_tokens", "timeout_s")}
    run_signature = fingerprint({"pdf": document["sha256"], "pipeline": PIPELINE_VERSION,
        "inventory_prompt": fingerprint(INVENTORY_PROMPT), "extraction_prompt": fingerprint(EXTRACTION_PROMPT),
        "image_preparation": IMAGE_PREPARATION_VERSION, "schema": fingerprint({
            "inventory_provider": InventoryReading.model_json_schema(),
            "inventory_internal": Inventory.model_json_schema(), "extraction": Extraction.model_json_schema(),
            "verification": WorkItemVerification.model_json_schema()}),
        "provider": public_config})
    store.prepare_run(uid, run_signature)
    run_id = store.start_run(uid, run_signature, public_config)
    store.update_document(uid, error=None, model=public_config
        | {"image_preparation": IMAGE_PREPARATION_VERSION, "pipeline_version": PIPELINE_VERSION,
           "processing_signature": run_signature, "run_id": run_id,
           "native_json_schema": native_schema_supported(config) if config else False,
           "structured_tool": structured_tool_supported(config) if config else False})
    try:
        inventory = inventory_document(uid, provider, run_id, run_signature)
        problems = extract_routes(uid, inventory, provider, run_id, run_signature)
        document = store.get_document(uid)
        order, order_issues = resolve_order(document, inventory)
        decision = store.checkpoints(uid, "decisions").get("order")
        order_source = fingerprint(sorted(str(p.get("production_order") or "") for p in inventory))
        if decision and decision.get("source_fingerprint") == order_source:
            order, order_issues = decision["production_order"], []
        confirmed = store.checkpoints(uid, "decisions").get("document_issues", {}).get("confirmed", {})
        combined = problems + order_issues
        problems = [p for p in combined if confirmed.get(p["code"]) != fingerprint(p)]
        store.update_document(uid, status="matching", production_order=order, issues=problems,
                              progress=95, progress_label="A cruzar com o CPIS e o planeamento")
        reconcile(uid, context_reader=context_reader)
    except DossierError as exc:
        store.finish_run(run_id, status="failed", error_kind=exc.kind, error_message=exc)
        raise
    except Exception as exc:
        store.finish_run(run_id, status="failed", error_kind="internal", error_message=exc)
        raise
    else:
        store.finish_run(run_id, status="completed")


@store.guarded
def review_piece(uid, piece_id, payload):
    if not isinstance(payload, dict):
        raise DossierError("A correção não contém campos válidos.")
    document = store.get_document(uid)
    piece = next((p for p in document["pieces"] if p["id"] == piece_id), None)
    if not piece:
        raise DossierError("Linha não encontrada.", 404)
    actor = str(payload.get("actor") or "Interface de planeamento").strip()[:120] or "Interface de planeamento"
    changes = payload.get("values", {})
    if not isinstance(changes, dict) or set(changes) - set(FIELD_LABELS):
        raise DossierError("A correção contém campos que não podem ser alterados.")
    machine_group = payload.get("machine_group", piece["machine_group"])
    if machine_group not in ("Vanguard", "Serrote", "Por atribuir"):
        raise DossierError("Seleciona um grupo de máquina válido.")
    reason = str(payload.get("reason") or (
        "Campos e encaminhamento atualizados na interface." if changes or machine_group != piece["machine_group"]
        else "Decisão específica guardada na interface.")).strip()[:1000]
    try:
        values = Piece.model_validate({**piece["values"], **changes}).model_dump()
    except ValueError:
        raise DossierError("Confirma os valores: quantidades inteiras, dimensões positivas e campos válidos.") from None
    reviewed = dict(piece["reviewed"])
    decisions = {key: dict(value) for key, value in reviewed.get("decisions", {}).items()}
    for field in changes:
        decisions.setdefault(field, {})["reading"] = reading_decision_fingerprint(field, values, piece["raw"])
    if payload.get("confirm_reading") is True:
        for field in FIELD_LABELS:
            if values.get(field) not in (None, ""):
                decisions.setdefault(field, {})["reading"] = reading_decision_fingerprint(field, values, piece["raw"])
        reviewed["warning_fingerprint"] = fingerprint(values.get("warnings", []))
        projected = [{**p, "values": values} if p["id"] == piece_id else p for p in document["pieces"]]
        total = route_quantity_state(projected).get(piece["source_key"].rsplit(":", 1)[0])
        if total:
            reviewed["route_total"] = total["signature"]
    projected_piece = {**piece, "values": values, "machine_group": machine_group,
                       "reviewed": {**reviewed, "decisions": decisions}}
    _problems, projected_match = cpis.assess(projected_piece, document.get("context", {}), document["page_count"])
    if payload.get("use_pdf_values") is True:
        effective = projected_match.get("effective_values", values)
        for difference in projected_match.get("differences", []):
            field = difference["field"]
            decisions.setdefault(field, {})["difference"] = difference_decision_fingerprint(
                field, effective, difference.get("plan"), projected_match.get("source_plan_key"))
    if payload.get("confirm_chamfer_mapping") is True and values.get("chanfro") not in (None, ""):
        reviewed.setdefault("mappings", {})["chanfro"] = fingerprint({"field": "chanfro",
            "value": values.get("chanfro"), "operations": values.get("operations", []),
            "evidence": values.get("evidence", {}).get("chanfro")})
    reviewed["decisions"] = decisions
    reviewed.pop("fields", None)
    reviewed.pop("warnings", None)
    reviewed.pop("differences", None)
    store.update_piece(uid, piece_id, payload.get("revision"), values, reviewed,
                       machine_group, actor, reason)
    reconcile(uid, replace_piece=piece_id if payload.get("replace_revision") is True else None)
    return store.get_document(uid)


@store.guarded
def exclude_piece(uid, piece_id, payload):
    if not isinstance(payload, dict):
        raise DossierError("Pedido de exclusão inválido.")
    store.exclude(uid, piece_id, payload.get("revision"), str(payload.get("actor") or ""), str(payload.get("reason") or ""))
    reconcile(uid)
    return store.get_document(uid)


@store.guarded
def review_document(uid, payload):
    doc = store.get_document(uid)
    if not isinstance(payload, dict) or doc["status"] in ("queued", "indexing", "extracting", "matching"):
        raise DossierError("Aguarda que a leitura termine antes de conferir o dossiê.", 409)
    if payload.get("revision") != doc["revision"]:
        raise DossierError("O dossiê mudou. Atualiza a página antes de conferir.", 409)
    actor = str(payload.get("actor") or "Interface de planeamento").strip()[:120] or "Interface de planeamento"
    reason = str(payload.get("reason") or "Identificação e dúvidas selecionadas guardadas na interface.").strip()[:1000]
    of = order_number(payload.get("production_order") or doc["production_order"])
    if not of:
        raise DossierError("Indica uma OF válida.")
    codes = payload.get("confirmed_codes", [])
    allowed = {p["code"] for p in doc["issues"] if not p["code"].startswith(("unresolved_", "empty_", "no_work_items"))}
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes) or not set(codes) <= allowed:
        raise DossierError("Uma referência sem desenho ou sem linhas precisa de nova leitura; não pode ser ignorada.")
    confirmed = {p["code"]: fingerprint(p) for p in doc["issues"] if p["code"] in codes}
    inventory = list(store.checkpoints(uid, "inventory").values())
    order_source = fingerprint(sorted(str(p.get("production_order") or "") for p in inventory))
    # Atualizar a decisão deliberada (a extração original mantém-se imutável).
    with store.connect() as conn:
        for key, data in (("order", {"production_order": of, "source_fingerprint": order_source}),
                          ("document_issues", {"confirmed": confirmed})):
            conn.execute("INSERT INTO checkpoints(document_id,stage,item_key,data_json,created_at) VALUES (?,'decisions',?,?,?) "
                         "ON CONFLICT(document_id,stage,item_key) DO UPDATE SET data_json=excluded.data_json",
                         (uid, key, store.dump(data), store.now()))
        store.event(conn, uid, "document_reviewed", {"production_order": of, "codes": codes, "reason": reason}, actor=actor)
        conn.execute("DELETE FROM needs WHERE piece_id IN (SELECT id FROM pieces WHERE document_id=?)", (uid,))
    issues = [p for p in doc["issues"] if p["code"] not in set(codes) | {"of_disagreement", "of_unresolved"}]
    store.update_document(uid, production_order=of, issues=issues)
    reconcile(uid)
    return store.get_document(uid)


def start_worker():
    stop = threading.Event()

    def scan_input():
        from . import inbox
        while not stop.is_set():
            try:
                store.root().mkdir(parents=True, exist_ok=True)
                with (store.root() / "inbox.lock").open("a") as lock:
                    try:
                        locking.acquire(lock)
                    except BlockingIOError:
                        stop.wait(2)
                        continue
                    try:
                        inbox.scan()
                    finally:
                        locking.release(lock)
            except Exception:
                log.exception("Leitura da pasta de dossiês indisponível")
            stop.wait(15)

    def run():
        while not stop.is_set():
            try:
                store.root().mkdir(parents=True, exist_ok=True)
                with (store.root() / "worker.lock").open("a") as lock:
                    try:
                        locking.acquire(lock)
                    except BlockingIOError:
                        stop.wait(2)
                        continue
                    uid = store.next_job()
                    if uid:
                        if configured():
                            try:
                                process_document(uid)
                            except DossierError as exc:
                                store.update_document(uid, status="error", error=str(exc), progress_label="Leitura interrompida")
                            except Exception:
                                log.exception("Falha no processamento do dossiê %s", uid)
                                store.update_document(uid, status="error", error="O processamento foi interrompido. Os passos concluídos ficaram guardados.")
                        else:
                            store.update_document(uid, status="waiting_api", progress_label="À espera da API do modelo")
                    locking.release(lock)
                    if uid:
                        continue
            except Exception:
                log.exception("Fila de dossiês indisponível")
            stop.wait(2)

    thread = threading.Thread(target=run, name="dossier-worker", daemon=True)
    thread.start()
    threading.Thread(target=scan_input, name="dossier-inbox", daemon=True).start()
    return stop
