'use strict';
// Definições do setor (06/10/2026): máquinas, turnos padrão, ficha de capacidades, velocidades das máquinas, turnos e feriados.
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

  // Com a tabela de velocidades (API nova) a coluna da máquina só diz que velocidade está em uso.
  function inUseCell(m) {
    return el('div', {class: 'rates'}, el('strong', {}, m.rate_in_use || '—'),
      m.excel_rate ? el('span', {class: 'muted', title: m.excel_rate.source || ''}, `Excel: ${fmt.format(m.excel_rate.value)} ${m.excel_rate.unit}`) : null);
  }

  // Sem a caixa «confirmada» (07/10/2026): qualquer máquina do setor tem calendários, velocidades e horas reais.
  function machineRow(m) {
    const turns = el('select', {'aria-label': `Turnos padrão ${m.name}`, disabled: !m.has_object}, [0, 1, 2, 3].map((n) => el('option', {value: n}, String(n))));
    turns.value = String(m.default_shifts);
    turns.addEventListener('change', () => send({tipo: 'maquina', id: m.id, expected_revision: m.revision, turnos_padrao: Number(turns.value)})
      .then((r) => { notice(`${short(m.name)}: ${turns.value} turno(s) padrão; ${r.changed - 1} semana(s) atualizadas.`); return load(); }).catch(error));
    return el('tr', {}, el('th', {scope: 'row'}, short(m.name), el('small', {class: 'muted'}, ` ${m.code || ''}`), namesCell(m)),
      el('td', {}, m.process || '—'), el('td', {}, turns), el('td', {}, weeksCell(m)), el('td', {}, fichaCell(m)), el('td', {}, data.speed_table ? inUseCell(m) : ratesCell(m)));
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
    const machine = el('select', {'aria-label': 'Máquina'}, data.machines.filter((m) => m.has_object).map((m) => el('option', {value: m.id}, short(m.name))));
    const from = el('input', {type: 'date', 'aria-label': 'De'}), to = el('input', {type: 'date', 'aria-label': 'Até'});
    const hours = el('input', {type: 'number', step: '0.1', min: 0, 'aria-label': 'Horas'}), operation = el('input', {'aria-label': 'Operação (opcional)'});
    const origin = el('input', {value: 'Correção manual', 'aria-label': 'Origem'});
    const replace = el('input', {type: 'checkbox', checked: true}), replaceLabel = el('label', {}, replace, ' Substituir as horas das folhas OCR deste período');
    const evidence = el('div', {class: 'muted worked-evidence'});
    const definition = (basis) => ({resource_id: machine.value, mode: 'period', start_date: from.value, end_date: to.value, hours: hours.value,
      operation: operation.value.trim(), operation_hours: [], replace_ocr: replace.checked, source: origin.value.trim() || 'Correção manual', basis_hash: basis, confirmed: true});
    const post = async (url, payload) => {
      const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify({request_id: crypto.randomUUID(), ...payload})});
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
      return body;
    };
    // Gravar confere logo as folhas OCR do período (07/10/2026): já não há um passo «Conferir» à parte.
    const save = el('button', {type: 'button', class: 'save'}, 'Gravar horas reais');
    save.addEventListener('click', async () => {
      try {
        const m = own.get(machine.value);
        if (!m) throw new Error('Escolhe a máquina.');
        const checked = await post('/planeamento/api/raw/horas/prever', {definition: definition(null)});
        const obs = checked.observations || [];
        await post('/planeamento/api/raw/objects/worked_hours', {expected_revision: 0, name: `${m.name} · ${from.value} a ${to.value}`, area: $('setor').value,
          definition: definition(checked.basis_hash)});
        notice(`Horas reais gravadas para ${short(m.name)}.`);
        await renderWorked();
        $('worked').querySelector('.worked-evidence').textContent = obs.length
          ? `Folhas OCR neste período: ${obs.map((o) => `${o.date} ${fmt.format(o.hours)} h`).join(' · ')}` : 'Sem horas OCR neste período.';
      } catch (e) { error(e); }
    });
    box.replaceChildren(
      items.length ? el('ul', {}, items.map((o) => el('li', {}, `${short((own.get(String(o.definition.resource_id)) || {}).name || '')} · ${o.definition.start_date || ''} a ${o.definition.end_date || ''} · ${fmt.format(Number(o.definition.hours) || 0)} h${o.definition.replace_ocr ? ' · substitui OCR' : ''} · ${o.definition.source || ''}`)))
        : el('p', {class: 'muted'}, 'Ainda não há horas corrigidas à mão neste setor.'),
      el('div', {class: 'worked-form'}, el('label', {}, 'Máquina', machine), el('label', {}, 'De', from), el('label', {}, 'Até (mesma semana)', to),
        el('label', {}, 'Horas', hours), el('label', {}, 'Operação (opcional)', operation), el('label', {}, 'Origem', origin)),
      el('div', {class: 'worked-actions'}, replaceLabel, save), evidence);
  }

  // Velocidades das máquinas (plano de 06/10, parte 3), como o ecrã «Planeamento Corte Térmico»: filtro por máquina,
  // separadores por operação, uma linha por velocidade, grava cada linha quando se sai dela (ou no botão Gravar).
  // Só aparece quando a API traz `speed_table`; sem ela fica a coluna antiga de taxas na tabela das máquinas.
  const speed = {tab: null, machine: '', drafts: [], preview: false, queue: Promise.resolve()};
  let draftSeq = 0;
  const shown = (v) => (v === null || v === undefined || v === '' ? '' : String(v).replace('.', ','));
  function num(v) {
    const t = String(v ?? '').trim().replace(/[\s  ]/g, '').replace(',', '.');
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : NaN;
  }
  // Uma gravação de cada vez, pela ordem em que foram pedidas (sair de uma linha e carregar ✕ noutra, por exemplo).
  const queued = (task) => { const run = speed.queue.then(task, task); speed.queue = run.catch(() => {}); return run; };

  function speedColumns(st) {
    const range = st.range || {};
    if (range.field === 'section') {
      return [
        {key: 'machine', label: 'Máquina'},
        {key: 'material_type', label: 'Tipo de material', text: true, placeholder: 'todos', send: 'tipo_material'},
        {key: 'section_min', label: `Área de (${range.unit || 'mm²'})`, placeholder: 'opcional', send: 'area_de'},
        {key: 'section_max', label: `Área até (${range.unit || 'mm²'})`, placeholder: 'opcional', send: 'area_ate'},
        {key: 'value', label: `Velocidade (${st.unit})`, send: 'valor'},
        {key: 'piece_seconds', label: 'Tempo por corte (s)', placeholder: '0', send: 'arranque_s'},
        {key: 'notes', label: 'Notas', text: true, send: 'notas'}];
    }
    return [
      {key: 'machine', label: 'Máquina'},
      {key: 'thickness_min', label: `Esp. de (${range.unit || 'mm'})`, send: 'esp_de'},
      {key: 'thickness_max', label: `Esp. até (${range.unit || 'mm'})`, send: 'esp_ate'},
      {key: 'value', label: `Velocidade (${st.unit})`, send: 'valor'},
      {key: 'piece_seconds', label: 'Arranque por peça (s)', placeholder: '0', send: 'arranque_s'},
      {key: 'notes', label: 'Notas', text: true, send: 'notas'}];
  }

  function speedTabs(st, machines, rates) {
    const own = new Set(machines.map((m) => m.id));
    const tabs = new Map();
    for (const t of st.operations || []) {  // só operações que uma máquina do setor faz (ou que já têm linhas)
      if ((t.machines || []).some((id) => own.has(id)) || rates.some((r) => r.operation_code === t.code)) tabs.set(t.code, t);
    }
    for (const r of rates) if (!tabs.has(r.operation_code)) tabs.set(r.operation_code, {code: r.operation_code, label: r.operation_code || 'Todas as operações', machines: []});
    return [...tabs.values()];
  }

  function timingForm(st) {
    const labels = st.timing_labels || {};
    const margin = el('input', {value: shown((st.timing || {}).margin_pct ?? 0), inputmode: 'decimal', class: 'n', id: 'speed-margin', 'aria-label': labels.margin_pct || 'Margem (%)'});
    const fixed = el('input', {value: shown((st.timing || {}).piece_minutes ?? 0), inputmode: 'decimal', class: 'n', id: 'speed-fixed', 'aria-label': labels.piece_minutes || 'Tempo fixo por peça (min)'});
    const save = el('button', {type: 'button', class: 'small', id: 'speed-timing-save'}, 'Gravar');
    save.addEventListener('click', () => {
      const m = num(margin.value), f = num(fixed.value);
      if (Number.isNaN(m) || Number.isNaN(f)) { error(new Error('Margem e tempo fixo: indica números.')); return; }
      queued(() => send({tipo: 'tempos', expected_revision: data.settings.revision, margin_pct: m ?? 0, piece_minutes: f ?? 0}))
        .then(() => { notice(`Margem ${fmt.format(m ?? 0)} % e tempo fixo ${fmt.format(f ?? 0)} min por peça gravados.`); return load(); }).catch(error);
    });
    return el('div', {class: 'speed-timing'},
      el('label', {}, labels.margin_pct || 'Margem sobre os tempos estimados (%)', margin),
      el('label', {}, labels.piece_minutes || 'Tempo fixo por peça (min)', fixed), save,
      el('span', {class: 'muted'}, '0 = as horas não mudam.'));
  }

  function seedBox(st, tabs) {
    const seed = st.seed || [];
    const label = (code) => (tabs.find((t) => t.code === code) || {}).label || code;
    if (!speed.preview) {
      const open = el('button', {type: 'button', class: 'small', id: 'speed-seed'}, 'Preencher com as velocidades atuais do Excel');
      open.addEventListener('click', () => { speed.preview = true; renderSpeeds(); });
      return el('div', {class: 'speed-seed'}, open);
    }
    const create = el('button', {type: 'button', class: 'save', id: 'speed-seed-create'}, `Criar estas ${seed.length} linhas`);
    const cancel = el('button', {type: 'button', class: 'small'}, 'Cancelar');
    cancel.addEventListener('click', () => { speed.preview = false; renderSpeeds(); });
    create.addEventListener('click', () => {
      create.disabled = true;
      queued(() => send({tipo: 'taxas_lote', linhas: seed.map((x) => ({...x, origem: 'Excel'}))}))
        .then((r) => { speed.preview = false; notice(`${r.changed} linha(s) criadas com as velocidades do Excel; ficam «origem Excel» até as confirmares.`); return load(); })
        .catch((e) => { create.disabled = false; error(e); });
    });
    return el('div', {class: 'speed-seed preview', id: 'speed-seed-preview'},
      el('p', {}, `Vai criar ${seed.length} linhas, marcadas «origem Excel»:`),
      el('div', {class: 'scroll'}, el('table', {class: 'grid speed-preview'},
        el('thead', {}, el('tr', {}, ['Máquina', 'Operação', 'Velocidade', 'Notas'].map((h) => el('th', {scope: 'col'}, h)))),
        el('tbody', {}, seed.map((x) => el('tr', {}, el('td', {}, short(x.nome)), el('td', {}, label(x.operacao)),
          el('td', {class: 'num'}, `${fmt.format(x.valor)} ${x.unidade || ''}`), el('td', {class: 'muted'}, x.notas || '')))))),
      el('div', {class: 'speed-actions'}, create, cancel));
  }

  function speedStatus(tr, text, bad) {
    const s = tr.querySelector('.row-status');
    if (!s) return;
    s.textContent = text;
    s.classList.toggle('bad', Boolean(bad));
  }

  function speedRow(st, cols, tab, options, item) {
    const r = item.rate;
    const tr = el('tr', {'data-key': item.key, class: [r && !r.in_force ? 'off' : '', r && r.source === 'Excel' ? 'excel' : ''].join(' ').trim() || null,
      title: r && !r.in_force ? (r.valid_from && r.valid_from > new Date().toISOString().slice(0, 10) ? `Só vale a partir de ${r.valid_from}` : `Terminou em ${r.valid_until || ''}`) : null});
    const inputs = {};
    const saveBtn = el('button', {type: 'button', class: 'small row-save', hidden: true}, 'Gravar');
    const markDirty = () => {
      tr.dataset.dirty = '1';
      saveBtn.hidden = false;
      speedStatus(tr, '');
      if (!r) for (const c of cols) item.values[c.key] = inputs[c.key].value;  // linha nova: sobrevive a um recarregar
    };
    for (const c of cols) {
      let input;
      if (c.key === 'machine') {
        input = el('select', {'aria-label': 'Máquina', 'data-field': 'machine'},
          r ? null : el('option', {value: ''}, 'Escolhe…'), options.map((m) => el('option', {value: m.id}, short(m.name))));
        input.value = item.values.machine || '';
      } else {
        const raw = item.values[c.key];
        input = el('input', {value: r ? (c.text ? (raw || '') : shown(raw)) : (raw ?? ''), inputmode: c.text ? null : 'decimal',
          placeholder: c.placeholder || null, 'aria-label': c.label, 'data-field': c.key, class: c.text ? 'txt' : 'n'});
      }
      input.addEventListener('input', markDirty);
      input.addEventListener('change', markDirty);
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && c.key !== 'machine') { e.preventDefault(); save(); } });
      inputs[c.key] = input;
      const extra = [];
      if (c.key === 'value' && r && r.method && r.method !== st.method) extra.push(el('small', {class: 'muted'}, ` ${data.methods[r.method] || r.method}`));
      if (c.key === 'notes' && r && r.source === 'Excel') {
        const ok = el('button', {type: 'button', class: 'linklike tag', title: 'Velocidade copiada do Excel. Confirmar (ou editar a linha) passa-a a confirmada.'}, 'origem Excel · confirmar');
        ok.addEventListener('click', () => { tr.dataset.dirty = '1'; save(); });
        extra.push(' ', ok);
      }
      tr.append(el('td', {class: c.key === 'machine' ? 'mach' : null}, input, extra));
    }
    const del = el('button', {type: 'button', class: 'del', title: 'Apagar linha', 'aria-label': 'Apagar linha'}, '✕');
    del.addEventListener('click', () => {
      if (!r) { speed.drafts = speed.drafts.filter((d) => d !== item); tr.remove(); return; }
      if (!confirm('Apagar esta linha da tabela de velocidades? Deixa de contar e fica no histórico.')) return;
      queued(() => send({tipo: 'taxa', id: r.id, expected_revision: r.revision, arquivar: true}))
        .then(() => { notice('Linha apagada da tabela de velocidades.'); return load(); })
        .catch((e) => { speedStatus(tr, e.message, true); error(e); });
    });
    saveBtn.addEventListener('click', () => save());
    tr.append(el('td', {}, el('div', {class: 'acts'}, saveBtn, del, el('span', {class: 'row-status', role: 'status'}))));
    tr.addEventListener('focusout', (e) => { if (tr.dataset.dirty && !tr.contains(e.relatedTarget)) save(); });

    function save() {
      if (!tr.dataset.dirty) return;
      const v = {};
      for (const c of cols) v[c.key] = c.key === 'machine' ? inputs.machine.value : c.text ? inputs[c.key].value.trim() : num(inputs[c.key].value);
      const badNumber = cols.find((c) => !c.text && c.key !== 'machine' && Number.isNaN(v[c.key]));
      if (badNumber) { speedStatus(tr, `${badNumber.label}: indica um número.`, true); return; }
      if (!v.machine) { speedStatus(tr, 'Escolhe a máquina.', true); return; }
      if (!(v.value > 0)) { speedStatus(tr, 'Falta a velocidade.', true); return; }
      const payload = {tipo: 'taxa', maquina: v.machine, operacao: tab.code, metodo: (r && r.method) || st.method};
      for (const c of cols) if (c.send) payload[c.send] = v[c.key];
      if (r) Object.assign(payload, {id: r.id, expected_revision: r.revision, perfil: r.profile || '', desde: r.valid_from || undefined, ate: r.valid_until || undefined});
      delete tr.dataset.dirty;
      saveBtn.hidden = true;
      speedStatus(tr, 'A gravar…');
      const name = short((options.find((m) => m.id === v.machine) || {}).name || '');
      queued(() => send(payload)).then(() => {
        notice(`Velocidade de ${name} gravada${r ? '' : ' (linha nova)'}.`);
        if (!r) { speed.drafts = speed.drafts.filter((d) => d !== item); return load(); }
        // Linha existente: atualiza só esta linha (a revisão sobe um), sem redesenhar o que se está a escrever.
        Object.assign(r, {revision: r.revision + 1, source: 'Confirmada', resource_id: v.machine});
        for (const c of cols) if (c.key !== 'machine') r[c.key] = v[c.key];
        tr.classList.remove('excel');
        tr.querySelector('.tag')?.remove();
        speedStatus(tr, 'Gravado');
        return null;
      }).catch((e) => { tr.dataset.dirty = '1'; saveBtn.hidden = false; speedStatus(tr, e.message, true); error(e); });
    }
    return tr;
  }

  function renderSpeeds() {
    const section = $('speeds-block'), box = $('speeds'), st = data.speed_table;
    if (!section || !box) return;
    if (!st) { section.hidden = true; return; }
    section.hidden = false;
    // Volta a pôr o cursor onde estava (recarregar depois de gravar redesenha a tabela).
    const active = document.activeElement && box.contains(document.activeElement) ? document.activeElement : null;
    const keep = active && active.closest('tr[data-key]') && active.dataset.field
      ? {key: active.closest('tr[data-key]').dataset.key, field: active.dataset.field} : null;
    const byId = new Map(data.machines.map((m) => [m.id, m]));
    const machines = data.machines.filter((m) => m.has_object);
    const rates = data.machines.flatMap((m) => m.rates || []).map((r) => ({...r, resource_id: String(r.resource_id)}));
    const tabs = speedTabs(st, machines, rates);
    const cols = speedColumns(st);
    const parts = [timingForm(st), el('p', {class: 'muted speed-rule'}, st.rule || '')];
    if (!tabs.length) {
      box.replaceChildren(...parts, el('p', {class: 'muted'}, 'Ainda não há máquinas com operações neste setor.'));
      return;
    }
    if (!tabs.some((t) => t.code === speed.tab)) speed.tab = tabs[0].code;
    const tab = tabs.find((t) => t.code === speed.tab);
    const filterMachines = machines.filter((m) => tabs.some((t) => (t.machines || []).includes(m.id)) || rates.some((r) => r.resource_id === m.id));
    if (speed.machine && !filterMachines.some((m) => m.id === speed.machine)) speed.machine = '';
    const filter = el('select', {id: 'speed-filter', 'aria-label': 'Filtrar por máquina'},
      el('option', {value: ''}, 'Todas as máquinas'), filterMachines.map((m) => el('option', {value: m.id}, short(m.name))));
    filter.value = speed.machine;
    filter.addEventListener('change', () => { speed.machine = filter.value; renderSpeeds(); });
    const add = el('button', {type: 'button', class: 'small', id: 'speed-add'}, 'Adicionar linha');
    add.addEventListener('click', () => {
      const item = {key: `new-${++draftSeq}`, tab: tab.code, values: {machine: speed.machine || ''}};
      speed.drafts.push(item);
      renderSpeeds();
      box.querySelector(`tr[data-key="${item.key}"] [data-field="${item.values.machine ? 'value' : 'machine'}"]`)?.focus();
    });
    const tabBar = el('div', {class: 'speed-tabs', role: 'tablist'}, tabs.map((t) => {
      const count = rates.filter((r) => r.operation_code === t.code).length;
      const b = el('button', {type: 'button', role: 'tab', 'aria-selected': t.code === tab.code ? 'true' : 'false', class: t.code === tab.code ? 'on' : null, 'data-code': t.code},
        t.label, count ? el('small', {}, ` (${count})`) : null);
      b.addEventListener('click', () => { speed.tab = t.code; renderSpeeds(); });
      return b;
    }));
    const options = machines.filter((m) => (tab.machines || []).includes(m.id));
    const optionFor = (id) => (options.some((m) => m.id === id) ? [] : byId.get(id) ? [byId.get(id)] : [{id, name: id}]);
    const rows = rates.filter((r) => r.operation_code === tab.code && (!speed.machine || r.resource_id === speed.machine))
      .sort((a, b) => short((byId.get(a.resource_id) || {}).name).localeCompare(short((byId.get(b.resource_id) || {}).name), 'pt')
        || (num(a.thickness_min ?? a.section_min) ?? -1) - (num(b.thickness_min ?? b.section_min) ?? -1)
        || String(a.material_type || '').localeCompare(String(b.material_type || ''), 'pt'));
    const body = el('tbody', {id: 'speed-rows'},
      rows.map((r) => speedRow(st, cols, tab, [...options, ...optionFor(r.resource_id)],
        {key: r.id, rate: r, values: {...r, machine: r.resource_id}})),
      speed.drafts.filter((d) => d.tab === tab.code).map((d) => speedRow(st, cols, tab, options, d)));
    const empty = !rows.length && !speed.drafts.some((d) => d.tab === tab.code);
    parts.push(el('div', {class: 'speed-bar'}, filter, add, !rates.length && (st.seed || []).length ? seedBox(st, tabs) : null),
      tabBar,
      el('div', {class: 'scroll'}, el('table', {class: 'grid speed-table', id: 'speed-table'},
        el('thead', {}, el('tr', {}, cols.map((c) => el('th', {scope: 'col'}, c.label)), el('th', {scope: 'col'}, el('span', {class: 'sr'}, 'Ações')))),
        body)),
      empty ? el('p', {class: 'muted'}, 'Sem linhas nesta operação: vale a velocidade mais recente do Excel (ou o histórico).') : null);
    box.replaceChildren(...parts.filter(Boolean));
    if (keep) box.querySelector(`tr[data-key="${keep.key}"] [data-field="${keep.field}"]`)?.focus();
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
    const head = $('rates-head');
    if (head) head.textContent = data.speed_table ? 'Velocidade em uso' : 'Tempos';
    renderSpeeds();
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
    $('setor').addEventListener('change', () => { speed.drafts = []; speed.preview = false; speed.machine = ''; load().catch(error); });
    $('shift-form').addEventListener('submit', (e) => saveShifts(e).catch(error));
    load().catch(error);
  });
})();
