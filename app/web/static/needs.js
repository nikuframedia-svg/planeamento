// Vistas por família e capacidade (plano de 01/10/2026). Fica escondida se o servidor tiver o interruptor desligado.
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const API = "/planeamento/api/setor";
  const nf = new Intl.NumberFormat("pt-PT", {maximumFractionDigits: 1});
  const nf2 = new Intl.NumberFormat("pt-PT", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const pct = new Intl.NumberFormat("pt-PT", {style: "percent", maximumFractionDigits: 0});
  const SLOTS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7"];
  const state = {meta: null, families: new Map(), open: new Map(), selected: null, stamps: {}, table: false, last: null};
  const uuid = () => crypto.randomUUID();
  const day = v => v ? String(v).slice(0, 10).split("-").reverse().join("/") : "—";
  const hours = v => v == null ? "?" : nf2.format(v) + " h";

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v; else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v); else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c != null) node.append(c);
    return node;
  }
  async function call(path, body) {
    const response = await fetch(API + path, {method: body === undefined ? "GET" : "POST", cache: "no-store",
      headers: body === undefined ? {Accept: "application/json"} : {"Content-Type": "application/json", Accept: "application/json"},
      body: body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) { const e = Error(result.error || result.detail || `Erro ${response.status}`); e.status = response.status; throw e; }
    return result;
  }
  const say = (message, error = false) => { const n = $("notice"); if (n) { n.textContent = message; n.classList.toggle("error", error); } };
  const safe = fn => async (...a) => { try { await fn(...a); } catch (e) { say(e.message || "Não foi possível concluir.", true); } };

  // Colour follows the family, fixed for the session: the 7 largest known loads, then «Outras».
  function familyColor(name) {
    if (!name || name === "Sem família SKU") return "var(--none)";
    const slot = state.families.get(name);
    return slot === undefined ? "var(--other)" : `var(${SLOTS[slot]})`;
  }

  const areas = () => $("needs-areas").value === "both" ? ["perfis", "cantoneiras"] : [$("needs-areas").value];
  const selectedValues = id => [...$(id).selectedOptions].map(o => o.value);
  function dims() {
    const chosen = selectedValues("needs-dims");
    return chosen.length ? [...$("needs-dims").options].filter(o => o.selected).map(o => o.value) : null;
  }
  function filters() {
    const f = {};
    const family = selectedValues("needs-family"), machine = selectedValues("needs-machine"), set = selectedValues("needs-set");
    if (family.length) f.sku_family = family;
    if (machine.length) f.machine = machine;
    if (set.length) f.set = set;
    const flags = [...document.querySelectorAll("#needs-flags input:checked")].map(i => i.value);
    if (flags.length) f.flags = flags;
    if ($("needs-q").value.trim()) f.q = $("needs-q").value.trim();
    return f;
  }
  function query(path, extra = {}) {
    return {areas: areas(), preset: $("needs-preset").value, dims: dims(), path, filters: filters(),
            horizon_weeks: Number($("needs-horizon").value), sort: $("needs-sort").value, limit: 100, ...extra};
  }

  // ---------------------------------------------------------------- tree

  function machineStrip(machines, total) {
    const strip = el("span", {class: "mstrip", role: "img",
      "aria-label": machines.map(m => `${m.machine}: ${m.occurrences}`).join("; ")});
    for (const m of machines.slice(0, 6)) {
      const part = el("span", {class: m.machine === "Sem máquina" ? "none" : m.suggested === m.occurrences ? "sug" : "",
        title: `${m.machine}: ${m.occurrences} ocorrências${m.suggested ? ` (${m.suggested} sugeridas)` : ""} · ${nf2.format(m.hours)} h${m.estimated_hours ? ` (${nf2.format(m.estimated_hours)} h estimadas)` : ""}${m.unknown_hours ? ` · ${m.unknown_hours} sem horas` : ""}`});
      part.style.flex = String(Math.max(1, m.occurrences));
      strip.append(part);
    }
    return el("span", {}, strip, el("span", {class: "state", text: machines.length > 1 ? `${machines.length} máquinas` : machines[0]?.machine || ""}));
  }
  function demandStrip(summary, periods) {
    const keys = ["atrasado", ...periods.map(p => p.key)];
    const values = keys.map(k => summary.demand[k] || 0);
    const max = Math.max(1, ...values);
    const strip = el("span", {class: "dstrip", role: "img", "aria-label": "Procura por período em horas conhecidas"});
    keys.forEach((k, i) => {
      const unknown = summary.unknown_demand[k] || 0;
      const label = i === 0 ? "Em atraso" : periods[i - 1].label;
      const bar = el("i", {class: values[i] ? (i === 0 ? "late" : "") : unknown ? "unknown" : "zero",
        title: `${label}: ${nf2.format(values[i])} h conhecidas${unknown ? ` · ${unknown} ocorrências sem horas` : ""}`});
      bar.style.height = values[i] ? `${Math.max(2, 22 * values[i] / max)}px` : unknown ? "6px" : "1px";
      strip.append(bar);
    });
    return strip;
  }
  function deadline(s) {
    if (s.max_late_days) return el("span", {class: "late", text: `${s.late_occurrences} atrasadas · até ${s.max_late_days} d`});
    if (s.next_priority_day) return el("span", {text: `próximo ${day(s.next_priority_day)}`});
    return el("span", {class: "pend", text: "sem prazo"});
  }
  function pending(s) {
    const parts = [];
    if (s.pending.no_machine) parts.push(`${s.pending.no_machine} sem máquina`);
    if (s.pending.no_hours) parts.push(`${s.pending.no_hours} sem horas`);
    if (s.pending.unknown_balance) parts.push(`${s.pending.unknown_balance} saldos por esclarecer`);
    return el("span", {class: parts.length ? "pend" : "", text: parts.join(" · ") || "—"});
  }

  // Sector, OF and reference of a group, read from the dimensions of its path.
  function context(result, path) {
    const ids = result.dims.map(d => d.id), at = id => ids.indexOf(id) >= 0 && ids.indexOf(id) < path.length ? path[ids.indexOf(id)] : null;
    const unit = at("unit");
    return {area: unit === "MTG2" ? "perfis" : unit === "MTG3" ? "cantoneiras" : areas().length === 1 ? areas()[0] : null,
            of: at("of"), reference: at("reference")};
  }

  function groupRow(group, result, depth) {
    const path = [...result.path, group.key];
    const s = group.summary, level = result.level.id, where = context(result, path);
    const key = JSON.stringify(path);
    const open = state.open.has(key);
    const toggle = el("button", {class: "toggle", type: "button", "aria-expanded": String(open),
      "aria-label": (open ? "Fechar " : "Abrir ") + group.label, text: open ? "▾" : "▸"});
    const name = el("td", {class: "name"}, el("span", {style: `padding-left:${depth * 16}px`}), toggle);
    if (level === "sku_family") name.append(el("span", {class: "swatch", style: `background:${familyColor(group.key)}`}));
    name.append(el("strong", {text: group.label}));
    const states = Object.keys(s.classification);
    if (level === "sku_family" && states.length) name.append(el("span", {class: "state", text: states.join(" / ")}));
    const coverage = s.hours_coverage == null ? "—" : `${pct.format(s.hours_coverage)} (${s.hours_covered}/${s.hours_basis})`;
    const actions = el("span", {class: "acts"},
      el("button", {type: "button", text: "Máquina…", onclick: () => safe(machineMenu)({path, label: group.label, level, area: where.area})}),
      where.of ? el("button", {type: "button", text: "Prazo…", onclick: () => priorityMenu({...where, label: group.label})}) : null,
      el("button", {type: "button", text: "Conjunto", title: "Guardar as referências deste grupo como conjunto congelado", onclick: () => setFromGroup(path, group.label, where.area)}));
    const tr = el("tr", {class: "group", "data-depth": depth},
      name, el("td", {class: "num", text: nf.format(s.occurrences)}), el("td", {class: "num", text: nf.format(s.ofs)}),
      el("td", {class: "num", text: nf.format(s.references)}),
      el("td", {class: "num", title: "Horas documentais + horas estimadas (máquina sugerida e velocidade do Excel)"},
        nf2.format(s.hours_known), s.hours_estimated ? el("small", {class: "est", text: ` + ${nf2.format(s.hours_estimated)} est.`}) : null),
      el("td", {text: coverage}), el("td", {}, deadline(s)), el("td", {}, machineStrip(s.machines, s.occurrences)),
      el("td", {}, pending(s)), el("td", {}, demandStrip(s, result.periods)), el("td", {}, actions));
    toggle.addEventListener("click", safe(async () => {
      if (state.open.has(key)) { collapse(tr, key); return; }
      await expand(tr, path, depth + 1, key);
    }));
    return tr;
  }

  function leafRow(row, depth) {
    const tr = el("tr", {class: "leaf" + (state.selected === row.key ? " selected" : ""), tabindex: "0"},
      el("td", {class: "name"}, el("span", {style: `padding-left:${depth * 16 + 24}px`}),
        el("span", {text: `${row.operation_label} · ocorr. ${row.occurrence}`}), el("span", {class: "state", text: row.phase})),
      el("td", {class: "num", text: row.remaining == null ? "?" : nf.format(row.remaining)}),
      el("td", {class: "num", text: row.of}), el("td", {class: "num", text: row.reference}),
      el("td", {class: "num", text: row.load_hours == null ? "?" : nf2.format(row.load_hours) + (row.load_basis === "estimada" ? " est." : "")}),
      el("td", {text: row.load_hours == null ? (row.load_origin || row.hours_reason || "por confirmar") : (row.load_origin || row.hours_origin || "")}),
      el("td", {class: row.late ? "late" : "", text: row.priority_day ? `${day(row.priority_day)} · ${row.priority?.priority_source || ""}` : (row.priority?.missing_reason || "sem prazo")}),
      el("td", {title: row.suggestion?.reason || ""}, row.machine_basis === "sugerida"
        ? el("span", {class: "pend", text: `${row.planning_machine} · sugerida`})
        : row.assigned_machine + (row.decision && ["assign", "prefer"].includes(row.decision.mode) ? (row.decision.mode === "assign" ? " · atribuída" : " · preferida") : "")),
      el("td", {class: row.balance_known ? "" : "pend", text: row.balance_known ? row.balance_origin : "saldo por esclarecer"}),
      el("td", {text: row.started ? "iniciada" : row.selection === "selected" ? "marcada para planear" : ""}),
      el("td", {}, el("span", {class: "acts"},
        el("button", {type: "button", text: "Máquina…", onclick: () => safe(machineMenu)({keys: [row.key], area: row.area, label: `${row.of} · ${row.reference} · ${row.operation_label}`, level: "occurrence"})}),
        el("button", {type: "button", text: "Prazo…", onclick: () => priorityMenu({area: row.area, of: row.of, reference: row.reference})}))));
    const open = safe(() => detail(row));
    tr.addEventListener("click", e => { if (!e.target.closest("button")) open(); });
    tr.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
    return tr;
  }

  function collapse(tr, key) {
    for (const node of state.open.get(key) || []) node.remove();
    for (const k of [...state.open.keys()]) if (k.startsWith(key.slice(0, -1))) state.open.delete(k);
    state.open.delete(key);
    const toggle = tr.querySelector(".toggle"); toggle.textContent = "▸"; toggle.setAttribute("aria-expanded", "false");
  }

  async function expand(tr, path, depth, key, offset = 0, anchor = tr) {
    const result = await call("/necessidades/arvore", query(path, {offset}));
    const rows = result.kind === "occurrences" ? result.rows.map(r => leafRow(r, depth)) : result.rows.map(g => groupRow(g, result, depth));
    if (result.count > offset + result.rows.length) {
      const more = el("tr", {class: "more"}, el("td", {colspan: "11"}, el("button", {type: "button",
        text: `Mostrar mais (${nf.format(result.count - offset - result.rows.length)} restantes)`})));
      more.querySelector("button").addEventListener("click", safe(async () => { more.remove(); state.open.get(key).splice(state.open.get(key).indexOf(more), 1);
        await expand(tr, path, depth, key, offset + result.rows.length, rows.at(-1) || anchor); }));
      rows.push(more);
    }
    anchor.after(...rows);
    state.open.set(key, [...(offset ? state.open.get(key) || [] : []), ...rows]);
    const toggle = tr.querySelector(".toggle"); if (toggle) { toggle.textContent = "▾"; toggle.setAttribute("aria-expanded", "true"); }
  }

  function kpis(result) {
    const f = result.filtered, p = result.population;
    const cards = [
      [f.hours_coverage == null ? "—" : pct.format(f.hours_coverage), `Cobertura das horas (${f.hours_covered} de ${f.hours_basis} ocorrências com saldo)`],
      [nf2.format(f.late_load_hours) + " h", `Em atraso · ${nf2.format(f.late_hours)} h documentais · ${nf.format(f.late_occurrences)} ocorrências`],
      [`${nf.format(f.pending.no_machine)}`, `Sem máquina atribuída · ${nf.format(f.suggested)} com máquina sugerida`],
      [nf2.format(f.load_hours) + " h", `Carga: ${nf2.format(f.hours_known)} h documentais + ${nf2.format(f.hours_estimated)} h estimadas · ${nf.format(f.no_load)} ocorrências sem horas`]];
    $("needs-kpis").replaceChildren(...cards.map(([v, l]) => el("div", {}, el("strong", {text: v}), el("span", {text: l}))));
    const notes = [];
    for (const [family, n] of Object.entries(result.family_notes || {})) notes.push(el("p", {class: "needs-note warn", text: `${family}: ${n.note} Motivo de fecho: ${Object.entries(n.closure_reasons).map(([k, v]) => `${k} (${v})`).join(", ")}; estado CPIS: ${Object.keys(n.cpis_states).join(", ")}.`}));
    if (Object.values(result.sources || {}).some(s => s.stale)) notes.push(el("p", {class: "needs-note warn", text: "A atualizar a base de operações; os números mostrados são da versão anterior."}));
    notes.push(el("p", {class: "needs-note", text: result.scope_note}));
    $("needs-notes").replaceChildren(...notes);
  }

  async function loadTree() {
    const result = await call("/necessidades/arvore", query([]));
    state.last = result; state.stamps = result.stamps; state.open.clear();
    kpis(result);
    $("needs-period-head").textContent = `Procura: atraso + ${result.periods.length} períodos`;
    const body = $("needs-tree").tBodies[0];
    body.replaceChildren(...result.rows.map(g => groupRow(g, result, 0)));
    if (!result.rows.length) body.append(el("tr", {}, el("td", {colspan: "11", text: "Nada corresponde aos filtros."})));
  }

  // ---------------------------------------------------------------- detail and menus

  async function detail(row) {
    state.selected = row.key;
    const info = await call(`/necessidades/ocorrencia?setor=${row.area}&key=${encodeURIComponent(row.key)}`);
    const o = info.occurrence, box = $("needs-detail");
    const lines = [["Ocorrência", `${o.of} · ${o.reference} · ${o.operation_label} (ocorr. ${o.occurrence}, ${o.phase})`],
      ["Família SKU", `${o.sku_family} · ${o.classification}`], ["Família da encomenda", o.cpis_family],
      ["Perfil", `${o.material_type} · ${o.profile}${o.length_mm ? ` · ${nf.format(o.length_mm)} mm` : ""}`],
      ["Saldo", `${o.remaining ?? "?"} de ${o.quantity_required ?? "?"} · ${o.balance_origin}${o.balance_provisional ? " · provisório" : ""}`],
      ["Horas", o.hours != null ? `${nf2.format(o.hours)} h · ${o.hours_origin}` : o.load_hours != null ? `${nf2.format(o.load_hours)} h estimadas · ${o.load_origin}` : (o.load_origin || o.hours_reason || "por confirmar")],
      ["Máquina sugerida", o.suggestion ? `${o.suggestion.machine} · ${o.suggestion.reason}${o.suggestion.conditions?.length ? ` · ${o.suggestion.conditions.length} condições por confirmar` : ""}` : "—"],
      ["Prazo", o.priority_day ? `${day(o.priority_day)} · ${o.priority.priority_source} · ${o.priority.policy_version}` : o.priority.missing_reason],
      ["Máquina indicada / atribuída", `${o.machine} / ${o.assigned_machine}${o.decision ? ` · ${o.decision.origin}` : ""}`],
      ["Rota", info.route.map(r => `${r.occurrence}. ${r.operation}`).join(" → ")],
      ["Conjuntos", info.sets.join(", ") || "—"],
      ["Fontes", `${info.sources.identity} · ${info.sources.snapshot || "aplicação"}${info.sources.excel_row ? ` · linha ${info.sources.excel_row}` : ""}`],
      ["Alternativas", info.alternatives.map(a => `${a.name}${a.code_change ? ` (operação ${String(a.proposed_code).replace("CPIS:", "")})` : ""}: ${{admissible: "admissível", conditional: "condicional", excluded: "excluída"}[a.eligibility]}${a.hours != null ? ` · ${nf2.format(a.hours)} h` : ""}${a.conditions.length ? ` · ${a.conditions.length} condições` : ""}`).join("; ") || "Sem alternativas documentais"],
      ["Histórico de decisões", info.decision_history.map(h => `${String(h.at).slice(0, 16).replace("T", " ")} ${h.mode} · ${h.actor}`).join("; ") || "—"]];
    box.replaceChildren(...lines.map(([k, v]) => el("p", {}, el("strong", {text: k}), el("span", {text: v}))));
    box.hidden = false;
    document.querySelectorAll("#needs-tree tr.selected").forEach(n => n.classList.remove("selected"));
  }

  function dialog(title, intro, body, submitLabel, onSubmit) {
    const form = $("needs-dialog-form"), error = el("p", {class: "error", role: "alert"});
    const submit = el("button", {class: "primary", type: "submit", text: submitLabel});
    form.replaceChildren(el("h3", {text: title}), intro ? el("p", {text: intro}) : null, ...body, error,
      el("div", {class: "actions"}, el("button", {type: "button", text: "Fechar", onclick: () => $("needs-dialog").close()}), submit));
    form.onsubmit = async event => {
      event.preventDefault(); submit.disabled = true; error.textContent = "";
      try { if (await onSubmit(error) !== false) $("needs-dialog").close(); }
      catch (e) { error.textContent = e.status === 409 ? `${e.message} Os valores introduzidos ficam no formulário; revê e grava de novo.` : e.message; }
      finally { submit.disabled = false; }
    };
    $("needs-dialog").showModal();
  }

  function scopeOf(target) {
    return target.keys ? {keys: target.keys} : {preset: $("needs-preset").value, dims: dims(), path: target.path, filters: filters()};
  }

  async function machineMenu(target) {
    const area = target.area;
    if (!area) throw Error("Abre o grupo dentro de um setor (MTG2 ou MTG3) para escolher a máquina.");
    const base = {setor: area, scope: scopeOf(target)};
    const first = await call("/maquinas/previsao", {...base, mode: "assign"});
    const resource = el("select", {required: true}, el("option", {value: "", text: "Escolhe a máquina"}),
      ...first.machines.map(m => el("option", {value: m.resource_id, text: `${m.name} · ${m.admissible} admissíveis · ${m.conditional} condicionais · ${m.excluded} excluídas · ${m.not_candidate} sem alternativa`})));
    const mode = el("select", {}, el("option", {value: "assign", text: "Atribuir (manter e mostrar impedimentos)"}),
      el("option", {value: "accept_suggestions", text: "Aceitar as sugestões (cada ocorrência na sua máquina sugerida)"}),
      el("option", {value: "prefer", text: "Preferir (usar se for utilizável)"}), el("option", {value: "automatic", text: "Voltar ao automático"}),
      ["sku_family", "reference", "profile", "set"].includes(target.level) ? el("option", {value: "future_preference", text: "Guardar preferência para trabalho futuro"}) : null);
    const include = el("select", {}, el("option", {value: "eligible", text: "Admissíveis e condicionais"}),
      el("option", {value: "admissible", text: "Só admissíveis"}), el("option", {value: "all", text: "Todas exceto iniciadas (guardar intenção)"}));
    const reason = el("input", {maxlength: "1000", placeholder: "Motivo (obrigatório exceto no automático)"});
    const summary = el("div", {});
    const current = Object.entries(first.current).map(([k, v]) => `${k}: ${v}`).join(" · ");
    let preview = null;
    async function refresh() {
      preview = null;
      const free = ["automatic", "accept_suggestions"].includes(mode.value);
      resource.disabled = free;
      if (mode.value === "future_preference" || !resource.value && !free) { summary.replaceChildren(); return; }
      preview = await call("/maquinas/previsao", {...base, mode: mode.value, resource_id: free ? null : resource.value});
      const rows = Object.entries(preview.statuses).filter(([, v]) => v.count);
      summary.replaceChildren(el("table", {}, el("thead", {}, el("tr", {}, el("th", {text: "Resultado por ocorrência"}), el("th", {text: "Ocorr."}), el("th", {text: "Horas conhecidas"}), el("th", {text: "Sem horas"}))),
        el("tbody", {}, ...rows.map(([, v]) => el("tr", {}, el("td", {text: v.label}), el("td", {text: v.count}), el("td", {text: nf2.format(v.hours)}), el("td", {text: v.unknown_hours}))))),
        el("p", {class: "hint", text: preview.members_truncated ? `Mostra as primeiras 300 ocorrências; a gravação usa as ${preview.occurrences}.` : `${preview.occurrences} ocorrências em ${preview.ofs} OF.`}));
    }
    for (const node of [resource, mode]) node.addEventListener("change", safe(refresh));
    dialog(`Máquina · ${target.label}`, `${first.occurrences} ocorrências · ${first.ofs} OF · ${first.unknown_balances} saldos por esclarecer. Escolha atual: ${current}. Cada ocorrência mantém a sua elegibilidade; trabalho iniciado conserva a máquina.`,
      [el("div", {class: "row"}, el("label", {}, "Máquina", resource), el("label", {}, "Modo", mode), el("label", {}, "Aplicar a", include)),
       el("label", {}, "Motivo", reason), summary],
      "Gravar", async () => {
        const payload = {...base, request_id: uuid(), mode: mode.value, resource_id: ["automatic", "accept_suggestions"].includes(mode.value) ? null : resource.value || null, reason: reason.value.trim(), include: include.value};
        if (mode.value === "future_preference") {
          const kind = target.level === "profile" ? "profile_group" : target.level;
          payload.selector = {kind, value: target.path.at(-1), label: target.label};
        } else {
          if (!preview) await refresh();
          payload.stamp = preview?.stamp || first.stamp;
        }
        const saved = await call("/maquinas/aplicar", payload);
        say(saved.mode === "future_preference" ? "Preferência futura guardada." : `${saved.changed} ocorrências atualizadas${Object.keys(saved.kept || {}).length ? ` · mantidas: ${Object.entries(saved.kept).map(([k, v]) => `${v} ${k}`).join(", ")}` : ""}. Gera uma proposta para recalcular horários.`);
        await reload();
      });
  }

  function priorityMenu(target) {
    const {area, of} = target, reference = target.reference || "*";
    if (!area || !of) { say("Abre a OF dentro de um setor para mudar o prazo.", true); return; }
    const date = el("input", {type: "date"}), field = el("select", {}, el("option", {value: "", text: "— ou usar outro campo —"}),
      ...Object.entries(state.meta?.priority?.fields || {}).map(([k, v]) => el("option", {value: k, text: v})));
    const applies = el("select", {}, el("option", {value: "principal", text: "Só a operação principal"}), el("option", {value: "all", text: "Todas as operações"}));
    const reason = el("input", {maxlength: "1000", placeholder: "Motivo"});
    const clear = el("label", {class: "check"}, el("input", {type: "checkbox"}), " Retirar a substituição");
    const prior = (state.meta?.priority?.overrides || []).find(o => o.area === area && o.production_order_no === of && o.reference === reference);
    dialog(`Prazo · ${of}${reference !== "*" ? " · " + reference : ""}`, `Política do setor: ${state.meta?.priority?.policies?.[area]?.version || ""}. A substituição vale só neste setor e fica registada com motivo.${prior ? ` Atual: ${prior.definition.due_date || prior.definition.field} (r${prior.revision}).` : ""}`,
      [el("div", {class: "row"}, el("label", {}, "Data", date), el("label", {}, "Campo", field), el("label", {}, "Vale para", applies)), el("label", {}, "Motivo", reason), clear],
      "Gravar prazo", async () => {
        await call("/prioridades/of", {setor: area, of, referencia: reference, request_id: uuid(), due_date: date.value || null, field: field.value || null,
          applies_to: applies.value, reason: reason.value.trim(), limpar: clear.querySelector("input").checked, expected_revision: prior?.revision || 0});
        say("Prazo gravado. O Gantt e a vista passam a usá-lo."); await loadMeta(); await reload();
      });
  }

  function policyMenu() {
    const p = state.meta.priority, fields = p.fields;
    const body = [];
    const controls = {};
    for (const area of ["cantoneiras", "perfis"]) {
      const policy = p.policies[area];
      const order = el("input", {value: policy.principal.join(", "), title: `Campos: ${Object.keys(fields).join(", ")}`});
      const following = el("input", {value: policy.following.join(", ")});
      const year = el("input", {type: "number", min: "2000", max: "2200", value: policy.assume_picking_year || "", placeholder: "ano por confirmar"});
      controls[area] = {order, following, year, revision: policy.revision || 0};
      body.push(el("p", {}, el("strong", {text: area === "cantoneiras" ? "MTG3 Cantoneiras" : "MTG2 Perfis"}), ` · ${policy.origin} · ${policy.version}`),
        el("div", {class: "row"}, el("label", {}, "Operação principal (ordem)", order), el("label", {}, "Operações seguintes", following), el("label", {}, "Ano de Picking assumido", year)));
    }
    const area = el("select", {}, el("option", {value: "cantoneiras", text: "Gravar MTG3"}), el("option", {value: "perfis", text: "Gravar MTG2"}));
    const reason = el("input", {maxlength: "1000", placeholder: "Motivo da mudança"});
    body.push(el("p", {class: "hint", text: `Campos disponíveis: ${Object.entries(fields).map(([k, v]) => `${k} (${v})`).join(", ")}. MTG3 por defeito: Data Corte; sem data fica «prioridade sem data».`}),
      el("div", {class: "row"}, el("label", {}, "Setor", area), el("label", {}, "Motivo", reason)));
    dialog("Prazos por setor", "Uma só regra para Carteira, vista de necessidades, Gantt, motor e verificador.", body, "Gravar política", async () => {
      const c = controls[area.value], split = v => v.value.split(",").map(x => x.trim()).filter(Boolean);
      await call("/prioridades/politica", {setor: area.value, request_id: uuid(), reason: reason.value.trim(), expected_revision: c.revision,
        definition: {principal: split(c.order), following: split(c.following), assume_picking_year: c.year.value ? Number(c.year.value) : null}});
      say("Política gravada."); await loadMeta(); await reload();
    });
  }

  function setFromGroup(path, label, area) {
    if (!area) { say("Abre o grupo dentro de um setor para guardar o conjunto.", true); return; }
    const name = el("input", {maxlength: "160", value: label, required: true});
    dialog("Guardar conjunto congelado", "Congela as referências deste grupo como estão agora (com os filtros atuais). Membros e versão ficam fixos.",
      [el("label", {}, "Nome", name)], "Guardar", async () => {
        const saved = await call("/conjuntos", {setor: area, request_id: uuid(), name: name.value.trim(), mode: "frozen",
          from: {preset: $("needs-preset").value, dims: dims(), path, filters: filters()}});
        say(`Conjunto «${saved.set.name}» guardado com ${saved.members} referências.`); await loadSets();
      });
  }

  function pasteSet() {
    const area = el("select", {}, el("option", {value: "cantoneiras", text: "MTG3 Cantoneiras"}), el("option", {value: "perfis", text: "MTG2 Perfis"}));
    const name = el("input", {maxlength: "160", required: true}), list = el("textarea", {rows: "8", placeholder: "Uma referência por linha (ou separadas por ; ,)"});
    const dynamic = el("label", {class: "check"}, el("input", {type: "checkbox"}), " Dinâmico: guardar os filtros atuais em vez da lista");
    dialog("Conjunto de referências", "A referência literal é a identidade: grafias parecidas não se fundem; desconhecidas ficam pendentes.",
      [el("div", {class: "row"}, el("label", {}, "Setor", area), el("label", {}, "Nome", name)), el("label", {}, "Referências", list), dynamic],
      "Guardar", async () => {
        const isDynamic = dynamic.querySelector("input").checked;
        const saved = await call("/conjuntos", {setor: area.value, request_id: uuid(), name: name.value.trim(), mode: isDynamic ? "dynamic" : "frozen",
          members: isDynamic ? undefined : list.value, filters: isDynamic ? filters() : undefined});
        say(`Conjunto guardado · ${saved.members || "filtro"} ${saved.repeated_in_list ? `· ${saved.repeated_in_list} repetidas ignoradas` : ""}`); await loadSets();
      });
  }

  async function actionsMenu() {
    const lists = await Promise.all(areas().map(a => call(`/maquinas/acoes?setor=${a}`).then(r => [a, r])));
    const rows = [];
    for (const [area, r] of lists) for (const a of r.actions) {
      const undo = a.mode !== "undo" && !a.undone ? el("button", {type: "button", text: "Desfazer", onclick: safe(async () => {
        const done = await call("/maquinas/desfazer", {setor: area, request_id: uuid(), action_id: a.id});
        say(`Desfeita: ${done.restored} ocorrências repostas${done.skipped_changed_later ? `, ${done.skipped_changed_later} mudadas depois mantidas` : ""}.`);
        $("needs-dialog").close(); await reload(); })}) : el("span", {text: a.undone ? "desfeita" : ""});
      rows.push(el("tr", {}, el("td", {text: String(a.created_at).slice(0, 16).replace("T", " ")}), el("td", {text: area}), el("td", {text: a.mode}),
        el("td", {text: a.summary.changed ?? a.summary.restored ?? ""}), el("td", {text: a.reason || ""}), el("td", {text: a.actor}), el("td", {}, undo)));
    }
    dialog("Decisões de máquina", "Cada ação tem um identificador comum; desfazer cria uma nova revisão e não mexe em ocorrências alteradas depois.",
      [el("table", {}, el("thead", {}, el("tr", {}, ...["Quando", "Setor", "Modo", "Ocorr.", "Motivo", "Autor", ""].map(t => el("th", {text: t})))), el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", {colspan: "7", text: "Sem ações."}))))],
      "Fechar", async () => true);
  }

  // ---------------------------------------------------------------- capacity

  function assignColors(cap) {
    if (state.families.size) return;
    const totals = new Map();
    for (const unit of Object.values(cap.units)) for (const p of unit.periods) for (const f of p.families)
      if (f.family !== "Sem família SKU") totals.set(f.family, (totals.get(f.family) || 0) + f.need_hours + f.allocated_hours);
    [...totals].sort((a, b) => b[1] - a[1]).slice(0, SLOTS.length).forEach(([name], i) => state.families.set(name, i));
  }

  // One axis (hours) for the periods only; late demand is a separate headline, never a column that crushes the scale.
  function unitChart(unit) {
    const columns = unit.periods.map(p => ({key: p.key, label: p.label, need: p.need_hours, alloc: p.allocated_hours, cap: p.capacity_hours,
      status: p.capacity_status, families: p.families, covered: p.need_covered_hours, pressure: p.pressure_pct}));
    const max = Math.max(1, ...columns.map(c => Math.max(c.need, c.alloc, c.cap || 0)));
    const W = 46, H = 140, top = 14, left = 64, width = left + columns.length * W + 8;
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", width); svg.setAttribute("height", top + H + 26); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${unit.label}: procura conhecida por prazo e ocupação do plano por período, em horas`);
    const tip = (node, text) => { node.append(Object.assign(document.createElementNS(ns, "title"), {textContent: text})); return node; };
    const add = (tag, attrs, text) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text != null) n.textContent = text; svg.append(n); return n; };
    for (const t of [0, .5, 1]) { const y = top + H * (1 - t); add("line", {x1: left, x2: width, y1: y, y2: y, class: "grid"}); add("text", {x: left - 6, y: y + 3, "text-anchor": "end", class: "lbl"}, nf.format(max * t) + " h"); }
    columns.forEach((c, i) => {
      const x = left + i * W + 4;
      let y = top + H;
      // Need stacked by family (fixed colour per family) with a 2 px surface gap between segments.
      for (const f of [...c.families].sort((a, b) => b.need_hours - a.need_hours)) {
        if (!f.need_hours) continue;
        const h = Math.max(1, H * f.need_hours / max);
        y -= h;
        tip(add("rect", {x, y: y + 1, width: 18, height: Math.max(1, h - 2), rx: 2, fill: familyColor(f.family)}),
            `${c.label} · ${f.family}: ${nf2.format(f.need_hours)} h de procura${f.pct_need_capacity != null ? ` (${f.pct_need_capacity}% da capacidade)` : ""}`);
      }
      if (c.alloc) {
        const h = H * c.alloc / max;
        tip(add("rect", {x: x + 20, y: top + H - h, width: 14, height: h, rx: 2, fill: "var(--action)"}), `${c.label}: ${nf2.format(c.alloc)} h ocupadas pelo plano`);
      }
      if (c.cap != null) {
        const y2 = top + H * (1 - Math.min(c.cap, max) / max);
        tip(add("line", {x1: x - 2, x2: x + 36, y1: y2, y2, class: c.status === "estimada" ? "cap est" : "cap"}),
          `${c.label}: capacidade ${c.status === "estimada" ? "estimada " : ""}${nf2.format(c.cap)} h${c.pressure != null ? ` · pressão ${c.pressure}% sobre ${nf2.format(c.covered)} h com capacidade conhecida` : ""}`);
      } else {
        tip(add("text", {x: x + 17, y: top - 3, "text-anchor": "middle", class: "lbl"}, "?"), `${c.label}: capacidade por confirmar`);
      }
      tip(add("text", {x: x + 17, y: top + H + 16, "text-anchor": "middle", class: "lbl"}, c.label), `${c.label}: ${nf2.format(c.need)} h de procura conhecida`);
    });
    return svg;
  }

  function unitLegend(unit) {
    const present = new Set(unit.periods.flatMap(p => p.families.filter(f => f.need_hours || f.allocated_hours).map(f => f.family)));
    const named = [...state.families.keys()].filter(f => present.has(f));
    const other = [...present].some(f => f !== "Sem família SKU" && !state.families.has(f));
    return el("div", {class: "cap-legend"}, ...named.map(name => el("span", {}, el("i", {style: `background:${familyColor(name)}`}), name)),
      other ? el("span", {}, el("i", {style: "background:var(--other)"}), "Outras famílias") : null,
      present.has("Sem família SKU") ? el("span", {}, el("i", {style: "background:var(--none)"}), "Sem família SKU") : null,
      el("span", {}, el("i", {style: "background:var(--action)"}), "Ocupação do plano"),
      el("span", {}, el("i", {style: "background:var(--ink);height:2px"}), "Capacidade (tracejada = estimada) · ? por confirmar"));
  }

  function unitTable(unit) {
    const head = el("tr", {}, ...["Período", "Capacidade", "Origem", "Procura (h)", "das quais estimadas", "Sem capacidade conhecida", "Pressão", "Ocupação", "Sem horas", "Sem máquina"].map(t => el("th", {text: t})));
    const rows = unit.periods.map(p => el("tr", {},
      el("td", {text: p.label}), el("td", {text: p.capacity_hours == null ? "por confirmar" : nf2.format(p.capacity_hours)}),
      el("td", {text: (p.capacity_basis || []).join(", ") || "—", title: p.without_capacity?.length ? `Sem capacidade: ${p.without_capacity.join(", ")}` : ""}),
      el("td", {text: nf2.format(p.need_hours)}), el("td", {text: nf2.format(p.need_estimated_hours || 0)}),
      el("td", {text: nf2.format(p.need_uncovered_hours || 0)}), el("td", {text: p.pressure_pct == null ? "—" : p.pressure_pct + "%"}),
      el("td", {text: p.occupation_pct == null ? nf2.format(p.allocated_hours) + " h" : p.occupation_pct + "%"}),
      el("td", {text: p.pending.no_hours}), el("td", {text: p.pending.no_machine})));
    return el("table", {class: "cap-table"}, el("thead", {}, head), el("tbody", {}, rows));
  }

  function resources(unit) {
    const details = el("details", {open: true}, el("summary", {text: `Máquinas e recursos (${unit.resources.length}) · carga e semanas ao ritmo da capacidade`}));
    const head = el("tr", {}, ...["Recurso", "Semanas de carga", "Capacidade semanal", "Carga total (h)", "das quais estimadas", "Sugeridas", "Atraso (h)", "Famílias principais"].map(t => el("th", {text: t})));
    const rows = unit.resources.map(r => el("tr", {}, el("td", {text: r.name + (r.shared ? " · partilhada" : ""), title: r.role_note || ""}),
      el("td", {class: r.weeks_to_clear > 4 ? "late" : "", text: r.weeks_to_clear == null ? "—" : nf.format(r.weeks_to_clear)}),
      el("td", {text: r.weekly_capacity_hours == null ? "por confirmar" : `${nf2.format(r.weekly_capacity_hours)} h · ${r.weekly_capacity_status}`,
        title: r.periods.find(p => p.capacity_source)?.capacity_source || ""}),
      el("td", {text: nf2.format(r.load_hours) + (r.unknown_occurrences ? ` (+${r.unknown_occurrences} sem horas)` : "")}),
      el("td", {text: nf2.format(r.estimated_hours)}), el("td", {text: nf.format(r.suggested_occurrences)}),
      el("td", {text: nf2.format(r.late_need_hours)}),
      el("td", {text: r.families.slice(0, 3).map(f => `${f.family} ${nf2.format(f.need_hours)} h${f.unknown_hours ? ` (+${f.unknown_hours} sem horas)` : ""}`).join("; ")})));
    details.append(el("table", {class: "cap-table"}, el("thead", {}, head), el("tbody", {}, rows)));
    return details;
  }

  function backlogCard(area, unit) {
    const b = unit.backlog, bal = b.balance;
    const box = (value, label, warn) => el("div", {class: warn ? "warn" : ""}, el("strong", {text: value}), el("small", {text: label}));
    return el("section", {}, el("h3", {text: `${unit.label} · próximos ${b.window_days} dias`}),
      el("div", {class: "flow"},
        box(hours(bal.initial_known_hours), "atraso + prazo na janela"), "→",
        box(bal.entries == null ? "—" : hours(bal.entries), "entradas (sem previsão)"), "→",
        box(bal.planned_completion_hours == null ? "por calcular" : hours(bal.planned_completion_hours), "conclusão prevista (plano aceite)", bal.planned_completion_hours == null), "→",
        box(bal.final_known_hours == null ? "—" : hours(bal.final_known_hours), "saldo final"),
        box(bal.capacity_hours == null ? "por confirmar" : hours(bal.capacity_hours), `capacidade na janela${bal.capacity_estimated ? " (estimada)" : ""}`, bal.capacity_hours == null || bal.capacity_estimated),
        box(bal.deficit_hours == null ? "—" : hours(bal.deficit_hours), "défice", bal.deficit_hours > 0),
        box(bal.late_weeks_at_capacity == null ? "—" : nf.format(bal.late_weeks_at_capacity) + " sem.", "atraso ÷ capacidade semanal", bal.late_weeks_at_capacity > 2)),
      el("p", {class: "hint", text: `Das ${hours(bal.initial_known_hours)}: ${hours(bal.initial_estimated_hours)} estimadas; ${hours(Math.max(0, bal.uncovered_hours))} em recursos sem capacidade conhecida${bal.without_capacity?.length ? ` (${bal.without_capacity.slice(0, 6).join(", ")})` : ""}.`}),
      el("p", {class: "hint", text: `Atraso: ${nf.format(b.late.occurrences)} ocorrências em ${nf.format(b.late.ofs)} OF · ${hours(b.late.known_hours)} conhecidas · ${nf.format(b.late.unknown_hours)} sem horas. Idade: ${["1–7 dias", "8–30 dias", "31–90 dias", "mais de 90 dias"].filter(k => b.late.ages[k]).map(k => `${k} ${b.late.ages[k].occurrences}`).join(", ") || "—"}. Bloqueadas na janela: ${b.blocked.no_machine} sem máquina, ${b.blocked.no_hours} sem horas, ${b.blocked.unknown_balance} saldo por esclarecer.`}),
      el("p", {class: "hint", text: [bal.entries_note, bal.planned_note, bal.capacity_note, b.recovery_note].filter(Boolean).join(" ")}));
  }

  async function loadCapacity() {
    const mode = $("capacity-mode").value;
    const cap = await call("/capacidade", {areas: areas(), horizon_weeks: Number($("needs-horizon").value), mode, capacity_scenario: $("capacity-scenario").value,
      scenario_id: mode === "proposal" ? ($("scenario")?.value || null) : null, filters: filters()});
    assignColors(cap);
    $("capacity-units").replaceChildren(...Object.entries(cap.units).map(([area, unit]) => el("div", {class: "cap-unit"},
      el("h3", {text: unit.label}),
      el("div", {class: "flow"}, el("div", {class: unit.late.load_hours ? "warn" : ""}, el("strong", {text: hours(unit.late.load_hours)}),
        el("small", {text: `procura em atraso (${hours(unit.late.estimated_hours)} estimadas) · ${nf.format(unit.late.occurrences)} ocorrências, ${nf.format(unit.late.unknown_hours)} sem horas`}))),
      (lim => lim ? el("p", {class: "needs-note warn", text: `Recurso limitante: ${lim.name} — ${nf.format(lim.weeks_to_clear)} semanas de carga ao ritmo de ${nf2.format(lim.weekly_capacity_hours)} h/semana (${lim.weekly_capacity_status}). O total do setor pode ter folga noutras máquinas que não fazem este trabalho.`}) : null)(
        [...unit.resources].filter(r => r.weeks_to_clear != null).sort((a, b) => b.weeks_to_clear - a.weeks_to_clear)[0]),
      el("p", {class: "hint", text: `Sem prazo: ${nf.format(unit.no_date.occurrences)} ocorrências (${hours(unit.no_date.known_hours)}). Depois do horizonte: ${hours(unit.after_horizon_hours)}. Fila sem máquina: ${nf.format(unit.pending_queue.no_machine.occurrences)} · sem horas: ${nf.format(unit.pending_queue.no_hours)}.`}),
      el("div", {class: "cap-chart"}, unitChart(unit)), unitLegend(unit),
      state.table ? unitTable(unit) : null, resources(unit))));
    if (cap.shared.length) $("capacity-units").append(el("div", {class: "cap-unit"}, el("h3", {text: "Partilhada (sem quota)"}),
      el("p", {class: "hint", text: cap.shared.map(s => `${s.name}: usada por ${s.areas.join(" e ")}`).join("; ") + ". Configura uma quota para dividir a capacidade."})));
    $("capacity-backlog").replaceChildren(...Object.entries(cap.units).map(([area, unit]) => backlogCard(area, unit)));
  }

  // ---------------------------------------------------------------- boot

  async function loadSets() {
    const lists = await Promise.all(["perfis", "cantoneiras"].map(a => call(`/conjuntos?setor=${a}`).catch(() => ({sets: []}))));
    const select = $("needs-set"), keep = selectedValues("needs-set");
    select.replaceChildren(...lists.flatMap(l => l.sets).map(s => el("option", {value: s.id, text: `${s.name} · ${s.mode === "frozen" ? s.members + " refs" : "dinâmico"}`, selected: keep.includes(s.id)})));
  }

  async function loadMeta() {
    const params = areas().map(a => `areas=${a}`).join("&");
    const [facets, priorityInfo] = await Promise.all([call(`/necessidades/facetas?${params}`), call("/prioridades")]);
    state.meta = {...facets, priority: priorityInfo};
    const preset = $("needs-preset"), keep = preset.value || "familias";
    preset.replaceChildren(...Object.entries(facets.presets).map(([k, v]) => el("option", {value: k, text: `${v.label} · ${v.dims.map(d => facets.dimensions[d]).join(" → ")}`})));
    preset.value = facets.presets[keep] ? keep : "familias";
    const dimsSelect = $("needs-dims"), keepDims = selectedValues("needs-dims");
    dimsSelect.replaceChildren(...Object.entries(facets.dimensions).map(([k, v]) => el("option", {value: k, text: v, selected: keepDims.includes(k)})));
    for (const [id, facet] of [["needs-family", "sku_family"], ["needs-machine", "machine"]]) {
      const keepValues = selectedValues(id);
      $(id).replaceChildren(...facets.facets[facet].map(f => el("option", {value: f.value, text: `${f.label} (${nf.format(f.count)})`, selected: keepValues.includes(f.value)})));
    }
    const flags = $("needs-flags"), checked = [...flags.querySelectorAll("input:checked")].map(i => i.value);
    flags.replaceChildren(...facets.facets.flags.map(f => el("label", {}, el("input", {type: "checkbox", value: f.value, checked: checked.includes(f.value)}), `${f.label} (${nf.format(f.count)})`)));
    flags.querySelectorAll("input").forEach(i => i.addEventListener("change", safe(reload)));
  }

  async function reload() { await Promise.all([loadTree(), loadCapacity()]); }

  async function start() {
    try { await loadMeta(); }
    catch (e) { if (e.status === 404) return; throw e; }  // switch off: keep the page as before
    $("needs").hidden = false; $("needs-capacity").hidden = false;
    await loadSets();
    let timer;
    const later = (fn, ms) => () => { clearTimeout(timer); timer = setTimeout(safe(fn), ms); };
    for (const id of ["needs-preset", "needs-dims", "needs-family", "needs-machine", "needs-set", "needs-horizon", "needs-sort"]) $(id).addEventListener("change", later(reload, 150));
    $("needs-areas").addEventListener("change", later(async () => { await loadMeta(); await reload(); }, 0));
    $("needs-q").addEventListener("input", later(reload, 350));
    $("capacity-mode").addEventListener("change", safe(loadCapacity));
    $("capacity-scenario").addEventListener("change", safe(loadCapacity));
    $("capacity-table-toggle").addEventListener("click", safe(async () => { state.table = !state.table; $("capacity-table-toggle").setAttribute("aria-pressed", String(state.table)); await loadCapacity(); }));
    $("needs-policy").addEventListener("click", () => policyMenu());
    $("needs-set-new").addEventListener("click", () => pasteSet());
    $("needs-actions").addEventListener("click", safe(actionsMenu));
    await reload();
  }

  document.addEventListener("DOMContentLoaded", () => safe(start)());
})();
