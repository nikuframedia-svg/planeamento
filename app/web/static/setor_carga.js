'use strict';
// Carga e turnos (06/10/2026): máquina × semana, − / + turno, recomendação e detalhe por OF.
(() => {
  const $ = (id) => document.getElementById(id);
  const h = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 0});
  const h1 = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1});
  const DAYS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
  let data = null, open = null, ticket = 0;

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
  const error = (e) => { $('error').textContent = e.message; $('error').hidden = false; };
  const notice = (t) => { $('notice').textContent = t; $('notice').hidden = false; $('error').hidden = true; };

  async function shiftsChange(mudancas, label) {
    const r = await fetch('/planeamento/api/setor/turnos', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
      body: JSON.stringify({setor: $('setor').value, request_id: crypto.randomUUID(), mudancas})});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
    notice(`${label}: ${body.changed} semana(s) atualizadas.`);
    await load();
  }

  function cell(m, w) {
    const pct = w.capacity ? Math.min(100, Math.round(100 * w.load / w.capacity)) : (w.load ? 100 : 0);
    const minus = el('button', {type: 'button', class: 'pm', 'aria-label': `Menos um turno ${m.name} S${w.week}`, disabled: w.shifts <= 0}, '−');
    const plus = el('button', {type: 'button', class: 'pm', 'aria-label': `Mais um turno ${m.name} S${w.week}`, disabled: w.shifts >= 3}, '+');
    minus.addEventListener('click', (e) => { e.stopPropagation(); shiftsChange([{maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts - 1}], `${short(m.name)} S${w.week}`).catch(error); });
    plus.addEventListener('click', (e) => { e.stopPropagation(); shiftsChange([{maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts + 1}], `${short(m.name)} S${w.week}`).catch(error); });
    const advice = w.advice || {};
    const apply = advice.delta ? el('button', {type: 'button', class: 'apply small', title: advice.text}, `${advice.delta > 0 ? '+' : ''}${advice.delta} · Aplicar`) : null;
    if (apply) apply.addEventListener('click', (e) => { e.stopPropagation(); shiftsChange([{maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts + advice.delta}], `${short(m.name)} S${w.week}`).catch(error); });
    const td = el('td', {class: `c ${w.status}${open && open.m === m.id && open.w === w.week && open.y === w.year ? ' open' : ''}`, tabindex: 0,
      title: `No plano ${h1.format(w.plan)} h · a vencer ${h1.format(w.due)} h · sugerida ${h1.format(w.suggested)} h${w.late ? ` · atrasado ${h1.format(w.late)} h` : ''}${w.unknown ? ` · ${w.unknown} operações sem horas` : ''}\n${advice.text || ''}`},
      el('div', {class: 'top'}, minus, el('span', {class: 'cap'}, `${w.shifts} t · ${h.format(w.capacity)} h`, w.manual ? el('span', {class: 'man', title: 'Mudada à mão'}, ' ✎') : null), plus),
      el('div', {class: 'bar'}, el('span', {class: 'fill', style: `width:${pct}%`})),
      el('div', {class: 'nums'}, el('span', {class: 'k plan'}, h.format(w.plan)), ' + ', el('span', {class: 'k due'}, h.format(w.due)), ' + ', el('span', {class: 'k sug'}, h.format(w.suggested)),
        ` = ${h.format(w.load)} h`, w.unknown ? el('span', {class: 'muted'}, ` · ${w.unknown}?`) : null),
      el('div', {class: 'adv'}, apply || el('span', {class: 'muted'}, advice.text && !advice.delta ? (/^(Certo|Sobram)/.test(advice.text) ? 'Certo' : advice.text) : '')));
    td.addEventListener('click', () => showDetail(m, w));
    td.addEventListener('keydown', (e) => { if (e.key === 'Enter') showDetail(m, w); });
    return td;
  }

  function render() {
    $('head').replaceChildren(el('tr', {}, el('th', {scope: 'col'}, 'Máquina'),
      ...data.weeks.map((w, i) => el('th', {scope: 'col'}, `S${w.week}`, el('small', {}, ` ${dm(w.monday)}`), i === 0 ? el('small', {class: 'muted'}, ' (atual)') : null))));
    $('body').replaceChildren(...data.machines.map((m) => el('tr', {},
      el('th', {scope: 'row'}, short(m.name), el('small', {class: 'muted'}, ` ${m.process || ''}`),
        m.no_date.operations ? el('div', {class: 'muted small'}, `Sem prazo: ${h.format(m.no_date.hours)} h`) : null),
      ...m.weeks.map((w) => cell(m, w)))));
    const advice = data.machines.flatMap((m) => m.weeks.filter((w) => w.advice && w.advice.delta).map((w) => ({maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts + w.advice.delta})));
    $('apply-all').hidden = !advice.length;
    $('apply-all').textContent = `Aplicar todas as recomendações (${advice.length})`;
    $('apply-all').onclick = () => { if (confirm(`Mudar os turnos em ${advice.length} semana(s)/máquina(s)?`)) shiftsChange(advice, 'Recomendações').catch(error); };
  }

  async function showDetail(m, w) {
    open = {m: m.id, w: w.week, y: w.year};
    document.querySelectorAll('td.c.open').forEach((x) => x.classList.remove('open'));
    const t = ++ticket;
    const box = $('detail');
    box.hidden = false;
    const days = el('div', {class: 'days'}, w.days.map((d, i) => {
      const minus = el('button', {type: 'button', class: 'pm', disabled: d.shifts <= 0, 'aria-label': `Menos um turno ${DAYS[i]}`}, '−');
      const plus = el('button', {type: 'button', class: 'pm', disabled: d.shifts >= 3, 'aria-label': `Mais um turno ${DAYS[i]}`}, '+');
      minus.addEventListener('click', () => shiftsChange([{maquina: m.id, dia: String(d.date).slice(0, 10), turnos: d.shifts - 1}], `${short(m.name)} ${DAYS[i]} ${dm(d.date)}`).catch(error));
      plus.addEventListener('click', () => shiftsChange([{maquina: m.id, dia: String(d.date).slice(0, 10), turnos: d.shifts + 1}], `${short(m.name)} ${DAYS[i]} ${dm(d.date)}`).catch(error));
      return el('div', {class: 'day'}, el('span', {}, `${DAYS[i]} ${dm(d.date)}`), el('span', {class: 'n'}, minus, ` ${d.shifts} t `, plus));
    }));
    box.replaceChildren(el('h2', {}, `${short(m.name)} · S${w.week} (${dm(w.monday)})`),
      el('p', {}, `Capacidade ${h1.format(w.capacity)} h · no plano ${h1.format(w.plan)} h · a vencer ${h1.format(w.due)} h · sugerida ${h1.format(w.suggested)} h`,
        w.late ? ` · atrasado ${h1.format(w.late)} h` : '', ' — ', el('b', {}, w.advice.text || '')),
      el('h3', {}, 'Turnos por dia'), days, el('h3', {}, 'OF nesta célula'), el('p', {class: 'muted'}, 'A carregar…'),
      el('p', {}, el('a', {href: `/planeamento/gantt?setor=${encodeURIComponent($('setor').value)}&semana=${w.year}-W${String(w.week).padStart(2, '0')}`}, 'Ver no Gantt desta semana →')));
    try {
      const r = await fetch(`/planeamento/api/setor/carga/celula?${new URLSearchParams({setor: $('setor').value, maquina: m.id, ano: w.year, semana: w.week})}`, {headers: {Accept: 'application/json'}});
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `Erro ${r.status}`);
      if (t !== ticket) return;
      const KIND = {plan: 'no plano', due: 'a vencer', suggested: 'sugerida'};
      const table = el('div', {class: 'scroll'}, el('table', {class: 'orders'},
        el('thead', {}, el('tr', {}, ...['OF', 'Cliente', 'Horas', 'Sem horas', 'Peças', 'Metros', 'Prazo', 'Atraso', 'Tipo', ''].map((x) => el('th', {scope: 'col'}, x)))),
        el('tbody', {}, d.orders.map((o) => el('tr', {}, el('td', {}, o.of), el('td', {}, o.customer || ''), el('td', {class: 'num'}, h1.format(o.hours)),
          el('td', {class: 'num'}, o.unknown || ''), el('td', {class: 'num'}, h.format(o.pieces)), el('td', {class: 'num'}, h.format(o.metres)),
          el('td', {}, o.priority_day ? dm(o.priority_day) : '—'), el('td', {class: 'num'}, o.late_days ? `${o.late_days} d` : ''),
          el('td', {}, o.kinds.map((k) => KIND[k]).join(', ')),
          el('td', {}, el('a', {href: `/planeamento/carteira?setor=${encodeURIComponent($('setor').value)}&vista=of_perfil&q=${encodeURIComponent(o.of)}`}, 'Carteira')))))));
      box.children[5].replaceWith(el('div', {}, el('p', {class: 'muted'}, `${d.orders.length} OF · ${h1.format(d.hours)} h${d.unknown ? ` · ${d.unknown} operações sem horas` : ''}`), table));
    } catch (e) { error(e); }
    box.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  async function load() {
    const r = await fetch(`/planeamento/api/setor/carga?setor=${encodeURIComponent($('setor').value)}`, {headers: {Accept: 'application/json'}});
    data = await r.json();
    if (!r.ok) throw new Error(data.error || `Erro ${r.status}`);
    render();
    if (open) {
      const m = data.machines.find((x) => x.id === open.m);
      const w = m && m.weeks.find((x) => x.week === open.w && x.year === open.y);
      if (m && w) showDetail(m, w);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const initial = new URLSearchParams(location.search).get('setor');
    if (initial) $('setor').value = initial;
    $('setor').addEventListener('change', () => { open = null; $('detail').hidden = true; load().catch(error); });
    load().catch(error);
  });
})();
