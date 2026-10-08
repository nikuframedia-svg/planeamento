'use strict';
// Carteira simples (esboço do Luís, 02/10/2026).
// Estados de cada linha: Planeado (Planear + Máquina) · Planeado para nesting (Máquina, sem Planear) ·
// Sem máquina atribuída. As caixas são uma marcação desta sessão, por setor; filtrar não a muda.
// Os números das máquinas = Planeado; entre parênteses o que as linhas marcadas acrescentam.
(() => {
  const $ = (id) => document.getElementById(id);
  const SIMPLE = ['familia', 'familia_sku', 'maquina', 'estado', 'q'];
  const EXPLICIT_LIMIT = 3000; // acima disto a ação vai como «grupo exceto …» para caber no pedido
  const number = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 0});
  const hoursFmt = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1});
  const metresFine = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1}); // na lupa: uma peça curta não aparece como «0 m»
  const STATE_LABEL = {planeado: 'Planeado', nesting: 'Nesting', sem_maquina: 'Sem máquina', excluida: 'Excluída'};
  const SOURCE_LABEL = {carteira: 'Escolhida na Carteira', tabela: 'Coluna Máquina da Tabela', conjunto: 'Conjunto de famílias'};
  // Ordem (P6, 08/10): as duas por data ordenam pela data mais antiga com saldo de cada grupo; «picking» só na MTG2.
  const ORDERS = {
    cantoneiras: [['corte', 'Data de corte mais próxima'], ['urgencia', 'Mais urgente primeiro'], ['metros', 'Mais metros primeiro']],
    perfis: [['picking', 'Data de picking mais próxima'], ['corte', 'Data de corte mais próxima'], ['urgencia', 'Mais urgente primeiro'],
             ['metros', 'Mais metros primeiro']],
  };
  const BY_DATE = new Set(['corte', 'picking']);
  const DUE_TITLE = {cut_date: 'Data de corte mais antiga com saldo', picking: 'Picking mais antigo com saldo',
                     galvanizing: 'Galvanização mais antiga com saldo', planned_period: 'Semana escolhida mais antiga com saldo',
                     override: 'Prazo corrigido mais antigo com saldo'};
  const dayMonth = new Intl.DateTimeFormat('pt-PT', {day: '2-digit', month: '2-digit'});

  const state = {
    sector: null,
    selected: new Map(), // chave do membro → token visto quando foi marcado
    groups: new Map(),   // caminho → {keys, tokens, seal, total}
    counts: new Map(),   // caminho → {selected, total, hidden_selected}
    open: [],
    preview: null,
    tickets: {list: 0, kpis: 0, preview: 0, counts: 0, suggest: 0},
    kpisWeek: false,  // KPIs da semana (filtro Prazo, 08/10): números das células da Carga, sem os acréscimos (+…)
    kpisBase: null,   // a última resposta sem semanas, para «Limpar filtros» voltar logo a ela
    noDateOrder: false, // Python antiga sem as ordens por data (P6, 08/10)
    parcial: false,     // a Python aceita «quantidade» no Planear (capabilities.parcial, 08/10): mostra o botão «%»
  };

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key === 'checked') node.checked = Boolean(value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat(Infinity)) if (child !== null && child !== undefined && child !== false) node.append(child);
    return node;
  }

  const metres = (m) => `${number.format(m || 0)} m`;
  // Linhas com metros por saber (saldo por confirmar ou sem comprimento) não somam: diz-se com um asterisco, como
  // no peso. «metres_unknown» desde 08/10; com a Python antiga, as de saldo por confirmar.
  const metresKnown = (m, unknown) => unknown
    ? el('span', {title: `${number.format(unknown)} linha(s) com metros por saber: saldo por confirmar ou sem comprimento (não contam)`}, metres(m), el('span', {class: 'muted'}, ' *'))
    : metres(m);
  const unknownMetres = (t) => (t.metres_unknown !== undefined ? t.metres_unknown : t.unknown_balances);
  const hours = (h) => `${hoursFmt.format(h || 0)} h`;
  const tonnes = (t) => `${hoursFmt.format(t || 0)} t`;
  const pathId = (path) => JSON.stringify(path);
  const shortName = (name) => String(name || '').replace(/^Ficep\s+/i, '');
  const statusOf = (s) => ({planeado: (s || {}).planeado || {lines: 0, metres: 0}, nesting: (s || {}).nesting || {lines: 0, metres: 0},
                            sem_maquina: (s || {}).sem_maquina || {lines: 0, metres: 0}});

  // --- Filtros

  const weeks = () => [...$('semanas-lista').querySelectorAll('input:checked')].map((i) => i.value);

  function filters() {
    const out = {};
    for (const id of SIMPLE) out[id] = $(id).value;
    out.semanas = weeks();
    return out;
  }

  function query(extra = {}) {
    const params = new URLSearchParams();
    const values = {setor: state.sector, vista: $('vista').value, ordem: $('ordem').value, ...filters(), ...extra};
    for (const [key, value] of Object.entries(values)) {
      if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
      else if (value !== null && value !== undefined && value !== '') params.set(key, value);
    }
    return params;
  }

  function weeksSummary() {
    const chosen = weeks();
    $('semanas-resumo').textContent = !chosen.length ? 'Todas' : chosen.length === 1
      ? $('semanas-lista').querySelector('input:checked').dataset.label : `${chosen.length} semanas`;
  }

  // --- Pedidos

  async function api(path, params) {
    const response = await fetch(`${path}?${params}`, {headers: {Accept: 'application/json'}});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(body.error || `Erro ${response.status}`), {body, status: response.status});
    return body;
  }

  async function post(path, payload, {retry = false} = {}) {
    const send = () => fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
                                    body: JSON.stringify(payload)});
    let response;
    try {
      response = await send();
    } catch (error) {
      if (!retry) throw error;
      response = await send(); // o mesmo request_id: repetir não cria uma segunda ação
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(body.error || `Erro ${response.status}`), {body, status: response.status});
    return body;
  }

  function compact(keys) {
    const out = {};
    for (const key of keys) {
      const cut = key.lastIndexOf(':') + 1;
      (out[key.slice(0, cut)] ||= []).push(key.slice(cut));
    }
    return out;
  }

  // --- Marcação

  const storeKey = () => `carteira.marcacao.${state.sector}`;
  function loadSelection() {
    state.selected = new Map();
    try {
      for (const [key, token] of Object.entries(JSON.parse(sessionStorage.getItem(storeKey()) || '{}'))) state.selected.set(key, token);
    } catch (error) { /* sem armazenamento: a marcação vive só nesta página */ }
  }
  function saveSelection() {
    try { sessionStorage.setItem(storeKey(), JSON.stringify(Object.fromEntries(state.selected))); } catch (error) { /* idem */ }
  }

  const timers = {};
  function schedule(name, fn, wait) {
    clearTimeout(timers[name]);
    timers[name] = setTimeout(fn, wait);
  }

  function selectionChanged() {
    saveSelection();
    schedule('counts', refreshCounts, 150);
    schedule('preview', refreshPreview, 250);
    schedule('suggest', refreshSuggestion, 400);
    for (const box of document.querySelectorAll('input.member-pick')) box.checked = state.selected.has(box.value);
    for (const tr of document.querySelectorAll('tr.member')) tr.classList.toggle('is-selected', state.selected.has(tr.dataset.key));
    for (const panel of document.querySelectorAll('.detail')) panelSummary(panel);
    renderMarked();
  }

  async function groupInfo(path, view) {
    const id = pathId(path);
    if (state.groups.has(id)) return state.groups.get(id);
    const data = await api('/planeamento/api/carteira/membros', query({vista: view || $('vista').value, caminho: path, limite: 1, cursor: 0}));
    const info = {keys: data.keys, tokens: data.tokens, seal: data.seal, total: data.total, asMembers: Boolean(data.todo_o_grupo)};
    state.groups.set(id, info);
    return info;
  }

  async function toggleGroup(path, box) {
    box.disabled = true;
    try {
      const info = await groupInfo(path, box.closest('tr').dataset.view);
      const all = info.keys.every((k) => state.selected.has(k));
      info.keys.forEach((k, i) => (all ? state.selected.delete(k) : state.selected.set(k, info.tokens[i])));
      state.counts.set(pathId(path), {selected: all ? 0 : info.total, total: info.total, hidden_selected: 0});
      paintRow(path);
      selectionChanged();
    } catch (error) {
      showError(error);
    } finally {
      box.disabled = false;
    }
  }

  // --- Tabela

  const rowFor = (path) => document.querySelector(`tr.group[data-path="${CSS.escape(pathId(path))}"]`);

  function paintRow(path) {
    const tr = rowFor(path);
    if (!tr) return;
    const count = state.counts.get(pathId(path)) || {selected: 0, total: Number(tr.dataset.total), hidden_selected: 0};
    const box = tr.querySelector('.group-pick');
    const label = tr.querySelector('.pick-count');
    const all = count.total > 0 && count.selected === count.total;
    box.checked = all;
    box.indeterminate = count.selected > 0 && !all;
    box.setAttribute('aria-label', `${count.selected} de ${count.total} selecionados em ${tr.dataset.name}`);
    label.textContent = count.selected && !all ? `${count.selected}/${count.total}` : '';
    label.title = count.hidden_selected ? `${count.hidden_selected} marcado(s) escondido(s) pelos filtros` : '';
    tr.classList.toggle('is-selected', all);
    tr.classList.toggle('is-partial', count.selected > 0 && !all);
  }

  function planCell(st, buttons) {
    // Linha planeada em parte (08/10): «Planeado: 1 987 m (parte)».
    const part = (st.planeado.partial_lines || 0) > 0;
    return el('td', {class: 'plan'}, el('div', {class: 'plan-cell'}, buttons ? el('span', {class: 'acts'}, buttons) : null,
      el('span', {class: 'planned', title: part ? `${number.format(st.planeado.partial_lines)} linha(s) planeada(s) em parte: o resto fica em nesting` : null},
        `Planeado: ${metres(st.planeado.metres)}${part ? ' (parte)' : ''}`)));
  }

  function row(group, data, path, depth) {
    const key = [...path, group.key];
    const st = statusOf(group.status);
    const allNesting = group.lines > 0 && st.nesting.lines === group.lines;
    const toggle = data.has_children
      ? el('button', {type: 'button', class: 'toggle', 'aria-expanded': 'false', 'aria-label': `Abrir ${group.key}`}, '▸')
      : el('span', {class: 'toggle-space'});
    const lupa = el('button', {type: 'button', class: 'lupa', 'aria-expanded': 'false', 'aria-label': `Ver os membros de ${group.key}`, title: 'Ver e marcar um a um'}, '🔍');
    const plan = el('button', {type: 'button', class: 'act act-plan', title: 'Planear as linhas marcadas (todas, se nenhuma estiver marcada). Só as que têm máquina.'}, 'Planear');
    const clear = el('button', {type: 'button', class: 'act act-clear', title: 'Tirar o Planear das linhas marcadas (todas, se nenhuma estiver marcada)'}, 'Limpar');
    // «%» = Planear parte (08/10): só quando a Python o aceita.
    const part = state.parcial ? el('button', {type: 'button', class: 'act act-part', title: 'Planear parte', 'aria-label': `Planear parte de ${group.key}`}, '%') : null;
    const tr = el('tr', {class: `group level-${depth}${allNesting ? ' is-nesting' : ''}`,
                         dataset: {path: pathId(key), depth: String(depth), total: String(group.member_total), name: group.key, view: data.view}},
      el('th', {scope: 'row', class: 'name'},
        el('div', {class: 'name-cell', style: `--depth:${depth}`},
          el('input', {type: 'checkbox', class: 'group-pick'}), toggle,
          el('strong', {}, group.key), dueTag(group.due_tag, data.order), lupa, el('span', {class: 'pick-count'}))),
      planCell(st, [part ? el('span', {class: 'plan-pair'}, plan, part) : plan, clear]),
      el('td', {class: 'num'}, metresKnown(group.metres, unknownMetres(group))),
      el('td', {class: 'num'}, number.format(group.pieces)),
      el('td', {class: 'num'}, number.format(group.ofs)),
      el('td', {class: 'num'}, st.sem_maquina.metres ? metres(st.sem_maquina.metres) : '—'),
      el('td', {class: 'num'}, st.nesting.metres ? metres(st.nesting.metres) : '—'));
    tr.querySelector('.group-pick').addEventListener('change', (event) => toggleGroup(key, event.target));
    if (data.has_children) toggle.addEventListener('click', () => expand(tr, key, depth));
    lupa.addEventListener('click', () => toggleLupa(tr, key, lupa));
    plan.addEventListener('click', () => act(key, 'selecionar', tr));
    clear.addEventListener('click', () => act(key, 'limpar', tr));
    if (part) part.addEventListener('click', () => openPartial(key, tr, part));
    return tr;
  }

  // Data do grupo, só nas ordens por data (P6, 08/10): «28/07» (vermelho se atrasada), «S42», «S42?» (ano deduzido),
  // «sem data», «estacionada». O título diz de onde vem.
  function dueTag(tag, order) {
    if (!tag || !BY_DATE.has(order)) return null;
    if (tag.none) return el('span', {class: 'due', title: tag.none === 'estacionada' ? 'Só linhas estacionadas no Excel (W 2026/53)' : 'Sem data nas linhas com saldo'}, tag.none);
    const day = dayMonth.format(new Date(`${tag.day}T12:00:00`));
    const what = DUE_TITLE[tag.field] || 'Prazo mais antigo com saldo';
    const title = [order === 'picking' && tag.field !== 'picking' ? `Sem Picking · ${what}` : what, tag.week ? `semana de ${day}` : null,
      tag.provisional ? 'ano deduzido' : null,
      tag.late ? `${number.format(tag.late_days)} ${tag.late_days === 1 ? 'dia' : 'dias'} de atraso` : null].filter(Boolean).join(' · ');
    return el('span', {class: `due${tag.late ? ' late' : ''}`, title}, tag.week ? `S${tag.week.slice(-2)}${tag.provisional ? '?' : ''}` : day);
  }

  function subtotal(t) {
    const st = statusOf(t.status);
    const note = subtotalNote(t);
    $('subtotal').replaceChildren(el('tr', {class: 'subtotal'},
      el('th', {scope: 'row'}, 'Subtotal'),
      planCell(st, null),
      el('td', {class: 'num'}, metresKnown(t.metres, unknownMetres(t))),
      el('td', {class: 'num'}, number.format(t.pieces)),
      el('td', {class: 'num'}, number.format(t.ofs)),
      el('td', {class: 'num'}, metres(st.sem_maquina.metres)),
      el('td', {class: 'num'}, metres(st.nesting.metres))), ...(note ? [note] : []));
  }

  // Avisos da lista (08/10), numa só linha discreta e só quando há casos: linhas possivelmente repetidas (contam a
  // dobrar; nada é removido) e produção acima da QTD (incluindo as que já saíram da Carteira por isso).
  function subtotalNote(t) {
    const parts = [];
    const r = t.repeated || {};
    if (r.lines) parts.push(el('span', {title: 'Outra linha da mesma OF tem a mesma referência, perfil, comprimento, QTD, material e qualidade: pode estar a contar a dobrar. Confirma no Excel; a lupa mostra «repetida».'},
      `${number.format(r.lines)} ${r.lines === 1 ? 'linha possivelmente repetida' : 'linhas possivelmente repetidas'} (+${metres(r.metres)})`));
    const x = t.production_excess || {};
    if (x.lines) parts.push(el('span', {title: `A produção registada passa a QTD${x.closed ? `; ${number.format(x.closed)} já saíram da Carteira com saldo 0` : ''}. Confere as folhas no MES.`},
      `${number.format(x.lines)} ${x.lines === 1 ? 'linha com produção acima da QTD' : 'linhas com produção acima da QTD'} (+${number.format(x.pieces)} peças)`));
    if (!parts.length) return null;
    return el('tr', {class: 'subtotal-note'}, el('td', {colspan: '7', class: 'muted'}, parts.flatMap((p, i) => (i ? [' · ', p] : [p]))));
  }

  function inside(id, path) {
    return Boolean(id) && (id === path || id.startsWith(path.slice(0, -1) + ','));
  }

  function descendants(tr) {
    const out = [];
    let next = tr.nextElementSibling;
    while (next && inside(next.dataset.path || next.dataset.detailFor, tr.dataset.path)) {
      out.push(next);
      next = next.nextElementSibling;
    }
    return out;
  }

  function collapse(tr) {
    descendants(tr).filter((n) => n.dataset.detailFor !== tr.dataset.path).forEach((n) => n.remove());
    const button = tr.querySelector('.toggle');
    button.setAttribute('aria-expanded', 'false');
    button.textContent = '▸';
    state.open = state.open.filter((p) => !inside(p, tr.dataset.path));
  }

  async function expand(tr, path, depth, {silent = false} = {}) {
    const button = tr.querySelector('.toggle');
    if (button.getAttribute('aria-expanded') === 'true') { if (!silent) collapse(tr); return; }
    button.disabled = true;
    const sector = state.sector;
    try {
      const data = await api('/planeamento/api/carteira', query({caminho: path}));
      if (sector !== state.sector || !tr.isConnected) return;
      let anchor = tr;
      while (anchor.nextElementSibling && anchor.nextElementSibling.dataset.detailFor === tr.dataset.path) anchor = anchor.nextElementSibling;
      for (const group of data.groups) {
        const child = row(group, data, path, depth + 1);
        anchor.after(child);
        anchor = child;
        paintRow([...path, group.key]);
      }
      if (data.truncated) anchor.after(el('tr', {class: 'more', dataset: {path: pathId([...path, '…'])}},
        el('td', {colspan: '7'}, `Mostram-se ${data.groups.length} de ${data.group_count}. Usa os filtros para ver os restantes.`)));
      button.setAttribute('aria-expanded', 'true');
      button.textContent = '▾';
      if (!state.open.includes(pathId(path))) state.open.push(pathId(path));
      schedule('counts', refreshCounts, 50);
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
    }
  }

  async function load() {
    const ticket = ++state.tickets.list;
    const sector = state.sector;
    const order = $('ordem').value;
    $('error').hidden = true;
    history.replaceState(null, '', `?${query()}`);
    state.groups.clear();
    try {
      const data = await api('/planeamento/api/carteira', query());
      if (ticket !== state.tickets.list || sector !== state.sector) return;
      state.parcial = Boolean((data.capabilities || {}).parcial);
      // Python antiga, sem «order» (P6, 08/10): ordenava por metros sem dizer. Fica a ordem de hoje e uma nota.
      if (!('order' in data) && BY_DATE.has(order)) {
        state.noDateOrder = true;
        orderOptions('urgencia');
        if ($('order-note')) $('order-note').hidden = false;
        return load();
      }
      subtotal(data.list_totals || data.totals);
      $('source').textContent = `Excel importado a ${new Date(data.imported_at).toLocaleString('pt-PT')}`;
      // Excel no Drive mais recente do que o importado (08/10): uma linha, só quando a API a manda.
      if ($('source-notice')) { $('source-notice').hidden = !data.source_notice; $('source-notice').textContent = data.source_notice || ''; }
      $('level-title').textContent = data.level.label;
      $('rows').replaceChildren(...data.groups.map((group) => row(group, data, [], 0)));
      data.groups.forEach((g) => paintRow([g.key]));
      if (data.truncated) $('rows').append(el('tr', {class: 'more'}, el('td', {colspan: '7'}, `Mostram-se ${data.groups.length} de ${data.group_count}. Usa os filtros para ver os restantes.`)));
      $('empty').hidden = data.groups.length > 0;
      const reopen = state.open;
      state.open = [];
      for (const id of reopen) {
        const tr = rowFor(JSON.parse(id));
        if (tr && ticket === state.tickets.list) await expand(tr, JSON.parse(id), Number(tr.dataset.depth), {silent: true});
      }
      schedule('counts', refreshCounts, 0);
    } catch (error) {
      if (ticket === state.tickets.list) showError(error);
    }
  }

  async function refreshCounts() {
    const ticket = ++state.tickets.counts;
    const sector = state.sector;
    if (!state.selected.size) {
      state.counts.clear();
      document.querySelectorAll('tr.group').forEach((tr) => paintRow(JSON.parse(tr.dataset.path)));
      return;
    }
    const chaves = compact([...state.selected.keys()]);
    try {
      for (const path of [[], ...state.open.map((id) => JSON.parse(id))]) {
        const data = await post('/planeamento/api/carteira/contagens',
          {setor: sector, vista: $('vista').value, caminho: path, filtros: filters(), chaves_compactas: chaves});
        if (ticket !== state.tickets.counts || sector !== state.sector) return;
        for (const [key, count] of Object.entries(data.groups)) {
          state.counts.set(pathId([...path, key]), count);
          paintRow([...path, key]);
        }
      }
    } catch (error) {
      if (ticket === state.tickets.counts) showError(error);
    }
  }

  // --- Lupa

  function closeLupa(tr, button) {
    const detail = tr.nextElementSibling;
    if (detail && detail.dataset.detailFor === tr.dataset.path) detail.remove();
    button.setAttribute('aria-expanded', 'false');
    button.focus();
  }

  function panelSummary(panel) {
    const info = panel._info;
    if (!info) return;
    const chosen = info.keys.filter((k) => state.selected.has(k)).length;
    panel.querySelector('.detail-sum').textContent = `${number.format(info.total)} linhas · ${number.format(chosen)} marcadas`;
  }

  function memberRow(m) {
    const st = m.status || {};
    // Linha excluída (decisão antiga) fica fora dos três estados: diz «Excluída», nunca «Sem máquina».
    const code = st.planeado ? 'planeado' : st.nesting ? 'nesting' : st.sem_maquina === false && m.decision === 'excluded' ? 'excluida' : 'sem_maquina';
    const box = el('input', {type: 'checkbox', class: 'member-pick', value: m.key, checked: state.selected.has(m.key),
                             'aria-label': `Marcar ${m.of} ${m.reference} ${m.profile} ${m.length_mm || ''} mm`});
    box.addEventListener('change', () => {
      if (box.checked) state.selected.set(m.key, m.token); else state.selected.delete(m.key);
      selectionChanged();
    });
    // Só falta a operação seguinte (08/10): «Abocardar: 12» em vez de «0» peças e «0 m».
    const following = !m.balance_unknown && !m.pieces && (m.following || []).length
      ? m.following.map((f) => `${f.label}: ${f.remaining === null || f.remaining === undefined ? 'por confirmar' : number.format(f.remaining)}`).join(' · ') : '';
    const unknownM = m.balance_unknown || m.metres === null || m.metres_unknown;
    return el('tr', {class: `member${code === 'nesting' ? ' is-nesting' : ''}${state.selected.has(m.key) ? ' is-selected' : ''}`, dataset: {key: m.key}},
      el('td', {}, box), el('td', {}, m.of), el('td', {}, m.reference), el('td', {}, m.profile),
      el('td', {class: 'num'}, m.length_mm ? `${number.format(m.length_mm)} mm` : '—'),
      el('td', {class: 'num', title: following ? 'O corte está feito; falta a operação seguinte' : null}, m.balance_unknown ? 'por confirmar' : following || number.format(m.pieces)),
      el('td', {class: 'num', title: unknownM && !m.balance_unknown ? 'Sem comprimento: metros por saber' : null}, unknownM || following ? '—' : `${metresFine.format(m.metres || 0)} m`),
      el('td', {title: m.machine ? (SOURCE_LABEL[m.machine_source] || '') + (m.machine_source === 'carteira' && m.tabela_machine ? ` (Tabela: ${m.tabela_machine})` : '') : (m.suggested ? m.suggested.label : null)},
        m.machine || (m.suggested ? el('span', {class: 'muted'}, `— sugerida: ${shortName(m.suggested.machine)}`) : '—')),
      el('td', {}, el('span', {class: `chip chip-${code}`},
        code === 'planeado' && m.partial ? `Planeado ${number.format(m.planned_pieces)} de ${number.format(m.pieces)}` : STATE_LABEL[code]),
        ...warnings(m)));
  }

  // Avisos de uma linha na lupa (08/10): nada é corrigido, só se diz.
  function warnings(m) {
    const out = [];
    if (m.repeated > 1) out.push(el('span', {class: 'warn', title: 'Outra linha da mesma OF tem a mesma referência, perfil, comprimento, QTD, material e qualidade: pode estar a contar a dobrar. Confirma no Excel.'}, `repetida ${m.repeated}×`));
    if (m.production_excess) out.push(el('span', {class: 'warn', title: 'A produção registada passa a QTD. Confere as folhas no MES.'}, `produção acima da QTD (+${number.format(m.production_excess)})`));
    return out;
  }

  async function toggleLupa(tr, path, button) {
    if (button.getAttribute('aria-expanded') === 'true') { closeLupa(tr, button); return; }
    const panelId = `lupa-${Math.random().toString(36).slice(2)}`;
    const search = el('input', {type: 'search', placeholder: 'Pesquisar nesta linha', 'aria-label': 'Pesquisar nesta linha'});
    const body = el('tbody');
    const more = el('button', {type: 'button', class: 'small', hidden: true}, 'Mostrar mais');
    const markAll = el('button', {type: 'button', class: 'small'}, 'Marcar todos');
    const unmarkAll = el('button', {type: 'button', class: 'small'}, 'Desmarcar todos');
    const panel = el('div', {class: 'detail', id: panelId, role: 'region', 'aria-label': `Membros de ${path[path.length - 1]}`},
      el('div', {class: 'lupa-head'}, el('span', {class: 'detail-sum'}, 'A carregar…'), search, markAll, unmarkAll),
      el('div', {class: 'detail-scroll'}, el('table', {class: 'members'},
        el('thead', {}, el('tr', {}, ...['', 'OF', 'Referência', 'Perfil', 'Comprimento', 'Peças', 'Metros', 'Máquina', 'Estado']
          .map((h, i) => el('th', {scope: 'col', class: i >= 4 && i <= 6 ? 'num' : null}, h)))),
        body)), more);
    const detail = el('tr', {class: 'detail-row', dataset: {detailFor: tr.dataset.path}}, el('td', {colspan: '7'}, panel));
    tr.after(detail);
    button.setAttribute('aria-expanded', 'true');
    button.setAttribute('aria-controls', panelId);
    panel.addEventListener('keydown', (event) => { if (event.key === 'Escape') { event.preventDefault(); closeLupa(tr, button); } });
    let cursor = 0, pageTicket = 0;
    const sector = state.sector;
    const view = tr.dataset.view;
    async function page(reset) {
      const ticket = ++pageTicket;
      try {
        const data = await api('/planeamento/api/carteira/membros', query({vista: view, caminho: path, cursor: reset ? 0 : cursor, limite: 200, pesquisa: search.value}));
        if (ticket !== pageTicket || sector !== state.sector || !detail.isConnected) return;
        if (reset) body.replaceChildren();
        const info = {keys: data.keys, tokens: data.tokens, seal: data.seal, total: data.total, asMembers: Boolean(data.todo_o_grupo)};
        state.groups.set(pathId(path), info);
        panel._info = info;
        data.items.forEach((m) => body.append(memberRow(m)));
        cursor = data.next_cursor;
        more.hidden = data.next_cursor === null;
        more.textContent = `Mostrar mais (${number.format(data.matching - body.children.length)})`;
        panelSummary(panel);
      } catch (error) {
        showError(error);
      }
    }
    let searchTimer;
    search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => page(true), 300); });
    more.addEventListener('click', () => page(false));
    markAll.addEventListener('click', () => {
      const info = panel._info;
      if (!info) return;
      info.keys.forEach((k, i) => state.selected.set(k, info.tokens[i]));
      selectionChanged();
    });
    unmarkAll.addEventListener('click', () => {
      if (!panel._info) return;
      panel._info.keys.forEach((k) => state.selected.delete(k));
      selectionChanged();
    });
    await page(true);
    search.focus();
  }

  // --- Planear / Limpar

  async function act(path, action, tr) {
    const buttons = tr.querySelectorAll('.act');
    buttons.forEach((b) => { b.disabled = true; });
    $('error').hidden = true;
    const sector = state.sector;
    try {
      const view = tr.dataset.view;
      const info = await groupInfo(path, view);
      const marked = info.keys.filter((k) => state.selected.has(k));
      const whole = !marked.length || marked.length === info.total;
      const payload = {setor: sector, acao: action, request_id: crypto.randomUUID()};
      if (whole && info.asMembers && info.keys.length <= EXPLICIT_LIMIT) {
        // Grupo inteiro como membros com o token visto (07/10/2026): uma linha que mudou fica de fora e as outras
        // gravam-se, em vez de valer o grupo de agora com linhas que ninguém viu. O selo fica para os grupos enormes.
        payload.membros = info.keys.map((k, i) => ({chave: k, token: state.selected.get(k) || info.tokens[i]}));
        payload.todo_o_grupo = true;
      } else if (whole) payload.grupo = {vista: view, caminho: path, selo: info.seal};
      else if (marked.length <= EXPLICIT_LIMIT) payload.membros = marked.map((k) => ({chave: k, token: state.selected.get(k)}));
      else payload.grupo = {vista: view, caminho: path, selo: info.seal, exceto: info.keys.filter((k) => !state.selected.has(k))};
      const result = await post('/planeamento/api/carteira/selecao', payload, {retry: true});
      if (sector !== state.sector) return;
      (whole ? info.keys : marked).forEach((k) => state.selected.delete(k));
      state.groups.delete(pathId(path)); // revisões novas: o selo e os tokens guardados já não servem
      const name = path[path.length - 1];
      const suggested = result.suggested_machine || 0;
      const done = action === 'selecionar'
        ? `${name}: ${number.format(result.planned ?? result.changed)} linha(s) planeada(s)${suggested ? `; ${number.format(suggested)} com a máquina sugerida (podes mudar)` : ''}.`
        : `${name}: ${number.format(result.changed)} linha(s) limpa(s).`;
      notice(result.repeated ? 'Este pedido já tinha sido gravado.' : done + left(result));
      selectionChanged();
      await Promise.all([load(), loadKpis()]);
    } catch (error) {
      const fields = (error.body || {}).fields || {};
      if (fields.conflicts && fields.conflicts.length) {
        state.groups.delete(pathId(path));
        await refreshTokens();
        showError(new Error(`${error.message} (${fields.conflict_count} linha(s)). Os dados foram atualizados: carrega outra vez.`));
      } else {
        showError(error);
      }
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  // --- Planear parte (P5, 08/10)
  // O âmbito é o do Planear: os membros marcados do grupo, ou o grupo todo. O total pedido (peças ou metros)
  // distribui-se pela ordem de prazo, a encher linha a linha; cada linha pode ser mudada. Metros → peças inteiras
  // por round(m × 1000 / comprimento), com mínimo 1 na última linha. Planear grava logo; não regista produção.

  const PARTIAL_LIMIT = 500;
  const metresOne = new Intl.NumberFormat('pt-PT', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  const pieceMetres = (line, n) => (line.length_mm ? n * line.length_mm / 1000 : 0);

  function byDue(a, b) {
    const da = a.priority_day || a.cut_date || '9999-12-31', db = b.priority_day || b.cut_date || '9999-12-31';
    return da < db ? -1 : da > db ? 1 : 0;  // estável: dentro do mesmo prazo fica a ordem da lista
  }

  // Distribuição do total: {chave: peças}. `unit` = 'pecas' | 'm'.
  function distribute(lines, amount, unit) {
    const out = {};
    let left = Math.max(0, Number(amount) || 0);
    for (const line of lines) {
      let take = 0;
      if (left > 0) {
        if (unit === 'm') {
          const full = pieceMetres(line, line.pieces);
          if (!line.length_mm) take = 0;
          else if (left >= full - 1e-9) { take = line.pieces; left -= full; }
          else { take = Math.min(line.pieces, Math.max(1, Math.round(left * 1000 / line.length_mm))); left = 0; }
        } else {
          take = Math.min(line.pieces, Math.floor(left));
          left -= take;
        }
      }
      out[line.key] = take;
    }
    return out;
  }

  function partialDialog() {
    let dialog = $('parcial');
    if (!dialog) {
      dialog = el('dialog', {id: 'parcial', class: 'parcial', 'aria-labelledby': 'parcial-title'});
      document.body.append(dialog);
    }
    return dialog;
  }

  async function openPartial(path, tr, button) {
    const dialog = partialDialog();
    const name = path[path.length - 1];
    const close = el('button', {type: 'button', class: 'small', value: 'cancel'}, 'Cancelar');
    close.addEventListener('click', () => dialog.close());
    dialog.replaceChildren(el('h2', {id: 'parcial-title'}, `Planear parte · ${name}`), el('p', {class: 'muted'}, 'A carregar…'));
    if (!dialog.open) dialog.showModal();
    button.disabled = true;
    try {
      const data = await api('/planeamento/api/carteira/membros',
        query({vista: tr.dataset.view, caminho: path, cursor: 0, limite: PARTIAL_LIMIT}));
      if (data.total > PARTIAL_LIMIT || data.next_cursor !== null && data.next_cursor !== undefined) {
        dialog.replaceChildren(el('h2', {id: 'parcial-title'}, `Planear parte · ${name}`),
          el('p', {}, 'Abre um nível abaixo para planear parte.'), el('div', {class: 'parcial-acts'}, close));
        return;
      }
      const marked = data.items.filter((m) => state.selected.has(m.key));
      const scope = marked.length ? marked : data.items.filter((m) => m.decision !== 'excluded');
      // Só as linhas com saldo conhecido e por cortar podem ir em parte; as outras ficam de fora deste diálogo.
      const lines = scope.filter((m) => !m.balance_unknown && m.pieces > 0).slice().sort(byDue);
      const out = scope.length - lines.length;
      renderPartial(dialog, path, tr, name, lines, out, close);
    } catch (error) {
      dialog.close();
      showError(error);
    } finally {
      button.disabled = false;
    }
  }

  function renderPartial(dialog, path, tr, name, lines, out, close) {
    const totalPieces = lines.reduce((a, l) => a + l.pieces, 0);
    const totalMetres = lines.reduce((a, l) => a + pieceMetres(l, l.pieces), 0);
    const amount = el('input', {type: 'number', id: 'parcial-quantidade', min: '0', step: 'any', inputmode: 'decimal',
                                'aria-label': 'Quanto planear'});
    const unit = el('select', {id: 'parcial-unidade', 'aria-label': 'Unidade'}, el('option', {value: 'pecas'}, 'peças'), el('option', {value: 'm'}, 'm'));
    const chosenText = el('p', {class: 'parcial-escolhido', id: 'parcial-escolhido'});
    const restText = el('p', {class: 'muted', id: 'parcial-resto'});
    const save = el('button', {type: 'button', class: 'act-plan', id: 'parcial-planear', disabled: true}, 'Planear');
    let take = Object.fromEntries(lines.map((l) => [l.key, 0]));
    let asked = null; // {amount, unit}: o que se pediu, para dizer o arredondamento
    const inputs = {};
    const metresCells = {};
    const table = lines.length > 1 ? el('div', {class: 'parcial-scroll'}, el('table', {class: 'members parcial-linhas'},
      el('thead', {}, el('tr', {}, ...['OF', 'Referência', 'Comp.', 'Saldo', 'Planear', 'm']
        .map((h, i) => el('th', {scope: 'col', class: i >= 2 ? 'num' : null}, h)))),
      el('tbody', {}, lines.map((l) => {
        const input = el('input', {type: 'number', min: '0', max: String(l.pieces), step: '1', value: '0', class: 'parcial-linha',
                                   'aria-label': `Peças a planear de ${l.of} ${l.reference}`, dataset: {key: l.key}});
        input.addEventListener('input', () => {
          const n = Math.max(0, Math.min(l.pieces, Math.floor(Number(input.value) || 0)));
          take[l.key] = n;
          asked = null;
          update(false);
        });
        inputs[l.key] = input;
        metresCells[l.key] = el('td', {class: 'num'}, '0');
        return el('tr', {}, el('td', {}, l.of), el('td', {}, l.reference),
          el('td', {class: 'num'}, l.length_mm ? number.format(l.length_mm) : '—'), el('td', {class: 'num'}, number.format(l.pieces)),
          el('td', {class: 'num'}, input), metresCells[l.key]);
      })))) : null;

    function update(fromTotal) {
      if (fromTotal) {
        take = distribute(lines, amount.value, unit.value);
        asked = amount.value !== '' ? {amount: Number(amount.value), unit: unit.value} : null;
      }
      let pieces = 0, m = 0;
      for (const l of lines) {
        pieces += take[l.key];
        m += pieceMetres(l, take[l.key]);
        if (inputs[l.key] && fromTotal) inputs[l.key].value = String(take[l.key]);
        if (metresCells[l.key]) metresCells[l.key].textContent = metresOne.format(pieceMetres(l, take[l.key]));
      }
      const rounding = asked && asked.unit === 'm' && Math.abs(asked.amount - m) > 0.05
        ? ` (pediste ${number.format(asked.amount)} m → ${number.format(pieces)} peças inteiras)` : '';
      chosenText.textContent = `Escolhido: ${number.format(pieces)} peças · ${metresOne.format(m)} m${rounding}`;
      restText.textContent = `Fica na Carteira: ${number.format(totalPieces - pieces)} peças · ${metresOne.format(totalMetres - m)} m`;
      save.disabled = pieces <= 0;
    }
    amount.addEventListener('input', () => update(true));
    unit.addEventListener('change', () => update(true));
    save.addEventListener('click', () => savePartial(dialog, path, tr, name, lines, take, save));
    dialog.replaceChildren(
      el('h2', {id: 'parcial-title'}, `Planear parte · ${name}`),
      el('p', {id: 'parcial-saldo'}, `Saldo: ${number.format(totalPieces)} peças · ${metresOne.format(totalMetres)} m`),
      out ? el('p', {class: 'muted'}, `${number.format(out)} linha(s) sem saldo por cortar ou com saldo por confirmar ficam de fora.`) : null,
      el('div', {class: 'parcial-entrada'}, amount, unit),
      chosenText, restText, table,
      el('p', {class: 'muted'}, 'Planear não regista produção.'),
      el('div', {class: 'parcial-acts'}, close, save));
    update(true);
    amount.focus();
  }

  async function savePartial(dialog, path, tr, name, lines, take, save) {
    const membros = [];
    for (const l of lines) {
      const n = take[l.key];
      if (!n) continue;
      const item = {chave: l.key, token: state.selected.get(l.key) || l.token};
      if (n < l.pieces) item.quantidade = n; // a linha toda vai sem quantidade (linha inteira)
      membros.push(item);
    }
    if (!membros.length) return;
    save.disabled = true;
    $('error').hidden = true;
    const sector = state.sector;
    try {
      const result = await post('/planeamento/api/carteira/selecao',
        {setor: sector, acao: 'selecionar', request_id: crypto.randomUUID(), membros}, {retry: true});
      if (sector !== state.sector) return;
      dialog.close();
      lines.forEach((l) => state.selected.delete(l.key));
      state.groups.delete(pathId(path));
      const partial = result.partial || 0;
      notice(result.repeated ? 'Este pedido já tinha sido gravado.'
        : `${name}: ${number.format(result.planned ?? result.changed)} linha(s) planeada(s)${partial ? `, ${number.format(partial)} em parte` : ''}.` + left(result));
      selectionChanged();
      await Promise.all([load(), loadKpis()]);
    } catch (error) {
      save.disabled = false;
      const fields = (error.body || {}).fields || {};
      dialog.close();
      if (fields.conflicts && fields.conflicts.length) {
        state.groups.delete(pathId(path));
        await refreshTokens();
        showError(new Error(`${error.message} (${fields.conflict_count} linha(s)). Os dados foram atualizados: abre outra vez.`));
      } else {
        showError(error);
      }
    }
  }

  function left(result) {
    // Linhas que ficaram de fora, com o motivo (07/10/2026); a Python antiga só mandava skipped_no_machine.
    const count = result.skipped_count ?? result.skipped_no_machine ?? 0;
    if (!count) return result.group_changed ? ' O grupo tinha mudado: contaram as linhas atuais.' : '';
    const reasons = {};
    for (const s of result.skipped || []) reasons[s.reason] = (reasons[s.reason] || 0) + 1;
    const why = Object.entries(reasons).map(([reason, n]) => `${number.format(n)}: ${reason}`).join(' · ');
    return ` ${number.format(count)} ficaram de fora${why ? ` (${why})` : ' sem máquina'}.` +
      (result.group_changed ? ' O grupo tinha mudado: contaram as linhas atuais.' : '');
  }

  async function refreshTokens() {
    // Depois de atribuir máquina ou de um conflito: os tokens das linhas marcadas passam a ser os atuais.
    if (!state.selected.size) return;
    try {
      const data = await post('/planeamento/api/carteira/tokens', {setor: state.sector, chaves_compactas: compact([...state.selected.keys()])});
      for (const [key, token] of Object.entries(data.tokens || {})) if (state.selected.has(key)) state.selected.set(key, token);
      saveSelection();
    } catch (error) { /* fica com os tokens antigos: o próximo pedido volta a avisar */ }
  }

  async function refreshSuggestion() {
    const select = $('assign-machine');
    if (!select || !state.selected.size) return;
    const ticket = ++state.tickets.suggest;
    try {
      const data = await post('/planeamento/api/carteira/sugestao', {setor: state.sector, chaves_compactas: compact([...state.selected.keys()])});
      if (ticket !== state.tickets.suggest || !$('assign-machine')) return;
      const keep = select.value;
      const s = data.suggestion;
      select.replaceChildren(el('option', {value: ''}, 'Máquina…'),
        ...(data.machines || []).map((m) => el('option', {value: m.id}, shortName(m.name) + (s && s.resource_id === m.id ? ` — sugerida (${s.label})` : ''))),
        el('option', {value: '__clear__'}, 'Tirar a escolha da Carteira'));
      select.value = keep && [...select.options].some((o) => o.value === keep) ? keep : (s ? s.resource_id : '');
    } catch (error) { /* sem sugestão: a lista fica como está */ }
  }

  async function assignMachine() {
    const select = $('assign-machine');
    const value = select.value;
    if (!value) { select.focus(); return; }
    const keys = [...state.selected.keys()];
    if (keys.length > EXPLICIT_LIMIT) { showError(new Error(`Marca até ${number.format(EXPLICIT_LIMIT)} linhas de cada vez.`)); return; }
    $('assign').disabled = true;
    $('error').hidden = true;
    try {
      const result = await post('/planeamento/api/carteira/maquina', {setor: state.sector, maquina: value === '__clear__' ? null : value,
        request_id: crypto.randomUUID(), membros: keys.map((k) => ({chave: k, token: state.selected.get(k)}))}, {retry: true});
      notice(result.repeated ? 'Este pedido já tinha sido gravado.' : result.machine
        ? `${number.format(result.changed)} linha(s) passam para ${shortName(result.machine)}. Continuam marcadas: podes carregar em Planear.`
        : `${number.format(result.changed)} linha(s) voltam à máquina da Tabela ou do conjunto.`);
      await refreshTokens();
      selectionChanged();
      await Promise.all([load(), loadKpis()]);
    } catch (error) {
      const fields = (error.body || {}).fields || {};
      if (fields.conflicts && fields.conflicts.length) {
        await refreshTokens();
        showError(new Error(`${error.message} (${fields.conflict_count} linha(s)). Os dados foram atualizados: carrega outra vez.`));
      } else {
        showError(error);
      }
    } finally {
      if ($('assign')) $('assign').disabled = false;
    }
  }

  // --- Painéis: máquinas e Resumo

  function machineRow(m) {
    if (state.kpisWeek) return weekRow(m);
    return el('li', {dataset: {machine: m.id}},
      el('span', {class: 'm-name', title: m.name}, shortName(m.name)),
      el('span', {class: 'm-metres'}, metres(m.base.metres), el('span', {class: 'delta delta-m'})),
      el('span', {class: 'm-hours', title: m.base.hours_unknown ? `${m.base.hours_unknown} operação(ões) sem horas conhecidas` : null},
        hours(m.base.hours), el('span', {class: 'delta delta-h'})));
  }

  // Semana escolhida no Prazo (08/10): «metros · carga / capacidade h» com a cor da Carga e turnos; na semana atual,
  // por baixo, o atrasado de semanas anteriores (a coluna Atrasado da Carga), só quando há.
  function weekRow(m) {
    const w = m.week;
    if (!w) return el('li', {dataset: {machine: m.id}}, el('span', {class: 'm-name', title: m.name}, shortName(m.name)),
      el('span', {class: 'm-metres'}, '—'), el('span', {class: 'm-hours'}, '—'));
    const parts = [`no plano ${hours(w.plan)}`, `a vencer ${hours(w.due)}`, `sugerida ${hours(w.suggested)}`,
                   ...(w.unknown ? [`${number.format(w.unknown)} sem horas`] : [])];
    const capacity = w.capacity === null || w.capacity === undefined ? '—' : hoursFmt.format(w.capacity);
    return el('li', {dataset: {machine: m.id}},
      el('span', {class: 'm-name', title: m.name}, shortName(m.name)),
      el('span', {class: 'm-metres'}, metresKnown(w.metres, w.metres_unknown)),
      el('span', {class: `m-hours m-load${w.status ? ` st-${w.status}` : ''}`, title: parts.join(' · ')},
        `${hoursFmt.format(w.load || 0)} / ${capacity} h`),
      w.late_before > 0 ? el('span', {class: 'm-late muted', title: 'Horas com prazo antes desta semana (coluna Atrasado da Carga e turnos)'},
        `atrasado ${hours(w.late_before)}`) : null);
  }

  // Linha de âmbito por cima dos painéis: o que os números querem dizer. Com a Python antiga (sem `scope`) e um
  // Prazo escolhido, os números continuam a ser os de todas as semanas: diz-se numa linha.
  function scopeLine(data) {
    const scope = data.scope;
    if (!scope) return weeks().length ? el('p', {class: 'kpis-scope muted'}, 'O Prazo ainda não muda estes números: falta reiniciar o serviço do planeamento.') : null;
    if (!(scope.weeks || []).length) return null; // sem Prazo: sem linha (P6, ecrãs simples)
    return el('p', {class: 'kpis-scope muted'}, `${scope.sector_label} · ${scope.label} · carga e capacidade como na Carga e turnos`);
  }

  function summaryRow(s) {
    const w = state.kpisWeek && s.week ? s.week : null;
    const shown = w || s;
    const unknownHours = w ? w.hours_unknown : 0;
    const hoursCell = w
      ? el('td', {class: 'num', title: unknownHours ? `${number.format(unknownHours)} operação(ões) sem horas conhecidas (não contam)` : null},
        hours(w.hours), s.code === 'sem_maquina' ? ' na sugerida' : null, unknownHours ? el('span', {class: 'muted'}, ' *') : null)
      : el('td', {class: 'num'}, s.code === 'sem_maquina' ? '—' : hours(s.hours));
    return el('tr', {dataset: {state: s.code}},
      el('th', {scope: 'row'}, s.label),
      el('td', {class: 'num'}, metresKnown(shown.metres, shown.metres_unknown)),
      hoursCell,
      el('td', {class: 'num', title: shown.weight_unknown ? `${number.format(shown.weight_unknown)} linha(s) sem peso unitário (não contam)` : null},
        tonnes(shown.tonnes), shown.weight_unknown ? el('span', {class: 'muted'}, ' *') : null));
  }

  function renderKpis(data) {
    state.kpisWeek = Boolean(data.scope && (data.scope.weeks || []).length);
    const panels = data.panels.map((p) => el('section', {class: 'panel'}, el('h2', {}, p.label),
      el('ul', {class: 'machines'}, p.machines.map(machineRow))));
    const rows = data.summary.map(summaryRow);
    const resumo = el('section', {class: 'panel resumo'}, el('h2', {}, 'Resumo'),
      el('table', {}, el('thead', {}, el('tr', {}, el('th', {scope: 'col'}, ''), el('th', {scope: 'col', class: 'num'}, 'Metros'),
        el('th', {scope: 'col', class: 'num'}, 'Horas'), el('th', {scope: 'col', class: 'num'}, 'Toneladas'))), el('tbody', {}, rows)),
      el('p', {class: 'marked-line', hidden: true}, el('span', {id: 'marked-text'}), ' ',
        el('button', {type: 'button', id: 'unmark', class: 'link'}, 'Desmarcar')),
      el('p', {class: 'assign-line', hidden: true},
        el('select', {id: 'assign-machine', 'aria-label': 'Máquina para as linhas marcadas'}, el('option', {value: ''}, 'Máquina…')), ' ',
        el('button', {type: 'button', id: 'assign', class: 'assign'}, 'Atribuir')),
      data.stale ? el('p', {class: 'muted'}, 'A atualizar as horas…') : null);
    // Na semana (E2-10): só as outras máquinas com números dessa semana (célula da Carga), «carga / capacidade h»;
    // sem eles (Python antiga) a linha não aparece, para não mostrar o Planeado de todas as semanas como da semana.
    const otherList = (data.other_machines || []).filter((m) => !state.kpisWeek || m.week);
    const otherText = (m) => {
      if (!state.kpisWeek) return `${shortName(m.name)} ${metres(m.base.metres)}`;
      const cap = m.week.capacity === null || m.week.capacity === undefined ? '' : ` / ${hoursFmt.format(m.week.capacity)}`;
      return `${shortName(m.name)} ${hoursFmt.format(m.week.load || 0)}${cap} h`;
    };
    const others = otherList.length
      ? el('p', {class: 'others muted'}, `Outras máquinas planeadas: ${otherList.map(otherText).join(' · ')}`) : null;
    const scope = scopeLine(data);
    $('kpis').replaceChildren(...(scope ? [scope] : []), ...panels, resumo, ...(others ? [others] : []));
    $('kpis').dataset.panels = String(panels.length + 1); // MTG3: Punção, Broca, Resumo; MTG2: máquinas e Resumo
    $('unmark').addEventListener('click', () => { state.selected.clear(); selectionChanged(); });
    $('assign').addEventListener('click', assignMachine);
    if (data.stale) setTimeout(() => { if (data.sector === state.sector) loadKpis(); }, 8000);
    renderMarked();
    refreshSuggestion();
  }

  // O filtro Prazo é o único que muda os KPIs (08/10): vai em `semanas`; os outros filtros não vão.
  async function loadKpis() {
    const ticket = ++state.tickets.kpis;
    const sector = state.sector;
    const params = new URLSearchParams({setor: sector});
    weeks().forEach((w) => params.append('semanas', w));
    try {
      const data = await api('/planeamento/api/carteira/kpis', params);
      if (ticket !== state.tickets.kpis || sector !== state.sector) return;
      if (!data.scope || !(data.scope.weeks || []).length) state.kpisBase = {sector, data};
      renderKpis(data);
      schedule('preview', refreshPreview, 0);
    } catch (error) {
      if (ticket === state.tickets.kpis) $('kpis').replaceChildren(el('p', {class: 'error'}, `Carga das máquinas indisponível: ${error.message}`));
    }
  }

  function renderMarked() {
    const n = state.selected.size;
    const line = document.querySelector('#kpis .marked-line');
    if (line) line.hidden = !n;
    const assign = document.querySelector('#kpis .assign-line');
    if (assign) assign.hidden = !n;
    const text = $('marked-text');
    if (!text) return;  // painel ainda a carregar
    text.textContent = n ? `${number.format(n)} marcada(s)` : '';
    document.querySelectorAll('#kpis .delta').forEach((d) => { d.textContent = ''; });
    const p = n ? state.preview : null;
    if (!p) return;
    let addM = 0, addH = 0;
    for (const [id, d] of Object.entries(p.delta || {})) {
      addM += d.metres; addH += d.hours;
      // Na semana escolhida Planear não muda a carga (passa de «a vencer» para «no plano»): sem acréscimos (08/10).
      const li = state.kpisWeek ? null : document.querySelector(`#kpis li[data-machine="${CSS.escape(id)}"]`);
      if (!li || !li.querySelector('.delta-m')) continue;
      li.querySelector('.delta-m').textContent = ` (+${metres(d.metres)})`;
      li.querySelector('.delta-h').textContent = ` (+${hours(d.hours)})`;
    }
    const nm = p.no_machine || {lines: 0, metres: 0};
    const tp = p.to_plan || {tonnes: 0};
    text.textContent = `${number.format(n)} marcada(s): Planear acrescenta ${metres(addM)} · ${hours(addH)} · ${tonnes(tp.tonnes)}` +
      (nm.lines ? ` · ${number.format(nm.lines)} sem máquina (${metres(nm.metres)}): será usada a sugerida ao planear` : '');
  }

  async function refreshPreview() {
    const ticket = ++state.tickets.preview;
    const sector = state.sector;
    if (!state.selected.size) { state.preview = null; renderMarked(); return; }
    try {
      const data = await post('/planeamento/api/carteira/previsao', {setor: sector, chaves_compactas: compact([...state.selected.keys()])});
      if (ticket !== state.tickets.preview || sector !== state.sector) return;
      state.preview = data;
      renderMarked();
    } catch (error) {
      if (ticket === state.tickets.preview) showError(error);
    }
  }

  // --- Mensagens

  function showError(error) { $('error').textContent = error.message; $('error').hidden = false; }
  function notice(text) { $('notice').textContent = text; $('notice').hidden = false; }

  // --- Opções e arranque

  async function options(initial) {
    const sector = state.sector;
    const data = await api('/planeamento/api/carteira/opcoes', new URLSearchParams({setor: sector}));
    if (sector !== state.sector) return;
    const fill = (id, items, value, label, keep) => {
      const select = $(id);
      select.replaceChildren(el('option', {value: ''}, 'Todas'), ...items.map((x) => el('option', {value: value(x)}, label(x))));
      if ([...select.options].some((o) => o.value === keep)) select.value = keep;
    };
    fill('familia_sku', data.sku_families || [], (f) => f.code, (f) => f.label, initial.familia_sku ?? $('familia_sku').value);
    fill('familia', data.families, (f) => f.code, (f) => f.label, initial.familia ?? $('familia').value);
    const machine = initial.maquina ?? $('maquina').value;
    fill('maquina', data.machines, (m) => m, (m) => m, machine);
    for (const [value, label] of [['sem', 'Sem máquina'], ['com', 'Com máquina']]) $('maquina').insertBefore(el('option', {value}, label), $('maquina').options[1]);
    $('maquina').value = machine && [...$('maquina').options].some((o) => o.value === machine) ? machine : '';
    const keep = new Set(initial.semanas || weeks());
    $('semanas-lista').replaceChildren(...(data.weeks || []).map((w) => el('label', {class: 'week'},
      el('input', {type: 'checkbox', value: w.code, checked: keep.has(w.code), dataset: {label: w.label}}), ` ${w.label}`)));
    weeksSummary();
  }

  // Opções de Ordem do setor (P6, 08/10): por defeito MTG3 pela data de corte e MTG2 pelo Picking.
  function orderOptions(keep) {
    const list = ORDERS[state.sector] || ORDERS.cantoneiras;
    const off = (v) => state.noDateOrder && BY_DATE.has(v);
    $('ordem').replaceChildren(...list.map(([value, label]) => el('option', {value, disabled: off(value)}, label)));
    $('ordem').value = list.some(([v]) => v === keep) && !off(keep) ? keep : state.noDateOrder ? 'urgencia' : list[0][0];
  }

  async function switchSector(initial = {}) {
    state.sector = $('setor').value;
    // Ao mudar de setor, uma ordem por data volta à do novo setor; «urgência» e «metros» ficam.
    orderOptions(initial.ordem || (BY_DATE.has($('ordem').value) ? null : $('ordem').value));
    state.open = [];
    state.counts.clear();
    state.preview = null;
    loadSelection();
    $('kpis').replaceChildren(el('p', {class: 'muted'}, 'A calcular a carga das máquinas…'));
    try { await options(initial); } catch (error) { showError(error); }
    loadKpis();
    selectionChanged();
    await load();
  }

  async function start() {
    const initial = new URLSearchParams(location.search);
    for (const id of ['setor', 'vista', 'estado', 'q']) {
      const value = initial.get(id);
      if (value && (id === 'q' || [...$(id).options].some((o) => o.value === value))) $(id).value = value;
    }
    const first = {familia: initial.get('familia') || '', familia_sku: initial.get('familia_sku') || '', maquina: initial.get('maquina') || '',
                   semanas: initial.getAll('semanas'), ordem: initial.get('ordem')};
    let timer;
    const reload = (wait) => { clearTimeout(timer); timer = setTimeout(load, wait); };
    for (const id of ['vista', 'ordem', 'familia', 'familia_sku', 'maquina', 'estado']) $(id).addEventListener('change', () => {
      if (id === 'vista') state.open = [];
      reload(0);
    });
    $('q').addEventListener('input', () => reload(300));
    $('semanas-lista').addEventListener('change', () => { weeksSummary(); reload(200); schedule('kpis', loadKpis, 200); });
    document.addEventListener('click', (event) => { if ($('semanas').open && !$('semanas').contains(event.target)) $('semanas').open = false; });
    $('semanas').addEventListener('keydown', (event) => { if (event.key === 'Escape') { $('semanas').open = false; $('semanas').querySelector('summary').focus(); } });
    $('setor').addEventListener('change', () => switchSector());
    $('controls').addEventListener('submit', (event) => event.preventDefault());
    $('limpar-filtros').addEventListener('click', () => {
      // Só filtros: setor, vista, ordem e marcações ficam.
      for (const id of SIMPLE) $(id).value = '';
      const hadWeeks = weeks().length > 0 || state.kpisWeek;
      $('semanas-lista').querySelectorAll('input').forEach((i) => { i.checked = false; });
      weeksSummary();
      load();
      if (hadWeeks) {  // os KPIs voltam logo à carga de todas as semanas e atualizam-se
        clearTimeout(timers.kpis);
        loadKpis();
        if (state.kpisBase && state.kpisBase.sector === state.sector) renderKpis(state.kpisBase.data);
      }
    });
    // Cabeçalho e Subtotal presos por baixo do menu (P2, 08/10).
    if (window.stickyHead) window.stickyHead($('cart-table'), $('tree'), {extra: $('subtotal')});
    await switchSector(first);
  }

  document.addEventListener('DOMContentLoaded', start);
})();
