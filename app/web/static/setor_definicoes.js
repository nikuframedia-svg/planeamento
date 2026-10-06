'use strict';
// Definições do setor (06/10/2026): máquinas, turnos padrão, ficha de capacidades, tempos, turnos e feriados.
(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1});
  const DAYS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
  let data = null;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') node.className = v; else if (k === 'checked') node.checked = Boolean(v); else if (k === 'value') node.value = v; else node.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }
  const short = (n) => String(n || '').replace(/^Ficep\s+/i, '');
  const error = (e) => { $('error').textContent = e.message; $('error').hidden = false; };
  const notice = (t) => { $('notice').textContent = t; $('notice').hidden = false; $('error').hidden = true; };

  async function send(payload) {
    const r = await fetch('/planeamento/api/setor/definicoes', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
      body: JSON.stringify({setor: $('setor').value, request_id: crypto.randomUUID(), ...payload})});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
    return body;
  }

  function weeksCell(machine) {
    const w = (data.weeks.find((x) => x.machine === machine.id) || {}).weeks || [];
    return el('div', {class: 'weeks'}, w.map((x) => el('span', {class: `wk${x.manual ? ' manual' : ''}`, title: `${x.year}-S${x.week}: ${fmt.format(x.hours)} h${x.manual ? ' · mudada à mão' : ''}${x.day_changes ? ` · ${x.day_changes} dia(s) diferentes` : ''}`},
      `S${x.week} ${x.shifts === null ? '—' : x.shifts}`)));
  }

  function fichaCell(m) {
    if (!m.ficha.length) return el('span', {class: 'muted'}, 'Sem ficha');
    return el('div', {class: 'ficha'}, m.ficha.map((f) => {
      const ov = m.override[f.operation] || {};
      const lo = el('input', {value: ov.min || '', placeholder: f.min || 'mín.', 'aria-label': `Perfil mínimo ${f.operation}`, size: 11});
      const hi = el('input', {value: ov.max || '', placeholder: f.max || 'máx.', 'aria-label': `Perfil máximo ${f.operation}`, size: 11});
      const save = el('button', {type: 'button', class: 'small'}, 'Gravar');
      save.addEventListener('click', () => {
        const ficha = Object.fromEntries(m.ficha.map((x) => [x.operation, m.override[x.operation] || {}]));
        ficha[f.operation] = {min: lo.value, max: hi.value};
        send({tipo: 'maquina', id: m.id, expected_revision: m.revision, ficha}).then(() => { notice(`Ficha de ${short(m.name)} gravada.`); return load(); }).catch(error);
      });
      return el('div', {class: 'ficha-row', title: f.source || ''}, el('span', {class: 'op'}, `${f.operation.replace('CPIS:', '')} · ${f.process || ''}`), ' ', lo, ' – ', hi, ' ', save);
    }));
  }

  function ratesCell(m) {
    const items = [];
    if (m.excel_rate) items.push(el('div', {title: m.excel_rate.source}, `Excel: ${fmt.format(m.excel_rate.value)} ${m.excel_rate.unit}`));
    if (m.observed_week_hours) items.push(el('div', {class: 'muted'}, `Feito por semana: ${fmt.format(m.observed_week_hours)} h (mediana)`));
    for (const r of m.rates) {
      const archive = el('button', {type: 'button', class: 'linklike', title: 'Deixa de contar; fica no histórico'}, 'Arquivar');
      archive.addEventListener('click', () => {
        if (!confirm('Arquivar esta taxa? Volta a valer a velocidade do Excel (ou outra taxa confirmada).')) return;
        send({tipo: 'taxa', id: r.id, maquina: m.id, metodo: r.method, valor: r.value, operacao: r.operation, perfil: r.profile, desde: r.valid_from, arquivar: true})
          .then(() => { notice(`Taxa de ${short(m.name)} arquivada.`); return load(); }).catch(error);
      });
      items.push(el('div', {class: 'rate'}, `Confirmada: ${fmt.format(r.value)} ${data.methods[r.method] || r.method}${r.profile ? ` · ${r.profile}` : ''}${r.operation ? ` · ${r.operation}` : ''}${r.valid_from ? ` · desde ${r.valid_from}` : ''} `, archive));
    }
    if (m.profile_speeds && m.profile_speeds.length) {
      items.push(el('details', {}, el('summary', {}, `Por perfil (${m.profile_speeds.length})`),
        el('ul', {class: 'speeds'}, m.profile_speeds.map((p) => el('li', {}, `${p.profile}: ${fmt.format(p.value)} m/h (${p.lines})`)))));
    }
    const add = el('details', {class: 'new-rate'}, el('summary', {}, 'Nova taxa confirmada'));
    const method = el('select', {}, Object.entries(data.methods).map(([k, v]) => el('option', {value: k}, v)));
    method.value = data.sector === 'perfis' ? 'area_hour' : 'metres_hour';
    const value = el('input', {type: 'number', step: 'any', min: '0', placeholder: 'valor', 'aria-label': 'Valor da taxa'});
    const op = el('input', {placeholder: data.sector === 'perfis' ? 'corte' : '119', size: 6, 'aria-label': 'Operação'});
    const prof = el('input', {placeholder: 'perfil (opcional)', size: 12, 'aria-label': 'Perfil'});
    const since = el('input', {type: 'date', 'aria-label': 'Válida desde', title: 'Válida desde (vazio = hoje)'});
    const ok = el('button', {type: 'button', class: 'small'}, 'Gravar');
    ok.addEventListener('click', () => send({tipo: 'taxa', maquina: m.id, metodo: method.value, valor: Number(value.value), operacao: op.value, perfil: prof.value, desde: since.value || undefined})
      .then(() => { notice(`Taxa de ${short(m.name)} gravada: passa a ter prioridade sobre o Excel.`); return load(); }).catch(error));
    add.append(el('div', {class: 'rate-form'}, value, method, op, prof, since, ok));
    items.push(add);
    return el('div', {class: 'rates'}, el('strong', {}, m.rate_in_use), items);
  }

  function machineRow(m) {
    const confirm = el('input', {type: 'checkbox', checked: m.confirmed, 'aria-label': `${m.name} confirmada`, disabled: !m.has_object});
    confirm.addEventListener('change', () => send({tipo: 'maquina', id: m.id, expected_revision: m.revision, confirmada: confirm.checked})
      .then(() => { notice(`${short(m.name)}: ${confirm.checked ? 'confirmada' : 'por confirmar'}.`); return load(); }).catch((e) => { confirm.checked = !confirm.checked; error(e); }));
    const turns = el('select', {'aria-label': `Turnos padrão ${m.name}`, disabled: !m.has_object}, [0, 1, 2, 3].map((n) => el('option', {value: n}, String(n))));
    turns.value = String(m.default_shifts);
    turns.addEventListener('change', () => send({tipo: 'maquina', id: m.id, expected_revision: m.revision, turnos_padrao: Number(turns.value)})
      .then((r) => { notice(`${short(m.name)}: ${turns.value} turno(s) padrão; ${r.changed - 1} semana(s) atualizadas.`); return load(); }).catch(error));
    return el('tr', {}, el('th', {scope: 'row'}, short(m.name), el('small', {class: 'muted'}, ` ${m.code || ''}`), namesCell(m)),
      el('td', {}, m.process || '—'), el('td', {}, confirm), el('td', {}, turns), el('td', {}, weeksCell(m)), el('td', {}, fichaCell(m)), el('td', {}, ratesCell(m)));
  }

  // Nomes da máquina no Excel e nas folhas OCR, operações e janela do histórico (antes em «Capacidades e horas»).
  const UNIT = {perfis: 'MTG2', cantoneiras: 'MTG3'}, AREA = {MTG2: 'perfis', MTG3: 'cantoneiras'};
  function namesCell(m) {
    if (!('aliases' in m) || !m.has_object) return null;
    const names = el('textarea', {rows: 3, 'aria-label': `Nomes de ${m.name}`});
    names.value = m.aliases.map((a) => `${UNIT[a.area] || a.area}: ${a.name}`).join('\n');
    const ops = el('input', {value: m.operations.join(', '), 'aria-label': `Operações de ${m.name}`});
    const days = el('input', {type: 'number', min: 1, value: m.history_window_days || 90, 'aria-label': `Dias de histórico de ${m.name}`});
    const save = el('button', {type: 'button', class: 'save small'}, 'Gravar nomes e operações');
    save.addEventListener('click', () => {
      try {
        const nomes = names.value.split('\n').map((x) => x.trim()).filter(Boolean).map((x) => {
          const i = x.indexOf(':'); if (i < 0) throw new Error('Usa «MTG2: nome» ou «MTG3: nome» em cada linha.');
          return {area: AREA[x.slice(0, i).trim().toUpperCase()] || x.slice(0, i).trim().toLowerCase(), name: x.slice(i + 1).trim()};
        });
        send({tipo: 'maquina', id: m.id, expected_revision: m.revision, nomes, operacoes: ops.value.split(',').map((x) => x.trim()).filter(Boolean), janela_historico: Number(days.value)})
          .then(() => { notice(`${short(m.name)}: nomes e operações gravados.`); return load(); }).catch(error);
      } catch (e) { error(e); }
    });
    return el('details', {class: 'names'}, el('summary', {}, 'Nomes e operações'),
      el('label', {}, 'Nomes no Excel e nas folhas (um por linha, «MTG2: nome» ou «MTG3: nome»)', names),
      el('label', {}, 'Operações (separadas por vírgula, ex.: CPIS:112, CPIS:119)', ops),
      el('label', {}, 'Dias de histórico para a produtividade', days), save);
  }

  // Horas reais corrigidas à mão (antes em «Capacidades e horas · Horas reais»): substituem ou completam as horas OCR.
  async function renderWorked() {
    const box = $('worked');
    if (!box) return;
    const own = new Map(data.machines.map((m) => [m.id, m]));
    let items = [];
    try {
      const r = await fetch(`/planeamento/api/raw/objects/worked_hours`, {headers: {Accept: 'application/json'}});
      if (r.ok) items = ((await r.json()).items || []).filter((o) => own.has(String(o.definition.resource_id)));
    } catch { items = []; }
    const machine = el('select', {'aria-label': 'Máquina'}, data.machines.filter((m) => m.confirmed).map((m) => el('option', {value: m.id}, short(m.name))));
    const from = el('input', {type: 'date', 'aria-label': 'De'}), to = el('input', {type: 'date', 'aria-label': 'Até'});
    const hours = el('input', {type: 'number', step: '0.1', min: 0, 'aria-label': 'Horas'}), operation = el('input', {'aria-label': 'Operação (opcional)'});
    const origin = el('input', {value: 'Correção manual', 'aria-label': 'Origem'});
    const replace = el('input', {type: 'checkbox'}), replaceLabel = el('label', {hidden: true}, replace, ' Substituir as horas das folhas OCR deste período');
    const evidence = el('div', {class: 'muted'});
    let basis = null;
    const definition = () => ({resource_id: machine.value, mode: 'period', start_date: from.value, end_date: to.value, hours: hours.value,
      operation: operation.value.trim(), operation_hours: [], replace_ocr: replace.checked, source: origin.value.trim() || 'Correção manual', basis_hash: basis, confirmed: true});
    const check = el('button', {type: 'button'}, 'Conferir as folhas deste período');
    check.addEventListener('click', async () => {
      try {
        const r = await fetch('/planeamento/api/raw/horas/prever', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
          body: JSON.stringify({request_id: crypto.randomUUID(), definition: definition()})});
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
        basis = body.basis_hash;
        const obs = body.observations || [];
        replaceLabel.hidden = !obs.length;
        evidence.textContent = obs.length ? `Folhas OCR neste período: ${obs.map((o) => `${o.date} ${fmt.format(o.hours)} h`).join(' · ')}` : 'Sem horas OCR neste período.';
        if (body.scope_conflict) evidence.textContent += ` ${body.scope_conflict}`;
      } catch (e) { error(e); }
    });
    const save = el('button', {type: 'button', class: 'save'}, 'Gravar horas reais');
    save.addEventListener('click', async () => {
      try {
        if (!basis) throw new Error('Confere as folhas deste período antes de gravar.');
        const m = own.get(machine.value);
        const r = await fetch('/planeamento/api/raw/objects/worked_hours', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
          body: JSON.stringify({request_id: crypto.randomUUID(), expected_revision: 0, name: `${m.name} · ${from.value} a ${to.value}`, area: $('setor').value, definition: definition()})});
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
        notice(`Horas reais gravadas para ${short(m.name)}.`);
        basis = null;
        await renderWorked();
      } catch (e) { error(e); }
    });
    box.replaceChildren(
      items.length ? el('ul', {}, items.map((o) => el('li', {}, `${short((own.get(String(o.definition.resource_id)) || {}).name || '')} · ${o.definition.start_date || ''} a ${o.definition.end_date || ''} · ${fmt.format(Number(o.definition.hours) || 0)} h${o.definition.replace_ocr ? ' · substitui OCR' : ''} · ${o.definition.source || ''}`)))
        : el('p', {class: 'muted'}, 'Ainda não há horas corrigidas à mão neste setor.'),
      el('div', {class: 'worked-form'}, el('label', {}, 'Máquina', machine), el('label', {}, 'De', from), el('label', {}, 'Até (mesma semana)', to),
        el('label', {}, 'Horas', hours), el('label', {}, 'Operação (opcional)', operation), el('label', {}, 'Origem', origin)),
      el('div', {class: 'worked-actions'}, check, replaceLabel, save), evidence);
  }

  function renderShifts(s) {
    const names = ['1.º turno', '2.º turno', '3.º turno'];
    $('template').replaceChildren(...[0, 1, 2].map((i) => {
      const pair = s.template[i] || ['', ''];
      return el('div', {class: 'shift'}, el('span', {}, names[i]),
        el('input', {type: 'time', value: pair[0], 'aria-label': `${names[i]} início`, 'data-i': i, 'data-k': 0}), ' – ',
        el('input', {type: 'time', value: pair[1], 'aria-label': `${names[i]} fim`, 'data-i': i, 'data-k': 1}),
        el('small', {class: 'muted'}, data.shift_hours[i] ? ` ${fmt.format(data.shift_hours[i])} h` : ''));
    }));
    $('workdays').replaceChildren(...DAYS.map((d, i) => el('label', {class: 'day'}, el('input', {type: 'checkbox', value: i + 1, checked: s.workdays.includes(i + 1)}), ` ${d}`)));
    $('holidays').value = (s.holidays || []).join('\n');
  }

  async function load() {
    const r = await fetch(`/planeamento/api/setor/definicoes?setor=${encodeURIComponent($('setor').value)}`, {headers: {Accept: 'application/json'}});
    data = await r.json();
    if (!r.ok) throw new Error(data.error || `Erro ${r.status}`);
    $('machines').replaceChildren(...data.machines.map(machineRow));
    renderShifts(data.settings);
    $('rules').replaceChildren(...data.rules.map((t) => el('li', {}, t)));
    renderWorked().catch(error);
  }

  async function saveShifts(event) {
    event.preventDefault();
    const turnos = [0, 1, 2].map((i) => [...$('template').querySelectorAll(`input[data-i="${i}"]`)].map((x) => x.value)).filter((p) => p[0] && p[1]);
    const dias = [...$('workdays').querySelectorAll('input:checked')].map((x) => Number(x.value));
    const feriados = $('holidays').value.split(/\s+/).filter(Boolean);
    const r = await send({tipo: 'setor', expected_revision: data.settings.revision, turnos, dias, feriados});
    notice(`Turnos e feriados gravados; ${r.changed} calendário(s) semanais atualizados.`);
    await load();
  }

  document.addEventListener('DOMContentLoaded', () => {
    const initial = new URLSearchParams(location.search).get('setor');
    if (initial) $('setor').value = initial;
    $('setor').addEventListener('change', () => load().catch(error));
    $('shift-form').addEventListener('submit', (e) => saveShifts(e).catch(error));
    load().catch(error);
  });
})();
