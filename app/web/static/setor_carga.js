'use strict';
// Carga e turnos (06/10/2026): máquina × semana, − / + turno, recomendação e detalhe por OF.
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
    previstas: 'Horas que a Carga usa: taxa confirmada; senão velocidade do Excel (mediana da máquina e perfil na MTG3, mm²/h na MTG2).',
    excel: 'Horas pela regra do próprio Excel, só na operação principal: MTG3 metros em falta ÷ velocidade Mt\\h da linha; MTG2 área ÷ taxa da folha CapacidadeMáquinas (×3 no Thomas acima de 50 peças). Escalada ao saldo atual.',
    reais: 'Horas declaradas nas folhas OCR validadas e horas corrigidas à mão, pela data de produção.',
    capacidade: 'Horas dos turnos dessa semana no calendário da máquina (na semana atual, só as que faltam).',
    calendarioExcel: 'Turnos × horas por turno da folha PlanDisponibilidadeSemanal do Excel (só MTG2).',
  };
  let data = null, open = null, ticket = 0;
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

  function cell(m, w) {
    const pct = w.capacity ? Math.min(100, Math.round(100 * w.load / w.capacity)) : (w.load ? 100 : 0);
    const minus = el('button', {type: 'button', class: 'pm', 'aria-label': `Menos um turno ${m.name} S${w.week}`, disabled: w.shifts <= 0}, '−');
    const plus = el('button', {type: 'button', class: 'pm', 'aria-label': `Mais um turno ${m.name} S${w.week}`, disabled: w.shifts >= 3}, '+');
    minus.addEventListener('click', (e) => { e.stopPropagation(); shiftsChange([{maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts - 1}], `${short(m.name)} S${w.week}`).catch(error); });
    plus.addEventListener('click', (e) => { e.stopPropagation(); shiftsChange([{maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts + 1}], `${short(m.name)} S${w.week}`).catch(error); });
    const advice = w.advice || {};
    const apply = advice.delta ? el('button', {type: 'button', class: 'apply small', title: advice.text}, `${advice.delta > 0 ? '+' : ''}${advice.delta} · Aplicar`) : null;
    if (apply) apply.addEventListener('click', (e) => { e.stopPropagation(); shiftsChange([{maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts + advice.delta}], `${short(m.name)} S${w.week}`).catch(error); });
    const extra = [
      w.excel_hours !== undefined ? `Horas segundo o Excel: ${h1.format(w.excel_hours)} h${w.excel_unknown ? ` (${w.excel_unknown} operações principais sem horas do Excel)` : ''}` : '',
      w.actual_hours !== undefined && w.actual_hours !== null ? `Horas reais declaradas: ${h1.format(w.actual_hours)} h` : '',
      w.excel_calendar_hours ? `Calendário do Excel: ${h1.format(w.excel_calendar_hours)} h` : ''].filter(Boolean).join('\n');
    const td = el('td', {class: `c ${w.status}${open && open.m === m.id && open.w === w.week && open.y === w.year ? ' open' : ''}`, tabindex: 0,
      title: `No plano ${h1.format(w.plan)} h · a vencer ${h1.format(w.due)} h · sugerida ${h1.format(w.suggested)} h${w.late ? ` · atrasado ${h1.format(w.late)} h` : ''}${w.unknown ? ` · ${w.unknown} operações sem horas` : ''}${extra ? '\n' + extra : ''}\n${advice.text || ''}`},
      el('div', {class: 'top'}, minus, el('span', {class: 'cap'}, `${w.shifts} t · ${h.format(w.capacity)} h`, w.manual ? el('span', {class: 'man', title: 'Mudada à mão'}, ' ✎') : null), plus),
      el('div', {class: 'bar'}, el('span', {class: 'fill', style: `width:${pct}%`})),
      el('div', {class: 'nums'}, el('span', {class: 'k plan'}, h.format(w.plan)), ' + ', el('span', {class: 'k due'}, h.format(w.due)), ' + ', el('span', {class: 'k sug'}, h.format(w.suggested)),
        ` = ${h.format(w.load)} h`, w.unknown ? el('span', {class: 'muted'}, ` · ${w.unknown}?`) : null),
      el('div', {class: 'adv'}, apply || el('span', {class: 'muted'}, advice.text && !advice.delta ? (/^(Certo|Sobram)/.test(advice.text) ? 'Certo' : advice.text) : '')));
    td.addEventListener('click', () => showDetail(m, w));
    td.addEventListener('keydown', (e) => { if (e.key === 'Enter') showDetail(m, w); });
    return td;
  }

  function renderWeeks() {
    $('head').replaceChildren(el('tr', {}, el('th', {scope: 'col'}, 'Máquina'),
      ...data.weeks.map((w, i) => el('th', {scope: 'col'}, `S${w.week}`, el('small', {}, ` ${dm(w.monday)}`), i === 0 ? el('small', {class: 'muted'}, ' (atual)') : null))));
    $('body').replaceChildren(...data.machines.map((m) => el('tr', {},
      el('th', {scope: 'row'}, short(m.name), el('small', {class: 'muted'}, ` ${m.process || ''}`),
        m.no_date.operations ? el('div', {class: 'muted small'}, `Sem prazo: ${h.format(m.no_date.hours)} h${m.no_date.unknown ? ` · ${m.no_date.unknown} operações sem horas` : ''}`) : null),
      ...m.weeks.map((w) => cell(m, w)))));
    const advice = data.machines.flatMap((m) => m.weeks.filter((w) => w.advice && w.advice.delta).map((w) => ({maquina: m.id, ano: w.year, semana: w.week, turnos: w.shifts + w.advice.delta})));
    $('apply-all').hidden = !advice.length || view() !== 'semanas';
    $('apply-all').textContent = `Aplicar todas as recomendações (${advice.length})`;
    $('apply-all').onclick = () => { if (confirm(`Mudar os turnos em ${advice.length} semana(s)/máquina(s)?`)) shiftsChange(advice, 'Recomendações').catch(error); };
  }

  // Separador Máquinas: totais de todo o trabalho aberto por máquina (o que a antiga «Capacidades das máquinas» mostrava).
  function renderMachines() {
    const perfis = $('setor').value === 'perfis';
    const head = ['Máquina', perfis ? 'Área por cortar (mm²)' : 'Metros por fazer', 'Peças por fazer', 'Peso (kg)', 'Horas previstas', 'Horas segundo o Excel', 'Atrasado (h)', 'Sem prazo (h)', 'Horas reais (4 semanas)', 'Operações sem horas'];
    const keys = {'Horas previstas': 'previstas', 'Horas segundo o Excel': 'excel', 'Horas reais (4 semanas)': 'reais'};
    $('machines-table').replaceChildren(
      el('thead', {}, el('tr', {}, ...head.map((x) => el('th', {scope: 'col', title: EXPLAIN[keys[x]] || null}, x)))),
      el('tbody', {}, (data.totals || []).map((t) => {
        const recent = (t.actual_recent || []).filter((x) => x.hours !== null && x.hours !== undefined);
        return el('tr', {class: t.id ? '' : 'nomachine'},
          el('th', {scope: 'row'}, short(t.name), t.process ? el('small', {class: 'muted'}, ` ${t.process}`) : null),
          el('td', {class: 'num'}, perfis ? h.format(t.area_mm2) : h.format(t.metres)), el('td', {class: 'num'}, h.format(t.pieces)),
          el('td', {class: 'num'}, h.format(t.weight_kg), t.weight_unknown ? el('small', {class: 'muted'}, ` · ${t.weight_unknown}?`) : null),
          el('td', {class: 'num'}, h1.format(t.load)), el('td', {class: 'num'}, h1.format(t.excel_hours), t.excel_unknown ? el('small', {class: 'muted', title: 'Operações principais sem horas do Excel (falta velocidade, comprimento ou área no Excel)'}, ` · ${t.excel_unknown}?`) : null),
          el('td', {class: 'num'}, h1.format(t.late)), el('td', {class: 'num'}, h1.format(t.no_date)),
          el('td', {class: 'num'}, recent.length ? recent.map((x) => `S${x.week} ${h1.format(x.hours)}`).join(' · ') : '—'),
          el('td', {class: 'num'}, t.unknown ? h.format(t.unknown) : ''));
      })));
    $('machines-note').textContent = (data.totals || []).some((t) => (t.actual_recent || []).some((x) => x.hours)) ? '' :
      'Horas reais: as folhas OCR validadas destas máquinas ainda não trazem horas trabalhadas; podem ser corrigidas à mão nas Definições do setor.';
  }

  function renderElsewhere() {
    const e = data.elsewhere, box = $('elsewhere');
    box.hidden = !e || !e.operations;
    if (!e || !e.operations) return;
    box.textContent = `${h.format(e.operations)} operações deste setor estão em máquinas de outro setor (não contam aqui): ` +
      e.machines.map((m) => `${short(m.name)} ${h.format(m.operations)} op. · ${h1.format(m.hours)} h`).join(' · ');
  }

  function render() {
    renderElsewhere();
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
    const rows = [
      [named('Capacidade', 'capacidade'), hrs(w.capacity)],
      [named('Horas previstas', 'previstas'), `${hrs(w.load)} (no plano ${h1.format(w.plan)} · a vencer ${h1.format(w.due)} · sugerida ${h1.format(w.suggested)}${w.late ? ` · atrasado ${h1.format(w.late)}` : ''})`],
      [named('Horas segundo o Excel', 'excel'), d && d.excel_hours !== undefined ? `${hrs(d.excel_hours)}${d.excel_unknown ? ` · ${d.excel_unknown} operações principais sem horas do Excel` : ''}` : '…'],
      [named('Horas reais declaradas', 'reais'), d && d.actual_hours !== undefined ? hrs(d.actual_hours) : '…'],
      ['Peso (kg)', d && d.weight_kg !== undefined ? h.format(d.weight_kg) : '…'],
    ];
    if (d && d.excel_calendar_hours) rows.push([named('Calendário do Excel', 'calendarioExcel'), hrs(d.excel_calendar_hours)]);
    return el('table', {class: 'summary', id: 'detail-summary'}, el('tbody', {}, rows.map(([k, v]) => el('tr', {}, el('th', {scope: 'row'}, k), el('td', {}, v)))));
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
    const week = `${w.year}-W${String(w.week).padStart(2, '0')}`;
    box.replaceChildren(el('h2', {}, `${short(m.name)} · S${w.week} (${dm(w.monday)})`),
      el('p', {}, el('b', {}, w.advice.text || '')),
      summaryTable(m, w, null),
      el('h3', {}, 'Turnos por dia'), days,
      el('h3', {}, 'OF nesta célula'), el('div', {id: 'detail-orders'}, el('p', {class: 'muted'}, 'A carregar…')),
      el('div', {id: 'detail-operations'}),
      el('h3', {}, 'Produção registada nesta semana'), el('div', {id: 'detail-production'}, el('button', {type: 'button', id: 'production-open'}, 'Ver produção registada')),
      el('p', {}, el('a', {href: `/planeamento/gantt?setor=${encodeURIComponent($('setor').value)}&semana=${week}`}, 'Ver no Gantt desta semana →')));
    $('production-open').addEventListener('click', () => showProduction(m, w, 1).catch(error));
    try {
      const d = await getJson(`/planeamento/api/setor/carga/celula?${new URLSearchParams({setor: $('setor').value, maquina: m.id, ano: w.year, semana: w.week})}`);
      if (t !== ticket) return;
      $('detail-summary').replaceWith(summaryTable(m, w, d));
      const table = el('div', {class: 'scroll'}, el('table', {class: 'orders'},
        el('thead', {}, el('tr', {}, ...['OF', 'Cliente', 'Horas previstas', 'Horas segundo o Excel', 'Sem horas', 'Peças', 'Metros', 'Peso (kg)', 'Prazo', 'Atraso', 'Tipo', ''].map((x) => el('th', {scope: 'col', title: x === 'Horas segundo o Excel' ? EXPLAIN.excel : x === 'Horas previstas' ? EXPLAIN.previstas : null}, x)))),
        el('tbody', {}, d.orders.map((o) => {
          const tr = el('tr', {class: 'clickable', tabindex: 0, title: 'Ver as operações e o cálculo'}, el('td', {}, o.of), el('td', {}, o.customer || ''), el('td', {class: 'num'}, h1.format(o.hours)),
            el('td', {class: 'num'}, o.excel_hours !== undefined ? h1.format(o.excel_hours) + (o.excel_unknown ? ` · ${o.excel_unknown}?` : '') : ''),
            el('td', {class: 'num'}, o.unknown || ''), el('td', {class: 'num'}, h.format(o.pieces)), el('td', {class: 'num'}, h.format(o.metres)),
            el('td', {class: 'num'}, o.weight_kg !== undefined ? h.format(o.weight_kg) : ''),
            el('td', {}, o.priority_day ? dm(o.priority_day) : '—'), el('td', {class: 'num'}, o.late_days ? `${o.late_days} d` : ''),
            el('td', {}, o.kinds.map((k) => KIND[k]).join(', ')),
            el('td', {}, el('a', {href: `/planeamento/carteira?setor=${encodeURIComponent($('setor').value)}&vista=of_perfil&q=${encodeURIComponent(o.of)}`}, 'Carteira')));
          const go = () => showOperations(m, w, o.of).catch(error);
          tr.addEventListener('click', (e) => { if (!e.target.closest('a')) go(); });
          tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
          return tr;
        }))));
      $('detail-orders').replaceChildren(el('p', {class: 'muted'}, `${d.orders.length} OF · ${h1.format(d.hours)} h${d.unknown ? ` · ${d.unknown} operações sem horas` : ''}. Clica numa OF para ver as operações e o cálculo.`), table);
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
      ['Horas previstas', `${h1.format(e.volume)} ÷ ${h1.format(e.rate)} = ${hrs(e.hours)}`],
    ];
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
          el('td', {class: 'num'}, o.weight_kg !== null && o.weight_kg !== undefined ? h.format(o.weight_kg) : ''),
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

  async function load() {
    data = await getJson(`/planeamento/api/setor/carga?setor=${encodeURIComponent($('setor').value)}`);
    render();
    if (open) {
      const m = data.machines.find((x) => x.id === open.m);
      const w = m && m.weeks.find((x) => x.week === open.w && x.year === open.y);
      if (m && w) showDetail(m, w);
    }
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
