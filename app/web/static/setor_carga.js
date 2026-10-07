'use strict';
// Carga e turnos (06/10/2026; tabela simples 07/10): máquina × semana «carga / capacidade h», atrasado à parte,
// recomendação por baixo; − / + turno no detalhe, com as OF.
// Também mostra o que as antigas páginas Capacidades e Disponibilidade mostravam (separador Máquinas,
// horas segundo o Excel, peso, horas reais declaradas, cálculo de cada operação, produção registada).
(() => {
  const $ = (id) => document.getElementById(id);
  const h = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 0});
  const h1 = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1});
  const DAYS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
  const KIND = {plan: 'no plano', due: 'a vencer', suggested: 'a vencer, máquina sugerida'};
  // Nomes com explicação no cursor (a mesma explicação em todas as páginas; ver static/nomes.json).
  const EXPLAIN = {
    previstas: 'Horas que a Carga usa: taxa confirmada da tabela de velocidades; senão histórico válido; senão velocidade mais recente do Excel (MTG3) ou taxa mm²/h da folha CapacidadeMáquinas (MTG2). Com margem e tempo fixo por peça das Definições.',
    excel: 'Horas pela regra do próprio Excel, só na operação principal: MTG3 metros em falta ÷ velocidade Mt\\h da linha; MTG2 área ÷ taxa da folha CapacidadeMáquinas (×3 no Thomas acima de 50 peças). Escalada ao saldo atual.',
    reais: 'Horas declaradas nas folhas OCR validadas e horas corrigidas à mão, pela data de produção.',
    capacidade: 'Horas dos turnos dessa semana no calendário da máquina (na semana atual, só as que faltam).',
    calendarioExcel: 'Turnos × horas por turno da folha PlanDisponibilidadeSemanal do Excel (só MTG2).',
  };
  let data = null, open = null, ticket = 0, loads = 0;
  const view = () => new URLSearchParams(location.search).get('vista') === 'maquinas' ? 'maquinas' : 'semanas';

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') node.className = v; else if (k === 'dataset') Object.assign(node.dataset, v); else node.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }
  const short = (n) => String(n || '').replace(/^Ficep\s+/i, '');
  const dm = (iso) => { const [, m, d] = String(iso).slice(0, 10).split('-'); return `${d}/${m}`; };
  const hrs = (v) => v === null || v === undefined ? '—' : `${h1.format(v)} h`;
  // Desconhecido nunca aparece como 0 (08/10): «—» quando nada se sabe; senão o conhecido com «(N sem …)».
  const known = (v, unknown, fmt, what) => v === null || v === undefined || (!v && unknown) ? '—'
    : `${fmt.format(v)}${unknown ? ` (+${unknown} ${what})` : ''}`;
  // Atrasado por tipo (08/10); com a Python antiga (sem os campos) fica só o total.
  const lateKinds = (lb) => lb && lb.plan !== undefined
    ? `no plano ${h1.format(lb.plan)} h · a vencer ${h1.format(lb.due)} h · sugerida ${h1.format(lb.suggested)} h` : '';
  const named = (label, key) => el('span', {title: EXPLAIN[key], class: 'named'}, label);
  const error = (e) => { $('error').textContent = e.message; $('error').hidden = false; };
  const notice = (t) => { $('notice').textContent = t; $('notice').hidden = false; $('error').hidden = true; };
  async function getJson(url) {
    const r = await fetch(url, {headers: {Accept: 'application/json'}});
    const body = await r.json().catch(() => ({}));
    if (r.status === 404 && !body.error) throw new Error('Esta parte precisa que o serviço do planeamento seja reiniciado.');
    if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
    return body;
  }

  async function shiftsChange(mudancas, label) {
    const r = await fetch('/planeamento/api/setor/turnos', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
      body: JSON.stringify({setor: $('setor').value, request_id: crypto.randomUUID(), mudancas})});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
    notice(`${label}: ${body.changed} semana(s) atualizadas.`);
    await load();
  }

  // Formato novo da API (07/10/2026): atrasado à parte (late_before) e capacidade da semana inteira (full_capacity).
  // Com a resposta antiga (sem late_before) a semana atual mostra a carga com o atrasado, como antes.
  const modern = () => data.machines.some((m) => m.late_before !== undefined);
  const hasCalendar = (m) => m.has_calendar !== undefined ? m.has_calendar : m.weeks.some((w) => w.status !== 'sem_calendario');
  const totalOf = (m) => (data.totals || []).find((t) => t.id === m.id) || null;
  const capOf = (w) => w.full_capacity !== undefined ? w.full_capacity : w.capacity;
  const turnos = (n) => `${n > 0 ? '+' : '−'}${Math.abs(n)} turno${Math.abs(n) > 1 ? 's' : ''}`;
  const adviceTitle = (a) => `${a.text || ''}${a.still_missing && !/ficam a faltar/.test(a.text || '') ? ` · mesmo assim faltam ${h.format(a.still_missing)} h` : ''}`;
  const isOpen = (m, w) => open && open.m === m.id && open.w === w.week && open.y === w.year;
  const change = (m, w, n) => shiftsChange([{maquina: m.id, ano: w.year, semana: w.week, turnos: n}], `${short(m.name)} S${w.week}`).catch(error);

  function cell(m, w) {
    const advice = w.advice || {};
    const apply = advice.delta ? el('button', {type: 'button', class: 'apply small', title: adviceTitle(advice)}, turnos(advice.delta)) : null;
    if (apply) apply.addEventListener('click', (e) => { e.stopPropagation(); change(m, w, w.shifts + advice.delta); });
    const td = el('td', {class: `c ${w.status}${isOpen(m, w) ? ' open' : ''}`, tabindex: 0, title: adviceTitle(advice) || null},
      el('span', {class: 'load-cap'}, `${h.format(w.load)} / ${h.format(capOf(w))} h`), apply ? el('div', {class: 'adv'}, apply) : null);
    td.addEventListener('click', () => showDetail(m, w));
    td.addEventListener('keydown', (e) => { if (e.key === 'Enter') showDetail(m, w); });
    return td;
  }

  // Máquinas de um posto (08/10): o Fita pav.1 contém o Doall e a Thomas, que partilham uma só capacidade.
  function sharedNote(m) {
    const s = m.shared;
    if (!s) return null;
    const others = (s.with || []).map(short).join(' e ');
    const total = s.hours !== null && s.hours !== undefined ? `: juntas têm ${h1.format(s.hours)} h` : '';
    const text = s.is_post ? `posto com ${others}${total}` : `partilha o posto ${short(s.post)}${others ? ` com ${others}` : ''}${total}`;
    return el('small', {class: 'shared muted', title: 'Capacidade conjunta do posto nesta semana (as linhas continuam por máquina; não se somam).'}, text);
  }

  function hoursCell(v, extra = {}) {
    return el('td', {class: `num ${extra.class || ''}`.trim(), title: extra.title || null}, v ? h.format(v) : '0');
  }

  function noCalendarList(list) {
    const box = $('no-calendar');
    if (!box) return;
    box.hidden = !list.length;
    if (!list.length) { box.replaceChildren(); return; }
    box.replaceChildren(el('details', {}, el('summary', {}, `Postos sem calendário: ${list.map((m) => short(m.name)).join(', ')}`),
      el('ul', {}, list.map((m) => {
        const t = totalOf(m);
        const ops = t ? t.operations : m.no_date.operations + (m.late_before ? m.late_before.operations : 0) + m.weeks.reduce((a, w) => a + (w.operations || 0), 0);
        const unknown = t ? t.unknown : m.no_date.unknown;
        const hours = t ? t.load : 0;
        const text = unknown >= ops ? `${h.format(ops)} operações sem horas` : `${h.format(ops)} operações · ${h1.format(hours)} h${unknown ? ` · ${h.format(unknown)} sem horas` : ''}`;
        return el('li', {}, `${short(m.name)} · ${text}`);
      })),
      el('p', {class: 'muted'}, 'Sem calendário nas Definições do setor, por isso não têm capacidade nem turnos aqui.')));
  }

  function applyButton(id, list, label) {
    const b = $(id);
    if (!b) return;
    b.hidden = !list.length || view() !== 'semanas';
    b.textContent = `${label} (${list.length})`;
    b.onclick = () => { if (confirm(`${label}: mudar os turnos em ${list.length} semana(s)/máquina(s)?`)) shiftsChange(list, label).catch(error); };
  }

  function renderWeeks() {
    const late = modern();
    const machines = data.machines.filter(hasCalendar);
    $('head').replaceChildren(el('tr', {}, el('th', {scope: 'col'}, 'Máquina'),
      late ? el('th', {scope: 'col', class: 'num', title: 'Horas com prazo antes desta semana. No cursor de cada máquina: no plano · a vencer · sugerida.'}, 'Atrasado (h)') : null,
      ...data.weeks.map((w, i) => el('th', {scope: 'col', class: i === 0 ? 'now' : null, title: i === 0 ? 'Semana atual' : null}, `S${w.week}`, el('small', {}, ` ${dm(w.monday)}`))),
      el('th', {scope: 'col', class: 'num'}, 'Sem prazo (h)'), el('th', {scope: 'col', class: 'num', title: 'Horas com prazo depois destas 13 semanas'}, 'Mais tarde (h)')));
    $('body').replaceChildren(...machines.map((m) => {
      const kinds = lateKinds(m.late_before);
      const lateCell = late ? hoursCell(m.late_before.hours, {class: m.late_before.hours > 0 ? 'late clickable' : '',
        title: `${h.format(m.late_before.operations)} operações com prazo antes desta semana${kinds ? `: ${kinds}` : ''}${m.late_before.unknown ? ` · ${m.late_before.unknown} sem horas` : ''}${m.late_before.hours > 0 ? '. Clica para ver as OF.' : ''}`}) : null;
      if (lateCell && m.late_before.hours > 0) lateCell.addEventListener('click', () => showDetail(m, m.weeks[0]));
      const t = totalOf(m);
      const after = m.after !== undefined ? m.after : t ? t.after : 0;
      return el('tr', {},
        el('th', {scope: 'row'}, short(m.name), sharedNote(m)), lateCell, ...m.weeks.map((w) => cell(m, w)),
        hoursCell(m.no_date.hours, {title: `${h.format(m.no_date.operations)} operações sem prazo${m.no_date.unknown ? ` · ${m.no_date.unknown} sem horas` : ''}`}),
        hoursCell(after));
    }));
    noCalendarList(data.machines.filter((m) => !hasCalendar(m)));
    elsewhereNote();
    // «Aplicar todas» só junta recomendações do mesmo sentido.
    const advice = machines.flatMap((m) => m.weeks.filter((w) => w.advice && w.advice.delta).map((w) => ({maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts + w.advice.delta, delta: w.advice.delta})));
    const strip = (list) => list.map(({delta, ...x}) => x);
    applyButton('apply-all', strip(advice.filter((x) => x.delta > 0)), 'Aplicar todas: mais turnos');
    applyButton('apply-less', strip(advice.filter((x) => x.delta < 0)), 'Aplicar todas: menos turnos');
  }

  // Separador Máquinas: 6 colunas; o resto (peças, peso, Excel, horas reais) no cursor.
  function renderMachines() {
    const perfis = $('setor').value === 'perfis';
    const shiftHours = data.shift_hours || [];
    const workdays = ((data.settings || {}).workdays || []).length;
    const normal = (t) => {
      if (t.week_capacity !== undefined) return t.week_capacity;
      const m = data.machines.find((x) => x.id === t.id);
      return m ? shiftHours.slice(0, m.default_shifts || 0).reduce((a, b) => a + b, 0) * workdays : 0;
    };
    const head = ['Máquina', perfis ? 'Por fazer (mm²)' : 'Por fazer (m)', 'Horas previstas', 'Atrasado (h)', 'Sem prazo (h)', 'Semanas de trabalho'];
    const titles = {'Horas previstas': EXPLAIN.previstas, 'Atrasado (h)': 'Horas com prazo antes desta semana',
      'Semanas de trabalho': 'Horas previstas ÷ capacidade de uma semana normal (turnos padrão da máquina)'};
    $('machines-table').replaceChildren(
      el('thead', {}, el('tr', {}, ...head.map((x, i) => el('th', {scope: 'col', class: i ? 'num' : null, title: titles[x] || null}, x)))),
      el('tbody', {}, (data.totals || []).map((t) => {
        const recent = (t.actual_recent || []).filter((x) => x.hours !== null && x.hours !== undefined);
        const cap = normal(t);
        const title = [`Peças por fazer: ${h.format(t.pieces)}`, `Peso: ${h.format(t.weight_kg)} kg${t.weight_unknown ? ` (${t.weight_unknown} sem peso)` : ''}`,
          `Horas segundo o Excel: ${h1.format(t.excel_hours)} h${t.excel_unknown ? ` (${t.excel_unknown} operações principais sem horas do Excel)` : ''}`,
          `Horas reais (4 semanas): ${recent.length ? recent.map((x) => `S${x.week} ${h1.format(x.hours)}`).join(' · ') : '—'}`,
          t.unknown ? `Operações sem horas: ${h.format(t.unknown)}` : '', cap ? `Semana normal: ${h1.format(cap)} h` : 'Sem turnos padrão'].filter(Boolean).join('\n');
        return el('tr', {class: t.id ? '' : 'nomachine', title},
          el('th', {scope: 'row'}, short(t.name)),
          el('td', {class: 'num'}, perfis ? h.format(t.area_mm2) : h.format(t.metres)),
          el('td', {class: 'num'}, h1.format(t.load)),
          el('td', {class: 'num'}, h1.format(t.late_before !== undefined ? t.late_before : t.late)),
          el('td', {class: 'num'}, h1.format(t.no_date)),
          el('td', {class: 'num'}, cap && t.id ? h1.format(t.load / cap) : '—'));
      })));
    $('machines-note').textContent = '';
  }

  function render() {
    const v = view();
    $('tab-semanas').setAttribute('aria-selected', String(v === 'semanas'));
    $('tab-maquinas').setAttribute('aria-selected', String(v === 'maquinas'));
    $('tab-maquinas').hidden = !data.totals;
    $('weeks-view').hidden = v !== 'semanas' && Boolean(data.totals);
    $('machines-view').hidden = v !== 'maquinas' || !data.totals;
    renderWeeks();
    if (data.totals) renderMachines();
  }

  function summaryTable(m, w, d) {
    const current = data.weeks.length && data.weeks[0].week === w.week && data.weeks[0].year === w.year;
    const cap = capOf(w);
    const rows = [
      [named('Capacidade', 'capacidade'), `${hrs(cap)} (${w.shifts} turno${w.shifts === 1 ? '' : 's'})${current && w.full_capacity !== undefined ? ` · faltam ${h1.format(w.capacity)} h desta semana` : ''}`],
      [named('Carga', 'previstas'), `${hrs(w.load)} (no plano ${h1.format(w.plan)} + a vencer ${h1.format(w.due)} + sugerida ${h1.format(w.suggested)})${w.unknown ? ` · ${w.unknown} operações sem horas` : ''}`],
    ];
    if (current && m.late_before) rows.push(['Atrasado', `${hrs(m.late_before.hours)} (prazo antes desta semana${lateKinds(m.late_before) ? `: ${lateKinds(m.late_before)}` : ''})${m.late_before.unknown ? ` · ${m.late_before.unknown} operações sem horas` : ''}`]);
    else if (w.late) rows.push(['Atrasado', hrs(w.late)]);
    rows.push([named('Horas segundo o Excel', 'excel'), d && d.excel_hours !== undefined ? `${hrs(d.excel_hours)}${d.excel_unknown ? ` · ${d.excel_unknown} operações principais sem horas do Excel` : ''}` : '…']);
    return el('table', {class: 'summary', id: 'detail-summary'}, el('tbody', {}, rows.map(([k, v]) => el('tr', {}, el('th', {scope: 'row'}, k), el('td', {}, v)))));
  }

  // Trabalho do setor em máquinas de outro setor (08/10): a nota aparece sempre que houver operações, mesmo sem
  // horas (antes só com horas, e ficava escondida), uma vez por baixo da grelha.
  function elsewhereNote() {
    const box = $('elsewhere-note');
    if (!box) return;
    const e = data.elsewhere;
    box.hidden = !(e && e.operations);
    if (box.hidden) return;
    const unknown = e.unknown !== undefined ? e.unknown : e.machines.reduce((a, x) => a + (x.unknown || 0), 0);
    const where = e.machines.map((x) => (x.hours ? `${short(x.name)} ${h1.format(x.hours)} h` : short(x.name))).join(' · ');
    box.textContent = `${h.format(e.operations)} operações deste setor estão em máquinas de outro setor e não contam aqui: ${where}` +
      (unknown >= e.operations ? ' (não têm horas).' : unknown ? ` · ${h.format(unknown)} sem horas.` : '.');
  }

  // Excel do setor no Drive mais recente do que o importado (08/10): uma linha, só quando a API a manda.
  function sourceNotice() {
    const box = $('source-notice');
    if (!box) return;
    box.hidden = !data.source_notice;
    box.textContent = data.source_notice || '';
  }

  async function showDetail(m, w) {
    open = {m: m.id, w: w.week, y: w.year};
    const t = ++ticket;
    const box = $('detail');
    box.hidden = false;
    const current = data.weeks.length && data.weeks[0].week === w.week && data.weeks[0].year === w.year;
    const days = el('div', {class: 'days'}, w.days.map((d, i) => {
      const minus = el('button', {type: 'button', class: 'pm', disabled: d.shifts <= 0, 'aria-label': `Menos um turno ${DAYS[i]}`}, '−');
      const plus = el('button', {type: 'button', class: 'pm', disabled: d.shifts >= 3, 'aria-label': `Mais um turno ${DAYS[i]}`}, '+');
      minus.addEventListener('click', () => shiftsChange([{maquina: m.id, dia: String(d.date).slice(0, 10), turnos: d.shifts - 1}], `${short(m.name)} ${DAYS[i]} ${dm(d.date)}`).catch(error));
      plus.addEventListener('click', () => shiftsChange([{maquina: m.id, dia: String(d.date).slice(0, 10), turnos: d.shifts + 1}], `${short(m.name)} ${DAYS[i]} ${dm(d.date)}`).catch(error));
      return el('div', {class: 'day'}, el('span', {}, `${DAYS[i]} ${dm(d.date)}`), el('span', {class: 'n'}, minus, ` ${d.shifts} t `, plus));
    }));
    const minus = el('button', {type: 'button', class: 'pm', 'aria-label': `Menos um turno ${m.name} S${w.week}`, disabled: w.shifts <= 0}, '−');
    const plus = el('button', {type: 'button', class: 'pm', 'aria-label': `Mais um turno ${m.name} S${w.week}`, disabled: w.shifts >= 3}, '+');
    minus.addEventListener('click', () => change(m, w, w.shifts - 1));
    plus.addEventListener('click', () => change(m, w, w.shifts + 1));
    const weekShifts = el('div', {class: 'week-shifts', id: 'week-shifts'}, minus, ` ${w.shifts} turno${w.shifts === 1 ? '' : 's'} `, plus,
      w.manual ? el('span', {class: 'man muted', title: 'Mudada à mão'}, ' ✎ mudada à mão') : null);
    const week = `${w.year}-W${String(w.week).padStart(2, '0')}`;
    const advice = w.advice && w.advice.text && w.status !== 'sem_calendario' ? adviceTitle(w.advice) : '';
    box.replaceChildren(...[el('h2', {}, `${short(m.name)} · S${w.week} (${dm(w.monday)})`),
      advice ? el('p', {}, el('b', {}, advice)) : null,
      summaryTable(m, w, null),
      el('h3', {}, 'Turnos da semana'), weekShifts,
      el('h3', {}, 'Turnos por dia'), days,
      el('h3', {}, current && m.late_before ? 'OF desta semana e atrasadas' : 'OF nesta semana'), el('div', {id: 'detail-orders'}, el('p', {class: 'muted'}, 'A carregar…')),
      el('div', {id: 'detail-operations'}),
      el('h3', {}, 'Produção registada nesta semana'), el('div', {id: 'detail-production'}, el('button', {type: 'button', id: 'production-open'}, 'Ver produção registada')),
      el('p', {}, el('a', {href: `/planeamento/gantt?setor=${encodeURIComponent($('setor').value)}&semana=${week}`}, 'Ver no Gantt desta semana →'))].filter(Boolean));
    $('production-open').addEventListener('click', () => showProduction(m, w, 1).catch(error));
    renderWeeks();
    try {
      const d = await getJson(`/planeamento/api/setor/carga/celula?${new URLSearchParams({setor: $('setor').value, maquina: m.id, ano: w.year, semana: w.week})}`);
      if (t !== ticket) return;
      $('detail-summary').replaceWith(summaryTable(m, w, d));
      // Semana atual (08/10): as horas desta semana (as da grelha) e as atrasadas em colunas separadas.
      const split = d.week_hours !== undefined && d.late_before && d.late_before.operations > 0;
      const head = ['OF', 'Cliente', split ? 'Horas desta semana' : 'Horas previstas', ...(split ? ['Atrasado (h)'] : []), 'Horas segundo o Excel', 'Sem horas', 'Peças', 'Metros', 'Peso (kg)', 'Prazo', 'Atraso', 'Tipo', ''];
      const table = el('div', {class: 'scroll'}, el('table', {class: 'orders'},
        el('thead', {}, el('tr', {}, ...head.map((x) => el('th', {scope: 'col', title: x === 'Horas segundo o Excel' ? EXPLAIN.excel : x === 'Horas previstas' || x === 'Horas desta semana' ? EXPLAIN.previstas : x === 'Atrasado (h)' ? 'Horas com prazo antes desta semana' : null}, x)))),
        el('tbody', {}, d.orders.map((o) => {
          const tr = el('tr', {class: 'clickable', tabindex: 0, title: 'Ver as operações e o cálculo'}, el('td', {}, o.of), el('td', {}, o.customer || ''),
            el('td', {class: 'num'}, h1.format(split ? o.week_hours : o.hours)),
            split ? el('td', {class: `num${o.late_before_hours ? ' late' : ''}`}, o.late_before_hours ? h1.format(o.late_before_hours) : '') : null,
            el('td', {class: 'num'}, o.excel_hours !== undefined ? h1.format(o.excel_hours) + (o.excel_unknown ? ` · ${o.excel_unknown}?` : '') : ''),
            el('td', {class: 'num'}, o.unknown || ''),
            el('td', {class: 'num', title: o.pieces_unknown ? `${o.pieces_unknown} linha(s) com saldo por confirmar (não contam)` : null}, known(o.pieces, o.pieces_unknown, h, 'por confirmar')),
            el('td', {class: 'num', title: o.metres_unknown ? `${o.metres_unknown} linha(s) com metros por saber (não contam)` : null}, known(o.metres, o.metres_unknown, h, 'por saber')),
            el('td', {class: 'num', title: o.weight_unknown ? `${o.weight_unknown} operação(ões) sem peso unitário (não contam)` : null},
              o.weight_kg === undefined ? '' : known(o.weight_kg, o.weight_unknown, h, 'sem peso')),
            el('td', {}, o.priority_day ? dm(o.priority_day) : '—'), el('td', {class: 'num'}, o.late_days ? `${o.late_days} d` : ''),
            el('td', {}, o.kinds.map((k) => KIND[k]).join(', ')),
            el('td', {}, el('a', {href: `/planeamento/carteira?setor=${encodeURIComponent($('setor').value)}&vista=of_perfil&q=${encodeURIComponent(o.of)}`}, 'Carteira')));
          const go = () => showOperations(m, w, o.of).catch(error);
          tr.addEventListener('click', (e) => { if (!e.target.closest('a')) go(); });
          tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
          return tr;
        }))));
      const total = split
        ? `${h1.format(d.week_hours)} h desta semana + ${h1.format(d.late_before.hours)} h atrasadas${lateKinds(d.late_before) ? ` (${lateKinds(d.late_before)})` : ''}`
        : `${h1.format(d.hours)} h`;
      $('detail-orders').replaceChildren(el('p', {class: 'muted'}, `${d.orders.length} OF · ${total}${d.unknown ? ` · ${d.unknown} operações sem horas` : ''}. Clica numa OF para ver as operações e o cálculo.`), table);
    } catch (e) { error(e); }
    box.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  // Origem das horas previstas desta linha (auditoria 06/10, C3-F5). As estimadas usam a velocidade do Excel
  // (decisão de 01/10); o Gantt técnico dá prioridade à taxa histórica válida da máquina, por isso pode diferir.
  function originNote(o) {
    if (!o || !o.load_basis) return null;
    const text = o.load_basis === 'estimada'
      ? `Estimada · ${o.load_origin || ''} · o Gantt técnico usa a taxa histórica da máquina quando é válida`
      : `${o.hours_origin || o.load_origin || 'Documental'}`;
    return el('p', {class: 'muted small'}, `Origem das horas previstas: ${text}`);
  }

  function proofList(p) {
    if (!p) return el('p', {class: 'muted'}, 'Sem cálculo do motor de capacidade para esta operação.');
    const rate = p.excel_rate && p.excel_rate.value !== undefined ? `${h1.format(p.excel_rate.value)} ${p.excel_rate.unit || ''}` : null;
    const items = [
      ['Taxa usada nas horas previstas', p.rate !== null && p.rate !== undefined ? `${p.rate} (${p.method || 'método por confirmar'}) · ${p.rate_source || 'origem por confirmar'}` : (p.reason || 'Taxa por confirmar')],
      ['Fórmula', p.formula || '—'],
      ['Volume usado', p.volume !== null && p.volume !== undefined ? `${h1.format(p.volume)} ${p.volume_unit || ''}` : '—'],
      ['Data da vigência da taxa', p.rate_date ? `${dm(p.rate_date)} · ${p.rate_date_source || ''}` : '—'],
      ['Regra do Excel', rate ? `${rate}${p.excel_factor && String(p.excel_factor) !== '1' ? ` × fator ${p.excel_factor}` : ''}` : (p.excel_reason || '—')],
      ['Horas segundo o Excel (esta linha, saldo do Excel)', hrs(p.excel_hours)],
      [`Valor guardado no Excel («${p.macro_column}»)`, hrs(p.macro_hours)],
      ['Peças, comprimento e área usados', [p.inputs.quantity !== undefined ? `${h.format(p.inputs.quantity)} peças` : null, p.inputs.length_mm ? `${h.format(p.inputs.length_mm)} mm` : null, p.inputs.section_unit ? `${h1.format(p.inputs.section_unit)} mm²` : null, p.inputs.quantity_source || null].filter(Boolean).join(' · ') || '—'],
    ];
    const dl = el('dl', {class: 'proof'}, items.map(([k, v]) => [el('dt', {}, k), el('dd', {}, v)]));
    if (p.history_hash) {
      const hist = el('button', {type: 'button', class: 'linklike'}, 'Histórico usado');
      hist.addEventListener('click', async () => {
        try {
          const r = await fetch(`/planeamento/api/raw/produtividade/${encodeURIComponent(p.history_hash)}`, {headers: {Accept: 'application/json'}});
          if (!r.ok) { hist.replaceWith(el('span', {class: 'muted'}, 'Sem histórico guardado para este cálculo.')); return; }
          const body = await r.json();
          const used = (body.used || body.cohorts || body.records || []).length;
          hist.replaceWith(el('span', {class: 'muted'}, `Histórico: ${used} registos usados${body.excluded ? ` · ${body.excluded.length} excluídos` : ''}.`));
        } catch (e) { error(e); }
      });
      dl.append(el('dt', {}, 'Produtividade'), el('dd', {}, hist));
    }
    return dl;
  }

  // Horas estimadas (auditoria 06/10, CARGA-OPS-01): a conta mostrada é a da estimativa que deu as horas da linha;
  // a prova do motor de capacidade fica abaixo, marcada como não usada. Compatível com a resposta antiga (sem estimate).
  function estimateList(e) {
    const items = [
      ['Fórmula', e.formula],
      ['Peças em falta', h.format(e.remaining)],
      e.volume_unit === 'm' ? ['Comprimento', `${h.format(e.length_mm)} mm`] : ['Área de corte unitária', `${h1.format(e.section_unit)} mm²`],
      ['Volume', `${h1.format(e.volume)} ${e.volume_unit}`],
      ['Taxa', `${h1.format(e.rate)} ${e.rate_unit}`],
      ['Origem da taxa', e.basis || '—'],
    ];
    // Tempo por peça e margem (tabela de velocidades e Definições): a conta mostrada tem de bater certo.
    if (e.piece_seconds || e.margin_pct) {
      if (e.piece_seconds) items.push(['Tempo por peça', `${h1.format(e.piece_seconds)} s`]);
      if (e.margin_pct) items.push(['Margem', `${h1.format(e.margin_pct)} %`]);
      const base = `${h1.format(e.volume)} ÷ ${h1.format(e.rate)}` +
        (e.piece_seconds ? ` + ${h.format(e.remaining)} × ${h1.format(e.piece_seconds)} ÷ 3600` : '');
      items.push(['Horas previstas', e.margin_pct ? `(${base}) × ${(1 + e.margin_pct / 100).toLocaleString('pt-PT', {maximumFractionDigits: 3})} = ${hrs(e.hours)}` : `${base} = ${hrs(e.hours)}`]);
    } else {
      items.push(['Horas previstas', `${h1.format(e.volume)} ÷ ${h1.format(e.rate)} = ${hrs(e.hours)}`]);
    }
    return el('dl', {class: 'proof'}, items.map(([k, v]) => [el('dt', {}, k), el('dd', {}, v)]));
  }

  function calculation(o) {
    const estimated = o.load_basis === 'estimada' || o.proof_used === false;
    if (!estimated) return [proofList(o.proof)];
    const out = [el('p', {class: 'small'}, 'Cálculo das horas previstas (estimativa da Carteira):'),
      o.estimate ? estimateList(o.estimate) : el('p', {class: 'muted'}, o.load_origin || 'Estimativa sem detalhe.')];
    if (o.proof) out.push(el('p', {class: 'muted small'}, 'Cálculo do motor de capacidade (não usado nestas horas):'), proofList(o.proof));
    return out;
  }

  async function showOperations(m, w, of) {
    const box = $('detail-operations');
    box.replaceChildren(el('h3', {}, `Operações da ${of}`), el('p', {class: 'muted'}, 'A carregar…'));
    const d = await getJson(`/planeamento/api/setor/carga/operacoes?${new URLSearchParams({setor: $('setor').value, maquina: m.id, ano: w.year, semana: w.week, of})}`);
    box.replaceChildren(el('h3', {}, `Operações da ${of}`), el('div', {class: 'scroll'}, el('table', {class: 'orders'},
      el('thead', {}, el('tr', {}, ...['Referência', 'Operação', 'Perfil', 'Comp. (mm)', 'Peças em falta', 'Horas previstas', 'Horas segundo o Excel', 'Peso (kg)', 'Prazo', 'Tipo', ''].map((x) => el('th', {scope: 'col'}, x)))),
      el('tbody', {}, d.operations.flatMap((o) => {
        const tr = el('tr', {}, el('td', {}, o.reference || ''), el('td', {}, o.operation || ''), el('td', {}, o.profile || ''),
          el('td', {class: 'num'}, o.length_mm ? h.format(o.length_mm) : ''), el('td', {class: 'num'}, o.remaining !== null ? h.format(o.remaining) : '?'),
          el('td', {class: 'num', title: o.load_hours === null ? (o.hours_reason || '') : ''}, o.load_hours !== null ? h1.format(o.load_hours) : 'sem horas'),
          el('td', {class: 'num'}, o.excel_hours !== null && o.excel_hours !== undefined ? h1.format(o.excel_hours) : '—'),
          el('td', {class: 'num'}, o.weight_kg !== null && o.weight_kg !== undefined ? h.format(o.weight_kg) : o.phase === 'principal' ? '—' : ''),
          el('td', {title: o.priority_source || ''}, o.priority_day ? dm(o.priority_day) : '—'), el('td', {}, o.kind + (o.late ? ' · atrasada' : '')));
        const details = el('details', {}, el('summary', {}, 'Ver cálculo'), originNote(o), ...calculation(o));
        tr.append(el('td', {}, details));
        return [tr];
      })))));
  }

  async function showProduction(m, w, page) {
    const box = $('detail-production');
    box.replaceChildren(el('p', {class: 'muted'}, 'A carregar…'));
    const d = await getJson(`/planeamento/api/setor/carga/producao?${new URLSearchParams({setor: $('setor').value, maquina: m.id, ano: w.year, semana: w.week, pagina: page})}`);
    // Horas da folha (CARGA-PROD-04): são da folha, não da linha; mostram-se na primeira linha de cada folha.
    const seen = new Set();
    const rows = d.rows.map((r) => {
      const v = {...(r.values || r)};
      const uid = r.sheet_uid;
      if (d.sheet_hours && uid && uid in d.sheet_hours) {
        v.sheet_hours_text = seen.has(uid) ? '' : (d.sheet_hours[uid] !== null ? h1.format(d.sheet_hours[uid]) : 'sem horas');
        seen.add(uid);
      } else {
        v.sheet_hours_text = v.hours_worked !== null && v.hours_worked !== undefined ? h1.format(v.hours_worked) : '—';
      }
      return v;
    });
    const pager = el('div', {class: 'pager'});
    if (page > 1) { const b = el('button', {type: 'button'}, '◀ Anterior'); b.addEventListener('click', () => showProduction(m, w, page - 1).catch(error)); pager.append(b); }
    if (page * 50 < d.total) { const b = el('button', {type: 'button'}, 'Seguinte ▶'); b.addEventListener('click', () => showProduction(m, w, page + 1).catch(error)); pager.append(b); }
    box.replaceChildren(
      el('p', {class: 'muted'}, `${h.format(d.total)} registos validados (${d.names.join(', ')}) · horas reais declaradas: ${hrs(d.actual_hours)}`),
      rows.length ? el('div', {class: 'scroll'}, el('table', {class: 'orders'},
        el('thead', {}, el('tr', {}, ...['Data', 'OF', 'Referência', 'Operação', 'Quantidade', 'Horas da folha', 'Associação', 'Folha'].map((x) => el('th', {scope: 'col'}, x)))),
        el('tbody', {}, rows.map((r) => el('tr', {}, el('td', {}, r.production_date ? dm(r.production_date) : ''), el('td', {}, r.of || ''), el('td', {}, r.component_ref || ''),
          el('td', {}, r.operation || ''), el('td', {class: 'num'}, r.quantity !== null && r.quantity !== undefined ? h.format(r.quantity) : ''),
          el('td', {class: 'num'}, r.sheet_hours_text),
          el('td', {}, r.association_status || ''), el('td', {}, r.sheet || '')))))) : el('p', {}, 'Sem produção validada nesta semana.'),
      pager);
  }

  async function load(quiet = false) {
    const mine = ++loads;
    const fresh = await getJson(`/planeamento/api/setor/carga?setor=${encodeURIComponent($('setor').value)}`);
    if (mine !== loads) return;  // já foi pedida outra (outro setor ou depois de gravar)
    // Versão anterior enquanto o servidor refaz as horas (07/10/2026): volta a pedir de 8 em 8 s, sem aviso, e só
    // volta a desenhar quando chega a versão atual (o detalhe aberto e a produção registada não se fecham).
    const again = () => setTimeout(() => { if (mine === loads) load(true).catch(error); }, 8000);
    if (quiet && fresh.stale) return again();
    data = fresh;
    render();
    sourceNotice();
    if (open) {
      const m = data.machines.find((x) => x.id === open.m);
      const w = m && m.weeks.find((x) => x.week === open.w && x.year === open.y);
      if (m && w) showDetail(m, w);
    }
    if (data.stale) again();
  }

  function setView(v) {
    const url = new URL(location.href);
    if (v === 'maquinas') url.searchParams.set('vista', 'maquinas'); else url.searchParams.delete('vista');
    url.searchParams.set('setor', $('setor').value);
    history.replaceState(null, '', url);
    if (data) render();
  }

  document.addEventListener('DOMContentLoaded', () => {
    const initial = new URLSearchParams(location.search).get('setor');
    if (initial) $('setor').value = initial;
    $('setor').addEventListener('change', () => { open = null; $('detail').hidden = true; setView(view()); load().catch(error); });
    $('tab-semanas').addEventListener('click', () => setView('semanas'));
    $('tab-maquinas').addEventListener('click', () => setView('maquinas'));
    load().catch(error);
  });
})();
