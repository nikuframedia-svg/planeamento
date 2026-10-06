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
    for (const r of m.rates) items.push(el('div', {class: 'rate'}, `Confirmada: ${fmt.format(r.value)} ${data.methods[r.method] || r.method}${r.profile ? ` · ${r.profile}` : ''}${r.operation ? ` · ${r.operation}` : ''}`));
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
    const ok = el('button', {type: 'button', class: 'small'}, 'Gravar');
    ok.addEventListener('click', () => send({tipo: 'taxa', maquina: m.id, metodo: method.value, valor: Number(value.value), operacao: op.value, perfil: prof.value})
      .then(() => { notice(`Taxa de ${short(m.name)} gravada: passa a ter prioridade sobre o Excel.`); return load(); }).catch(error));
    add.append(el('div', {class: 'rate-form'}, value, method, op, prof, ok));
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
    return el('tr', {}, el('th', {scope: 'row'}, short(m.name), el('small', {class: 'muted'}, ` ${m.code || ''}`)),
      el('td', {}, m.process || '—'), el('td', {}, confirm), el('td', {}, turns), el('td', {}, weeksCell(m)), el('td', {}, fichaCell(m)), el('td', {}, ratesCell(m)));
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
