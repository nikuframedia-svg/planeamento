'use strict';
// Conjuntos de famílias SKU com máquina pré-definida (05/10/2026). Cada família só num conjunto.
(() => {
  const $ = (id) => document.getElementById(id);
  const number = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 0});
  let data = null, editing = null;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') node.className = v; else if (k === 'checked') node.checked = Boolean(v); else node.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }
  const short = (n) => String(n || '').replace(/^Ficep\s+/i, '');
  function error(e) { $('error').textContent = e.message; $('error').hidden = false; }
  function notice(t) { $('notice').textContent = t; $('notice').hidden = false; }

  async function send(path, payload) {
    const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify(payload)});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `Erro ${r.status}`);
    return body;
  }

  async function load() {
    $('error').hidden = true;
    const r = await fetch(`/planeamento/api/carteira/conjuntos?setor=${encodeURIComponent($('setor').value)}`, {headers: {Accept: 'application/json'}});
    data = await r.json();
    if (!r.ok) throw new Error(data.error || `Erro ${r.status}`);
    $('rows').replaceChildren(...data.sets.map((s) => {
      const edit = el('button', {type: 'button'}, 'Editar');
      const drop = el('button', {type: 'button'}, 'Arquivar');
      edit.addEventListener('click', () => open(s));
      drop.addEventListener('click', () => archive(s).catch(error));
      return el('tr', {}, el('th', {scope: 'row'}, s.name), el('td', {}, s.families.join(', ')), el('td', {}, short(s.machine)),
        el('td', {class: 'num'}, number.format(s.lines)), el('td', {class: 'num'}, `${number.format(s.metres)} m`), el('td', {class: 'acts'}, edit, drop));
    }));
    $('empty').hidden = !data.has_families || data.sets.length > 0;
    $('sem-familias').hidden = data.has_families;
    $('novo').disabled = !data.has_families;
  }

  function renderFamilies() {
    const text = $('filtro').value.trim().toUpperCase();
    const chosen = new Set([...$('familias').querySelectorAll('input:checked')].map((i) => i.value));
    (editing ? editing.families : []).forEach((f) => { if (!$('familias').children.length) chosen.add(f); });
    $('familias').replaceChildren(...data.families.filter((f) => !text || f.code.toUpperCase().includes(text) || chosen.has(f.code)).map((f) => {
      const other = f.set && (!editing || f.set !== editing.name);
      return el('label', {class: other ? 'family taken' : 'family', title: other ? `Já está em «${f.set}»` : (f.usual_machine ? `Na Tabela: ${Math.round(100 * f.usual_share)}% ${f.usual_machine}` : null)},
        el('input', {type: 'checkbox', value: f.code, checked: chosen.has(f.code), disabled: other}),
        ` ${f.code} `, el('small', {}, `${number.format(f.lines)} linhas${f.usual_machine ? ` · ${short(f.usual_machine)}` : ''}${other ? ` · em ${f.set}` : ''}`));
    }));
  }

  function open(set) {
    editing = set || null;
    $('nome').value = set ? set.name : '';
    $('maquina').replaceChildren(el('option', {value: ''}, 'Escolher…'), ...data.machines.map((m) => el('option', {value: m.id}, short(m.name) + (m.process ? ` · ${m.process}` : ''))));
    $('maquina').value = set ? set.resource_id : '';
    $('filtro').value = '';
    $('familias').replaceChildren();
    renderFamilies();
    $('editor').hidden = false;
    $('nome').focus();
  }

  async function save(event) {
    event.preventDefault();
    const familias = [...$('familias').querySelectorAll('input:checked')].map((i) => i.value);
    const result = await send('/planeamento/api/carteira/conjuntos', {setor: $('setor').value, id: editing ? editing.id : null,
      expected_revision: editing ? editing.revision : null, nome: $('nome').value, familias, maquina: $('maquina').value, request_id: crypto.randomUUID()});
    $('editor').hidden = true;
    notice(`Conjunto «${result.name}» gravado: as linhas destas famílias sem máquina passam para ${short(result.machine)}.`);
    await load();
  }

  async function archive(set) {
    if (!confirm(`Arquivar «${set.name}»? As linhas que só tinham a máquina deste conjunto ficam sem máquina.`)) return;
    await send('/planeamento/api/carteira/conjuntos/arquivar', {setor: $('setor').value, id: set.id, expected_revision: set.revision, request_id: crypto.randomUUID()});
    notice(`Conjunto «${set.name}» arquivado.`);
    await load();
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('setor').addEventListener('change', () => { $('editor').hidden = true; load().catch(error); });
    $('novo').addEventListener('click', () => open(null));
    $('cancelar').addEventListener('click', () => { $('editor').hidden = true; });
    $('filtro').addEventListener('input', renderFamilies);
    $('editor').addEventListener('submit', (e) => save(e).catch(error));
    load().catch(error);
  });
})();
