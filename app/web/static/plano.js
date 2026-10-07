(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const DAYS = 7, FIRST_ROWS = 10;  // uma semana (seg–dom) por máquina, com os dias (pedido de 06/10/2026)
  const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
  const state = {sector: "cantoneiras", data: null, offset: 0, showAll: false, showIdle: false, loading: 0, day: null, dayMachine: null, dayData: null, dayLoading: 0};

  const el = (tag, text, cls) => {const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n};
  const day = iso => new Date(iso.slice(0, 10) + "T12:00:00Z");
  const iso = d => d.toISOString().slice(0, 10);
  const addDays = (d, n) => {const r = new Date(d); r.setUTCDate(r.getUTCDate() + n); return r};
  const between = (a, b) => Math.round((b - a) / 86400000);
  const short = value => value ? value.slice(8, 10) + "/" + value.slice(5, 7) : "—";
  const number = value => Math.round(value || 0).toLocaleString("pt-PT");
  const plural = (n, one, many) => `${number(n)} ${n === 1 ? one : many}`;
  // Peças por confirmar nunca aparecem como 0 (08/10): null = nenhuma conhecida; «unknown» linhas sem saldo à parte.
  const pieces = (n, unknown) => n === null || n === undefined ? "peças por confirmar"
    : `${plural(n, "peça", "peças")}${unknown ? ` (+${plural(unknown, "linha", "linhas")} por confirmar)` : ""}`;
  const todayIso = () => state.data?.today || iso(new Date());
  const monday = value => {const d = day(value); return addDays(d, -((d.getUTCDay() + 6) % 7))};
  const hours = value => (Math.round((value || 0) * 10) / 10).toLocaleString("pt-PT");
  const isoWeek = d => {const t = new Date(d); t.setUTCDate(t.getUTCDate() + 3 - ((t.getUTCDay() + 6) % 7)); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
    return 1 + Math.round(((t - y) / 86400000 - 3 + ((y.getUTCDay() + 6) % 7)) / 7)};
  const mondayOf = (year, week) => {const j4 = new Date(Date.UTC(year, 0, 4)); return addDays(j4, -((j4.getUTCDay() + 6) % 7) + (week - 1) * 7)};

  function notice(message, error = false) {
    const box = $("notice");
    box.hidden = !message; box.textContent = message || ""; box.classList.toggle("error", error);
  }

  async function load(quiet = false) {
    const serial = ++state.loading;
    if (!quiet) $("source").textContent = "A carregar o plano…";
    try {
      const response = await fetch(`/planeamento/api/setor/quadro?setor=${encodeURIComponent(state.sector)}`, {cache: "no-store"});
      const result = await response.json().catch(() => ({}));
      if (serial !== state.loading) return;
      if (response.status === 404) throw Error("Esta página precisa que o serviço do planeamento seja reiniciado para ficar ativa.");
      if (!response.ok) throw Error(result.error || result.detail || `Erro ${response.status}`);
      // Versão anterior enquanto o servidor refaz o quadro (07/10/2026): volta a pedir de 8 em 8 s, sem aviso, e
      // só volta a desenhar quando chega outra versão (o dia aberto e a página não saltam a cada pedido).
      const again = () => setTimeout(() => { if (serial === state.loading) load(true); }, 8000);
      if (quiet && result.stale && result.imported_at === state.data?.imported_at) return again();
      state.data = result; notice("");
      render(); sourceNotice();
      if (state.day) openDay(state.day, state.dayMachine, false);
      if (result.stale) again();
    } catch (error) {
      if (serial !== state.loading) return;
      if (!quiet) $("source").textContent = "";
      notice(error.message || "Não foi possível carregar o plano.", true);
    }
  }

  function render() {
    const d = state.data;
    const imported = d.imported_at ? new Date(d.imported_at).toLocaleString("pt-PT", {timeZone: "Europe/Lisbon", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"}) : "—";
    $("source").textContent = d.source.kind === "aceite"
      ? `${d.sector_label} · plano aceite «${d.source.name}» de ${short(d.source.accepted_at)} · dados do Excel de ${imported}`
      : d.source.kind === "automatica"
        ? `${d.sector_label} · proposta automática (não aceite; o Excel é o plano oficial) · ${number(d.source.placed)} de ${number(d.source.operations)} operações com hora · as restantes no dia da Tabela · dados de ${imported}`
        : `${d.sector_label} · máquina e dia tirados do planeamento (Excel) · dados de ${imported}`;
    renderAlert(); renderBoard();
  }

  // Excel do setor no Drive mais recente do que o importado (08/10): uma linha, só quando a API a manda.
  function sourceNotice() {
    const box = $("source-notice");
    if (!box) return;
    box.hidden = !state.data?.source_notice; box.textContent = state.data?.source_notice || "";
  }

  // --- Lista vermelha

  function renderAlert() {
    const {orders} = state.data.unplanned, outside = state.data.not_in_plans || [];
    $("alert").hidden = !orders.length && !outside.length;
    $("all-planned").hidden = Boolean(orders.length || outside.length);
    $("alert-count").textContent = number(orders.length);
    $("alert-title").textContent = orders.length === 1 ? "OF por planear" : "OF por planear";
    const list = $("alert-list"); list.replaceChildren();
    for (const order of state.showAll ? orders : orders.slice(0, FIRST_ROWS)) list.append(orderRow(order));
    const more = $("alert-more");
    more.hidden = orders.length <= FIRST_ROWS;
    more.textContent = state.showAll ? "Mostrar só as 10 mais urgentes" : `Ver todas as ${number(orders.length)} OF por planear`;
    $("cpis").hidden = !outside.length;
    $("cpis-title").textContent = `+ ${plural(outside.length, "OF entrou", "OF entraram")} no CPIS nos últimos 3 meses e não ${outside.length === 1 ? "está" : "estão"} em nenhum plano`;
    const body = $("cpis-list"); body.replaceChildren();
    for (const row of outside) {
      const tr = el("tr");
      tr.append(el("td", row.of), el("td", row.customer), el("td", row.family),
        el("td", `${short(row.registered)} · há ${plural(row.waiting_days, "dia", "dias")}`), el("td", short(row.delivery)));
      body.append(tr);
    }
  }

  function orderRow(order) {
    const li = el("li", null, "pq-of");
    const id = el("div", order.of, "pq-of-id");
    if (order.waiting_days != null) id.append(el("small", `entrou há ${plural(order.waiting_days, "dia", "dias")}`));
    const who = el("div", null, "pq-of-who");
    who.append(el("strong", order.customer), el("span", order.designation || order.family));
    const tags = el("div", null, "pq-tags");
    if (order.priority != null) tags.append(el("span", `${order.priority}.ª prioridade`, "pq-tag priority"));
    if (order.partial) tags.append(el("span", `Falta máquina em ${order.lines} de ${order.lines_total} linhas`, "pq-tag"));
    for (const warning of order.warnings) tags.append(el("span", warning, "pq-tag"));
    if (tags.childElementCount) who.append(tags);
    const size = el("div", null, "pq-of-size");
    size.append(el("strong", `${number(order.metres)} m`), el("span", pieces(order.pieces, order.pieces_unknown)));
    const today = day(todayIso());
    const when = el("div", null, "pq-of-when");
    if (order.late_days > 0) when.append(el("strong", `Atrasada ${plural(order.late_days, "dia", "dias")}`), el("span", `prazo ${short(order.due)}`));
    else if (order.due) {
      when.classList.add("on-time");
      const left = between(today, day(order.due));
      when.append(el("strong", `Prazo ${short(order.due)}`), el("span", left === 0 ? "é hoje" : `faltam ${plural(left, "dia", "dias")}`));
    } else {when.classList.add("on-time"); when.append(el("strong", "Sem prazo"))}
    const actions = el("div", null, "pq-of-actions");
    if (order.marked) actions.append(el("span", "Marcada · falta máquina", "pq-marked"));
    // Desde 07/10/2026 o Planear dá a máquina sugerida às linhas sem máquina, também às já marcadas: o botão
    // aparece sempre que o servidor diz que há linhas por planear (`plannable`).
    if ((order.plannable === undefined && !order.marked) || order.plannable > 0) {
      const plan = el("button", "Planear", "pq-plan"); plan.type = "button";
      plan.title = "Planeia as linhas desta OF. As que não têm máquina recebem a máquina sugerida (podes mudar).";
      plan.addEventListener("click", () => planOrder(order, plan));
      actions.append(plan);
    }
    const give = el("a", "Dar máquina");
    give.href = `/planeamento/raw?area=${encodeURIComponent(state.sector)}&q=${encodeURIComponent(order.of)}&mostrar=machine,cut_date`;
    actions.append(give);
    li.append(id, who, size, when, actions);
    return li;
  }

  async function planOrder(order, button) {
    button.disabled = true; button.textContent = "A marcar…";
    try {
      const response = await fetch("/planeamento/api/carteira/selecao", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({setor: state.sector, vista: "of_perfil", caminho: [order.of], filtros: {},
                              acao: "selecionar", request_id: crypto.randomUUID()}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(result.error || result.detail || `Erro ${response.status}`);
      const skipped = result.skipped_no_machine || 0;
      const suggested = result.suggested_machine || 0;  // 07/10/2026: sem máquina, o Planear usa a sugerida
      notice(`${order.of}: ${result.planned ?? result.changed ?? 0} linha(s) planeada(s)` +
             (suggested ? `; ${suggested} com a máquina sugerida (podes mudar)` : '') + '.' +
             (skipped ? ` ${skipped} sem máquina ficaram por planear — dá-lhes Máquina na Tabela.` : ''));
      await load();
    } catch (error) {
      button.disabled = false; button.textContent = "Planear";
      notice(`Não foi possível marcar ${order.of}: ${error.message}`, true);
    }
  }

  // --- Quadro das máquinas

  function windowStart() {return addDays(monday(todayIso()), state.offset * 7)}

  function renderBoard() {
    const start = windowStart(), end = addDays(start, DAYS), today = todayIso();
    $("range").textContent = `Semana ${isoWeek(start)} · ${short(iso(start))} a ${short(iso(addDays(end, -1)))}`;
    const machines = state.data.machines.map(m => ({...m, visible: m.boxes.filter(b => day(b.end) > start && day(b.start) < end)}));
    const busy = machines.filter(m => m.visible.length), idle = machines.filter(m => !m.visible.length);
    const total = machines.reduce((n, m) => n + m.boxes.length, 0);
    renderBehind(today);
    renderElsewhere(); renderMissing();
    const gantt = $("gantt"), empty = $("empty");
    gantt.replaceChildren();
    const shown = state.showIdle ? [...busy, ...idle] : busy;
    gantt.hidden = !shown.length;
    empty.hidden = Boolean(busy.length);
    if (!busy.length) renderEmpty(total, start);
    const toggle = $("idle-toggle");
    toggle.hidden = !idle.length || !total;
    toggle.textContent = state.showIdle ? "Esconder as máquinas sem trabalho" : `Mostrar as ${plural(idle.length, "máquina", "máquinas")} sem trabalho nesta semana`;
    if (!shown.length) return;

    const grid = el("div", null, "pq-grid pq-head");
    grid.style.setProperty("--q-days", DAYS);
    grid.append(el("div", "Máquina", "corner"));
    for (let i = 0; i < DAYS; i++) {
      const d = addDays(start, i), cell = el(state.data.day_view ? "button" : "div", WEEKDAYS[d.getUTCDay()]);
      cell.append(el("b", short(iso(d))));
      if (state.data.day_view) {  // ver o dia com as horas e os turnos de todas as máquinas do setor
        cell.type = "button"; cell.className = "pq-day-link"; cell.dataset.day = iso(d);
        cell.title = `Ver ${WEEKDAYS[d.getUTCDay()].toLowerCase()} ${short(iso(d))} hora a hora, por turno`;
        cell.addEventListener("click", () => openDay(iso(d), null));
      }
      if ([0, 6].includes(d.getUTCDay())) cell.classList.add("weekend");
      if (iso(d) === today) cell.classList.add("today");
      grid.append(cell);
    }
    gantt.append(grid);
    for (const machine of shown) gantt.append(machineRow(machine, start, today));
  }

  // Caixas cujo último dia já passou mas que continuam no plano (ainda falta fazer): vermelhas e listadas à parte.
  const overdue = box => box.late || box.end <= todayIso();

  function renderBehind(today) {
    const behind = state.data.machines.flatMap(m => m.boxes.filter(b => b.end <= today).map(b => ({box: b, machine: m})))
      .sort((a, b) => a.box.start.localeCompare(b.box.start));
    const box = $("behind"); box.replaceChildren(); box.hidden = !behind.length;
    if (!behind.length) return;
    box.append(el("strong", `Ficaram para trás: ${plural(behind.length, "OF tinha", "OF tinham")} dia marcado antes de hoje e ainda falta fazer.`));
    const list = el("div");
    for (const {box: b, machine} of behind) {
      const chip = el("button", `${b.of} · ${machine.name} · ${short(b.start)}`); chip.type = "button";
      chip.addEventListener("click", () => openBox(b, machine));
      list.append(chip);
    }
    box.append(list);
  }

  function machineRow(machine, start, today) {
    const lanes = [], placed = [];
    for (const box of [...machine.visible].sort((a, b) => a.start.localeCompare(b.start) || a.of.localeCompare(b.of))) {
      const from = Math.max(0, between(start, day(box.start))), to = Math.min(DAYS, between(start, day(box.end)));
      let lane = lanes.findIndex(last => last <= from);
      if (lane < 0) {lane = lanes.length; lanes.push(0)}
      lanes[lane] = to;
      placed.push({box, from, to, lane});
    }
    const rows = Math.max(1, lanes.length);
    const row = el("div", null, "pq-grid pq-row");
    row.style.setProperty("--q-days", DAYS);
    row.dataset.id = machine.id;
    const label = el("div", null, "pq-machine");
    label.style.gridRow = `1 / span ${rows}`;
    const orders = new Set(machine.visible.map(b => b.of)).size;
    label.append(el("strong", machine.name), el("span", orders ? plural(orders, "OF", "OF") : "Sem trabalho"));
    row.append(label);
    for (let i = 0; i < DAYS; i++) {
      const d = addDays(start, i), cell = el("div", null, "pq-cell");
      cell.style.gridColumn = String(i + 2); cell.style.gridRow = `1 / span ${rows}`;
      if ([0, 6].includes(d.getUTCDay())) cell.classList.add("weekend");
      if (iso(d) === today) cell.classList.add("today");
      if (state.data.day_view) {cell.classList.add("clickable"); cell.title = `${machine.name} · ${short(iso(d))} hora a hora`; cell.addEventListener("click", () => openDay(iso(d), machine.id))}
      if (machine.days) {  // horas planeadas / horas do calendário nesse dia
        const date = iso(d), capacity = machine.days[date] || 0;
        const planned = machine.boxes.reduce((n, b) => n + ((b.days || []).find(x => x.date === date)?.hours || 0), 0);
        if (capacity || planned) {
          const tag = el("span", `${hours(planned)} / ${hours(capacity)} h`, "pq-load" + (planned > capacity + 0.05 ? " over" : ""));
          tag.title = `Planeado ${hours(planned)} h de ${hours(capacity)} h de turnos`;
          cell.append(tag);
        }
      }
      row.append(cell);
    }
    for (const {box, from, to, lane} of placed) {
      const late = overdue(box), button = el("button", null, "pq-box" + (late ? " late" : "") + (box.approximate ? " approximate" : "") +
        (day(box.start) < start ? " cut-start" : "") + (between(start, day(box.end)) > DAYS ? " cut-end" : "") + (to - from < 2 ? " narrow" : ""));
      button.type = "button";
      button.style.gridColumn = `${from + 2} / ${to + 2}`; button.style.gridRow = String(lane + 1);
      button.append(el("b", box.of), el("span", box.customer || box.designation || ""),
        el("span", box.hours ? `${hours(box.hours)} h · ${pieces(box.pieces, box.pieces_unknown)}` : pieces(box.pieces, box.pieces_unknown)));
      if (box.forecast) button.classList.add("approximate");
      button.setAttribute("aria-label", `${box.of}, ${box.customer || ""}, ${machine.name}, de ${short(box.start)} a ${short(lastDay(box))}${late ? ", atrasada" : ""}`);
      button.addEventListener("click", () => openBox(box, machine));
      row.append(button);
    }
    return row;
  }

  const lastDay = box => iso(addDays(day(box.end), -1));

  function renderEmpty(total, start) {
    const empty = $("empty"); empty.replaceChildren();
    if (total) {
      const all = state.data.machines.flatMap(m => m.boxes);
      const next = all.filter(b => day(b.start) >= start).sort((a, b) => a.start.localeCompare(b.start))[0];
      empty.append(el("strong", "Nesta semana não há nada no plano."));
      if (next) {
        const jump = el("button", `Ir para o próximo trabalho (${short(next.start)})`); jump.type = "button";
        jump.addEventListener("click", () => {state.offset = Math.floor(between(monday(todayIso()), monday(next.start)) / 7); renderBoard()});
        empty.append(jump);
      } else empty.append(el("span", "Usa ◀ para ver as semanas anteriores."));
      return;
    }
    empty.append(el("strong", "Ainda não há nada no plano."), el("span", "Para uma OF aparecer aqui:"));
    const steps = el("ol");
    steps.append(el("li", "Carrega em «Planear» na lista vermelha (ou na Carteira)."), el("li", "Na Tabela, escreve a Máquina e a Data de corte (é o dia em que aparece aqui)."));
    empty.append(steps);
    const selected = state.data.source.selected_orders || 0;
    if (selected) empty.append(el("p", `Já ${selected === 1 ? "há 1 OF marcada" : `há ${number(selected)} OF marcadas`}; falta máquina ou dia.`));
  }

  function openBox(box, machine) {
    const late = overdue(box), passed = box.end <= todayIso();
    const title = $("dialog-title"); title.textContent = box.of; title.classList.toggle("late", late);
    const body = $("dialog-body"); body.replaceChildren();
    const when = box.approximate ? `Semana de ${short(box.start)} (o dia ainda não está definido)` :
      box.start === lastDay(box) ? `Dia ${short(box.start)}` : `De ${short(box.start)} a ${short(lastDay(box))}`;
    const whenText = passed ? `${when} · já passou e ainda falta fazer` : when;
    const perDay = (box.days || []).filter(x => x.hours).map(x => `${short(x.date)} ${hours(x.hours)} h`).join(" · ");
    const rows = [["Cliente", box.customer || "—"], ["Descrição da obra", box.designation || "—"], ["Máquina", machine.name], ["Quando", whenText, passed ? "late" : ""],
      ["Horas", box.hours ? `${hours(box.hours)} h${box.hours_estimated ? " (estimativa)" : ""}${perDay ? ` · ${perDay}` : ""}${box.hours_unknown ? ` · ${box.hours_unknown} sem horas` : ""}` : "Por calcular"],
      ...(box.shifts?.length ? [["Turnos", shiftText(box.shifts)]] : []),
      ["Faltam fazer", `${pieces(box.pieces, box.pieces_unknown)}${box.lines > 1 ? ` (${box.lines} linhas)` : ""}`],
      ["Prazo", box.due ? `${short(box.due)}${box.late ? " · vai ficar atrasada" : ""}` : "Sem prazo", box.late ? "late" : ""]];
    for (const [label, value, cls] of rows) body.append(el("dt", label), el("dd", value, cls));
    const actions = $("dialog-actions"); actions.replaceChildren();
    const open = el("a", "Ver na Carteira");
    open.href = `/planeamento/carteira?setor=${encodeURIComponent(state.sector)}&vista=of&q=${encodeURIComponent(box.of)}`;
    const close = el("button", "Fechar"); close.value = "close";
    actions.append(open);
    if (state.data?.day_view && !box.approximate && !state.day) {
      const see = el("button", `Ver o dia ${short(box.start < todayIso() && lastDay(box) >= todayIso() ? todayIso() : box.start)}`); see.type = "button";
      see.addEventListener("click", () => {$("dialog").close(); openDay(box.start < todayIso() && lastDay(box) >= todayIso() ? todayIso() : box.start, machine.id)});
      actions.append(see);
    }
    actions.append(close);
    $("dialog").showModal();
  }

  // «07/10 1.º 3,5 h · 2.º 7,5 h»: horas de uma caixa por dia e turno (turno vazio = fora do horário dos turnos)
  function shiftText(list) {
    const byDay = new Map();
    for (const s of list) {if (!byDay.has(s.date)) byDay.set(s.date, []); byDay.get(s.date).push(s)}
    return [...byDay].map(([d, items]) => `${short(d)} ${items.map(s => `${s.shift ? s.shift + ".º" : "sem hora"} ${hours(s.hours)} h`).join(" · ")}`).join(" | ");
  }

  function renderElsewhere() {
    const box = $("elsewhere"), info = state.data?.elsewhere;
    if (!box) return;
    box.hidden = !info?.operations;
    if (!info?.operations) return;
    box.querySelector("summary").textContent = `${plural(info.operations, "operação deste setor está", "operações deste setor estão")} em máquinas de outro setor: ` +
      info.machines.map(m => `${m.name} (${plural(m.orders, "OF", "OF")}, ${hours(m.hours)} h)`).join(" · ");
    const list = box.querySelector("ul"); list.replaceChildren();
    for (const m of info.machines) for (const it of m.items) list.append(el("li", `${it.of} · ${m.name} · ${short(it.start)}`));
  }

  // 2.ª operação das cantoneiras fora do plano (08/10): uma linha discreta, só quando a API manda o número e é > 0.
  function renderSecondOperation() {
    const box = $("missing"), n = state.data?.source?.second_operation || 0;
    if (!box) return;
    let line = $("second-operation");
    if (!line) {
      line = el("p", null, "pq-sub"); line.id = "second-operation"; line.hidden = true;
      box.after(line);
    }
    line.hidden = !n;
    line.textContent = n ? `${plural(n, "operação", "operações")} de 2.ª operação fora do plano` : "";
  }

  // Operações escolhidas que não ficam em caixa nenhuma: ditas com o motivo, nunca escondidas.
  function renderMissing() {
    const box = $("missing"), list = state.data?.source?.missing || [];
    renderSecondOperation();
    if (!box) return;
    box.hidden = !list.length;
    if (!list.length) return;
    // As que a proposta não coloca mas têm previsão da Tabela aparecem só como previsão: ditas à parte.
    const forecast = list.filter(op => op.forecast), gone = list.length - forecast.length;
    box.querySelector("summary").textContent = [
      gone ? `${plural(gone, "operação planeada não aparece", "operações planeadas não aparecem")} no quadro (sem dia ou sem máquina)` : "",
      forecast.length ? `${plural(forecast.length, "operação planeada fica", "operações planeadas ficam")} fora da proposta automática (só previsão da Tabela)` : ""].filter(Boolean).join(" · ");
    const ul = box.querySelector("ul"); ul.replaceChildren();
    for (const op of list) ul.append(el("li", `${op.of} · ${op.reference || ""} · ${op.operation || ""}: ${op.reasons.join("; ") || "motivo por indicar"}` +
      (op.forecast ? ` (previsão a ${op.forecast_day ? short(op.forecast_day) : "—"})` : "")));
  }

  // --- Dia hora a hora (pedido de 06/10/2026): eixo 00–24, faixas dos turnos, trabalho com hora e totais por turno

  const pxHour = () => innerWidth <= 600 ? 30 : 44;
  const at = (value, start) => (Date.parse(value) - Date.parse(start)) / 3600000 * pxHour();
  const clock = value => new Date(value).toLocaleTimeString("pt-PT", {timeZone: "Europe/Lisbon", hour: "2-digit", minute: "2-digit"});
  const shiftName = (s, dayIso) => `${s.shift}.º turno${s.shift_date && s.shift_date !== dayIso ? ` de ${WEEKDAYS[day(s.shift_date).getUTCDay()].toLowerCase()} ${short(s.shift_date)}` : ""}`;

  function setDayUrl(push) {
    const url = new URL(location.href);
    if (state.day) url.searchParams.set("dia", state.day); else url.searchParams.delete("dia");
    if (state.day && state.dayMachine) url.searchParams.set("maquina", state.dayMachine); else url.searchParams.delete("maquina");
    if (push) history.pushState(null, "", url); else history.replaceState(null, "", url);
  }

  async function openDay(dayIso, machineId, push = true) {
    state.day = dayIso; state.dayMachine = machineId || null; setDayUrl(push);
    $("week-board").hidden = true; $("day").hidden = false;
    if (push) $("day").scrollIntoView({block: "start"});
    const machine = state.data?.machines.find(m => m.id === machineId);
    $("day-title").textContent = `${WEEKDAYS[day(dayIso).getUTCDay()]} ${short(dayIso)}${machine ? ` · ${machine.name}` : " · todas as máquinas do setor"}`;
    $("day-all").hidden = !machineId;
    $("day-content").replaceChildren(el("p", "A carregar o dia…", "pq-sub"));
    const serial = ++state.dayLoading;
    try {
      const query = new URLSearchParams({setor: state.sector, dia: dayIso}); if (machineId) query.set("maquina", machineId);
      const response = await fetch(`/planeamento/api/setor/quadro/dia?${query}`, {cache: "no-store"});
      const result = await response.json().catch(() => ({}));
      if (serial !== state.dayLoading) return;
      if (response.status === 404 && !result.error) throw Error("A vista do dia precisa que o serviço do planeamento seja reiniciado.");
      if (!response.ok) throw Error(result.error || result.detail || `Erro ${response.status}`);
      state.dayData = result; renderDay();
    } catch (error) {
      if (serial !== state.dayLoading) return;
      $("day-content").replaceChildren(el("p", error.message || "Não foi possível carregar o dia.", "pq-notice error"));
    }
  }

  function closeDay(push = true) {
    state.day = null; state.dayMachine = null; state.dayData = null; setDayUrl(push);
    $("day").hidden = true; $("week-board").hidden = false;
  }

  function renderDay() {
    const d = state.dayData, width = at(d.end, d.start), content = $("day-content");
    content.replaceChildren();
    const scroll = el("div", null, "pq-day-scroll"), table = el("div", null, "pq-day-grid");
    table.style.setProperty("--q-track", `${Math.round(width)}px`);
    const head = el("div", null, "pq-day-row pq-day-head"), corner = el("div", "Máquina", "pq-day-label"), axis = el("div", null, "pq-track");
    for (const b of d.bands) {
      const band = el("div", `${shiftName(b, d.day)} · ${b.from}–${b.to}`, "pq-band");
      band.style.left = `${at(b.start, d.start)}px`; band.style.width = `${Math.max(2, at(b.end, d.start) - at(b.start, d.start))}px`;
      axis.append(band);
    }
    for (const t of d.ticks) {const tick = el("span", t.label, "pq-tick"); tick.style.left = `${at(t.at, d.start)}px`; axis.append(tick)}
    head.append(corner, axis); table.append(head);
    const now = Date.now(), nowInside = now >= Date.parse(d.start) && now < Date.parse(d.end);
    for (const m of d.machines) {
      const row = el("div", null, "pq-day-row"); row.dataset.id = m.id;
      const label = el("div", null, "pq-day-label");
      label.append(el("strong", m.name));
      for (const s of m.shifts) label.append(el("span", `${shiftName(s, d.day)}: ${hours(s.planned)} / ${hours(s.capacity)} h`, "pq-shift-total" + (s.planned > s.capacity + 0.05 ? " over" : "")));
      if (m.day.untimed) label.append(el("span", `Sem hora marcada: ${hours(m.day.untimed)} h`, "pq-shift-total"));
      label.append(el("span", `Dia: ${hours(m.day.planned)} / ${hours(m.day.capacity)} h`, "pq-day-total"));
      const track = el("div", null, "pq-track");
      for (const w of m.windows) {const win = el("div", null, "pq-window"); win.style.left = `${at(w.start, d.start)}px`; win.style.width = `${at(w.end, d.start) - at(w.start, d.start)}px`; win.title = `${w.shift ? w.shift + ".º turno" : "Fora de turno"} · ${clock(w.start)}–${clock(w.end)}`; track.append(win)}
      for (const g of m.segments) {
        const seg = el("button", null, "pq-seg" + (g.late ? " late" : "")); seg.type = "button";
        seg.style.left = `${at(g.start, d.start)}px`; seg.style.width = `${Math.max(3, at(g.end, d.start) - at(g.start, d.start))}px`;
        const refs = g.references.length === 1 ? g.references[0] : g.references.length ? `${g.references.length} ref.` : "";
        seg.append(el("b", g.of), el("span", [refs, `${hours(g.hours)} h`].filter(Boolean).join(" · ")));
        seg.title = `${g.of} · ${clock(g.start)}–${clock(g.end)} · ${g.shift ? shiftName(g, d.day) : "fora do horário dos turnos"} · ${hours(g.hours)} h`;
        seg.addEventListener("click", () => openSegment(g, m, d));
        track.append(seg);
      }
      if (nowInside) {const line = el("div", null, "pq-now"); line.style.left = `${at(new Date(now).toISOString(), d.start)}px`; line.title = "Agora"; track.append(line)}
      row.append(label, track); table.append(row);
      if (m.untimed.length) {
        const strip = el("div", null, "pq-untimed");
        const dayItems = m.untimed.filter(u => u.precision === "day"), weekItems = m.untimed.filter(u => u.precision === "week");
        if (dayItems.length) strip.append(el("span", "Sem hora marcada: " + dayItems.map(u => `${u.of}${u.hours ? ` (${hours(u.hours)} h${u.estimated ? ", estimativa" : ""})` : ""}`).join(" · ")));
        if (weekItems.length) strip.append(el("span", "Só se sabe a semana: " + weekItems.map(u => u.of).join(" · ")));
        table.append(strip);
      }
    }
    if (!d.machines.length) content.append(el("p", "Este setor não tem máquinas com calendário neste dia.", "pq-sub"));
    scroll.append(table); content.append(scroll);
    // Abrir já no trabalho (ou na hora atual, ou no 1.º turno), sobretudo no telemóvel.
    const firstSeg = d.machines.flatMap(m => m.segments).map(g => g.start).sort()[0];
    const firstWin = d.machines.flatMap(m => m.windows).map(w => w.start).sort()[0];
    const target = firstSeg || (nowInside ? new Date(now).toISOString() : firstWin);
    if (target) scroll.scrollLeft = Math.max(0, at(target, d.start) - 2 * pxHour());
    if (d.elsewhere?.operations) content.append(el("p", `${plural(d.elsewhere.operations, "operação deste setor está", "operações deste setor estão")} em máquinas de outro setor (não aparecem aqui).`, "pq-sub"));
  }

  function openSegment(g, m, d) {
    const title = $("dialog-title"); title.textContent = g.of; title.classList.toggle("late", g.late);
    const body = $("dialog-body"); body.replaceChildren();
    const rows = [["Cliente", g.customer || "—"], ["Máquina", m.name], ["Turno", g.shift ? shiftName(g, d.day) : "Fora do horário dos turnos"],
      ["Hora", `${clock(g.start)}–${clock(g.end)}${g.cut_start ? " (começou antes)" : ""}${g.cut_end ? " (continua depois)" : ""}`],
      ["Horas", `${hours(g.hours)} h`], ["Referências", g.references.join(", ") || "—"], ["Faltam fazer", pieces(g.pieces)]];
    for (const [label, value] of rows) body.append(el("dt", label), el("dd", value));
    const actions = $("dialog-actions"); actions.replaceChildren();
    const open = el("a", "Ver na Carteira"); open.href = `/planeamento/carteira?setor=${encodeURIComponent(state.sector)}&vista=of&q=${encodeURIComponent(g.of)}`;
    const close = el("button", "Fechar"); close.value = "close";
    actions.append(open, close);
    $("dialog").showModal();
  }

  // --- Arranque

  function chooseSector(sector) {
    state.sector = sector; state.showAll = false; state.showIdle = false;
    state.offset = state.weekStart ? Math.round(between(monday(iso(new Date())), state.weekStart) / 7) : 0;
    state.weekStart = null;
    for (const b of document.querySelectorAll("[data-sector]")) b.setAttribute("aria-pressed", String(b.dataset.sector === sector));
    try {localStorage.setItem("plano.setor", sector)} catch {}
    const url = new URL(location.href); url.searchParams.set("setor", sector); history.replaceState(null, "", url);
    load();
  }

  for (const b of document.querySelectorAll("[data-sector]")) b.addEventListener("click", () => chooseSector(b.dataset.sector));
  $("prev").addEventListener("click", () => {state.offset--; if (state.data) renderBoard()});
  $("next").addEventListener("click", () => {state.offset++; if (state.data) renderBoard()});
  $("today").addEventListener("click", () => {state.offset = 0; if (state.data) renderBoard()});
  $("alert-more").addEventListener("click", () => {state.showAll = !state.showAll; renderAlert()});
  $("idle-toggle").addEventListener("click", () => {state.showIdle = !state.showIdle; renderBoard()});
  const shiftDay = n => {const next = iso(addDays(day(state.day), n)); state.offset = Math.floor(between(monday(todayIso()), monday(next)) / 7); openDay(next, state.dayMachine)};
  $("day-prev").addEventListener("click", () => shiftDay(-1));
  $("day-next").addEventListener("click", () => shiftDay(1));
  $("day-back").addEventListener("click", () => {closeDay(); if (state.data) renderBoard()});
  $("day-all").addEventListener("click", () => openDay(state.day, null));
  window.addEventListener("popstate", () => {
    const q = new URLSearchParams(location.search), asked = q.get("dia");
    if (asked && /^\d{4}-\d{2}-\d{2}$/.test(asked)) openDay(asked, q.get("maquina"), false); else if (state.day) {closeDay(false); if (state.data) renderBoard()}
  });
  const askedDay = new URLSearchParams(location.search).get("dia");
  if (askedDay && /^\d{4}-\d{2}-\d{2}$/.test(askedDay)) {state.day = askedDay; state.dayMachine = new URLSearchParams(location.search).get("maquina"); state.weekStart = monday(askedDay)}
  const askedWeek = /^(\d{4})-W(\d{2})$/.exec(new URLSearchParams(location.search).get("semana") || "");
  if (askedWeek && !state.weekStart) state.weekStart = mondayOf(Number(askedWeek[1]), Number(askedWeek[2]));
  let initial = new URLSearchParams(location.search).get("setor");
  if (!initial) try {initial = localStorage.getItem("plano.setor")} catch {}
  chooseSector(["cantoneiras", "perfis"].includes(initial) ? initial : "cantoneiras");
})();
