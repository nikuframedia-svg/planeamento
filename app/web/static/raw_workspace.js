"use strict";
window.Raw = (() => {
  const $ = (id) => document.getElementById(id),
    el = (tag, text, cls) => {
      const x = document.createElement(tag);
      if (text !== undefined) x.textContent = text;
      if (cls) x.className = cls;
      return x;
    },
    state = {
      loadSerial: 0,
      area: new URLSearchParams(location.search).get("area") || "perfis",
      population: "active",
      page: 1,
      size: 100,
      filters: [],
      order: [],
      columns: [],
      widths: {},
      column_order: [],
      column_groups: {},
      pinned: ['of', 'ov', 'component_ref'],
      columnOpen: {},
      selected: new Set(),
      cells: null,
      data: null,
      fields: [],
      cat: null,
      view: null,
      density: "compact",
      q: new URLSearchParams(location.search).get("q") || "",
      editing: null,
      evidence: null,
      formatRules: [],
    };
  async function api(path, p, method = "POST") {
    const r = await fetch(
      "/planeamento/api/" + path,
      p === undefined
        ? {}
        : {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(p),
          },
    );
    let data;
    try {
      data = await r.json();
    } catch {
      throw Error(
        "Resposta indisponível. Tenta atualizar dentro de alguns segundos.",
      );
    }
    if (!r.ok)
      throw Error(
        data.error || data.detail || "Não foi possível completar a ação.",
      );
    return data;
  }
  const request = (p) => ({ request_id: crypto.randomUUID(), ...p });
  const safe =
    (fn) =>
    async (...args) => {
      try {
        return await fn(...args);
      } catch (e) {
        const target = $("editor").open
          ? "edit-error"
          : $("drawer").open
            ? "drawer-error"
            : "notice";
        $(target).textContent = e.message;
        console.error(e);
      }
    };
  function fmt(v, f = {}) {
    if (v === null || v === undefined || v === "") return "—";
    if (
      typeof v === "string" &&
      /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v)
    )
      return (
        new Intl.DateTimeFormat("pt-PT", {
          dateStyle: "short",
          timeStyle: "short",
          timeZone: state.data?.display_timezone || "Europe/Lisbon",
        }).format(new Date(v)) +
        " · " +
        (state.data?.display_timezone || "Europe/Lisbon")
      );
    if (
      (f.data_type === "date" || /^\d{4}-\d{2}-\d{2}$/.test(String(v))) &&
      /^\d{4}-\d{2}-\d{2}/.test(String(v))
    )
      return String(v).slice(0, 10).split("-").reverse().join("-");
    if (f.id === "id") return String(v);
    if (typeof v === "boolean") return v ? "Sim" : "Não";
    if (typeof v === "number")
      return new Intl.NumberFormat("pt-PT", {
        maximumFractionDigits: 4,
      }).format(v);
    return String(v);
  }
  function config() {
    return {
      area: state.area,
      population: state.population,
      columns: state.columns,
      widths: state.widths,
      column_order: state.column_order,
      column_groups: state.column_groups,
      pinned: state.pinned,
      density: state.density,
      page_size: state.size,
      q: state.q,
      filters: state.filters,
      order: state.order,
      formula_ids: state.formula_ids || [],
      format_ids: state.format_ids || [],
    };
  }
  function params(extra = {}) {
    return {
      area: state.area,
      population: state.population,
      version: state.data?.version,
      page: state.page,
      page_size: state.size,
      q: state.q,
      filters: state.filters,
      order: state.order,
      ...extra,
    };
  }
  function drawer(title, content, wide = false) {
    state.evidence = null;
    $("drawer-title").textContent = title;
    $("drawer-body").replaceChildren(content || el("div"));
    $("drawer-error").textContent = "";
    $("drawer").classList.toggle("wide", wide);
    if (!$("drawer").open) $("drawer").showModal();
    return $("drawer-body");
  }
  function confirm(title, content) {
    $("confirm-title").textContent = title;
    $("confirm-body").replaceChildren(content);
    $("confirm-dialog").showModal();
    return new Promise((resolve) => {
      const finish = (x) => {
        $("confirm-dialog").close();
        resolve(x);
      };
      $("confirm-yes").onclick = () => finish(true);
      $("confirm-no").onclick = () => finish(false);
      $("confirm-dialog").oncancel = (e) => {
        e.preventDefault();
        finish(false);
      };
    });
  }
  function field(label, control) {
    const l = el("label", label);
    control.setAttribute("aria-label", label);
    l.append(control);
    return l;
  }
  function button(label, action, cls) {
    const b = el("button", label, cls);
    b.type = "button";
    b.onclick = safe(action);
    return b;
  }
  function input(value = "", type = "text") {
    const i = el("input");
    i.type = type;
    i.value = value ?? "";
    return i;
  }
  function select(options, value) {
    const s = el("select");
    for (const o of options) {
      const opt = el("option", typeof o === "object" ? o.label : o);
      opt.value = typeof o === "object" ? o.value : o;
      s.append(opt);
    }
    s.value = value ?? "";
    return s;
  }
  function smallTable(headers, rows, onclick) {
    const wrap = el("div", undefined, "table-scroll"),
      table = el("table", undefined, "mini-table"),
      head = el("thead"),
      tr = el("tr");
    headers.forEach((h) => {
      const th = el("th", h);
      th.scope = "col";
      tr.append(th);
    });
    head.append(tr);
    table.append(head);
    const body = el("tbody");
    rows.forEach((r, i) => {
      const t = el("tr");
      r.forEach((v) => t.append(el("td", v)));
      if (onclick) {
        t.tabIndex = 0;
        t.onclick = () => onclick(i);
        t.onkeydown = (e) => {
          if (e.key === "Enter") onclick(i);
        };
      }
      body.append(t);
    });
    table.append(body);
    wrap.append(table);
    return wrap;
  }
  async function catalog() {
    const d = await api("raw/colunas?area=" + state.area);
    state.fields = d.columns;
    state.cat = d.catalog;
    document.body.dataset.area = state.area;
    state.defaultColumns = d.default_columns;
    state.defaultWidths = d.default_widths;
    if (!state.columns.length && !state.view)
      state.widths = { ...d.default_widths };
    if (!state.columns.length)
      state.columns = d.default_columns || [
        "of",
        "ov",
        "component_ref",
        ...d.columns
          .filter((c) => !c.pinned && c.default_visible)
          .map((c) => c.id),
      ];
    if (!state.column_order.length) {
      let saved;
      try { saved = JSON.parse(localStorage.getItem('planning-layout-' + state.area)); } catch {}
      if (saved && !state.view) Object.assign(state, saved);
      normalizeColumns();
    }
    $("area").value = state.area;
    $("manual").href = "/planeamento/manual?area=" + state.area;
    $("pdf").href = "/planeamento/dossies?area=" + state.area;
  }
  async function load(fresh = false) {
    const serial=++state.loadSerial,area=state.area;
    const scroll = { x: $("grid").scrollLeft, y: $("grid").scrollTop };
    $("notice").textContent = "A consultar…";
    const d = await api(
      "raw/consultas",
      params(fresh ? { version: undefined } : {}),
    );
    if(serial!==state.loadSerial||area!==state.area)return state.data;
    state.data = d;
    state.fields = d.columns;
    render();
    $("grid").scrollLeft = scroll.x;
    $("grid").scrollTop = scroll.y;
    $("notice").textContent = d.aggregates_pending ? "Linhas atualizadas; agregados ainda em processamento." : d.source_refresh_pending ? "Atualização das restantes dependências em processamento." : "";
    const openEvidence=$("drawer").open?state.evidence:null;
    if(openEvidence&&$("drawer").open&&state.evidence===openEvidence){
      const scroll=$("drawer").scrollTop;
      let row=d.rows.find(r=>r.key===openEvidence.key);
      if(!row){const found=await api("raw/consultas",params({selected:[openEvidence.key],page:1,page_size:25}));row=found.rows[0];}
      if(serial!==state.loadSerial||state.evidence!==openEvidence)return state.data;
      if(row)await evidence(row,openEvidence.tab);
      else drawer("Peça atualizada").append(el("p","Esta peça já não pertence à população ou aos filtros atuais."));
      $("drawer").scrollTop=scroll;
    }
    return d;
  }
  const visible = () =>
    state.columns
      .map((k) => {
        const f = state.fields.find((f) => f.id === k);
        return f && { ...f, pinned: state.pinned.includes(k) };
      })
      .filter(Boolean);
  function width(f) {
    return (
      state.widths[f.id] ||
      (innerWidth < 720 && f.pinned
        ? { of: 90, ov: 87, component_ref: 116 }[f.id]
        : { of: 125, ov: 120, component_ref: 165 }[f.id] ||
          ([
            "customer",
            "designation",
            "notes",
            "description",
            "material_description",
          ].includes(f.id)
            ? 230
            : 160))
    );
  }
  function pinnedStyles() {
    let left = 0;
    const cols = visible();
    const grid = $("grid");
    const pinnedWidth = cols.filter(f => f.pinned).reduce((sum, f) => sum + width(f), 0);
    // Keep room to read scrolling columns without changing the saved pin choices.
    const pinOverflow = pinnedWidth > grid.clientWidth - Math.min(160, grid.clientWidth / 2);
    grid.dataset.pinOverflow = String(pinOverflow);
    grid.style.scrollPaddingLeft = (pinOverflow ? 0 : pinnedWidth) + "px";
    cols.forEach((f, i) => {
      if (f.pinned) {
        for (const c of document.querySelectorAll(`[data-col="${i}"]`)) {
          c.style.left = left + "px";
          c.style.width = width(f) + "px";
        }
        left += width(f);
      }
    });
  }
  function render() {
    persistLayout();
    requestAnimationFrame(syncHorizontal);
    const cols = visible(),
      thead = $("sheet").tHead,
      tbody = $("sheet").tBodies[0];
    thead.replaceChildren();
    tbody.replaceChildren();
    const h = el("tr");
    for (const [j, f] of cols.entries()) {
      const th = el("th");
      th.dataset.col = j;
      th.style.width = width(f) + "px";
      th.style.minWidth = width(f) + "px";
      th.style.maxWidth = width(f) + "px";
      if (f.pinned) th.classList.add("fixed");
      if (f.id === "component_ref") th.classList.add("pin-edge");
      const head = el("div", undefined, "head"),
        label = el("span", f.short_label || f.label, "label");
      label.title = f.label;
      const sort = state.order.find((x) => x.field === f.id);
      if (sort)
        label.append(
          document.createTextNode(sort.direction === "asc" ? " ↑" : " ↓"),
        );
      label.tabIndex = 0;
      label.onclick = safe((e) => sortBy(f, e.shiftKey));
      label.onkeydown = safe((e) => {
        if (e.key === "Enter") return sortBy(f, e.shiftKey);
      });
      head.append(label);
      const filter = button("⌄", () => filterPanel(f));
      filter.title = "Filtrar " + f.label;
      filter.setAttribute("aria-label", "Filtrar " + f.label);
      filter.classList.toggle(
        "active",
        state.filters.some((x) => x.field === f.id),
      );
      head.append(filter);
      th.append(head);
      const resize = el("span", undefined, "resize");
      resize.dataset.resizeColumn = f.id;
      resize.tabIndex = 0;
      resize.setAttribute("role", "separator");
      resize.setAttribute("aria-label", "Largura de " + f.label);
      resize.onpointerdown = (e) => {
        e.preventDefault();
        const x = e.clientX,
          w = width(f);
        resize.setPointerCapture(e.pointerId);
        resize.onpointermove = (ev) => {
          state.widths[f.id] = Math.max(70, Math.min(600, w + ev.clientX - x));
          for (const cell of document.querySelectorAll(`[data-col="${j}"]`)) {
            cell.style.width = state.widths[f.id] + "px";
            cell.style.minWidth = state.widths[f.id] + "px";
            cell.style.maxWidth = state.widths[f.id] + "px";
          }
          pinnedStyles();
        };
        resize.onpointerup = () => {
          resize.onpointermove = null;
          persistLayout();
        };
      };
      resize.onkeydown = (e) => {
        if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
          e.preventDefault();
          state.widths[f.id] = Math.max(
            70,
            Math.min(600, width(f) + (e.key === "ArrowLeft" ? -10 : 10)),
          );
          render();
          document.querySelector(`[data-resize-column="${CSS.escape(f.id)}"]`)?.focus({preventScroll:true});
        }
      };
      th.append(resize);
      h.append(th);
    }
    thead.append(h);
    $("sheet").style.width = cols.reduce((s, f) => s + width(f), 0) + "px";
    for (const [i, row] of state.data.rows.entries()) {
      const tr = el("tr");
      for (const [j, f] of cols.entries()) {
        const td = el("td"),
          v = row.values[f.id];
        td.dataset.row = i;
        td.dataset.col = j;
        td.tabIndex = 0;
        td.title = f.label + ": " + fmt(v, f);
        if (
          state.area === "cantoneiras" &&
          ["operation", "operation_detail"].includes(f.id)
        ) {
          const option = [
            ...(state.cat.operations || []),
            ...(state.cat.additional_operations || []),
          ].find((x) => String(x.value) === String(v));
          if (option) td.title = option.label;
        }
        td.style.width = width(f) + "px";
        td.style.maxWidth = width(f) + "px";
        if (f.pinned) td.classList.add("fixed");
        if (f.id === "component_ref") td.classList.add("pin-edge");
        if (f.data_type === "number") td.classList.add("numeric");
        if (v == null || v === "") td.classList.add("unknown");
        if (f.editable) td.classList.add("editable");
        for (const rule of row.formats || [])
          if (!state.format_ids?.length || state.format_ids.includes(rule.id))
            td.classList.add("condition-" + rule.style);
        if (f.id === "of") {
          const box = el("div", undefined, "of-cell"),
            check = el("input");
          check.type = "checkbox";
          check.checked = state.selected.has(row.key);
          check.setAttribute("aria-label", "Selecionar " + fmt(v));
          check.onchange = () => {
            check.checked
              ? state.selected.add(row.key)
              : state.selected.delete(row.key);
            selectionLabel();
          };
          box.append(check, el("span", fmt(v, f)));
          td.append(box);
        } else td.textContent = fmt(v, f);
        if (f.id === "component_ref")
          td.append(button("⋯", evidence.bind(null, row), "row-action"));
        td.onpointerdown = (e) => {
          if (e.target.closest("button,input")) return;
          state.cells =
            e.shiftKey && state.cells
              ? { ...state.cells, end: [i, j] }
              : { start: [i, j], end: [i, j] };
          highlight();
        };
        td.ondblclick = safe(() =>
          f.editable ? editCell(row, f) : evidence(row),
        );
        td.onkeydown = safe((e) => cellKey(e, i, j, row, f));
        tr.append(td);
      }
      tbody.append(tr);
    }
    $("count").textContent =
      state.data.total.toLocaleString("pt-PT") + " linhas";
    $("page-number").textContent =
      state.page +
      " / " +
      Math.max(1, Math.ceil(state.data.total / state.size));
    $("prev").disabled = state.page <= 1;
    $("next").disabled = state.page * state.size >= state.data.total;
    $("grid").classList.toggle("comfortable", state.density === "comfortable");
    selectionLabel();
    pinnedStyles();
    highlight();
    chips();
  }
  function selectionLabel() {
    $("selection").textContent = state.selected.size
      ? state.selected.size + " selecionadas"
      : "";
    const row =
      state.selected.size === 1
        ? state.data?.rows.find((r) => state.selected.has(r.key))
        : null;
    const context =
      "area=" +
      state.area +
      (row?.values.of ? "&of=" + encodeURIComponent(row.values.of) : "");
    $("manual").href = "/planeamento/manual?" + context;
    $("pdf").href = "/planeamento/dossies?" + context;
  }
  function highlight() {
    const s = state.cells;
    for (const td of $("sheet").querySelectorAll("tbody td")) {
      const i = +td.dataset.row,
        j = +td.dataset.col;
      td.classList.toggle(
        "selected",
        !!s &&
          i >= Math.min(s.start[0], s.end[0]) &&
          i <= Math.max(s.start[0], s.end[0]) &&
          j >= Math.min(s.start[1], s.end[1]) &&
          j <= Math.max(s.start[1], s.end[1]),
      );
    }
  }
  async function cellKey(e, i, j, row, f) {
    if (e.key === "Enter") {
      e.preventDefault();
      return f.editable ? editCell(row, f) : evidence(row);
    }
    const delta = {
      ArrowDown: [1, 0],
      ArrowUp: [-1, 0],
      ArrowRight: [0, 1],
      ArrowLeft: [0, -1],
      Tab: [0, e.shiftKey ? -1 : 1],
    }[e.key];
    if (delta) {
      e.preventDefault();
      const r = Math.max(0, Math.min(state.data.rows.length - 1, i + delta[0])),
        c = Math.max(0, Math.min(visible().length - 1, j + delta[1]));
      if (e.shiftKey && e.key !== "Tab" && state.cells)
        state.cells.end = [r, c];
      else state.cells = { start: [r, c], end: [r, c] };
      $("sheet")
        .querySelector(`tbody td[data-row="${r}"][data-col="${c}"]`)
        ?.focus();
      highlight();
    }
  }
  async function sortBy(f, multi) {
    const existing = state.order.find((x) => x.field === f.id);
    if (!multi) state.order = [];
    else state.order = state.order.filter((x) => x.field !== f.id);
    state.order.push({
      field: f.id,
      direction: existing?.direction === "asc" ? "desc" : "asc",
    });
    state.page = 1;
    await load();
  }
  function chips() {
    $("filter-chips").replaceChildren();
    for (const [i, f] of state.filters.entries())
      $("filter-chips").append(
        button(
          (state.fields.find((x) => x.id === f.field)?.label || f.field) +
            " · " +
            (f.values?.join(", ") ||
              f.value ||
              [f.min, f.max].filter(Boolean).join(" – ") ||
              f.op) +
            " ×",
          async () => {
            state.filters.splice(i, 1);
            state.page = 1;
            await load();
          },
          "chip",
        ),
      );
    $("clear-filters").hidden = !state.filters.length && !state.q;
  }
  async function filterPanel(f) {
    const box = drawer("Filtrar · " + f.label),
      ops = [
        { value: "in", label: "Selecionar valores" },
        { value: "empty", label: "Vazios / por confirmar" },
        { value: "known", label: "Com valor" },
        ...(f.data_type === "number" || f.data_type === "date"
          ? [
              { value: "between", label: "Entre" },
              { value: "gte", label: "Maior ou igual" },
              { value: "lte", label: "Menor ou igual" },
            ]
          : [
              { value: "contains", label: "Contém" },
              { value: "starts", label: "Começa por" },
            ]),
      ],
      prior = state.filters.find((x) => x.field === f.id),
      op = select(ops, prior?.op || "in"),
      controls = el("div"),
      values = new Set(prior?.values || []);
    box.append(field("Condição", op), controls);
    let value, min, max;
    const show = safe(async () => {
      controls.replaceChildren();
      if (op.value === "in") {
        const search = input(),
          list = el("div", undefined, "facet-list");
        controls.append(
          field("Procurar valores em todas as páginas", search),
          list,
        );
        let page = 1;
        const fetchOptions = async () => {
          const r = await api(
            "raw/opcoes",
            params({ field: f.id, search: search.value, page }),
          );
          list.replaceChildren();
          for (const x of r.options) {
            const check = el("input");
            check.type = "checkbox";
            check.checked = values.has(String(x.value));
            check.onchange = () =>
              check.checked
                ? values.add(String(x.value))
                : values.delete(String(x.value));
            const label = field(fmt(x.value, f) + " (" + x.n + ")", check);
            if (x.value === null) {
              check.disabled = true;
              label.title = "Usa Vazios / por confirmar para estes valores.";
            }
            list.append(label);
          }
          list.append(el("p", r.total + " valores distintos", "muted"));
          if (page > 1)
            list.append(
              button("Anterior", () => {
                page--;
                return fetchOptions();
              }),
            );
          if (page * 100 < r.total)
            list.append(
              button("Mais valores", () => {
                page++;
                return fetchOptions();
              }),
            );
        };
        search.oninput = safe(() => {
          page = 1;
          return fetchOptions();
        });
        await fetchOptions();
      } else if (op.value === "between") {
        min = input(prior?.min, f.data_type === "date" ? "date" : "text");
        max = input(prior?.max, f.data_type === "date" ? "date" : "text");
        controls.append(field("De", min), field("Até", max));
      } else if (!["empty", "known"].includes(op.value)) {
        value = input(prior?.value, f.data_type === "date" ? "date" : "text");
        controls.append(field("Valor", value));
      }
    });
    op.onchange = show;
    await show();
    const actions = el("div", undefined, "actions");
    actions.append(
      button(
        "Aplicar",
        async () => {
          const filter = { field: f.id, op: op.value };
          if (op.value === "in") filter.values = [...values];
          else if (op.value === "between") {
            filter.min = min.value;
            filter.max = max.value;
          } else if (value) filter.value = value.value;
          state.filters = state.filters.filter((x) => x.field !== f.id);
          state.filters.push(filter);
          state.page = 1;
          await load();
          $("drawer").close();
        },
        "primary",
      ),
      button("Limpar este filtro", async () => {
        state.filters = state.filters.filter((x) => x.field !== f.id);
        state.page = 1;
        await load();
        $("drawer").close();
      }),
    );
    box.append(actions);
  }
  function columnPanel() {
    const box = drawer("Colunas"),
      search = input(),
      groups = el("div");
    box.append(
      field("Procurar uma coluna", search),
      button(
        "Repor vista de " +
          (state.area === "cantoneiras" ? "Cantoneiras" : "Perfis"),
        () => {
          state.columns = [...state.defaultColumns];
          state.widths = { ...state.defaultWidths };
          state.column_order = [...state.defaultColumns, ...state.fields.map(f => f.id)];
          state.column_groups = {};
          state.pinned = ['of', 'ov', 'component_ref'];
          normalizeColumns();
          state.view = null;
          $("views").value = "";
          paint();
          render();
        },
      ),
      groups,
    );
    let dragged = null;
    function paint(openGroup) {
      const focus = document.activeElement?.dataset.columnControl;
      const scroll = $('drawer').scrollTop;
      const innerScroll = box.scrollTop;
      for (const d of groups.querySelectorAll('details')) state.columnOpen[d.dataset.group] = d.open;
      if (typeof openGroup === 'string') state.columnOpen[openGroup] = true;
      groups.replaceChildren();
      const labels = {
        identity: "Identificação",
        quantity: "Quantidades",
        technical: "Características",
        work: "Preparação",
        material: "Material",
        production: "Produção OCR e acompanhamento",
        calculated: "Colunas calculadas",
      };
      for (const [g, label] of Object.entries(labels)) {
        const fields = state.column_order.map(id => state.fields.find(f => f.id === id)).filter(Boolean).filter(
          (f) =>
            (state.column_groups[f.id] || f.group) === g &&
            f.label
              .toLocaleLowerCase("pt-PT")
              .includes(search.value.toLocaleLowerCase("pt-PT")),
        );
        const details = el("details", undefined, "columns-group");
        details.dataset.group = g;
        details.open = !!search.value || (state.columnOpen[g] ?? false);
        details.ondragover = e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; };
        details.ondrop = e => {
          e.preventDefault();
          if (!dragged) return;
          const target = e.target.closest('[data-column-id]')?.dataset.columnId;
          move(dragged, target, g, target && e.clientY > e.target.closest('[data-column-id]').getBoundingClientRect().top + e.target.closest('[data-column-id]').getBoundingClientRect().height / 2);
          dragged = null;
        };
        const summary = el("summary"),
          all = el("input");
        all.type = "checkbox";
        const chosen = fields.filter((f) =>
          state.columns.includes(f.id),
        ).length;
        all.checked = chosen === fields.length;
        all.indeterminate = chosen > 0 && chosen < fields.length;
        all.onclick = (e) => e.stopPropagation();
        all.onchange = () => {
          for (const f of fields) {
            state.columns = state.columns.filter((k) => k !== f.id);
            if (all.checked) state.columns.push(f.id);
          }
          normalizeColumns();
          render();
          paint();
        };
        summary.append(all, el("span", label));
        details.append(summary);
        for (const f of fields) {
          const row = el("div", undefined, "column-row"),
            check = el("input");
          row.dataset.columnId = f.id;
          row.draggable = true;
          row.ondragstart = e => { dragged = f.id; e.dataTransfer.setData('text/plain', f.id); e.dataTransfer.effectAllowed = 'move'; };
          row.ondragend = () => { dragged = null; };
          check.type = "checkbox";
          check.checked = state.columns.includes(f.id);
          check.dataset.columnControl = f.id + ':visible';
          check.onchange = () => {
            state.columns = state.columns.filter((k) => k !== f.id);
            if (check.checked) state.columns.push(f.id);
            normalizeColumns();
            render();
            all.indeterminate = true;
          };
          row.append(field(f.label, check));
          const pin = button(state.pinned.includes(f.id) ? 'Desafixar' : 'Fixar', () => {
            state.pinned = state.pinned.filter(k => k !== f.id).concat(state.pinned.includes(f.id) ? [] : [f.id]);
            render(); paint();
          });
          pin.dataset.columnControl = f.id + ':pin';
          pin.setAttribute('aria-label', (state.pinned.includes(f.id) ? 'Desafixar ' : 'Fixar ') + f.label);
          row.append(pin);
          const groupSelect = el('select');
          groupSelect.setAttribute('aria-label', 'Grupo de ' + f.label);
          groupSelect.dataset.columnControl = f.id + ':group';
          for (const [id, name] of Object.entries(labels)) {
            const option = el('option', 'Mover para: ' + name); option.value = id; groupSelect.append(option);
          }
          groupSelect.value = g;
          groupSelect.onchange = () => move(f.id, null, groupSelect.value);
          row.append(groupSelect);
          {
            for (const [text, delta] of [
              ["↑", -1],
              ["↓", 1],
            ])
              {
                const arrow = button(text, () => {
                  const i = fields.findIndex(x => x.id === f.id), j = i + delta;
                  if (j < 0 || j >= fields.length) return;
                  move(f.id, fields[j].id, g, delta > 0);
                });
                arrow.dataset.columnControl = f.id + ':' + delta;
                arrow.title = (delta < 0 ? 'Subir ' : 'Descer ') + f.label;
                row.append(arrow);
              }
          }
          details.append(row);
        }
        groups.append(details);
      }
      if (focus) [...groups.querySelectorAll('[data-column-control]')].find(n => n.dataset.columnControl === focus)?.focus({preventScroll:true});
      $('drawer').scrollTop = scroll;
      box.scrollTop = innerScroll;
    }
    function move(id, target, group, after = false) {
      if (id === target) return;
      const order = state.column_order.filter(k => k !== id);
      let index = target ? order.indexOf(target) : -1;
      if (index < 0) {
        index = order.reduce((last,k,i) => (state.column_groups[k] || state.fields.find(f => f.id === k)?.group) === group ? i+1 : last, order.length);
      } else if (after) index++;
      order.splice(index,0,id);
      state.column_order = order;
      state.column_groups[id] = group;
      state.columnOpen[group] = true;
      normalizeColumns(); render(); paint(group);
    }
    search.oninput = paint;
    paint();
    box.append(
      button(
        "Aplicar e fechar",
        () => {
          $("drawer").close();
          render();
        },
        "primary",
      ),
    );
  }
  function normalizeColumns() {
    const known = new Set(state.fields.map(f => f.id));
    state.column_order = [...new Set([...state.column_order, ...state.columns, ...known])].filter(k => known.has(k));
    const chosen = new Set(state.columns);
    state.columns = state.column_order.filter(k => chosen.has(k));
    state.pinned = [...new Set(state.pinned)].filter(k => known.has(k));
  }
  function persistLayout() {
    try {
      localStorage.setItem('planning-layout-' + state.area, JSON.stringify({columns:state.columns,
        widths:state.widths,column_order:state.column_order,column_groups:state.column_groups,pinned:state.pinned}));
    } catch { /* The shared saved view remains available when storage is disabled. */ }
  }
  function syncHorizontal() {
    const grid = $('grid'), range = $('horizontal-position');
    const max = Math.max(0, grid.scrollWidth - grid.clientWidth);
    range.max = max; range.value = grid.scrollLeft;
    range.disabled = max === 0;
    range.setAttribute('aria-valuetext', max ? Math.round(100*grid.scrollLeft/max) + '% da largura' : 'Todas as colunas visíveis');
    $('scroll-first').disabled = grid.scrollLeft <= 0;
    $('scroll-last').disabled = grid.scrollLeft >= max;
  }
  function selectOptions(f, row) {
    const c = state.cat,
      v = row.values;
    let opts =
      f.id === "machine"
        ? c.machines
        : f.id === "team"
          ? c.teams
          : f.id === "material_type"
            ? c.material_types
            : f.id === "operation"
              ? c.operations
              : f.id === "operation_detail"
                ? c.additional_operations
                : f.id === "profile"
                  ? c.profiles?.[
                      String(v.material_type || "")
                        .trim()
                        .toLocaleLowerCase("pt-PT")
                        .replace(/\s+/g, " ")
                    ] || []
                  : [];
    return (opts || []).map((o) =>
      typeof o === "object"
        ? { value: o.value, label: o.label || o.value }
        : { value: o, label: o },
    );
  }
  async function editCell(row, f) {
    if (row.values.planning_active === false) return evidence(row);
    state.editing = { row, f };
    $("edit-title").textContent = f.label + " · " + row.values.of;
    $("edit-error").textContent = "";
    const box = $("edit-control");
    box.replaceChildren();
    const val = row.values[f.id];
    let control;
    if (f.type === "checkbox") {
      control = el("input");
      control.type = "checkbox";
      control.checked = val === "X" || val === true;
    } else if (f.type === "tristate") {
      control = select(
        [
          { value: "", label: "Por confirmar" },
          { value: "true", label: "Sim" },
          { value: "false", label: "Não" },
        ],
        val == null ? "" : String(val),
      );
    } else if (f.type === "select") {
      const options = selectOptions(f, row);
      if (f.id === "profile" && !options.length) control = input(val);
      else {
        control = select(
          [
            {
              value: "",
              label: f.id === "machine" ? "Por definir" : "Selecionar",
            },
            ...options,
          ],
          val,
        );
        if (val && !options.some((o) => o.value === val)) {
          const opt = el("option", val + " · valor histórico a rever");
          opt.value = val;
          control.append(opt);
          control.value = val;
        }
        if (f.id === "profile") {
          const opt = el("option", "Outra designação");
          opt.value = "__custom";
          control.append(opt);
        }
      }
    } else control = input(val, f.type === "date" ? "date" : "text");
    control.id = "edit-value";
    box.append(field(f.label, control));
    const extra = input("");
    extra.id = "edit-extra";
    extra.hidden = true;
    box.append(extra);
    if (f.id === "profile")
      control.onchange = () => {
        extra.hidden = control.value !== "__custom";
      };
    if (f.unit) box.append(el("p", "Unidade: " + f.unit, "muted"));
    if (f.id === "picking_week") {
      const year = input(row.values.picking_year ?? "");
      year.id = "edit-year";
      box.append(field("Ano ISO do picking (vazio: desconhecido)", year));
    }
    if (f.id === "material_type") {
      const dependent = el("div");
      box.append(dependent);
      control.onchange = () => {
        dependent.replaceChildren();
        const options = selectOptions(
            { id: "profile" },
            { values: { ...row.values, material_type: control.value } },
          ),
          level2 = options.length
            ? select(
                [{ value: "", label: "Selecionar perfil" }, ...options],
                "",
              )
            : input("");
        level2.id = "edit-family-profile";
        dependent.append(
          field("Tipo de perfil nível 2", level2),
          el(
            "p",
            options.length
              ? "Escolhe o perfil da nova família."
              : "Preenchimento manual — esta família não tem catálogo de nível 2.",
            "muted",
          ),
        );
      };
      box.append(
        el(
          "p",
          "Alterar a família exige confirmar o nível 2. Os restantes dados técnicos são conservados para revisão.",
          "muted",
        ),
      );
    }
    $("editor").showModal();
    control.focus();
  }
  async function saveCell(e) {
    e.preventDefault();
    const { row, f } = state.editing,
      c = $("edit-value");
    let v =
      f.type === "checkbox"
        ? c.checked
          ? "X"
          : "-"
        : f.type === "tristate"
          ? c.value === ""
            ? null
            : c.value === "true"
          : c.value;
    const values = { [f.id]: v };
    if (f.id === "profile" && v === "__custom") {
      values.profile = $("edit-extra").value;
      values.special_profile = $("edit-extra").value;
      values.custom_profile = true;
    }
    if (f.id === "picking_week")
      values.picking_year = $("edit-year").value || null;
    if (f.id === "material_type" && $("edit-family-profile")) {
      values.profile = $("edit-family-profile").value || null;
      values.custom_profile = false;
      values.special_profile = null;
    }
    const result = await api(
      "raw/lotes",
      request({
        area: state.area,
      population: state.population,
        version: state.data.version,
        edits: [{ key: row.key, expected_revision: row.revision, values }],
      }),
    );
    $("editor").close();
    state.editing = null;
    $("notice").textContent = "Rascunho guardado. A atualizar a tabela…";
    await waitUpdated(result);
    $("notice").textContent = state.data.aggregates_pending ? "Rascunho guardado e linha atualizada. Agregados em processamento." : "Rascunho guardado.";
    return result;
  }
  async function waitUpdated(result) {
    if(result?.publication?.areas?.[state.area])return load(true);
    const before = state.data.version;
    for (let i = 0; i < 35; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const x = await api(
        "raw/workspace/atualizacao?area=" + state.area + "&version=" + before,
      );
      if (x.available) return load(true);
    }
    $("notice").textContent =
      "Guardado. A nova versão está a ser preparada; podes continuar a consultar.";
  }
  async function evidence(row, tab = 0) {
      const box = drawer(
        "Peça · " + (row.values.component_ref || "Por identificar"),
        undefined,
        true,
      ),
      v = row.values;
    const selected={key:row.key,tab};state.evidence=selected;
    box.append(el("p", [v.of, v.ov, v.customer].filter(Boolean).join(" · ")));
    if (row.population) {
      box.append(el("p", row.population.active
        ? "Planeamento ativo · sem fecho declarado no CPIS ou na macro."
        : "Histórico · fechado em " + (row.population.closed_sources || []).join(" e ") + "."));
      for (const state of row.population.unknown_states || [])
        box.append(el("p", "Estado desconhecido em " + state.source + ": " + state.value + ". Não interpretado como fecho.", "pill"));
    }
    const tabs = el("div", undefined, "tabs"),
      content = el("div");
    box.append(tabs, content);
    tabs.addEventListener('click',event=>{
      const target=event.target.closest('button'),index=[...tabs.children].indexOf(target);
      if(index>=0&&state.evidence===selected)selected.tab=index;
    });
    function showValues() {
      content.replaceChildren(
        smallTable(
          ["Campo", "Valor atual", "Valor importado"],
          state.fields.map((f) => [
            f.label,
            fmt(v[f.id], f),
            fmt(state.area === "cantoneiras" && f.id === "weight_unit" && Object.hasOwn(row.raw || {}, "Peso un. Kg")
              ? row.raw["Peso un. Kg"] : row.original?.[f.id], f),
          ]),
        ),
      );
      for (const warning of row.warnings || [])
        content.prepend(el("p", warning, "pill"));
    }
    function calculationSource(source) {
      if (!source) return "—";
      if (typeof source === "string") return source;
      if (Array.isArray(source)) return source.map(calculationSource).join(" · ") || "—";
      if (source.sources) return calculationSource(source.sources);
      const cell = source.cell || (source.sheet === "Tabela pesos" && source.row ? "C" + source.row : null);
      return [
        source.source || source.rule,
        source.sheet ? source.sheet + (cell ? "!" + cell : "") : cell,
        source.designation,
        source.kg_m != null ? fmt(source.kg_m) + " kg/m" : null,
        source.area != null ? fmt(source.area) + " mm²" : null,
      ].filter(Boolean).join(" · ") || "—";
    }
    function calculationInput(value, preserveKeys = false) {
      if (Array.isArray(value)) return value.map(item => calculationInput(item, preserveKeys)).join("; ") || "—";
      if (value && typeof value === "object")
        return Object.entries(value).map(([key, item]) => (preserveKeys ? key : key === "quantity" ? "Quantidade (un.)" : calculationInputLabel(key)) + "=" + calculationInput(item, preserveKeys)).join("; ") || "—";
      return fmt(value);
    }
    function calculationInputLabel(name) {
      return ({
        deadline: "Prazo considerado", deadline_source: "Origem da data",
        local_date: "Data local", operation_balances: "Saldos por operação",
        operations_known: "Operações confirmadas", current_description: "Descrição atual",
        original_description: "Descrição original", technical_description: "Descrição técnica",
        quantity: "Saldo da operação (un.)", rate: "Taxa aplicada", method: "Método",
        volume: "Volume pendente", volume_unit: "Unidade do volume",
        setup_minutes: "Preparação aplicada (min)", excel_factor: "Fator Excel",
        reference_rate_value: "Taxa Excel antes do fator",
        Q: "Quantidade necessária (un.)", L: "Comprimento da peça (mm)",
        A: "Área unitária (mm²)", S: "Comprimento do perfil inteiro (mm)",
        B: "Produção de abocardar (un.)", saldo: "Saldo (un.)", produced: "Produção selecionada (un.)",
        operation: "Operação", operation_detail: "Operação adicional",
        ocr_total: "Total OCR da operação (un.)", excel_total: "Acumulado Excel (un.)",
        local_initial: "Condição inicial local", compatible: "Identidade compatível",
        ocr_events: "Eventos OCR considerados", coverage_reasons: "Limitações da cobertura OCR",
        density_kg_m3: "Densidade (kg/m³)", kg_m: "Peso por metro (kg/m)",
        manual_stock_length_mm: "Comprimento substituído (mm)",
        source: "Origem", instance_id: "Instância", sheet_uid: "Folha", record_id: "Registo",
        row_index: "Linha", child_key: "Peça filha", validated: "Validado",
      })[name] || state.fields.find((field) => field.id === name)?.label || name;
    }
    function calculationFieldLabel(name) {
      return state.fields.find((field) => field.id === name)?.label || ({
        section_unit: "Área unitária (mm²)", section_total: "Área total (mm²)",
        section_pending: "Área pendente (mm²)", bars: "Perfis inteiros necessários (un.)",
        expected_year: "Ano ISO previsto",
      })[name] || name;
    }
    function calculationInputs(rule) {
      return Object.entries(rule.inputs || {}).map(([name, value]) => {
        let shown;
        if (name === "rate" && value && typeof value === "object") {
          const unit = ({area_hour:"mm²/h",metres_hour:"m/h",units_hour:"un./h",minutes_unit:"min/un.",fixed_minutes:"min"})[value.method] || value.unit || "";
          shown = [fmt(value.value) + (unit ? " " + unit : ""),
            value.source ? calculationSource(value.source) : null,
            value.valid_from ? "Vigência " + fmt(value.valid_from) + " / " + (value.valid_until ? fmt(value.valid_until) : "sem fim definido") : null,
          ].filter(Boolean).join("; ");
        } else if (name === "method") {
          shown = ({area_hour:"Área por hora",metres_hour:"Metros por hora",units_hour:"Unidades por hora",minutes_unit:"Minutos por unidade",fixed_minutes:"Minutos fixos"})[value] || calculationInput(value);
        } else {
          shown = calculationInput(name === "deadline_source" ? ({expected_date:"Data prevista",delivery_date:"Data de entrega"})[value] || value : value, name === "operation_balances");
        }
        return calculationInputLabel(name) + "=" + shown;
      }).join(" · ") + (rule.unit ? " · " + rule.unit : "");
    }
    tabs.append(
      button("Dados e origem", showValues),
      button("Cálculos", () => {
        content.replaceChildren(
          smallTable(
            ["Campo", "Valor atual", "Fórmula", "Entradas / unidade", "Origem", "Motivo de indisponibilidade"],
            Object.entries(row.calculation?.rules || {}).map(([k, r]) => [
              calculationFieldLabel(k),
              fmt(v[k], state.fields.find((f) => f.id === k)),
              r.formula || r.error,
              calculationInputs(r),
              calculationSource(r.source),
              r.reason || "—",
            ]),
          ),
        );
        content.append(
          el(
            "p",
            "Valores importados mantêm a sua origem. Estimativas não confirmam stock nem incluem perdas de corte.",
            "muted",
          ),
        );
      }),
      button("Taxas e horas", () => {
        content.replaceChildren();
        for(const estimate of row.calculation?.operation_estimates || []){
          content.append(el("h3",estimate.operation+" · "+(estimate.machine||"Máquina por definir")));
          content.append(smallTable(["Saldo","Horas previstas","Origem","Taxa","Unidade","Motivo"],[[fmt(estimate.quantity),fmt(estimate.hours),estimate.source,fmt(estimate.rate?.value),({area_hour:"mm²/h",metres_hour:"m/h",units_hour:"un./h",minutes_unit:"min/un.",fixed_minutes:"min"})[estimate.rate?.method],estimate.reason]]));
          if(estimate.calculation) content.append(smallTable(["Fórmula","Entradas / unidade"],[[estimate.calculation.formula,calculationInputs(estimate.calculation)]]));
          if(estimate.history_hash) content.append(button("Histórico usado / exclusões",async()=>{
            const h=await api("raw/produtividade/"+estimate.history_hash);
            content.append(el("p",`${h.window.start} / ${h.window.end} · ${h.sheet_count} folhas · ${h.event_count} eventos · ${fmt(h.volume)} / ${fmt(h.hours)} h = ${fmt(h.value)} ${h.unit}`));
            content.append(smallTable(["Coorte","Eventos","Volume","Horas","Origem"],h.cohorts.map(c=>[c.key,c.events.join(", "),fmt(c.volume),fmt(c.hours),c.hours_origin])));
            content.append(smallTable(["Excluída","Motivo"],h.excluded.map(c=>[c.key,c.reasons.join("; ")])));
          }));
        }
      }),
      button("Produção por operação", () => {
        content.replaceChildren();
        for (const op of row.operations || []) {
          content.append(
            el("h3", op.label || op.operation),
            smallTable(
              ["Acumulado macro", "Saldo macro", "OCR validado"],
              [
                [
                  fmt(op.macro_quantity),
                  fmt(op.macro_remaining),
                  fmt(op.ocr_quantity),
                ],
              ],
            ),
          );
          content.append(
            smallTable(
              ["Folha / linha", "Quantidade", "Validação"],
              (op.ocr_records || []).map((r) => [
                r.sheet_uid + " / " + r.row_index,
                fmt(r.quantity),
                r.validated_at || "—",
              ]),
            ),
          );
        }
        for (const [key, records] of Object.entries(row.ocr_evidence || {})) {
          if (!records.length) continue;
          content.append(
            el("h3", key),
            smallTable(
              ["Registo", "Quantidade", "Operação"],
              records.map((r) => [
                r.record_id || r.id,
                fmt(r.quantity),
                r.operation || key,
              ]),
            ),
          );
        }
        content.append(
          el(
            "p",
            "A produção validada não é somada aos acumulados da macro.",
            "muted",
          ),
        );
        content.append(
          button("Resolver associações / confirmar quantidade", () =>
            RawPanels.associations(row),
          ),
        );
      }),
      button("Origem e alterações", async () => {
        if (!row.need_id) {
          content.replaceChildren(
            el("p", "Linha importada da macro. Ainda não tem decisões locais."),
          );
          return;
        }
        const data = await api("necessidades/" + row.need_id + "/historico");
        content.replaceChildren();
        const fields = data.fields || [],
          pick = select(
            [
              { value: "", label: "Todos os campos" },
              ...fields.map((f, i) => ({
                value: String(i),
                label:
                  (state.fields.find((x) => x.id === f.field)?.label ||
                    f.field) +
                  (f.scope === "piece" ? " · peça" : " · operação"),
              })),
            ],
            "",
          ),
          history = el("div");
        content.append(field("Consultar campo", pick), history);
        function paintHistory() {
          history.replaceChildren();
          const chosen = pick.value === "" ? null : fields[Number(pick.value)];
          if (chosen) {
            const origin = chosen.source || {};
            history.append(
              smallTable(
                [
                  "Valor utilizado",
                  "Sugestão atual",
                  "Origem",
                  "Versão",
                  "Decisão / autor",
                ],
                [
                  [
                    fmt(chosen.value),
                    fmt(chosen.suggestion),
                    {
                      pdf: "PDF",
                      plan_line: "Macro importada",
                      manual: "Introdução manual",
                      system: "Cálculo do sistema",
                    }[origin.kind] || "Origem detalhada não disponível",
                    origin.version || "—",
                    chosen.human_decision
                      ? chosen.actor || "Utilizador não identificado"
                      : "Sugestão / sistema",
                  ],
                ],
              ),
            );
          }
          for (const event of data.events || []) {
            const changes = (event.detail?.changes || []).filter(
              (x) =>
                !chosen ||
                (x.field === chosen.field &&
                  (!x.scope || x.scope === chosen.scope)),
            );
            if (chosen && !changes.length) continue;
            history.append(
              el(
                "h3",
                ({
                  preparation_saved: "Ficha guardada",
                  source_updated: "Sugestão atualizada",
                  production_association: "Associação de produção",
                  balance_conference: "Quantidade em falta confirmada",
                  preparation_quantity_calculated: "Quantidade calculada",
                  material_request_forecast: "Previsão de requisição calculada",
                }[event.action] || "Registo de alteração") +
                  " · " +
                  event.actor,
              ),
              el("p", fmt(event.created_at), "muted"),
              smallTable(
                ["Campo", "Antes", "Depois"],
                changes.map((x) => [
                  state.fields.find((f) => f.id === x.field)?.label || x.field,
                  fmt(x.before),
                  fmt(x.after),
                ]),
              ),
            );
          }
        }
        pick.onchange = paintHistory;
        paintHistory();
      }),
    );
    const pdfs = (row.sources || []).filter((source) => source.kind === "pdf");
    tabs.append(
      button("Desenho", () => {
        content.replaceChildren();
        if (!pdfs.length) {
          content.append(el("p", "Sem PDF associado a esta peça."));
          return;
        }
        const document = select(
            pdfs.map((source, i) => ({
              value: String(i),
              label:
                "Dossiê PDF " +
                (i + 1) +
                " · revisão " +
                (source.payload?.version ||
                  source.source_version ||
                  "guardada"),
            })),
            "0",
          ),
          frame = el("iframe");
        frame.title = "Desenho original da peça";
        frame.style.cssText = "width:100%;height:65vh;border:1px solid #dce4e7";
        function open() {
          const source = pdfs[Number(document.value)],
            id = source.payload?.document_id || source.source_id.split("/")[0];
          frame.src =
            "/planeamento/api/dossies/" + encodeURIComponent(id) + "/pdf";
        }
        document.onchange = open;
        content.append(field("Documento de origem", document), frame);
        open();
      }),
    );
    showValues();
    if(tab>0)tabs.children[tab]?.click();
    const link = el("a", "Abrir formulário");
    link.href =
      "/planeamento/manual?area=" +
      state.area +
      (row.need_id
        ? "&necessidade=" + row.need_id
        : "&of=" +
          encodeURIComponent(v.of || "") +
          "&linha=" +
          encodeURIComponent(row.plan_key || ""));
    link.target = "_blank";
    link.rel = "noopener";
    box.append(link);
  }
  async function paste(e) {
    if (!state.cells || e.target.closest("input,textarea,dialog")) return;
    const text = e.clipboardData?.getData("text/plain");
    if (!text) return;
    e.preventDefault();
    const rows = text
        .replace(/\r/g, "")
        .replace(/\n$/, "")
        .split("\n")
        .map((x) => x.split("\t")),
      cols = visible(),
      [r0, c0] = state.cells.start,
      edits = [];
    if (rows.length > 500) throw Error("Cola até 500 linhas por lote.");
    for (let i = 0; i < rows.length; i++) {
      const row = state.data.rows[r0 + i];
      if (!row)
        throw Error(
          "A colagem ultrapassa as linhas desta página. Aumenta o tamanho da página.",
        );
      if (row.values.planning_active === false)
        throw Error("A colagem inclui uma peça fechada. Consulta-a no histórico.");
      const values = {};
      for (let j = 0; j < rows[i].length; j++) {
        const f = cols[c0 + j];
        if (!f?.editable)
          throw Error(
            "A colagem inclui uma coluna de consulta. Seleciona apenas campos locais editáveis.",
          );
        let val = rows[i][j];
        if (f.type === "checkbox") {
          if (
            !["X", "-", "sim", "não", "nao", "true", "false"].includes(
              val.toLowerCase(),
            ) &&
            !["X", "-"].includes(val)
          )
            throw Error("Abocardar aceita X ou -.");
          val = ["x", "sim", "true"].includes(val.toLowerCase()) ? "X" : "-";
        }
        if (f.type === "tristate")
          val =
            val === ""
              ? null
              : ["sim", "true"].includes(val.toLowerCase())
                ? true
                : ["não", "nao", "false"].includes(val.toLowerCase())
                  ? false
                  : val;
        if (f.type === "date" && /^\d{2}-\d{2}-\d{4}$/.test(val))
          val = val.split("-").reverse().join("-");
        values[f.id] = val;
      }
      edits.push({ key: row.key, expected_revision: row.revision, values });
    }
    if (
      await confirm(
        "Guardar " + edits.length + " linhas?",
        smallTable(
          ["OF", "Referência", "Alterações"],
          edits.map((x, i) => [
            state.data.rows[r0 + i].values.of,
            state.data.rows[r0 + i].values.component_ref,
            Object.entries(x.values)
              .map(([k, v]) => k + ": " + fmt(v))
              .join(" · "),
          ]),
        ),
      )
    ) {
      const result=await api(
        "raw/lotes",
        request({ area: state.area, version: state.data.version, edits }),
      );
      await waitUpdated(result);
    }
  }
  function copy(e) {
    if (!state.cells || e.target.closest("input,textarea,dialog")) return;
    const s = state.cells,
      cols = visible(),
      lines = [];
    for (
      let i = Math.min(s.start[0], s.end[0]);
      i <= Math.max(s.start[0], s.end[0]);
      i++
    ) {
      const values = [];
      for (
        let j = Math.min(s.start[1], s.end[1]);
        j <= Math.max(s.start[1], s.end[1]);
        j++
      )
        values.push(
          fmt(state.data.rows[i]?.values[cols[j]?.id], cols[j]).replace(
            /[\t\n]/g,
            " ",
          ),
        );
      lines.push(values.join("\t"));
    }
    e.preventDefault();
    e.clipboardData.setData("text/plain", lines.join("\n"));
  }
  async function refreshViews() {
    const data = await api("raw/objects/view?area=" + state.area);
    state.views = data.items;
    $("views").replaceChildren(el("option", "Vista inicial"));
    $("views").firstChild.value = "";
    for (const v of state.views) {
      const opt = el("option", v.name);
      opt.value = v.id;
      $("views").append(opt);
    }
    $("views").value = state.view?.id || "";
  }
  async function init() {
    await catalog();
    await refreshViews();
    $("search").value = state.q;
    const need = new URLSearchParams(location.search).get("need");
    if (need) state.directNeed = need;
    await load();
    if (need) {
      const row = await api(
        "raw/consultas",
        params({ selected: [need], q: "", filters: [] }),
      );
      if (row.rows.length) await evidence(row.rows[0]);
      else
        $("notice").textContent =
          "A ficha foi guardada. A ligação à RAW será atualizada pelo trabalhador.";
    }
    const poll = safe(async () => {
        let delay = 500;
        try {
        if (!state.data || state.polling) return;
        state.polling=true;
        const d = await api(
          "raw/workspace/atualizacao?area=" +
            state.area +
            "&version=" +
            state.data.version,
        );
        if (d.pending) {
          delay = 250;
          if (!$('editor').open)
            $('notice').textContent = 'Atualização em processamento; a rever linhas e agregados.';
        }
        if (d.available) {
          if ($("editor").open)
            $("notice").textContent =
              "Há uma versão nova. As alterações abertas foram conservadas.";
          // A background source change publishes core rows and then shared
          // capacities. Fetch the complete page once at the coherent revision.
          // Explicit saves still load their committed line in waitUpdated().
          else if (!d.pending) await load(true);
        }
        } finally {
          state.polling=false;
          setTimeout(poll, delay);
        }
    });
    setTimeout(poll, 1000);
  }
  $("area").onchange = safe(async () => {
    state.area = $("area").value;
    state.columns = [];
    state.column_order = [];
    state.column_groups = {};
    state.pinned = ['of', 'ov', 'component_ref'];
    state.columnOpen = {};
    state.data = null;
    state.page = 1;
    state.filters = [];
    state.order = [];
    state.selected.clear();
    state.view = null;
    await catalog();
    await refreshViews();
    await load(true);
  });
  $('grid').addEventListener('scroll', syncHorizontal, {passive:true});
  $('horizontal-position').oninput = e => { $('grid').scrollLeft = +e.target.value; syncHorizontal(); };
  $('scroll-first').onclick = () => { $('grid').scrollLeft = 0; syncHorizontal(); };
  $('scroll-last').onclick = () => { $('grid').scrollLeft = $('grid').scrollWidth; syncHorizontal(); };
  const horizontalObserver = new ResizeObserver(syncHorizontal);
  horizontalObserver.observe($('grid')); horizontalObserver.observe($('sheet'));
  $("search-form").onsubmit = safe(async (e) => {
    e.preventDefault();
    state.q = $("search").value;
    state.page = 1;
    await load();
  });
  $("page-size").onchange = safe(async () => {
    state.size = +$("page-size").value;
    state.page = 1;
    await load();
  });
  $("density").onchange = () => {
    state.density = $("density").value;
    render();
  };
  $("population").onchange = safe(async () => {
    state.population = $("population").value;
    state.selected.clear();
    state.page = 1;
    await load(true);
  });
  $("open-only").onchange = safe(async () => {
    state.filters = state.filters.filter((f) => f.field !== "status");
    if ($("open-only").checked)
      state.filters.push({
        field: "status",
        op: "in",
        values: ["Em Aberto", "Em Produção"],
      });
    state.page = 1;
    await load();
  });
  $("prev").onclick = safe(async () => {
    state.page--;
    await load();
  });
  $("next").onclick = safe(async () => {
    state.page++;
    await load();
  });
  $("clear-filters").onclick = safe(async () => {
    state.filters = [];
    state.q = "";
    $("search").value = "";
    $("open-only").checked = false;
    state.page = 1;
    await load();
  });
  $("refresh").onclick = safe(() => load(true));
  $("open-columns").onclick = columnPanel;
  $("close-drawer").onclick = () => $("drawer").close();
  $("cancel-edit").onclick = () => {
    $("editor").close();
    state.editing = null;
  };
  $("editor-form").onsubmit = safe(saveCell);
  $("cell-evidence").onclick = safe(() => evidence(state.editing.row));
  document.addEventListener("copy", copy);
  document.addEventListener("paste", safe(paste));
  window.addEventListener("resize", () => {
    if (state.data) render();
  });
  $("views").onchange = safe(async () => {
    state.view = state.views.find((v) => v.id === $("views").value) || null;
    const d = state.view?.definition;
    if (d) {
      Object.assign(state, {
        columns:
          d.columns ||
          state.fields
            .filter(
              (f) => !(d.hidden || d.hidden_groups || []).includes(f.group),
            )
            .map((f) => f.id),
        widths: d.widths || {},
        column_order: d.column_order || d.columns || [],
        column_groups: d.column_groups || {},
        pinned: d.pinned || ['of', 'ov', 'component_ref'],
        density: d.density || "compact",
        population: d.population || "active",
        size: d.page_size || 100,
        q: d.q || "",
        filters: d.filters instanceof Array ? d.filters : [],
        order: d.order || [],
        formula_ids: d.formula_ids || [],
        format_ids: d.format_ids || [],
      });
    } else {
      state.columns = [];
      state.column_order = [];
      state.column_groups = {};
      state.pinned = ['of','ov','component_ref'];
      localStorage.removeItem('planning-layout-' + state.area);
      state.filters = [];
      state.population = "active";
      state.order = [];
      state.q = "";
      await catalog();
    }
    normalizeColumns();
    state.page = 1;
    $("search").value = state.q;
    $("density").value = state.density;
    $("population").value = state.population;
    $("page-size").value = state.size;
    await load(true);
  });
  setTimeout(() => safe(init)(), 0);
  return {
    state,
    $,
    el,
    api,
    request,
    safe,
    fmt,
    config,
    params,
    drawer,
    confirm,
    field,
    button,
    input,
    select,
    smallTable,
    load,
    render,
    refreshViews,
    evidence,
    waitUpdated,
  };
})();
