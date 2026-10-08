'use strict';
// Vistas da previsão na Carga e turnos (Etapa 3, pontos 11 e 12, 08/10/2026): «Calendário» e «Capacidade e prazos».
// Previsão = o que cada máquina vai fazer, com a capacidade dos turnos (motor de previsão). Realizado = MES (folhas
// OCR validadas), pela data de produção: sempre à parte e com o seu nome, nunca misturado com a previsão.
// Risco em 3 estados (atrasa, em risco, sem previsão) e «já em atraso» à parte; 100 % = «completa», nunca erro.
// Com ?cenario=<id>: os mesmos dados da simulação, com a faixa «Simulação …: nada mudou no plano em uso».
// Uso (setor_carga.js): window.cargaPrevisao.show(contentor, {vista: 'calendario'|'capacidade', setor}).
(() => {
  const TEXT = 'Previsão: o que cada máquina vai fazer, com a capacidade dos turnos.';
  const h = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 0});
  const h1 = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1});
  const DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
  const STEP = 28;  // ◀ ▶ de 4 em 4 semanas
  const S = {box: null, vista: null, setor: null, cal: {from: null}, grao: 'dia', ticket: 0, dayTicket: 0, open: null, timer: 0};

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
  const dmy = (iso) => { const [y, m, d] = String(iso).slice(0, 10).split('-'); return `${d}/${m}/${y}`; };
  const local = (iso, opts) => (iso ? new Date(iso).toLocaleString('pt-PT', {timeZone: 'Europe/Lisbon', ...opts}) : '');
  const when = (iso) => local(iso, {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const weekday = (iso) => DAYS[(new Date(`${String(iso).slice(0, 10)}T12:00:00Z`).getUTCDay() + 6) % 7];
  const addDays = (iso, n) => { const d = new Date(`${String(iso).slice(0, 10)}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const isoWeek = (iso) => {
    const d = new Date(`${String(iso).slice(0, 10)}T12:00:00Z`);
    const day = (d.getUTCDay() + 6) % 7;
    d.setUTCDate(d.getUTCDate() - day + 3);
    const first = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
    const week = 1 + Math.round(((d - first) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7);
    return `${d.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
  };
  const plural = (n, one, many) => `${h.format(n)} ${n === 1 ? one : many}`;
  const cenario = () => new URLSearchParams(location.search).get('cenario') || '';

  async function getJson(url) {
    const r = await fetch(url, {headers: {Accept: 'application/json'}});
    const body = await r.json().catch(() => ({}));
    if (r.status === 404 && !body.error) throw new Error('Esta vista precisa que o serviço do planeamento seja reiniciado.');
    if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
    return body;
  }
  const params = (extra) => {
    const p = new URLSearchParams({setor: S.setor, ...extra});
    if (cenario()) p.set('cenario', cenario());
    return p;
  };
  const sticky = (box, table) => {
    if (typeof window.stickyHead !== 'function') return;
    try { const s = window.stickyHead(box, table); if (s && s.refresh) s.refresh(); } catch (e) { console.warn('Cabeçalho fixo indisponível', e); }
  };

  // --- esqueleto (uma vez): as tabelas ficam as mesmas, só o conteúdo muda (o cabeçalho fixo segue a tabela).
  function skeleton(box) {
    if (box.querySelector('#fc-text')) return;
    box.replaceChildren(
      el('p', {id: 'fc-text', class: 'legend muted'}, TEXT),
      el('p', {id: 'fc-banner', class: 'fc-banner', role: 'status', hidden: true}),
      el('p', {id: 'fc-error', class: 'error', role: 'alert', hidden: true}),
      el('div', {id: 'fc-cal', hidden: true},
        el('div', {class: 'fc-nav'},
          el('button', {type: 'button', id: 'fc-prev', 'aria-label': 'Semanas anteriores'}, '◀'),
          el('span', {id: 'fc-range'}),
          el('button', {type: 'button', id: 'fc-next', 'aria-label': 'Semanas seguintes'}, '▶'),
          el('span', {id: 'fc-when', class: 'muted'})),
        el('p', {class: 'legend muted'}, 'Semana passada: só o realizado (MES). Hoje e depois: a previsão. ',
          el('span', {class: 'sw fc-closed'}), ' fechado · ', el('span', {class: 'sw fc-lt85'}), ' < 85 % · ',
          el('span', {class: 'sw fc-p85'}), ' 85–99 % · ', el('span', {class: 'sw fc-full'}), ' 100 % · completa (normal). Clica num dia para ver o detalhe.'),
        el('div', {class: 'grid-wrap', id: 'fc-cal-wrap'}, el('table', {class: 'calgrid', id: 'fc-cal-table'},
          el('thead', {}, el('tr', {}, DAYS.map((d) => el('th', {scope: 'col'}, d)))), el('tbody', {id: 'fc-cal-body'}))),
        el('section', {id: 'fc-day', class: 'detail', hidden: true})),
      el('div', {id: 'fc-cap', hidden: true},
        el('div', {class: 'view-line'},
          el('span', {class: 'seg', role: 'group', 'aria-label': 'Grão'},
            el('button', {type: 'button', id: 'fc-dia', 'aria-pressed': 'true'}, 'Por dia'),
            el('button', {type: 'button', id: 'fc-semana', 'aria-pressed': 'false'}, 'Por semana')),
          el('span', {id: 'fc-cap-when', class: 'muted'})),
        el('div', {id: 'fc-counters', class: 'fc-counters'}),
        el('p', {id: 'fc-apart', class: 'muted', hidden: true}),
        el('p', {class: 'legend muted'}, 'Cada célula: horas previstas ÷ capacidade dos turnos. ',
          el('span', {class: 'sw fc-closed'}), ' fechado · ', el('span', {class: 'sw fc-lt85'}), ' < 85 % · ',
          el('span', {class: 'sw fc-p85'}), ' 85–99 % · ', el('span', {class: 'sw fc-full'}), ' 100 % · completa (normal) · ',
          el('span', {class: 'dot late'}, '●'), ' acaba e atrasa · ', el('span', {class: 'dot risk'}, '●'), ' acaba em risco.'),
        el('div', {class: 'grid-wrap', id: 'fc-map-wrap'}, el('table', {class: 'loadgrid capmap', id: 'fc-map'},
          el('thead', {id: 'fc-map-head'}), el('tbody', {id: 'fc-map-body'}))),
        el('h3', {id: 'fc-risks-title'}, 'Riscos principais'),
        el('div', {id: 'fc-risks'}),
        el('h3', {}, 'Previsão com dados em falta'),
        el('div', {id: 'fc-missing'})),
      el('div', {id: 'fc-cen', hidden: true}));
    const $ = (id) => box.querySelector(`#${id}`);
    $('fc-prev').addEventListener('click', () => moveCalendar(-STEP));
    $('fc-next').addEventListener('click', () => moveCalendar(STEP));
    $('fc-dia').addEventListener('click', () => { if (S.grao !== 'dia') { S.grao = 'dia'; loadCapacity(); } });
    $('fc-semana').addEventListener('click', () => { if (S.grao !== 'semana') { S.grao = 'semana'; loadCapacity(); } });
  }
  const $ = (id) => S.box.querySelector(`#${id}`);

  function fail(e) {
    const box = $('fc-error');
    box.textContent = e.message;
    box.hidden = false;
  }

  // Faixa da simulação (contrato com os cenários): só quando ?cenario.
  function banner(scenario) {
    const box = $('fc-banner');
    const id = cenario();
    box.hidden = !id;
    if (!id) { box.replaceChildren(); return; }
    const plain = new URL(location.href);
    plain.searchParams.delete('cenario');
    if (scenario && scenario.available === false) {
      box.replaceChildren(`Cenários ainda não disponíveis: mostra o plano em uso · `, el('a', {href: plain.pathname + plain.search}, 'Ver plano em uso'));
      return;
    }
    const name = (scenario && scenario.name) || id;
    box.replaceChildren(`Simulação «${name}»: nada mudou no plano em uso · `, el('a', {href: plain.pathname + plain.search}, 'Ver plano em uso'));
  }

  const computed = (d) => (d.computed_at ? `Previsão calculada às ${local(d.computed_at, {hour: '2-digit', minute: '2-digit'})} de ${local(d.computed_at, {day: '2-digit', month: '2-digit'})}.` : '');
  function again(fn, mine) {
    clearTimeout(S.timer);
    S.timer = setTimeout(() => { if (mine === S.ticket) fn(true); }, 8000);
  }

  // --- Calendário (P12)
  function dayCell(d, today) {
    const cls = ['fc-day'];
    if (d.date === today) cls.push('today');
    if (d.past) cls.push('past');
    else if (d.state === 'fechado') cls.push('fc-closed');
    else if (d.state === 'completa') cls.push('fc-full');
    else if (d.state === 'parcial') cls.push(d.pct >= 85 ? 'fc-p85' : 'fc-lt85');
    else if (d.state === 'sem_carga') cls.push('fc-empty');
    if (S.open === d.date) cls.push('open');
    const lines = [el('div', {class: 'fc-date'}, `${weekday(d.date)} ${dm(d.date)}`)];
    if (!d.past) {
      if (d.state === 'fechado') lines.push(el('div', {}, 'Fechado'));
      else if (d.state === 'sem_carga') lines.push(el('div', {}, `Sem carga · ${h1.format(d.capacity_h)} h`));
      else {
        lines.push(el('div', {class: 'fc-load'}, `${h1.format(d.forecast_h)} / ${h1.format(d.capacity_h)} h`,
          el('span', {class: 'fc-pct'}, `${d.state === 'completa' ? '100 % · completa' : `${h.format(d.pct)} %`}`)));
        lines.push(el('div', {class: 'fc-bar'}, el('span', {style: `width:${Math.min(100, d.pct || 0)}%`})));
      }
    }
    const parts = [];
    if (!d.past && d.ofs) parts.push(plural(d.ofs, 'OF', 'OF'));
    if (!d.past && d.ends.length) parts.push(`${h.format(d.ends.length)} ${d.ends.length === 1 ? 'acaba' : 'acabam'}`);
    if (d.due.length) {
      const kinds = [...new Set(d.due.map((x) => x.label).filter(Boolean))].map((x) => x.toLowerCase());
      parts.push(`${plural(d.due.length, 'prazo', 'prazos')}${kinds.length ? ` (${kinds.join(', ')})` : ''}`);
    }
    if (d.deliveries && d.deliveries.length) parts.push(plural(d.deliveries.length, 'entrega', 'entregas'));
    if (parts.length) lines.push(el('div', {class: 'fc-meta'}, parts.join(' · ')));
    const risks = [];
    if (d.late) risks.push(el('span', {class: 'risk late'}, `${h.format(d.late)} ${d.late === 1 ? 'atrasa' : 'atrasam'}`));
    if (d.at_risk) risks.push(el('span', {class: 'risk at'}, `${h.format(d.at_risk)} em risco`));
    if (risks.length) lines.push(el('div', {class: 'fc-risks'}, risks));
    if (d.realized && d.realized.records) {
      lines.push(el('div', {class: 'fc-real'}, `Realizado: ${h.format(d.realized.pieces)} peças · ${plural(d.realized.sheets, 'folha', 'folhas')}`));
    }
    const title = [d.already_late ? `${plural(d.already_late, 'OF já em atraso acaba', 'OF já em atraso acabam')} neste dia` : '',
      d.deliveries && d.deliveries.length ? `Entregas (CPIS): ${d.deliveries.join(', ')}` : '',
      d.due.length ? `Prazos: ${d.due.map((x) => `${x.of}${x.label ? ` (${x.label})` : ''}`).join(', ')}` : ''].filter(Boolean).join('\n');
    const td = el('td', {class: cls.join(' '), tabindex: 0, title: title || null, dataset: {date: d.date}}, lines);
    td.addEventListener('click', () => showDay(d.date));
    td.addEventListener('keydown', (e) => { if (e.key === 'Enter') showDay(d.date); });
    return td;
  }

  async function loadCalendar(quiet = false) {
    const mine = ++S.ticket;
    const extra = S.cal.from ? {de: S.cal.from, ate: addDays(S.cal.from, 41)} : {};
    if (!quiet) $('fc-range').textContent = 'A carregar…';
    let d;
    try { d = await getJson(`/planeamento/api/setor/calendario?${params(extra)}`); } catch (e) { if (mine === S.ticket) { $('fc-range').textContent = ''; fail(e); } return; }
    if (mine !== S.ticket) return;
    if (quiet && d.stale) return again(loadCalendar, mine);
    $('fc-error').hidden = true;
    banner(d.scenario);
    S.cal = {from: String(d.from).slice(0, 10), to: String(d.to).slice(0, 10), today: String(d.today).slice(0, 10)};
    $('fc-range').textContent = `${dm(S.cal.from)} – ${dmy(S.cal.to)}`;
    $('fc-when').textContent = computed(d);
    // ▶ até ao fim das 13 semanas da previsão; ◀ sem limite (só realizado).
    $('fc-next').disabled = addDays(S.cal.from, STEP) > addDays(S.cal.today, 13 * 7);
    const rows = [];
    for (let i = 0; i < d.days.length; i += 7) rows.push(el('tr', {}, d.days.slice(i, i + 7).map((x) => dayCell(x, S.cal.today))));
    $('fc-cal-body').replaceChildren(...rows);
    sticky($('fc-cal-wrap'), $('fc-cal-table'));
    if (S.open && d.days.some((x) => x.date === S.open)) showDay(S.open, true);
    if (d.stale) again(loadCalendar, mine);
  }

  function moveCalendar(n) {
    if (!S.cal.from) return;
    S.cal.from = addDays(S.cal.from, n);
    loadCalendar();
  }

  function machineBlock(m) {
    const shifts = m.shifts.map((s) => `${s.shift}.º ${s.start || ''}–${s.end || ''}`).join(', ');
    const load = m.state === 'completa' ? '100 % · completa' : m.pct !== null && m.pct !== undefined ? `${h.format(m.pct)} %` : m.state === 'fechado' ? 'fechado' : '';
    const summary = [short(m.name), shifts ? `turnos ${shifts}` : 'sem turnos', `${h1.format(m.forecast_h)} / ${m.capacity_h === null ? '—' : h1.format(m.capacity_h)} h${load ? ` · ${load}` : ''}`,
      plural(m.ofs.length, 'OF', 'OF')].join(' · ');
    const table = el('div', {class: 'scroll'}, el('table', {class: 'orders'},
      el('thead', {}, el('tr', {}, ['OF', 'Cliente', 'Horas neste dia', 'Peças', 'Metros', 'Planeado / resto', 'Prazo', 'Acaba'].map((x, i) => el('th', {scope: 'col', class: i >= 2 && i <= 4 ? 'num' : null}, x)))),
      el('tbody', {}, m.ofs.map((o) => el('tr', {},
        el('td', {}, o.of), el('td', {}, o.customer || ''), el('td', {class: 'num'}, h1.format(o.hours)),
        el('td', {class: 'num'}, o.pieces === null || o.pieces === undefined ? '—' : h.format(o.pieces)),
        el('td', {class: 'num'}, o.metres === null || o.metres === undefined ? '—' : h1.format(o.metres)),
        el('td', {}, o.kind),
        el('td', {}, o.due_day ? `${dm(o.due_day)}${o.due_label ? ` (${o.due_label})` : ''}` : '—'),
        el('td', {}, o.ends ? local(o.ends, {hour: '2-digit', minute: '2-digit'}) : o.conclusion ? `depois (${when(o.conclusion)})` : 'depois do horizonte'))))));
    return el('details', {class: 'fc-machine'}, el('summary', {}, summary), m.ofs.length ? table : el('p', {class: 'muted'}, 'Sem trabalho previsto.'));
  }

  function peopleLine(people) {
    if (!people || !people.length) return null;
    return el('p', {class: 'fc-people'}, 'Pessoas: ', people.map((p) => `${p.shift}.º turno precisas ${h.format(p.need)} · disponíveis ${p.available === null ? '—' : h.format(p.available)}${p.deficit ? ` (faltam ${h.format(p.deficit)})` : ''}`).join(' · '));
  }

  async function showDay(date, quiet = false) {
    S.open = date;
    for (const td of $('fc-cal-body').querySelectorAll('td.open')) td.classList.remove('open');
    const cell = $('fc-cal-body').querySelector(`td[data-date="${date}"]`);
    if (cell) cell.classList.add('open');
    const t = ++S.dayTicket;
    const box = $('fc-day');
    box.hidden = false;
    const gantt = `/planeamento/gantt?${new URLSearchParams({setor: S.setor, dia: date, semana: isoWeek(date)})}`;
    const carga = `/planeamento/setor/carga?${new URLSearchParams({setor: S.setor})}`;
    const head = [el('h2', {}, `${weekday(date)} ${dmy(date)}`),
      el('p', {class: 'fc-links'}, el('a', {href: gantt}, 'Ver no Gantt (dia)'), ' · ', el('a', {href: carga}, 'Ver a semana na Carga'))];
    if (!quiet) box.replaceChildren(...head, el('p', {class: 'muted'}, 'A carregar…'));
    let d;
    try { d = await getJson(`/planeamento/api/setor/calendario/dia?${params({dia: date})}`); } catch (e) { if (t === S.dayTicket) box.replaceChildren(...head, el('p', {class: 'error'}, e.message)); return; }
    if (t !== S.dayTicket) return;
    const forecastPart = [el('h3', {}, 'Previsão')];
    if (d.past) forecastPart.push(el('p', {class: 'muted'}, 'Dia passado: sem previsão.'));
    else {
      const total = d.total;
      if (total) forecastPart.push(el('p', {}, total.state === 'fechado' ? 'Setor fechado neste dia.'
        : `Setor: ${h1.format(total.forecast_h)} / ${h1.format(total.capacity_h)} h${total.state === 'completa' ? ' · 100 % · completa' : total.pct !== null ? ` · ${h.format(total.pct)} %` : ''}`));
      forecastPart.push(peopleLine(d.people));
      forecastPart.push(d.machines.length ? el('div', {class: 'fc-machines'}, d.machines.map(machineBlock)) : el('p', {class: 'muted'}, 'Nenhuma máquina com turnos ou trabalho previsto.'));
    }
    const realizedPart = [];
    if (d.past || date === S.cal.today) {
      realizedPart.push(el('h3', {}, 'Realizado neste dia'), el('p', {class: 'muted'}, 'Do MES (folhas OCR validadas), pela data de produção. Não entra na previsão.'));
      if (!d.realized_available) realizedPart.push(el('p', {class: 'muted'}, 'Sem dados do MES.'));
      else if (!d.realized.length) realizedPart.push(el('p', {}, 'Sem registos neste dia.'));
      else realizedPart.push(el('div', {class: 'scroll'}, el('table', {class: 'orders', id: 'fc-realized'},
        el('thead', {}, el('tr', {}, ['Máquina', 'Peças', 'Metros', 'Horas das folhas', 'Folhas'].map((x, i) => el('th', {scope: 'col', class: i ? 'num' : null}, x)))),
        el('tbody', {}, d.realized.map((r) => el('tr', {}, el('td', {}, short(r.machine)), el('td', {class: 'num'}, h.format(r.pieces)),
          el('td', {class: 'num', title: r.metres_unknown ? `${plural(r.metres_unknown, 'registo', 'registos')} sem comprimento (não contam)` : null}, r.metres === null || r.metres === undefined ? '—' : `${h1.format(r.metres)}${r.metres_unknown ? '*' : ''}`), el('td', {class: 'num'}, r.hours === null || r.hours === undefined ? '—' : h1.format(r.hours)),
          el('td', {class: 'num'}, h.format(r.sheets))))))));
    }
    box.replaceChildren(...head, el('section', {class: 'fc-forecast'}, forecastPart), ...(realizedPart.length ? [el('section', {class: 'fc-realized'}, realizedPart)] : []));
    if (!quiet) box.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  // --- Capacidade e prazos (ponto 11)
  function counters(d) {
    const c = d.counters;
    const lim = d.limiting || [];
    const limText = lim.length ? lim.map((x) => `${short(x.machine)} (${x.recovers === false ? 'não recupera no horizonte' : x.recovery ? `recupera a ${dm(x.recovery)}` : 'recupera'})`).join(' · ') : 'nenhuma';
    const limTitle = lim.map((x) => [`${short(x.machine)}${x.machines && x.machines.length > 1 ? ` (${x.machines.map(short).join(', ')})` : ''}`,
      x.peak_gap_weeks !== null && x.peak_gap_weeks !== undefined ? `pico de falta ${h1.format(x.peak_gap_weeks)} semanas de turnos (${h.format(x.peak_hours)} h)` : '',
      `${h1.format(x.late_hours || 0)} h acabam depois do prazo`, x.queue_end ? `fila até ${local(x.queue_end, {day: '2-digit', month: '2-digit'})}` : '',
      x.suggested_share ? `${h.format(x.suggested_share * 100)} % da fila em máquinas sugeridas` : ''].filter(Boolean).join(' · ')).join('\n');
    $('fc-counters').replaceChildren(
      el('div', {class: 'counter late'}, el('span', {class: 'n'}, h.format(c.atrasam)), el('span', {}, 'OF que atrasam')),
      el('div', {class: 'counter at'}, el('span', {class: 'n'}, h.format(c.em_risco)), el('span', {}, `OF em risco (margem abaixo de ${plural(d.folga, 'dia útil', 'dias úteis')})`)),
      el('div', {class: 'counter limit', title: limTitle || null}, el('span', {class: 'n'}, h.format(lim.length)), el('span', {}, `Máquinas que limitam: ${limText}`)));
    $('fc-apart').hidden = !c.ja_em_atraso;
    $('fc-apart').textContent = c.ja_em_atraso ? `À parte: ${plural(c.ja_em_atraso, 'OF já em atraso', 'OF já em atraso')} (prazo antes de hoje).` : '';
  }

  function mapCell(c, grao) {
    const cls = ['m'];
    let text;
    if (c.state === 'sem_calendario') { text = 'Sem calendário'; cls.push('fc-none'); }
    else if (c.state === 'fechado') { text = 'Fechado'; cls.push('fc-closed'); }
    else if (c.state === 'sem_carga') { text = 'Sem carga'; cls.push('fc-empty'); }
    else if (c.state === 'completa') { text = '100 % · completa'; cls.push('fc-full'); }
    else { text = `${h.format(c.pct)} %`; cls.push(c.pct >= 85 ? 'fc-p85' : 'fc-lt85'); }
    const marks = c.risk_marks || {};
    const title = [c.capacity_h === null ? 'Sem calendário' : `previsão ${h1.format(c.forecast_h)} h · capacidade ${h1.format(c.capacity_h)} h`,
      c.deadline_h !== undefined ? `pelo prazo ${h1.format(c.deadline_h)} h · previsão ${h1.format(c.forecast_h)} h` : '',
      marks.atrasa ? `${plural(marks.atrasa, 'OF acaba', 'OF acabam')} e ${marks.atrasa === 1 ? 'atrasa' : 'atrasam'}` : '',
      marks.em_risco ? `${plural(marks.em_risco, 'OF acaba', 'OF acabam')} em risco` : '',
      marks.ja_em_atraso ? `${plural(marks.ja_em_atraso, 'OF já em atraso acaba', 'OF já em atraso acabam')} aqui` : ''].filter(Boolean).join('\n');
    return el('td', {class: cls.join(' '), title}, text,
      marks.atrasa ? el('span', {class: 'dot late'}, ` ●${marks.atrasa > 1 ? h.format(marks.atrasa) : ''}`) : null,
      marks.em_risco ? el('span', {class: 'dot risk'}, ` ●${marks.em_risco > 1 ? h.format(marks.em_risco) : ''}`) : null);
  }

  function renderMap(d) {
    const week = d.grao === 'semana';
    $('fc-map-head').replaceChildren(el('tr', {}, el('th', {scope: 'col'}, 'Máquina'),
      d.periods.map((p, i) => el('th', {scope: 'col', class: i === 0 ? 'now' : null}, week ? `S${p.week} ` : `${weekday(p.key)} `, el('small', {}, dm(p.start))))));
    $('fc-map-body').replaceChildren(...d.machines.map((m) => el('tr', {},
      el('th', {scope: 'row', title: m.queue_end ? `A fila acaba a ${when(m.queue_end)}` : null}, short(m.name),
        m.queue_end ? el('small', {class: 'muted fc-queue'}, ` fila até ${local(m.queue_end, {day: '2-digit', month: '2-digit'})}`) : null),
      m.periods.map((c) => mapCell(c, d.grao)))));
    sticky($('fc-map-wrap'), $('fc-map'));
  }

  function renderRisks(d) {
    $('fc-risks-title').textContent = `Riscos principais (${h.format(d.risks_total)})`;
    if (!d.risks.length) { $('fc-risks').replaceChildren(el('p', {}, 'Nenhuma OF atrasa nem está em risco.')); return; }
    const margin = (n) => (n === null || n === undefined ? '—' : n > 0 ? `+${h.format(n)}` : n < 0 ? `−${h.format(-n)}` : '0');
    $('fc-risks').replaceChildren(el('div', {class: 'scroll'}, el('table', {class: 'orders', id: 'fc-risks-table'},
      el('thead', {}, el('tr', {}, ['OF', 'Cliente', 'Máquina', 'Prazo', 'Conclusão prevista', 'Margem (dias úteis)', 'Motivo', 'Estado'].map((x, i) => el('th', {scope: 'col', class: i === 5 ? 'num' : null}, x)))),
      el('tbody', {}, d.risks.map((r) => el('tr', {title: r.approximate && r.approximate.length ? `Aproximada: ${r.approximate.join(', ')}` : null},
        el('td', {}, r.of), el('td', {}, r.customer || ''), el('td', {}, short(r.machine) || '—'),
        el('td', {}, r.due_day ? `${dm(r.due_day)}${r.due_label ? ` (${r.due_label})` : ''}` : '—'),
        el('td', {}, r.beyond ? 'depois do horizonte' : when(r.conclusion)),
        el('td', {class: 'num'}, margin(r.margin_days)), el('td', {}, String(r.reason || '').replace(/\bFicep\s+/g, '')),
        el('td', {class: r.state === 'atrasa' ? 'late' : 'at'}, r.state === 'atrasa' ? 'atrasa' : 'em risco')))))),
      ...(d.risks_total > d.risks.length ? [el('p', {class: 'muted'}, `Mostra as primeiras ${h.format(d.risks.length)}.`)] : []));
  }

  function renderMissing(d) {
    const u = d.unreliable || {};
    const items = (u.reasons || []).map((r) => el('li', {}, `${r.label}: ${plural(r.count, 'operação', 'operações')} sem previsão`));
    if (u.approximate_lines) items.push(el('li', {}, `${plural(u.approximate_lines, 'linha aproximada', 'linhas aproximadas')}${(u.approximate || []).length ? ` (${u.approximate.map((x) => `${x.label} ${h.format(x.count)}`).join(' · ')})` : ''}`));
    const src = u.sources || {};
    const ages = [src.excel_imported_at ? `Excel importado a ${when(src.excel_imported_at)}` : '', src.v2_at ? `camada v2 de ${when(src.v2_at)}` : ''].filter(Boolean);
    if (ages.length) items.push(el('li', {}, `Idade dos dados: ${ages.join(' · ')}`));
    $('fc-missing').replaceChildren(items.length ? el('ul', {class: 'fc-missing'}, items) : el('p', {}, 'Sem dados em falta.'));
  }

  async function loadCapacity(quiet = false) {
    const mine = ++S.ticket;
    $('fc-dia').setAttribute('aria-pressed', String(S.grao === 'dia'));
    $('fc-semana').setAttribute('aria-pressed', String(S.grao === 'semana'));
    if (!quiet) $('fc-cap-when').textContent = 'A carregar…';
    let d;
    try { d = await getJson(`/planeamento/api/setor/capacidade-prazos?${params({grao: S.grao})}`); } catch (e) { if (mine === S.ticket) { $('fc-cap-when').textContent = ''; fail(e); } return; }
    if (mine !== S.ticket) return;
    if (quiet && d.stale) return again(loadCapacity, mine);
    $('fc-error').hidden = true;
    banner(d.scenario);
    $('fc-cap-when').textContent = computed(d);
    counters(d);
    renderMap(d);
    renderRisks(d);
    renderMissing(d);
    if (d.stale) again(loadCapacity, mine);
  }

  function show(box, opts = {}) {
    if (S.box !== box) { S.box = box; }
    skeleton(box);
    const changed = S.setor !== opts.setor;
    S.setor = opts.setor;
    if (changed) { S.cal = {from: null}; S.open = null; $('fc-day').hidden = true; }
    S.vista = opts.vista;
    $('fc-error').hidden = true;
    $('fc-cal').hidden = S.vista !== 'calendario';
    $('fc-cap').hidden = S.vista !== 'capacidade';
    $('fc-cen').hidden = S.vista !== 'cenarios';
    $('fc-banner').hidden = true;
    clearTimeout(S.timer);
    if (S.vista === 'calendario') loadCalendar();
    else if (S.vista === 'capacidade') loadCapacity();
    else S.ticket++;
    return $('fc-cen');
  }

  window.cargaPrevisao = {show};
})();
