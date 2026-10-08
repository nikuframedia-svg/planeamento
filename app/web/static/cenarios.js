'use strict';
// Cenários (Etapa 5, ponto 8, 08/10/2026): vista «Cenários» da Carga e turnos.
// Contrato com setor_carga.js: window.cenariosView(contentor, {setor}) desenha tudo dentro do contentor.
// Simulação: nada muda no plano em uso até Aplicar. A comparação calcula-se no servidor em segundo plano: enquanto
// está «a calcular», o ecrã volta a pedir de 2 em 2 s. Com a Python antiga (404 sem erro) diz que falta reiniciar.
(() => {
  const API = '/planeamento/api/setor/cenarios';
  const h1 = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1});
  const dmFmt = new Intl.DateTimeFormat('pt-PT', {day: '2-digit', month: '2-digit', timeZone: 'Europe/Lisbon'});
  const dmhFmt = new Intl.DateTimeFormat('pt-PT', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Lisbon'});
  const STATE = {atrasa: 'atrasa', em_risco: 'em risco', sem_previsao: 'sem previsão', ok: 'ok'};
  const STATUS = {aberto: 'aberto', aplicado: 'aplicado', arquivado: 'descartado'};
  const RESTART = 'Os cenários precisam que o serviço do planeamento seja reiniciado.';

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }
  const dm = (iso) => iso ? (String(iso).length <= 10 ? `${String(iso).slice(8, 10)}/${String(iso).slice(5, 7)}` : dmFmt.format(new Date(iso))) : '—';
  const dmh = (iso) => iso ? dmhFmt.format(new Date(iso)).replace(',', '') : '—';
  const arrow = (a, b) => a === b ? String(a) : `${a} → ${b}`;

  async function call(url, options = {}) {
    const r = await fetch(url, {headers: {Accept: 'application/json', ...(options.body ? {'Content-Type': 'application/json'} : {})}, ...options});
    const body = await r.json().catch(() => ({}));
    if (r.status === 404 && !body.error) throw new Error(RESTART);
    if (!r.ok) {
      const e = new Error(body.error || `Erro ${r.status}`);
      e.status = r.status;
      throw e;
    }
    return body;
  }

  window.cenariosView = function cenariosView(root, {setor}) {
    const s = {setor, list: null, current: new URLSearchParams(location.search).get('cenario'), compare: null, timer: null, ticket: 0, confirm: false, adding: false};
    const box = el('section', {class: 'cen', 'aria-label': 'Cenários'});
    root.replaceChildren(box);
    const alive = () => box.isConnected;

    const status = el('p', {class: 'cen-msg', role: 'status', hidden: true});
    const error = el('p', {class: 'cen-error', role: 'alert', hidden: true});
    const say = (text) => { status.textContent = text; status.hidden = !text; error.hidden = true; };
    const fail = (e) => { error.textContent = e.message || String(e); error.hidden = false; status.hidden = true; };

    async function post(payload) {
      return call(API, {method: 'POST', body: JSON.stringify({setor: s.setor, request_id: crypto.randomUUID(), ...payload})});
    }
    async function load(keepMessage) {
      if (!keepMessage) { status.hidden = true; error.hidden = true; }
      try {
        s.list = await call(`${API}?setor=${encodeURIComponent(s.setor)}`);
      } catch (e) { s.list = null; draw(); fail(e); return; }
      if (s.current && !s.list.scenarios.some((x) => x.id === s.current)) s.current = null;
      if (!s.current && s.list.scenarios.length) s.current = (s.list.scenarios.find((x) => x.status === 'aberto') || s.list.scenarios[0]).id;
      s.compare = null;
      draw();
      fetchCompare();
    }
    const scenario = () => (s.list?.scenarios || []).find((x) => x.id === s.current) || null;
    const names = () => Object.fromEntries((s.list?.machines || []).map((m) => [m.id, m.name]));

    // ------------------------------------------------------------ comparação (com repetição enquanto calcula)
    async function fetchCompare() {
      clearTimeout(s.timer);
      const sc = scenario();
      if (!sc || sc.status === 'arquivado') return;
      const ticket = ++s.ticket;
      try {
        const out = await call(`${API}/${sc.id}/comparacao?setor=${encodeURIComponent(s.setor)}`);
        if (ticket !== s.ticket || !alive()) return;
        s.compare = out;
        drawCompare();
        if (out.pending) s.timer = setTimeout(fetchCompare, 2000);
      } catch (e) {
        if (ticket !== s.ticket || !alive()) return;
        s.compare = {error: e.message};
        drawCompare();
      }
    }

    // ------------------------------------------------------------ desenho
    const listBox = el('div', {class: 'cen-list'});
    const body = el('div', {class: 'cen-body'});
    const compareBox = el('div', {class: 'cen-compare'});
    box.append(el('p', {class: 'cen-banner', role: 'note'}, 'Simulação: nada muda no plano em uso até Aplicar.'), status, error, listBox, body);

    function draw() {
      drawList();
      drawBody();
    }

    function drawList() {
      const items = (s.list?.scenarios || []).map((x) => el('li', {},
        el('button', {type: 'button', class: 'cen-pick', 'aria-pressed': String(x.id === s.current),
          onclick: () => { s.current = x.id; s.confirm = false; s.compare = null; draw(); fetchCompare(); }},
        el('b', {}, x.name), ` · ${STATUS[x.status] || x.status} · ${x.created_by}`)));
      const form = el('form', {class: 'cen-new', hidden: !s.adding, onsubmit: async (ev) => {
        ev.preventDefault();
        const name = form.querySelector('input').value.trim();
        if (!name) return;
        try {
          const out = await post({acao: 'criar', nome: name});
          s.current = out.id; s.adding = false;
          say(`Cenário «${name}» criado.`);
          await load(true);
        } catch (e) { fail(e); }
      }}, el('input', {type: 'text', maxlength: '120', placeholder: 'Nome do cenário', 'aria-label': 'Nome do cenário'}),
      el('button', {type: 'submit', class: 'primary'}, 'Criar'),
      el('button', {type: 'button', onclick: () => { s.adding = false; drawList(); }}, 'Cancelar'));
      listBox.replaceChildren(...[
        el('div', {class: 'cen-row'}, el('h2', {}, 'Cenários'),
          el('button', {type: 'button', class: 'cen-add-btn', disabled: !s.list?.installed, onclick: () => { s.adding = true; drawList(); form.querySelector('input').focus(); }}, 'Novo')),
        s.list && !s.list.installed ? el('p', {class: 'muted'}, 'Os cenários ainda não estão instalados (migração 054).') : null,
        s.list?.installed && !items.length ? el('p', {class: 'muted'}, 'Ainda não há cenários. Cria um com «Novo».') : null,
        items.length ? el('ul', {class: 'cen-items'}, items) : null, form].filter(Boolean));
    }

    function drawBody() {
      const sc = scenario();
      if (!sc) { body.replaceChildren(); return; }
      if (sc.status === 'aplicado') { body.replaceChildren(el('h2', {}, `«${sc.name}» · aplicado por ${sc.applied_by} em ${dmh(sc.applied_at)}`), compareBox); drawCompare(); return; }
      const changes = el('ol', {class: 'cen-changes'}, sc.changes.map((c) => el('li', {},
        el('span', {}, c.label),
        el('button', {type: 'button', class: 'cen-x', title: 'Retirar esta alteração', 'aria-label': `Retirar: ${c.label}`, onclick: async () => {
          try { await post({acao: 'retirar_alteracao', cenario: sc.id, expected_revision: sc.revision, alteracao: c.id}); await load(); }
          catch (e) { fail(e); }
        }}, '✕'))));
      body.replaceChildren(
        el('h2', {}, `Alterações de «${sc.name}»`),
        sc.changes.length ? changes : el('p', {class: 'muted'}, 'Sem alterações: o cenário é igual ao plano em uso.'),
        addForm(sc),
        el('h2', {}, 'Comparação com o plano em uso'),
        compareBox,
        actions(sc));
      drawCompare();
    }

    // ------------------------------------------------------------ formulário mínimo por tipo
    function addForm(sc) {
      const machines = s.list.machines || [];
      const machineSelect = () => el('select', {name: 'maquina', 'aria-label': 'Máquina', required: true},
        machines.map((m) => el('option', {value: m.id}, m.name)));
      const field = (label, input) => el('label', {}, `${label} `, input);
      const kind = el('select', {name: 'tipo', 'aria-label': 'Tipo de alteração'},
        Object.entries(s.list.kinds).map(([k, v]) => el('option', {value: k}, v)));
      const fields = el('span', {class: 'cen-fields'});
      const today = new Date().toISOString().slice(0, 10);
      function render() {
        const k = kind.value;
        const parts = {
          cancelar: () => [field('', el('select', {name: 'que', 'aria-label': 'O que cancelar'}, el('option', {value: 'of'}, 'OF'), el('option', {value: 'ov'}, 'OV (obra)'), el('option', {value: 'ref'}, 'OF + referência'))),
            field('', el('input', {name: 'codigo', type: 'text', required: true, placeholder: 'OF ou OV', 'aria-label': 'OF ou OV', size: '12'})),
            field('', el('input', {name: 'referencia', type: 'text', placeholder: 'Referência (só OF + referência)', 'aria-label': 'Referência', size: '16'}))],
          maquina_parada: () => [field('Máquina', machineSelect()), field('De', el('input', {name: 'de', type: 'datetime-local', required: true, value: `${today}T06:00`})),
            field('Até', el('input', {name: 'ate', type: 'datetime-local', required: true, value: `${today}T13:30`}))],
          turnos: () => [field('Máquina', machineSelect()), field('', el('select', {name: 'quando', 'aria-label': 'Dia ou semana'}, el('option', {value: 'dia'}, 'No dia'), el('option', {value: 'semana'}, 'Na semana de'))),
            field('', el('input', {name: 'dia', type: 'date', required: true, value: today, 'aria-label': 'Dia'})),
            field('Turnos', el('select', {name: 'turnos'}, [0, 1, 2, 3].map((n) => el('option', {value: String(n)}, String(n)))))],
          pessoas_em_falta: () => [field('Dia', el('input', {name: 'dia', type: 'date', required: true, value: today})),
            field('Turno', el('select', {name: 'turno'}, Array.from({length: s.list.shifts || 3}, (_, i) => el('option', {value: String(i + 1)}, `${i + 1}.º`)))),
            field('Faltam', el('input', {name: 'n', type: 'number', min: '1', max: '50', value: '1', required: true, size: '3'}))],
          urgente: () => [field('OF', el('input', {name: 'of', type: 'text', required: true, size: '12'}))],
          prazo: () => [field('OF', el('input', {name: 'of', type: 'text', required: true, size: '12'})), field('Novo prazo', el('input', {name: 'data', type: 'date', required: true, value: today}))],
        };
        fields.replaceChildren(...parts[k]());
      }
      kind.addEventListener('change', render);
      render();
      const form = el('form', {class: 'cen-add', onsubmit: async (ev) => {
        ev.preventDefault();
        const v = Object.fromEntries(new FormData(form).entries());
        const k = v.tipo;
        let alvo = {}, parametros = {};
        if (k === 'cancelar') alvo = v.que === 'ov' ? {ov: v.codigo} : v.que === 'ref' ? {of: v.codigo, referencia: v.referencia} : {of: v.codigo};
        else if (k === 'maquina_parada') { alvo = {maquina: v.maquina}; parametros = {de: v.de, ate: v.ate}; }
        else if (k === 'turnos') {
          alvo = {maquina: v.maquina};
          if (v.quando === 'dia') parametros = {dia: v.dia, turnos: Number(v.turnos)};
          else { const [y, w] = isoWeek(v.dia); parametros = {ano: y, semana: w, turnos: Number(v.turnos)}; }
        } else if (k === 'pessoas_em_falta') parametros = {dia: v.dia, turno: Number(v.turno), n: Number(v.n)};
        else if (k === 'urgente') alvo = {of: v.of};
        else { alvo = {of: v.of}; parametros = {data: v.data}; }
        try {
          await post({acao: 'alterar', cenario: sc.id, expected_revision: sc.revision, tipo: k, alvo, parametros});
          await load();
        } catch (e) { fail(e); }
      }}, el('label', {}, 'Acrescentar ', kind), fields, el('button', {type: 'submit'}, 'Acrescentar'));
      return form;
    }

    function isoWeek(day) {
      const d = new Date(`${day}T12:00:00Z`);
      const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
      const n = t.getUTCDay() || 7;
      t.setUTCDate(t.getUTCDate() + 4 - n);
      const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
      return [t.getUTCFullYear(), Math.ceil(((t - y0) / 86400000 + 1) / 7)];
    }

    // ------------------------------------------------------------ ações: ver, aplicar (com confirmação), descartar
    function actions(sc) {
      const real = sc.changes.filter((c) => c.kind !== 'pessoas_em_falta');
      const confirmBox = el('div', {class: 'cen-confirm', hidden: !s.confirm, role: 'region', 'aria-label': 'Confirmar Aplicar'},
        el('p', {}, el('b', {}, 'Aplicar grava isto no plano em uso:')),
        el('ul', {}, sc.changes.map((c) => el('li', {}, c.apply_text))),
        el('p', {class: 'muted'}, 'Depois podes desfazer cada alteração na lista «Aplicado».'),
        el('button', {type: 'button', class: 'primary', onclick: async () => {
          try {
            const out = await post({acao: 'aplicar', cenario: sc.id, expected_revision: sc.revision});
            s.confirm = false;
            say(`Aplicado: ${out.applied.map((x) => `${x.label} — ${x.written}`).join('; ')}.`);
            await load(true);
          } catch (e) { fail(e); }
        }}, 'Confirmar e aplicar'),
        el('button', {type: 'button', onclick: () => { s.confirm = false; drawBody(); }}, 'Cancelar'));
      return el('div', {class: 'cen-actions'},
        el('a', {href: `/planeamento/setor/carga?setor=${encodeURIComponent(s.setor)}&vista=calendario&cenario=${sc.id}`}, 'Ver no calendário'),
        el('button', {type: 'button', class: 'primary', disabled: !real.length, title: real.length ? null : 'Só pessoas em falta: não há nada para gravar',
          onclick: () => { s.confirm = true; drawBody(); box.querySelector('.cen-confirm button')?.focus(); }}, 'Aplicar…'),
        el('button', {type: 'button', onclick: async () => {
          try { await post({acao: 'descartar', cenario: sc.id, expected_revision: sc.revision}); s.current = null; say(`«${sc.name}» descartado.`); await load(true); }
          catch (e) { fail(e); }
        }}, 'Descartar'),
        confirmBox);
    }

    // ------------------------------------------------------------ comparação
    function counter(label, value, title) {
      return el('div', {class: 'cen-count', title}, el('span', {}, label), el('b', {}, value));
    }
    function end(row, which) {
      if (which === 'after' && row.cancelled) return 'cancelada';
      if (row[`beyond_${which}`]) return 'além dos calendários';
      return dmh(row[which]);
    }
    function table(head, rows) {
      return el('div', {class: 'cen-wrap'}, el('table', {class: 'cen-table'},
        el('thead', {}, el('tr', {}, head.map((x) => el('th', {}, x)))), el('tbody', {}, rows)));
    }

    function drawCompare() {
      const c = s.compare;
      const sc = scenario();
      if (!sc) { compareBox.replaceChildren(); return; }
      if (!c) { compareBox.replaceChildren(el('p', {class: 'muted'}, 'A pedir a comparação…')); return; }
      if (c.error) { compareBox.replaceChildren(el('p', {class: 'cen-error', role: 'alert'}, c.error)); return; }
      if (c.applied) { compareBox.replaceChildren(...appliedView(sc, c)); return; }
      const d = c.pending ? c.previous : c;
      const parts = [];
      if (c.pending) parts.push(el('p', {class: 'muted', role: 'status'}, d ? 'A recalcular com os dados novos… (abaixo, o resultado anterior)' : 'A calcular a comparação em segundo plano…'));
      if (!d) { compareBox.replaceChildren(...parts.filter(Boolean)); return; }
      const k = d.counters;
      const people = k.people_short_after === null ? '—' : arrow(k.people_short_before, k.people_short_after);
      parts.push(el('div', {class: 'cen-counters'},
        counter('Passam a atrasar', String(k.late_new)),
        counter('Deixam de atrasar', String(k.late_gone)),
        counter('Máquinas acima da capacidade', arrow(k.over_capacity_before, k.over_capacity_after), 'Máquinas com falta de horas até ao prazo (em uso → cenário)'),
        counter('Turnos com falta de pessoas', people, k.people_short_after === null ? 'Sem pessoas disponíveis por turno nas Definições' : 'em uso → cenário')));
      parts.push(el('p', {class: 'muted'}, d.suggested_text));
      for (const st of d.stops || []) {
        const alt = (st.ranking || []).map((x) => `${x.name}: atrasa ${x.late_orders} OF${x.late_hours ? ` (+${h1.format(x.late_hours)} h)` : ''}${x.chosen ? ' ✓' : ''}`).join(' · ');
        parts.push(el('p', {}, `${st.label}: param ${st.machines.join(', ') || 'nenhuma máquina'}${st.chosen_by === 'utilizador' ? ' (escolha tua)' : ''}.`,
          st.missing ? ` Ainda faltam ${st.missing} pessoa(s).` : '', alt ? el('br') : '', alt ? el('span', {class: 'muted'}, `Parar cada uma: ${alt}`) : ''));
        if (sc.status === 'aberto' && (st.ranking || []).length > 1) parts.push(swapForm(sc, st));
      }
      if (d.orders.length) {
        const shown = d.orders.slice(0, 150);
        parts.push(el('h3', {}, `OF que mudam (${d.orders_total})`), table(['OF', 'Cliente', 'Prazo', 'Conclusão em uso → cenário', 'Δ dias úteis', 'Porquê'],
          shown.map((r) => el('tr', {class: r.state_after === 'atrasa' && r.state_before !== 'atrasa' ? 'cen-late' : null},
            el('td', {}, r.of), el('td', {}, r.customer || ''),
            el('td', {}, r.due_day_before && r.due_day_before !== r.due_day ? `${dm(r.due_day_before)} → ${dm(r.due_day)}` : dm(r.due_day)),
            el('td', {}, `${end(r, 'before')} → ${end(r, 'after')}`, r.state_after && r.state_after !== r.state_before ? el('span', {class: `cen-tag cen-${r.state_after}`}, STATE[r.state_after]) : null),
            el('td', {class: 'num'}, r.delta_days === null || r.delta_days === undefined ? '—' : (r.delta_days > 0 ? `+${r.delta_days}` : String(r.delta_days))),
            el('td', {}, r.why)))));
        const total = d.orders_total ?? d.orders.length;  // o servidor devolve só as primeiras 200 (revisão 08/10)
        if (total > shown.length) parts.push(el('p', {class: 'muted'}, `Mais ${total - shown.length} OF.`));
      } else parts.push(el('p', {class: 'muted'}, 'Nenhuma OF muda de conclusão nem de estado.'));
      if (d.machines.length) {
        const rec = (m, w) => !m[`overloaded_${w}`] ? 'sem falta' : m[`recovers_${w}`] ? dm(m[`recovery_${w}`]) : 'não recupera';
        parts.push(el('h3', {}, 'Máquinas'), table(['Máquina', 'Fila acaba (em uso → cenário)', 'Recupera (em uso → cenário)', 'Horas atrasadas'],
          d.machines.map((m) => el('tr', {}, el('td', {}, m.name), el('td', {}, `${dmh(m.queue_end_before)} → ${dmh(m.queue_end_after)}`),
            el('td', {}, arrow(rec(m, 'before'), rec(m, 'after'))), el('td', {class: 'num'}, arrow(h1.format(m.late_hours_before || 0), h1.format(m.late_hours_after || 0)))))));
      }
      if (d.weeks.length) {
        parts.push(el('h3', {}, 'Máquina × semana (horas em uso → cenário)'), table(['Máquina', 'Semana', 'Previsão h', 'Capacidade h'],
          d.weeks.map((w) => el('tr', {}, el('td', {}, w.name), el('td', {}, `${w.year}-S${String(w.week).padStart(2, '0')}`),
            el('td', {class: 'num'}, arrow(h1.format(w.load_before), h1.format(w.load_after))),
            el('td', {class: 'num'}, arrow(h1.format(w.capacity_before), h1.format(w.capacity_after)))))));
      }
      if (d.people.length) {
        const n = (v) => v === null || v === undefined ? '—' : String(v);
        parts.push(el('h3', {}, 'Pessoas por dia e turno (em uso → cenário)'), table(['Dia', 'Turno', 'Máquinas a trabalhar', 'Pessoas precisas', 'Disponíveis', 'Falta'],
          d.people.map((p) => el('tr', {}, el('td', {}, dm(p.date)), el('td', {}, `${p.shift}.º`),
            el('td', {class: 'num'}, arrow(n(p.machines_before), n(p.machines_after))), el('td', {class: 'num'}, arrow(n(p.need_before), n(p.need_after))),
            el('td', {class: 'num'}, arrow(n(p.available_before), n(p.available_after))), el('td', {class: 'num'}, arrow(n(p.deficit_before), n(p.deficit_after)))))));
      }
      compareBox.replaceChildren(...parts.filter(Boolean));
    }

    function swapForm(sc, st) {
      const change = sc.changes[st.change - 1];
      if (!change) return null;
      const boxes = st.ranking.map((x) => el('label', {}, el('input', {type: 'checkbox', value: x.id, checked: x.chosen}), ` ${x.name}`));
      return el('form', {class: 'cen-swap', onsubmit: async (ev) => {
        ev.preventDefault();
        const chosen = boxes.map((b) => b.querySelector('input')).filter((i) => i.checked).map((i) => i.value);
        if (!chosen.length) return;
        try {
          const out = await post({acao: 'retirar_alteracao', cenario: sc.id, expected_revision: sc.revision, alteracao: change.id});
          await post({acao: 'alterar', cenario: sc.id, expected_revision: out.revision, tipo: 'pessoas_em_falta', alvo: {}, parametros: {...change.params, maquinas: chosen}});
          await load();
        } catch (e) { fail(e); }
      }}, el('span', {}, 'Parar antes: '), boxes, el('button', {type: 'submit'}, 'Trocar'));
    }

    function appliedView(sc, c) {
      const out = [el('h3', {}, 'Aplicado')];
      out.push(el('ul', {class: 'cen-applied'}, (c.items || []).map((it) => el('li', {},
        el('span', {}, `${it.label} — ${it.written}`),
        it.simulation_only ? null : it.undone_at ? el('span', {class: 'muted'}, ` · desfeita por ${it.undone_by} (${it.undo_note})`)
          : el('button', {type: 'button', onclick: async () => {
            try { const r = await post({acao: 'desfazer_aplicada', cenario: sc.id, expected_revision: sc.revision, alteracao: it.change_id}); say(`Desfeita: ${r.note}.`); await load(true); }
            catch (e) { fail(e); }
          }}, 'Desfazer')))));
      out.push(el('h3', {}, 'Previsão nova comparada com a simulada'));
      if (!c.simulated) out.push(el('p', {class: 'muted'}, 'A comparação não estava calculada quando se aplicou: não há previsão simulada guardada.'));
      else {
        if (c.stale) out.push(el('p', {class: 'muted'}, 'A previsão em uso ainda se está a atualizar com o que foi aplicado.'));
        out.push(el('p', {}, c.differences_total ? `${c.differences_total} OF acabam de forma diferente do simulado.` : 'A previsão nova é igual à simulada.'));
        if (c.differences_total) out.push(table(['OF', 'Cliente', 'Simulada', 'Agora'], c.differences.map((x) => el('tr', {},
          el('td', {}, x.of), el('td', {}, x.customer || ''), el('td', {}, `${dmh(x.simulated)}${x.state_simulated ? ` · ${STATE[x.state_simulated] || x.state_simulated}` : ''}`),
          el('td', {}, `${dmh(x.now)}${x.state_now ? ` · ${STATE[x.state_now] || x.state_now}` : ''}`)))));
      }
      return out;
    }

    load();
  };
})();
