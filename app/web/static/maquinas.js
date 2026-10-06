// Página «Máquinas» (1/10/2026): carga, sugestões e equilíbrio. Todas as gravações usam as ações de máquina
// por grupo do servidor (uma transação, histórico, desfazer).
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const API = "/planeamento/api/setor";
  const nf = new Intl.NumberFormat("pt-PT", {maximumFractionDigits: 1});
  const nh = v => v == null ? "—" : `${nf.format(v)} h`;
  const day = v => v ? String(v).slice(0, 10).split("-").reverse().join("/") : "—";
  const PAGE = 40;
  const state = {area: "", data: null, tab: "load", shown: PAGE, selectedSuggest: new Set(), selectedBalance: new Set(), polling: null, lastStamps: null};
  const CONDITIONS = {
    confirmar_graminho_ferramentas_e_desenho: "graminho, ferramentas e desenho", revisao_tecnica_por_validar: "revisão técnica",
    processo_119_em_puncao_por_confirmar: "119 em punção (prática do Excel)", confirmar_numero_de_diametros_da_peca: "nº de diâmetros",
    confirmar_geometria_furacao_e_revisao: "geometria e furação", confirmar_cliente_nacional: "mercado nacional",
    mudanca_112_para_119_requer_decisao: "mudança 112→119", limites_por_validar: "limites da máquina", perfil_por_interpretar: "perfil por interpretar",
    abas_desiguais_por_validar: "abas desiguais"};

  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) if (c != null && c !== false) n.append(c);
    return n;
  }
  async function call(path, body) {
    const r = await fetch(API + path, {method: body ? "POST" : "GET", cache: "no-store",
      headers: body ? {"Content-Type": "application/json", Accept: "application/json"} : {Accept: "application/json"},
      body: body ? JSON.stringify(body) : undefined});
    const out = await r.json().catch(() => ({}));
    if (!r.ok) { const e = Error(out.error || out.detail || `Erro ${r.status}`); e.status = r.status; throw e; }
    return out;
  }
  function toast(message, {error = false, undo = null} = {}) {
    const t = $("toast");
    t.replaceChildren(el("span", {text: message}), undo ? el("button", {type: "button", text: "Desfazer", onclick: () => undoAction(undo)}) : null,
      el("button", {type: "button", text: "Fechar", onclick: () => { t.hidden = true; }}));
    t.classList.toggle("error", error); t.hidden = false;
  }
  const areas = () => state.area ? [state.area] : ["cantoneiras", "perfis"];
  const busy = () => !state.data || state.data.stale;

  // ------------------------------------------------------------- loading

  async function load({quiet = false} = {}) {
    if (!quiet) $("status").textContent = "A carregar…";
    const params = new URLSearchParams({cenario: $("scenario").value});
    for (const a of areas()) params.append("areas", a);
    const data = await call(`/maquinas/painel?${params}`);
    state.data = data;
    const stamps = JSON.stringify(data.stamps);
    const waiting = state.lastStamps && stamps === state.lastStamps;
    if (data.stale || waiting) {
      $("status").textContent = "A atualizar com as últimas decisões… os botões voltam dentro de segundos.";
      $("status").className = "status warn";
      clearTimeout(state.polling); state.polling = setTimeout(() => load({quiet: true}).catch(showError), 4000);
    } else {
      state.lastStamps = null;
      $("status").textContent = `Atualizado · capacidade: ${data.scenarios[data.scenario]}`;
      $("status").className = "status";
    }
    render();
  }
  const showError = e => toast(e.message || "Não foi possível concluir.", {error: true});

  function render() {
    renderKpis(); renderMachines(); renderSuggestions(); renderBalance();
    if (state.tab === "history") renderHistory().catch(showError);
  }

  function tab(name) {
    state.tab = name;
    for (const [t, p] of [["load", "load"], ["suggest", "suggest"], ["balance", "balance"], ["history", "history"]]) {
      $(`tab-${t}`).setAttribute("aria-selected", String(t === name)); $(`panel-${p}`).hidden = t !== name;
    }
    if (name === "history") renderHistory().catch(showError);
  }

  // ------------------------------------------------------------- KPIs and machine load

  function renderKpis() {
    const d = state.data;
    const ranked = d.machines.filter(m => m.weeks != null);
    const worst = ranked[0];
    const sugg = d.suggestions, moves = d.rebalance;
    const perUnit = [...new Set(ranked.map(m => m.unit))].map(unit => {
      const ms = ranked.filter(m => m.unit === unit);
      return {unit, before: Math.max(...ms.map(m => m.weeks)), after: Math.max(...ms.map(m => m.after_rebalance_weeks ?? m.weeks))};
    }).filter(u => u.after < u.before - 0.05);
    $("kpis").replaceChildren(
      el("button", {class: "kpi " + (worst && worst.weeks > 4 ? "alert" : "good"), type: "button", onclick: () => tab("load")},
        el("strong", {text: worst ? `${worst.name} · ${nf.format(worst.weeks)} semanas` : "Sem capacidade conhecida"}),
        el("span", {text: worst ? `Máquina com a fila mais longa (${worst.unit}). ${nh(worst.load_hours)} à frente, a ${nh(worst.weekly_capacity_hours)}/semana.` : "Não há calendário nem ritmo observado para calcular semanas."})),
      el("button", {class: "kpi " + (sugg.length ? "alert" : "good"), type: "button", onclick: () => tab("suggest")},
        el("strong", {text: `${nf.format(sugg.length)} lotes sem máquina`}),
        el("span", {text: `${nf.format(sugg.reduce((s, g) => s + g.occurrences, 0))} operações com máquina sugerida, à espera da tua decisão.`})),
      el("button", {class: "kpi " + (moves.length ? "alert" : "good"), type: "button", onclick: () => tab("balance")},
        el("strong", {text: moves.length ? `${moves.length} mudanças propostas` : "Carga equilibrada"}),
        el("span", {text: moves.length && perUnit.length ? `Fila mais longa: ${perUnit.map(u => `${u.unit.split(" ")[0]} ${nf.format(u.before)} → ${nf.format(u.after)} semanas`).join(" · ")}. Nenhum trabalho é retirado.` : "Não há mudanças que encurtem a fila mais longa."})));
    $("count-suggest").textContent = sugg.length; $("count-balance").textContent = moves.length;
  }

  function renderMachines() {
    const list = state.data.machines;
    const max = Math.max(4, ...list.map(m => Math.max(m.weeks || 0, m.after_rebalance_weeks || 0)));
    const box = $("machines");
    if (!list.length) { box.replaceChildren(el("p", {class: "empty", text: "Sem máquinas com carga neste setor."})); return; }
    box.replaceChildren(...list.map(m => {
      const known = m.weeks != null;
      const est = m.load_hours && m.estimated_hours / m.load_hours > 0.5;
      const fill = el("i", {class: (m.weeks > 4 ? "hot " : "") + (est ? "est" : "")});
      fill.style.width = `${Math.min(100, 100 * (m.weeks || 0) / max)}%`;
      const bar = el("div", {class: "bar", role: "img", "aria-label": known ? `${nf.format(m.weeks)} semanas de carga` : "capacidade por confirmar"}, known ? fill : null);
      if (m.after_rebalance_weeks != null) {
        const mark = el("b", {title: `Depois do equilíbrio: ${nf.format(m.after_rebalance_weeks)} semanas`});
        mark.style.left = `calc(${Math.min(100, 100 * m.after_rebalance_weeks / max)}% - 1px)`; bar.append(mark);
      }
      const detail = el("div", {class: "detail", hidden: true},
        el("span", {text: `Capacidade: ${m.capacity_source || "por confirmar"}`}),
        el("span", {text: `Carga: ${nh(m.load_hours)}, das quais ${nh(m.estimated_hours)} estimadas pela velocidade do Excel; ${nf.format(m.suggested_occurrences)} operações com máquina sugerida; ${nf.format(m.unknown_occurrences)} sem horas.`}),
        el("span", {text: `Principais famílias: ${m.families.map(f => `${f.family} ${nh(f.need_hours)}`).join(" · ") || "—"}`}));
      const card = el("button", {class: "machine", type: "button", "aria-expanded": "false"},
        el("div", {class: "name"}, el("strong", {text: m.name}), el("small", {text: m.unit})),
        bar,
        el("div", {class: "weeks"}, el("strong", {text: known ? nf.format(m.weeks) : "—"}), el("small", {text: known ? "semanas" : "sem capacidade"})),
        el("div", {class: "meta", text: `${nh(m.load_hours)} de trabalho · ${nh(m.late_hours)} em atraso · ${m.weekly_capacity_hours ? `${nh(m.weekly_capacity_hours)}/semana (${m.capacity_status})` : "capacidade por confirmar"}${m.after_rebalance_weeks != null ? ` · depois do equilíbrio: ${nf.format(m.after_rebalance_weeks)} semanas` : ""}`}),
        detail);
      card.addEventListener("click", () => { detail.hidden = !detail.hidden; card.setAttribute("aria-expanded", String(!detail.hidden)); });
      return card;
    }));
  }

  // ------------------------------------------------------------- suggestions

  function filteredSuggestions() {
    const machine = $("suggest-machine").value, late = $("suggest-late").checked, q = $("suggest-q").value.trim().toUpperCase();
    return state.data.suggestions.filter(g => (!machine || g.machine === machine) && (!late || g.late)
      && (!q || `${g.of} ${g.profile} ${g.customer}`.toUpperCase().includes(q)));
  }
  const groupId = g => `${g.area}|${g.of}|${g.operation}|${g.profile}`;

  function renderSuggestions() {
    const select = $("suggest-machine"), keep = select.value;
    const machines = [...new Set(state.data.suggestions.map(g => g.machine))].sort();
    select.replaceChildren(el("option", {value: "", text: "Todas"}), ...machines.map(m => el("option", {value: m, text: m})));
    if (machines.includes(keep)) select.value = keep;
    const rows = filteredSuggestions();
    const box = $("suggestions");
    if (!rows.length) { box.replaceChildren(el("p", {class: "empty", text: "Não há trabalho sem máquina neste filtro."})); $("suggest-more").hidden = true; return; }
    box.replaceChildren(...rows.slice(0, state.shown).map(g => {
      const id = groupId(g);
      const check = el("input", {type: "checkbox", "aria-label": `Selecionar ${g.of} ${g.profile}`, checked: state.selectedSuggest.has(id)});
      check.addEventListener("change", () => { check.checked ? state.selectedSuggest.add(id) : state.selectedSuggest.delete(id); updateBulk(); });
      return el("div", {class: "card"}, check,
        el("div", {},
          el("h3", {text: `${g.of} · ${g.profile} · operação ${g.operation}`}),
          el("p", {}, g.late ? el("span", {class: "pill late", text: `${g.late} em atraso · até ${g.max_late_days} dias`}) : el("span", {class: "pill", text: `prazo ${day(g.first_day)}`}),
            ` ${g.customer} · ${g.occurrences} operações · ${nh(g.hours)}${g.unknown_hours ? ` (+${g.unknown_hours} sem horas)` : ""}`),
          el("p", {class: "move"}, "Sugerida: ", el("b", {text: g.machine}), g.mixed ? " (várias máquinas no lote)" : "", el("br"),
            el("small", {text: g.reason})),
          g.conditions.length ? el("p", {}, ...g.conditions.slice(0, 3).map(c => el("span", {class: "pill cond", text: `confirmar ${CONDITIONS[c] || c.replaceAll("_", " ")}`}))) : null),
        el("div", {class: "go"},
          el("button", {type: "button", class: "primary", text: "Aceitar", disabled: busy(), onclick: () => acceptSuggestions([g]).catch(showError)}),
          el("button", {type: "button", text: "Outra máquina…", disabled: busy(), onclick: () => chooseOther(g).catch(showError)})));
    }));
    $("suggest-more").hidden = rows.length <= state.shown;
    $("suggest-more").textContent = `Mostrar mais (${rows.length - state.shown} restantes)`;
    updateBulk();
  }

  function updateBulk() {
    $("suggest-accept-selected").disabled = busy() || !state.selectedSuggest.size;
    $("suggest-accept-selected").textContent = state.selectedSuggest.size ? `Aceitar ${state.selectedSuggest.size} selecionadas` : "Aceitar selecionadas";
    $("balance-apply-selected").disabled = busy() || !state.selectedBalance.size;
    $("balance-apply-selected").textContent = state.selectedBalance.size ? `Aplicar ${state.selectedBalance.size} selecionadas` : "Aplicar selecionadas";
  }

  async function write(area, body, message) {
    const before = JSON.stringify(state.data.stamps);
    const saved = await call("/maquinas/aplicar", {setor: area, request_id: crypto.randomUUID(), stamp: state.data.stamps[area], ...body});
    if (saved.changed) state.lastStamps = before;  // wait for the rebuilt data before enabling buttons again
    toast(`${message}: ${saved.changed} operações gravadas${Object.keys(saved.kept || {}).length ? ` (${Object.values(saved.kept).reduce((a, b) => a + b, 0)} mantidas, por já estarem iniciadas, decididas ou incompatíveis)` : ""}.`,
      {undo: {area, id: saved.action_id}});
    state.selectedSuggest.clear(); state.selectedBalance.clear();
    await load({quiet: true});
  }

  async function acceptSuggestions(groups) {
    for (const area of new Set(groups.map(g => g.area))) {
      const targets = {};
      for (const g of groups.filter(x => x.area === area)) for (const k of g.keys) targets[k] = null;
      // Each occurrence keeps its own suggested machine; one action for the whole selection.
      await write(area, {mode: "accept_suggestions", scope: {keys: Object.keys(targets)}, reason: "Sugestão aceite no painel de máquinas"},
        groups.length === 1 ? `Aceite ${groups[0].machine} para ${groups[0].of}` : `Aceites ${groups.length} lotes`);
    }
  }

  async function chooseOther(g) {
    const preview = await call("/maquinas/previsao", {setor: g.area, mode: "assign", scope: {keys: g.keys}});
    const box = $("choose-options");
    const options = preview.machines.filter(m => m.admissible + m.conditional > 0);
    $("choose-title").textContent = `Máquina para ${g.of} · ${g.profile}`;
    $("choose-info").textContent = `${g.occurrences} operações. Só aparecem máquinas que são alternativa técnica para este lote; «condicional» quer dizer que há condições por confirmar (ex.: desenho, ferramentas).`;
    box.replaceChildren(...options.map((m, i) => el("label", {class: "choice"},
      el("input", {type: "radio", name: "machine", value: m.resource_id, checked: m.name === g.machine || (i === 0 && !options.some(o => o.name === g.machine))}),
      el("span", {}, `${m.name}${m.name === g.machine ? " (sugerida)" : ""}`,
        el("small", {text: `${m.admissible} admissíveis · ${m.conditional} condicionais${m.not_candidate ? ` · ${m.not_candidate} não podem` : ""}${m.hours ? ` · ~${nh(m.hours)}` : ""}`})))));
    $("choose-reason").value = ""; $("choose-error").textContent = "";
    $("choose").showModal();
    $("choose-form").onsubmit = async ev => {
      ev.preventDefault();
      const picked = box.querySelector("input:checked");
      if (!picked) { $("choose-error").textContent = "Escolhe uma máquina."; return; }
      try {
        $("choose").close();
        await write(g.area, {mode: "assign", resource_id: picked.value, scope: {keys: g.keys}, include: "eligible",
          reason: $("choose-reason").value.trim() || "Escolhida no painel de máquinas"}, `Gravado para ${g.of}`);
      } catch (e) { showError(e); }
    };
  }

  // ------------------------------------------------------------- rebalance

  const moveId = p => `${p.area}|${p.of}|${p.operation}|${p.profile}|${p.from_id}`;

  function renderBalance() {
    const select = $("balance-from"), keep = select.value;
    const sources = [...new Set(state.data.rebalance.map(p => p.from))].sort();
    select.replaceChildren(el("option", {value: "", text: "Todas"}), ...sources.map(m => el("option", {value: m, text: m})));
    if (sources.includes(keep)) select.value = keep;
    const rows = state.data.rebalance.filter(p => !select.value || p.from === select.value);
    const box = $("balance");
    if (!rows.length) { box.replaceChildren(el("p", {class: "empty", text: "A carga já está equilibrada: nenhuma mudança encurta a fila mais longa."})); updateBulk(); return; }
    box.replaceChildren(...rows.map(p => {
      const id = moveId(p);
      const check = el("input", {type: "checkbox", "aria-label": `Selecionar ${p.of} ${p.profile}`, checked: state.selectedBalance.has(id)});
      check.addEventListener("change", () => { check.checked ? state.selectedBalance.add(id) : state.selectedBalance.delete(id); updateBulk(); });
      return el("div", {class: "card"}, check,
        el("div", {},
          el("h3", {text: `${p.of} · ${p.profile} · operação ${p.operation}`}),
          el("p", {}, p.late ? el("span", {class: "pill late", text: `${p.late} em atraso`}) : null, ` ${p.customer} · ${p.occurrences} operações · ${p.origin}`),
          el("p", {class: "move"}, el("b", {text: p.from}), ` ${nf.format(p.from_weeks[0])} → ${nf.format(p.from_weeks[1])} sem.   ⟶   `,
            el("b", {text: p.to}), ` ${nf.format(p.to_weeks[0])} → ${nf.format(p.to_weeks[1])} sem.`),
          el("p", {text: `${nh(p.hours_from)} na ${p.from} passam a ~${nh(p.hours_to)} na ${p.to} · ${p.process || "processo por indicar"} · ${p.eligibility}`}),
          p.conditions.length ? el("p", {}, ...p.conditions.slice(0, 3).map(c => el("span", {class: "pill cond", text: `confirmar ${CONDITIONS[c] || c.replaceAll("_", " ")}`}))) : null),
        el("div", {class: "go"}, el("button", {type: "button", class: "primary", text: `Mudar para ${p.to}`, disabled: busy(), onclick: () => applyMoves([p]).catch(showError)})));
    }));
    updateBulk();
  }

  async function applyMoves(moves) {
    for (const area of new Set(moves.map(p => p.area))) {
      const targets = {};
      for (const p of moves.filter(x => x.area === area)) for (const k of p.keys) targets[k] = p.to_id;
      await write(area, {mode: "assign_each", targets, reason: moves.length === 1 ? `Equilíbrio de carga: ${moves[0].from} → ${moves[0].to}` : "Equilíbrio de carga (painel de máquinas)"},
        moves.length === 1 ? `${moves[0].of} mudado para ${moves[0].to}` : `${moves.length} lotes mudados`);
    }
  }

  // ------------------------------------------------------------- history and undo

  async function renderHistory() {
    const lists = await Promise.all(areas().map(a => call(`/maquinas/acoes?setor=${a}`).then(r => r.actions.map(x => ({...x, area: a})))));
    const actions = lists.flat().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    const box = $("history");
    if (!actions.length) { box.replaceChildren(el("p", {class: "empty", text: "Ainda não há decisões de máquina."})); return; }
    const modes = {assign: "Atribuição", prefer: "Preferência", automatic: "Voltar ao automático", accept_suggestions: "Sugestões aceites",
      assign_each: "Mudanças de máquina", future_preference: "Preferência futura", undo: "Desfeito"};
    box.replaceChildren(...actions.slice(0, 80).map(a => el("div", {class: "card"}, el("span", {}),
      el("div", {}, el("h3", {text: `${modes[a.mode] || a.mode} · ${a.summary?.changed ?? a.summary?.restored ?? 0} operações`}),
        el("p", {text: `${String(a.created_at).slice(0, 16).replace("T", " ")} · ${a.actor} · ${a.area === "perfis" ? "MTG2" : "MTG3"}${a.reason ? ` · ${a.reason}` : ""}`})),
      el("div", {class: "go"}, a.mode !== "undo" && !a.undone ? el("button", {type: "button", text: "Desfazer", onclick: () => undoAction({area: a.area, id: a.id}).catch(showError)})
        : el("span", {class: "pill", text: a.undone ? "desfeita" : "—"})))));
  }

  async function undoAction(undo) {
    const before = JSON.stringify(state.data.stamps);
    const done = await call("/maquinas/desfazer", {setor: undo.area, request_id: crypto.randomUUID(), action_id: undo.id});
    if (done.restored) state.lastStamps = before;
    toast(`Desfeito: ${done.restored} operações repostas${done.skipped_changed_later ? `; ${done.skipped_changed_later} mudadas depois ficaram como estão` : ""}.`);
    await load({quiet: true});
    if (state.tab === "history") await renderHistory();
  }

  // ------------------------------------------------------------- wiring

  for (const b of document.querySelectorAll(".seg button")) b.addEventListener("click", () => {
    state.area = b.dataset.area; state.shown = PAGE; state.selectedSuggest.clear(); state.selectedBalance.clear();
    document.querySelectorAll(".seg button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    load().catch(showError);
  });
  $("scenario").addEventListener("change", () => load().catch(showError));
  for (const t of ["load", "suggest", "balance", "history"]) $(`tab-${t}`).addEventListener("click", () => tab(t));
  for (const id of ["suggest-machine", "suggest-late"]) $(id).addEventListener("change", () => { state.shown = PAGE; renderSuggestions(); });
  $("suggest-q").addEventListener("input", () => { state.shown = PAGE; renderSuggestions(); });
  $("suggest-more").addEventListener("click", () => { state.shown += PAGE; renderSuggestions(); });
  $("balance-from").addEventListener("change", renderBalance);
  $("suggest-accept-selected").addEventListener("click", () => acceptSuggestions(state.data.suggestions.filter(g => state.selectedSuggest.has(groupId(g)))).catch(showError));
  $("balance-apply-selected").addEventListener("click", () => applyMoves(state.data.rebalance.filter(p => state.selectedBalance.has(moveId(p)))).catch(showError));
  $("choose-cancel").addEventListener("click", () => $("choose").close());
  $("suggest-select-all").addEventListener("click", () => {
    for (const g of filteredSuggestions().slice(0, state.shown)) state.selectedSuggest.add(groupId(g)); renderSuggestions();
  });
  $("balance-select-all").addEventListener("click", () => {
    for (const p of state.data.rebalance.filter(p => !$("balance-from").value || p.from === $("balance-from").value)) state.selectedBalance.add(moveId(p)); renderBalance();
  });
  document.addEventListener("DOMContentLoaded", () => load().catch(showError));
})();
