'use strict';
// Carteira (plano de 28/09/2026): grupos por nível, abertos a pedido. Só leitura.
(() => {
  const $ = (id) => document.getElementById(id);
  const FILTERS = ['setor', 'vista', 'familia', 'janela', 'maquina', 'sinal', 'q', 'ordem'];
  const WINDOWS = ['atrasado', '3_semanas', 'mais_tarde', 'sem_data'];
  const SIGNAL_LABELS = {prioridade: null, anulada: 'Anulada', eletrofer: 'Eletrofer', validacao: 'Após validação', estado_cpis: 'CPIS por confirmar'};
  const number = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 0});
  const km = new Intl.NumberFormat('pt-PT', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  let request = 0;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child);
    return node;
  }

  function day(value) {
    if (!value) return '—';
    const [y, m, d] = String(value).slice(0, 10).split('-');
    return `${d}/${m}/${y}`;
  }

  function state() {
    const out = {};
    for (const id of FILTERS) out[id] = $(id).value;
    return out;
  }

  function query(extra = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries({...state(), ...extra})) {
      if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
      else if (value) params.set(key, value);
    }
    return params;
  }

  async function api(path, params) {
    const response = await fetch(`${path}?${params}`, {headers: {Accept: 'application/json'}});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `Erro ${response.status}`);
    return body;
  }

  function windowBar(windows, metres) {
    const bar = el('span', {class: 'wbar', role: 'img', 'aria-label': WINDOWS.map((w) => `${w.replace('_', ' ')}: ${number.format(windows[w] || 0)} m`).join('; ')});
    for (const w of WINDOWS) {
      const value = windows[w] || 0;
      if (value > 0 && metres > 0) bar.append(el('span', {class: `w w-${w}`, style: `width:${Math.max(2, (100 * value) / metres)}%`, title: `${number.format(value)} m`}));
    }
    return bar;
  }

  function signalBadges(group) {
    const badges = [];
    if (group.priority !== null && group.priority !== undefined) badges.push(el('span', {class: 'badge badge-priority', title: 'Há linhas de OF com esta prioridade escrita na designação'}, `${group.priority}.ª prioridade`));
    for (const [name, label] of Object.entries(SIGNAL_LABELS)) {
      const count = (group.signals || {})[name];
      if (label && count) badges.push(el('span', {class: `badge badge-${name}`, title: `${count} linha(s)`}, label));
    }
    for (const week of group.written_weeks || []) badges.push(el('span', {class: 'badge badge-week', title: 'Semana de entrega escrita na designação'}, `Entrega ${week}`));
    return badges;
  }

  function subtitle(level, group) {
    if (level === 'of' || level === 'work') return [group.customers.join(', '), group.designation].filter(Boolean).join(' · ');
    return group.customers.join(', ');
  }

  function row(group, data, path, depth) {
    const level = data.level.id;
    const key = [...path, group.key];
    const toggle = data.has_children
      ? el('button', {type: 'button', class: 'toggle', 'aria-expanded': 'false', 'aria-label': `Abrir ${group.key}`}, '▸')
      : el('span', {class: 'toggle-space'});
    const tr = el('tr', {class: `level-${depth}`, dataset: {path: JSON.stringify(key), depth: String(depth)}},
      el('th', {scope: 'row', class: 'group'},
        el('div', {class: 'group-cell', style: `--depth:${depth}`}, toggle,
          el('span', {class: 'group-text'}, el('strong', {}, group.key), el('small', {title: subtitle(level, group)}, subtitle(level, group))))),
      el('td', {class: 'num'}, number.format(group.metres)),
      el('td', {class: 'num'}, number.format(group.pieces)),
      el('td', {class: 'num'}, number.format(group.ofs)),
      el('td', {class: 'num'}, group.metres_without_machine ? number.format(group.metres_without_machine) : '—'),
      el('td', {}, day(group.earliest_cut_date)),
      el('td', {}, windowBar(group.windows, group.metres)),
      el('td', {class: 'machines'}, group.machines.map((m) => el('span', {}, `${m.machine} · ${number.format(m.metres)} m`))),
      el('td', {class: 'signals'}, signalBadges(group)));
    if (data.has_children) toggle.addEventListener('click', () => expand(tr, key, depth));
    return tr;
  }

  function collapse(tr) {
    const prefix = tr.dataset.path.slice(0, -1);
    let next = tr.nextElementSibling;
    while (next && next.dataset.path && next.dataset.path.startsWith(prefix + ',')) {
      const remove = next;
      next = next.nextElementSibling;
      remove.remove();
    }
  }

  async function expand(tr, path, depth) {
    const button = tr.querySelector('.toggle');
    if (button.getAttribute('aria-expanded') === 'true') {
      collapse(tr);
      button.setAttribute('aria-expanded', 'false');
      button.textContent = '▸';
      return;
    }
    button.disabled = true;
    try {
      const data = await api('/planeamento/api/carteira', query({caminho: path}));
      let anchor = tr;
      for (const group of data.groups) {
        const child = row(group, data, path, depth + 1);
        anchor.after(child);
        anchor = child;
      }
      if (data.truncated) anchor.after(el('tr', {class: `level-${depth + 1} more`, dataset: {path: JSON.stringify([...path, '…'])}},
        el('td', {colspan: '9'}, `Mostram-se ${data.groups.length} de ${data.group_count}. Usa os filtros para ver os restantes.`)));
      button.setAttribute('aria-expanded', 'true');
      button.textContent = '▾';
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
    }
  }

  function showError(error) {
    $('error').textContent = error.message;
    $('error').hidden = false;
  }

  function totals(data) {
    const t = data.totals;
    const card = (label, value, hint) => el('div', {class: 'card'}, el('span', {}, label), el('strong', {}, value), hint ? el('small', {}, hint) : null);
    $('totals').replaceChildren(
      card('Por cortar', `${km.format(t.metres / 1000)} km`, `${number.format(t.pieces)} peças · ${number.format(t.lines)} linhas`),
      card('OF', number.format(t.ofs), `${number.format(data.group_count)} grupos neste nível`),
      card('Sem máquina', `${km.format(t.metres_without_machine / 1000)} km`, t.metres ? `${Math.round((100 * t.metres_without_machine) / t.metres)}% do total` : ''),
      card('Data Corte já passada', `${km.format(t.windows.atrasado / 1000)} km`),
      card('Até ao fim da semana ISO +2', `${km.format(t.windows['3_semanas'] / 1000)} km`),
      card('Sem Data Corte', `${km.format(t.windows.sem_data / 1000)} km`));
    $('source').textContent = `Excel importado a ${new Date(data.imported_at).toLocaleString('pt-PT')} · importação ${data.snapshot} · prazos contados a ${day(data.today)}`;
    $('level-title').textContent = data.level.label;
    $('rule-list').replaceChildren(...Object.values(data.rules).map((text) => el('li', {}, text)));
  }

  async function load() {
    const ticket = ++request;
    $('error').hidden = true;
    history.replaceState(null, '', `?${query()}`);
    try {
      const data = await api('/planeamento/api/carteira', query());
      if (ticket !== request) return;
      totals(data);
      $('rows').replaceChildren(...data.groups.map((group) => row(group, data, [], 0)));
      $('empty').hidden = data.groups.length > 0;
    } catch (error) {
      if (ticket === request) showError(error);
    }
  }

  async function options() {
    const data = await api('/planeamento/api/carteira/opcoes', new URLSearchParams({setor: $('setor').value}));
    const family = $('familia');
    for (const f of data.families) family.append(el('option', {value: f.code}, f.label));
    const machine = $('maquina');
    for (const m of data.machines) machine.append(el('option', {value: m}, m));
  }

  async function start() {
    const initial = new URLSearchParams(location.search);
    for (const id of FILTERS) if (initial.get(id) && id !== 'familia' && id !== 'maquina') $(id).value = initial.get(id);
    try {
      await options();
    } catch (error) {
      showError(error);
    }
    for (const id of ['familia', 'maquina']) if (initial.get(id)) $(id).value = initial.get(id);
    let timer;
    for (const id of FILTERS) {
      $(id).addEventListener(id === 'q' ? 'input' : 'change', () => {
        clearTimeout(timer);
        timer = setTimeout(load, id === 'q' ? 300 : 0);
      });
    }
    $('controls').addEventListener('submit', (event) => event.preventDefault());
    await load();
  }

  document.addEventListener('DOMContentLoaded', start);
})();
