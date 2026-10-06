"use strict";
(() => {
  const $ = (id) => document.getElementById(id),
    mode = document.body.dataset.mode;
  const state = {
    area: new URLSearchParams(location.search).get("area") || "perfis",
    page: 1,
    size: 100,
    data: null,
    resources: [],
    editing: false,
    loadSerial: 0,
    detail: null,
  };
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const fmt = (v, d = 2) =>
    v == null
      ? "Por confirmar"
      : typeof v === "number"
        ? v.toLocaleString("pt-PT", { maximumFractionDigits: d })
        : String(v);
  const stamp = (v) => {
    if (!v) return "Sem confirmação";
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("pt-PT", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: state.data?.timezone || "Europe/Lisbon",
      })
        .formatToParts(new Date(v))
        .map((p) => [p.type, p.value]),
    );
    return `${parts.day}-${parts.month}-${parts.year}, ${parts.hour}:${parts.minute} · ${state.data?.timezone || "Europe/Lisbon"}`;
  };
  const safe =
    (fn) =>
    async (...args) => {
      try {
        return await fn(...args);
      } catch (e) {
        $("notice").textContent = e.message;
        if ($("edit-panel").open) $("edit-error").textContent = e.message;
        else if ($("panel").open) {
          const box = el("p", e.message, "warning-box");
          $("panel-body").prepend(box);
        }
      }
    };
  const button = (label, fn, cls) => {
    const b = el("button", label, cls);
    b.type = "button";
    b.onclick = safe(fn);
    return b;
  };
  const input = (v = "", type = "text") => {
    const i = el("input");
    i.type = type;
    i.value = v ?? "";
    return i;
  };
  const select = (items, v) => {
    const s = el("select");
    for (const x of items) {
      const o = el("option", x.label ?? x);
      o.value = x.value ?? x;
      s.append(o);
    }
    if (v != null) s.value = v;
    return s;
  };
  const field = (label, node) => {
    const l = el("label", label);
    l.append(node);
    return l;
  };
  const table = (heads, rows) => {
    const wrap = el("div", null, "capacity-table-wrap"),
      t = el("table"),
      h = el("thead"),
      tr = el("tr");
    heads.forEach((v) => tr.append(el("th", v)));
    h.append(tr);
    t.append(h);
    const body = el("tbody");
    for (const row of rows) {
      const tr = el("tr");
      for (const v of row) {
        const td = el("td");
        td.append(
          v instanceof Node
            ? v
            : document.createTextNode(v == null ? "Por confirmar" : String(v)),
        );
        tr.append(td);
      }
      body.append(tr);
    }
    t.append(body);
    wrap.append(t);
    return wrap;
  };
  async function api(path, p) {
    const r = await fetch(
      "/planeamento/api/" + path,
      p === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(p),
          },
    );
    const d = await r.json();
    if (!r.ok)
      throw new Error(
        typeof d.detail === "string"
          ? d.detail
          : d.error || JSON.stringify(d.detail || d),
      );
    return d;
  }
  const req = (p) => ({ request_id: crypto.randomUUID(), ...p });
  function panel(title) {
    state.detail = null;
    $("panel-title").textContent = title;
    $("panel-body").replaceChildren();
    if (!$("panel").open) $("panel").showModal();
    return $("panel-body");
  }
  function query() {
    return {
      mode,
      area: state.area,
      page: state.page,
      page_size: state.size,
      q: $("search").value,
      year: $("year")?.value || undefined,
      week: $("week")?.value || undefined,
      unscheduled: $("unscheduled")?.checked || false,
    };
  }
  function headers() {
    return mode === "weekly"
      ? [
          ["machine", "Máquina"],
          ["available_hours", "Disponíveis confirmadas (h)"],
          ["reference_available_hours", "Calendário importado (h)"],
          ["reference_hours", "Carga segundo a macro (h)"],
          ["planned_hours", "Carga prevista (h)"],
          ["free_hours", "Livres (h)"],
          ["occupancy", "Ocupação (%)"],
          ["actual_hours", "Horas reais declaradas"],
          ["weight", "Peso (kg)"],
          ["lines_total", "Operações"],
        ]
      : [
          ["machine", "Máquina"],
          ["pending_quantity", "Peças pendentes"],
          [
            state.area === "perfis" ? "pending_area" : "pending_metres",
            state.area === "perfis"
              ? "Área pendente (mm²)"
              : "Metros pendentes",
          ],
          ["reference_hours", "Carga segundo a macro (h)"],
          ["planned_hours", "Carga prevista (h)"],
          ["reference_equivalent_shifts", "Turnos equivalentes · macro"],
          ["weight", "Peso (kg)"],
          ["lines_total", "Operações"],
          ["unknown_load", "Por confirmar"],
        ];
  }
  async function load() {
    const serial=++state.loadSerial,area=state.area;
    $("notice").textContent = "A consultar…";
    const data = await api("raw/capacidade/consulta", query());
    if(serial!==state.loadSerial||area!==state.area)return;
    state.data = data;
    if ($("year") && !$("year").value) $("year").value = data.year;
    if ($("week") && !$("week").value) $("week").value = data.week;
    $("source-state").textContent =
      `Versão ${data.version} · ${stamp(data.created_at)}`;
    $("period-state").textContent =
      mode === "weekly"
        ? $("unscheduled").checked
          ? "Trabalho sem período completo"
          : `W${String(data.week).padStart(2, "0")} / ${data.year}`
        : "Todas as semanas e trabalho por calendarizar";
    $("subtitle").textContent =
      mode === "machines"
        ? "Carga e parâmetros por máquina. Consulta as peças para verificar cada cálculo."
        : "Calendário, carga e produção da semana. Uma semana vazia pode coexistir com trabalho por calendarizar.";
    for (const [id, url] of [
      ["raw-link", "raw"],
      ["machines-link", "capacidades"],
      ["weekly-link", "disponibilidade"],
    ])
      $(id).href = "/planeamento/" + url + "?area=" + state.area;
    const t = data.totals;
    $("totals").textContent =
      `Estimativa da operação principal: ${fmt(t.reference_hours)} h · ${t.reference_known}/${t.primary_operations} operações com cálculo conhecido. ${t.additional_operations} operações adicionais. ${data.unscheduled_operations} operações sem período completo na área. CPIS importado — sem confirmação direta.`;
    $("notice").textContent = "";
    render();
    const openDetail=$("panel").open?state.detail:null;
    if(openDetail&&!state.editing&&$("panel").open&&state.detail===openDetail){
      const scroll=$("panel-body").scrollTop;
      let row=data.rows.find(r=>r.key===openDetail.key);
      if(!row){const found=await api("raw/consultas",{area,version:data.version,dataset:mode==="weekly"?"capacity":"capacity_machines",selected:[openDetail.key]});row=found.rows[0];}
      if(serial!==state.loadSerial||state.detail!==openDetail)return;
      if(row)await detail(row,openDetail.tab,openDetail);else panel("Período atualizado").append(el("p","Este período já não contém trabalho ou disponibilidade nesta versão."));
      $("panel-body").scrollTop=scroll;
    }
  }
  function render() {
    const heads = headers(),
      thead = $("matrix").querySelector("thead"),
      tbody = $("matrix").querySelector("tbody");
    thead.replaceChildren();
    tbody.replaceChildren();
    const tr = el("tr");
    heads.forEach(([k, label]) => tr.append(el("th", label)));
    thead.append(tr);
    for (const row of state.data.rows) {
      const tr = el("tr");
      for (const [k] of heads) {
        const td = el("td"),
          v = row.values[k];
        if (k === "machine") {
          td.append(button(v, () => detail(row)));
          if(row.physical_status) td.append(el("small",row.physical_status));
          if (row.calendar_conflict)
            td.append(
              el("small", "Calendário por conferir", "capacity-conflict"),
            );
          if (row.values.year == null && mode === "weekly")
            td.append(
              el(
                "small",
                row.values.week
                  ? "W" + row.values.week + " · ano por confirmar"
                  : "Por calendarizar",
              ),
            );
        } else {
          td.className = "numeric";
          td.textContent = fmt(v);
          if (v < 0) td.classList.add("negative");
          const coverage = row.coverage?.[k];
          if (coverage && coverage.known < coverage.total) {
            td.textContent = coverage.known
              ? fmt(coverage.sum_known)
              : "Por confirmar";
            td.append(
              el(
                "small",
                `${coverage.known}/${coverage.total} ${coverage.population || "operações"} · parcial`,
              ),
            );
          }
          if (k === "reference_available_hours" && row.calendar_conflict) {
            td.textContent = row.calendars
              .filter((x) => !x.local)
              .map((x) => fmt(x.hours))
              .join(" / ");
            td.append(
              el("small", "Conflito · não somadas", "capacity-conflict"),
            );
          }
          if (k === "reference_equivalent_shifts" && row.reference_shift_hours)
            td.append(
              el(
                "small",
                fmt(row.reference_shift_hours) + " h/turno · origem Excel",
              ),
            );
          if (
            k === "actual_hours" &&
            row.actual_coverage?.known < row.actual_coverage.total
          )
            td.append(
              el(
                "small",
                `${row.actual_coverage.known}/${row.actual_coverage.total} declarações`,
              ),
            );
        }
        tr.append(td);
      }
      tbody.append(tr);
    }
    if (!state.data.rows.length) {
      const tr = el("tr"),
        td = el(
          "td",
          "Sem linhas neste filtro. Consulta também o trabalho por calendarizar.",
        );
      td.colSpan = heads.length;
      tr.append(td);
      tbody.append(tr);
    }
    $("count").textContent = fmt(state.data.total, 0) + " máquinas / períodos";
    $("page").textContent =
      state.page +
      " / " +
      Math.max(1, Math.ceil(state.data.total / state.size));
    $("prev").disabled = state.page === 1;
    $("next").disabled = state.page * state.size >= state.data.total;
  }
  const support = (row) => ({
    area: state.area,
    version: state.data.version,
    dataset: mode === "weekly" ? "capacity" : "capacity_machines",
    ...(mode === "weekly"
      ? { bucket_key: row.key }
      : { machine_key: row.values.machine_key }),
  });
  async function detail(row,tab=0,previous=null) {
    const b=panel(row.values.machine),actions=el("div",null,"actions");
    let body=null;
    const tabs=[["Peças e cálculos",pieceList],["Calendário e parâmetros",parameters],["Comparar com Excel",excel],["Produção registada",production]];
    const selected={key:row.key,tab,page:previous?.page||1,piece:previous?.piece||null};state.detail=selected;
    const show=async index=>{
      selected.tab=index;
      const next=el("section");
      if(body)body.replaceWith(next);else b.append(next);
      body=next;
      await tabs[index][1](row,next,index===0?selected.page:undefined);
    };
    tabs.forEach(([label],index)=>actions.append(button(label,()=>show(index))));
    b.append(actions);await show(tab);
  }
  async function pieceList(row, body, page = 1) {
    if(state.detail?.key===row.key)state.detail.page=page;
    body.replaceChildren(el("p", "A consultar as peças…"));
    const d = await api("raw/capacidade/pecas", {
      ...support(row),
      page,
      page_size: 100,
    });
    if(!body.isConnected)return;
    body.replaceChildren();
    if(state.detail?.key===row.key&&state.detail.piece){
      const selected=d.rows.find(r=>r.key===state.detail.piece);
      if(selected)return pieceProof(selected,body,row,page);
      state.detail.piece=null;
    }
    body.append(
      el(
        "p",
        "A carga prevista usa taxa manual aplicável, depois histórico compatível, depois Excel provisório. O fator Thomas ×3 só se aplica à referência Excel.",
        "capacity-source-meta",
      ),
    );
    const rows = d.rows.map((r) => {
      const v = r.values,
        ref = button(v.component_ref || "Sem referência", () =>
          pieceProof(r, body, row, page),
        );
      return [
        v.of,
        ref,
        v.area,
        v.operation,
        v.draft ? "Rascunho" : "Importado / preparado",
        fmt(v.quantity),
        fmt(v.planned_hours),
        fmt(v.reference_hours),
        r.reason || v.rate_source || "Origem por confirmar",
        r.period_source,
      ];
    });
    body.append(
      table(
        [
          "OF",
          "Referência",
          "Área",
          "Operação",
          "Situação",
          "Qtd.",
          "Carga prevista (h)",
          "Macro (h)",
          "Conferência",
          "Período",
        ],
        rows,
      ),
    );
    const nav = el("div", null, "actions"),
      prev = button("← Anterior", () => pieceList(row, body, page - 1)),
      next = button("Seguinte →", () => pieceList(row, body, page + 1));
    prev.disabled = page <= 1;
    next.disabled = page * 100 >= d.total;
    nav.append(
      prev,
      el("span", `${fmt(d.total, 0)} operações · página ${page}`),
      next,
    );
    body.append(nav);
  }
  function pieceProof(item, body, row, page) {
    if(state.detail?.key===row.key){state.detail.piece=item.key;state.detail.page=page;}
    body.replaceChildren(
      button("← Voltar às peças", () => {if(state.detail?.key===row.key)state.detail.piece=null;return pieceList(row, body, page);}),
    );
    const v = item.values,
      x = item.inputs;
    body.append(el("h3", v.of + " · " + v.component_ref + " · " + v.operation));
    body.append(
      table(
        ["Entrada", "Valor"],
        [
          ["Quantidade utilizada", fmt(x.quantity)],
          ["Origem da quantidade", x.quantity_source],
          ["Comprimento (mm)", fmt(x.length_mm)],
          ["Área unitária (mm²)", fmt(x.section_unit)],
          ["Peso unitário comprovado (kg)", fmt(x.weight_unit)],
          ["Versão da macro", x.snapshot],
          [
            "Taxa importada",
            fmt(item.reference_rate?.value) +
              " " +
              (item.reference_rate?.unit || ""),
          ],
          ["Fator histórico na macro", fmt(item.reference_factor)],
          [
            "Taxa aplicada",
            item.applied_rate?.rate ? fmt(item.applied_rate.rate.value) + " · " + ({area_hour:"mm²/h",metres_hour:"m/h",units_hour:"un./h",minutes_unit:"min/un.",fixed_minutes:"min"})[item.applied_rate.rate.method] + " · " + item.applied_rate.source : "Por confirmar",
          ],
          ["Carga prevista (h)", fmt(v.planned_hours)],
          ["Fórmula aplicada", item.applied_rate?.calculation?.formula || "Por confirmar"],
          ["Volume pendente usado", fmt(item.applied_rate?.calculation?.inputs?.volume) + (item.applied_rate?.calculation?.inputs?.volume_unit ? " " + item.applied_rate.calculation.inputs.volume_unit : "")],
          ["Preparação aplicada (min)", fmt(item.applied_rate?.calculation?.inputs?.setup_minutes)],
          ["Estimativa segundo a macro (h)", fmt(v.reference_hours)],
          ["Valor de horas guardado no Excel", fmt(v.macro_hours)],
          ["Conferência", item.reason || "Compatível"],
          ["Data usada para a vigência da taxa", datePt(item.rate_date)],
          ["Significado desta data", item.rate_date_source],
          [
            "Regra importada",
            item.reference_reason ||
              (v.area === "perfis"
                ? "quantidade × área unitária ÷ taxa C ÷ fator histórico"
                : "quantidade × comprimento / 1000 ÷ velocidade da linha"),
          ],
        ],
      ),
    );
    if(item.applied_rate?.history_hash) body.append(button("Histórico usado / exclusões",async()=>{
      const h=await api("raw/produtividade/"+item.applied_rate.history_hash);
      const detail=el("section");
      detail.append(el("h3","Produtividade histórica · "+h.window.start+" / "+h.window.end));
      detail.append(el("p",`${h.sheet_count} folhas · ${h.event_count} eventos · ${fmt(h.volume)} de volume / ${fmt(h.hours)} h = ${fmt(h.value)} ${h.unit}`));
      detail.append(table(["Coorte","Folhas","Eventos","Volume","Horas","Origem"],h.cohorts.map(c=>[c.key,c.sheets.join(", "),c.events.join(", "),fmt(c.volume),fmt(c.hours),c.hours_origin])));
      detail.append(table(["Excluída","Folhas","Motivo"],h.excluded.map(c=>[c.key,c.sheets.join(", "),c.reasons.join("; ")])));
      body.append(detail);
    }));
    const link = el("a", "Abrir a peça na RAW");
    link.href =
      "/planeamento/raw?area=" +
      item.values.area +
      "&q=" +
      encodeURIComponent(v.component_ref);
    link.target = "_blank";
    link.rel = "noopener";
    body.append(link);
  }
  async function parameters(row, body) {
    body.replaceChildren();
    if (row.warnings?.length)
      body.append(el("p", row.warnings.join(" "), "warning-box"));
    const cals = row.calendars || [];
    if (mode === "weekly")
      body.append(
        table(
          ["Origem", "Turnos", "Horas/turno", "Total (h)", "Estado"],
          cals.map((c) => [
            c.local
              ? "Decisão local · revisão " + c.revision
              : `${c.source?.sheet}!${c.source?.row}`,
            fmt(c.shifts),
            fmt(c.hours_per_shift),
            fmt(c.hours),
            c.local && c.confirmed ? "Confirmado" : "Sugestão importada",
          ]),
        ),
      );
    const resource = row.resource;
    body.append(
      el(
        "p",
        resource
          ? "Recurso físico: " +
              resource.name +
              " · " +
              resource.definition.operations.join(", ")
          : "Este nome ainda não foi confirmado como recurso físico.",
      ),
    );
    body.append(
      button(
        resource ? "Editar máquina física" : "Associar a máquina física",
        () =>
          editConfig(
            "resource",
            resource,
            {
              aliases: (row.aliases || [])
                .map(([area, name]) => ({ area, name }))
                .filter((x) => x.name),
              operations: state.area === "perfis" ? ["corte"] : [],
              confirmed: false,
            },
            row.values.machine,
          ),
      ),
    );
    if (resource) {
      body.append(
        button("Calendário desta semana", async () => {
          const cals = (await api("raw/objects/calendar")).items;
          const old = cals.find(
            (x) =>
              x.definition.resource_id === resource.id &&
              x.definition.year === row.values.year &&
              x.definition.week === row.values.week,
          );
          await editConfig("calendar", old, {
            resource_id: resource.id,
            year: row.values.year || state.data.year,
            week: row.values.week || state.data.week,
          });
        }),
        button("Adicionar parâmetro", () =>
          editConfig("rate", null, {
            resource_id: resource.id,
            area: state.area,
            operation: state.area === "perfis" ? "corte" : "",
            method: state.area === "perfis" ? "area_hour" : "metres_hour",
          }),
        ),
      );
    }
    body.append(
      table(
        ["Parâmetro", "Método", "Taxa", "Vigência", "Origem"],
        (row.rates || []).map((r) => [
          button(r.name, () => editConfig("rate", r)),
          r.definition.method,
          fmt(r.definition.value),
          r.definition.valid_from +
            " / " +
            (r.definition.valid_until || "sem fim"),
          r.definition.source || "Decisão local",
        ]),
      ),
    );
    const v = row.values;
    body.append(
      table(
        ["Resultado", "Valor"],
        [
          ["Horas disponíveis confirmadas", fmt(v.available_hours)],
          ["Área prevista conhecida (mm²)", fmt(row.coverage?.area_load?.known ? row.coverage.area_load.sum_known : null)+` · ${row.coverage?.area_load?.known||0}/${row.coverage?.area_load?.total||0} operações`],
          ["Metros previstos conhecidos", fmt(row.coverage?.metres?.known ? row.coverage.metres.sum_known : null)+` · ${row.coverage?.metres?.known||0}/${row.coverage?.metres?.total||0} operações`],
          ["Peso conhecido (kg)", fmt(row.coverage?.weight?.known ? row.coverage.weight.sum_known : null)+` · ${row.coverage?.weight?.known||0}/${row.coverage?.weight?.total||0} peças`],
          ["Carga prevista (h)", fmt(v.planned_hours)],
          ["Turnos equivalentes confirmados", fmt(v.equivalent_shifts)],
          ["Turnos equivalentes · macro", fmt(v.reference_equivalent_shifts)],
          [
            "Horas por turno usadas na comparação",
            fmt(row.reference_shift_hours),
          ],
          ["Horas livres", fmt(v.free_hours)],
          ["Ocupação (%)", fmt(v.occupancy)],
          [
            "Capacidade física total",
            fmt(v.capacity_total) + " " + (row.capacity_unit || ""),
          ],
          [
            "Capacidade física livre",
            fmt(v.capacity_free) + " " + (row.capacity_unit || ""),
          ],
          ["Rascunhos: carga conhecida (h)", fmt(v.draft_hours)],
          ["Rascunhos por confirmar", fmt(v.draft_unknown)],
        ],
      ),
    );
    body.append(
      el(
        "p",
        "Os rascunhos ativos entram na carga prevista quando têm dados suficientes. As horas livres desta semana não incluem trabalho sem semana definida.",
      ),
    );
  }
  async function excel(row, body) {
    body.replaceChildren(el("p", "A consultar as células de origem…"));
    const src = await api("raw/capacidade/excel", { ...support(row) });
    if(!body.isConnected)return;
    body.replaceChildren(
      el(
        "p",
        src.source_filename + " · " + src.snapshot_id,
        "capacity-source-meta",
      ),
      el("p", src.notice),
    );
    const choices = select(Object.keys(src.sheets)),
      content = el("div"),
      search = input(row?.values?.machine || "");
    body.append(
      field("Folha", choices),
      field("Procurar no valor, fórmula ou célula", search),
      content,
    );
    const render = () => {
      content.replaceChildren();
      const term = search.value.toLocaleLowerCase("pt-PT");
      const rows = src.sheets[choices.value] || [];
      const matched = term
        ? rows.filter((r) =>
            Object.values(r.cells).some(
              (c) =>
                String(c.value ?? "")
                  .toLocaleLowerCase("pt-PT")
                  .includes(term) ||
                String(c.formula || "")
                  .toLocaleLowerCase("pt-PT")
                  .includes(term),
            ),
          )
        : rows;
      content.append(
        el(
          "p",
          `${matched.length} linhas da folha. Valores manuais e totais antigos ficam preservados; não substituem o recálculo.`,
        ),
      );
      const flattened = [];
      for (const r of matched)
        for (const [col, c] of Object.entries(r.cells))
          flattened.push([
            c.cell,
            // Datas do Excel: mostra a data (dd/mm/aaaa) em vez do número de série guardado.
            c.date ? c.date.slice(0, 10).split("-").reverse().join("/") : fmt(c.value),
            c.formula ? "=" + c.formula : "—",
            c.kind === "formula"
              ? "Fórmula"
              : choices.value === "CapacidadeMáquinas" &&
                  col === "C" &&
                  r.row >= 2 &&
                  r.row <= 12
                ? "Parâmetro consultado pela fórmula"
                : "Valor / preenchimento manual",
          ]);
      content.append(
        table(
          ["Célula", "Valor guardado", "Fórmula original", "Categoria"],
          flattened,
        ),
      );
    };
    choices.onchange = () => {
      search.value = "";
      render();
    };
    search.oninput = render;
    render();
    if (row.source_totals?.length) {
      body.append(el("h3", "Totais antigos de CapacidadeMáquinas"));
      for (const x of row.source_totals)
        body.append(
          table(
            ["Origem", "Área", "Horas", "Turnos", "Peso (t)"],
            [
              [
                x.area + " · " + x.machine,
                fmt(x.values.area?.value),
                fmt(x.values.hours?.value),
                fmt(x.values.shifts?.value),
                fmt(x.values.weight_t?.value),
              ],
            ],
          ),
        );
      body.append(
        el(
          "p",
          "Os totais desta folha podem estar limitados a Planeamento!7:1035. A aplicação recalcula todas as linhas elegíveis.",
          "warning-box",
        ),
      );
    }
  }
  async function production(row, body, page = 1, area = state.area) {
    body.replaceChildren();
    const areas=[...new Set((row.aliases||[]).map(x=>x[0]))];
    if(areas.length>1){const choice=select(areas.map(a=>({value:a,label:a==='perfis'?'OCR Perfis':'OCR Cantoneiras'})),area);choice.onchange=safe(()=>production(row,body,1,choice.value));body.append(field("Produção deste recurso partilhado — escolher área",choice));}

    const v = row.values,
      aliases = (row.aliases || [])
        .filter(([a]) => a === area)
        .map(([, m]) => m)
        .filter(Boolean),
      filters = [{ field: "machine", op: "in", values: aliases }];
    if (v.year && v.week) {
      const monday = isoMonday(v.year, v.week),
        end = new Date(monday);
      end.setUTCDate(end.getUTCDate() + 6);
      filters.push({
        field: "production_date",
        op: "between",
        min: monday.toISOString().slice(0, 10),
        max: end.toISOString().slice(0, 10),
      });
    }
    const d = await api("raw/consultas", {
      area,
      dataset: "production",
      filters,
      page,
      page_size: 100,
      order: [{ field: "production_date", direction: "desc" }],
    });
    if(!body.isConnected)return;
    body.append(
      el(
        "p",
        "Eventos validados segundo a data de produção. As horas declaradas pertencem à folha e não são repetidas em cada peça.",
      ),
    );
    body.append(
      table(
        [
          "Data",
          "OF",
          "Referência",
          "Operação",
          "Quantidade",
          "Associação",
          "Folha",
        ],
        d.rows.map((r) => [
          datePt(r.values.production_date),
          r.values.of,
          r.values.component_ref,
          r.values.operation,
          fmt(r.values.quantity),
          r.values.association_status,
          sheetLink(r),
        ]),
      ),
    );
    body.append(
      el(
        "p",
        `${fmt(d.total, 0)} eventos · página ${page}. Horas reais conhecidas: ${fmt(v.actual_hours)}.`,
      ),
    );
    const nav = el("div", null, "actions");
    if (page > 1)
      nav.append(button("← Anterior", () => production(row, body, page - 1, area)));
    if (page * 100 < d.total)
      nav.append(button("Seguinte →", () => production(row, body, page + 1, area)));
    body.append(nav);
    if (row.actual_evidence?.length)
      body.append(
        table(
          ["Origem", "Folhas / período", "Horas", "Estado"],
          row.actual_evidence.map((e) => [e.origin || "OCR", (e.sheets || []).join(", ") + (e.start_date ? " · " + e.start_date + " / " + e.end_date : ""), fmt(e.hours), e.reason || "Utilizável"]),
        ),
      );
  }
  function datePt(v) {
    return /^\d{4}-\d{2}-\d{2}/.test(String(v))
      ? String(v).slice(0, 10).split("-").reverse().join("-")
      : "Por confirmar";
  }
  function sheetLink(r) {
    return (
      String(r.values.sheet || r.sheet_uid || "Folha") +
      " · linha " +
      (r.row_index ?? "por confirmar")
    );
  }

  function isoMonday(y, w) {
    const d = new Date(Date.UTC(y, 0, 4));
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) + (w - 1) * 7);
    return d;
  }
  async function files() {
    const b = panel("Fontes e versões"),
      d = await api("raw/ficheiros");
    b.append(el("p", d.notice));
    b.append(
      table(
        [
          "Área",
          "Consulta ao Drive",
          "Alteração do ficheiro",
          "Importado",
          "Geração",
          "Estado",
        ],
        d.sources.map((x) => [
          x.area,
          stamp(x.drive?.checked_at),
          stamp(x.drive?.remote_modified_at),
          stamp(x.imported?.loaded_at),
          x.generation?.id || "Por preparar",
          x.drive?.error ||
            (x.newer_available
              ? x.newer_folder
                ? `Versão mais recente na pasta «${x.newer_folder}»; a carga automática só lê a raiz`
                : "Existe versão por importar"
              : x.drive?.checked_at
                ? "Hash coincide"
                : "Drive por verificar"),
        ]),
      ),
    );
    for (const x of d.sources)
      b.append(
        el(
          "p",
          x.area +
            " · " +
            x.snapshot.snapshot_id +
            " · SHA-256 " +
            x.imported.source_sha256,
          "capacity-source-meta",
        ),
      );
    b.append(
      el(
        "p",
        "A consulta de metadados não importa ficheiros. O horário de sincronização do Drive continua a ser o existente. CPIS importado — sem confirmação direta.",
        "warning-box",
      ),
    );
  }
  async function configuration(kind = "resource") {
    const b = panel("Definições · Capacidades e horas"),
      tabs = el("div", null, "actions");
    for (const [k, label] of [
      ["resource", "Máquinas físicas"],
      ["calendar", "Calendários"],
      ["worked_hours", "Horas reais"],
      ["rate", "Parâmetros"],
    ])
      tabs.append(button(label, () => configuration(k)));
    tabs.append(button("Sugestões do Excel", () => suggestions()));
    b.append(tabs);
    const d = await api("raw/objects/" + kind);
    b.append(button("Adicionar", () => editConfig(kind), "primary"));
    b.append(
      table(
        ["Nome", "Área", "Revisão", "Estado", "Ações"],
        d.items.map((o) => [
          button(o.name, () => editConfig(kind, o)),
          o.area,
          o.revision,
          o.definition.confirmed ? "Confirmado" : "Por confirmar",
          button("Histórico", () => history(o, kind)),
        ]),
      ),
    );
  }
  async function history(o, kind) {
    const b = panel("Histórico · " + o.name),
      d = await api("raw/objects/" + o.id + "/historico");
    b.append(button("← Configuração", () => configuration(kind)));
    for (const v of d.versions) {
      b.append(el("h3", "Revisão " + v.revision + " · " + v.actor));
      b.append(
        table(
          ["Campo", "Valor"],
          Object.entries(v.definition).map(([k, x]) => [
            k,
            Array.isArray(x)
              ? x
                  .map((a) =>
                    typeof a === "object" ? Object.values(a).join(" · ") : a,
                  )
                  .join(", ")
              : fmt(x),
          ]),
        ),
      );
    }
  }
  function parseHoursAllocations(value) {
    return String(value || "").split("\n").filter(line=>line.trim()).map(line=>{
      const match=line.trim().match(/^(perfis|cantoneiras):([^=]+)=(.+)$/);
      if(!match)throw Error("Usa área:operação=horas, uma linha por operação.");
      const hours=Number(match[3].trim().replace(",","."));
      if(!Number.isFinite(hours))throw Error("Horas de repartição inválidas.");
      return {area:match[1],operation:match[2].trim(),hours};
    });
  }
  async function editConfig(kind, obj = null, seed = {}, suggestedName = "") {
    const d = { ...(obj?.definition || seed) },
      isNew = !obj;
    state.resources = (await api("raw/objects/resource")).items;
    const controls = {},
      wrap = $("edit-fields");
    wrap.replaceChildren();
    $("edit-error").textContent = "";
    $("edit-title").textContent = {
      resource: "Máquina física",
      calendar: "Calendário semanal",
      rate: "Parâmetro de cálculo",
      worked_hours: "Horas efetivamente trabalhadas",
    }[kind];
    const add = (k, label, node) => {
      controls[k] = node;
      wrap.append(field(label, node));
    };
    add("name", "Nome", input(obj?.name || suggestedName));
    if (kind === "resource") {
      add(
        "aliases",
        "Nomes equivalentes — uma linha por área:nome da máquina",
        (() => {
          const i = el("textarea");
          i.value = (d.aliases || [])
            .map((a) => a.area + ":" + a.name)
            .join("\n");
          i.placeholder = "perfis:Vanguard\ncantoneiras:Nome exato";
          return i;
        })(),
      );
      add(
        "operations",
        "Operações suportadas — códigos separados por vírgula",
        input((d.operations || []).join(", ")),
      );
      add("history_window_days", "Janela de produtividade histórica (dias)", input(d.history_window_days ?? 90, "number"));
      add(
        "shift_hours",
        "Horas por turno de referência (opcional)",
        input(d.shift_hours),
      );
    }
    if (["calendar", "rate", "worked_hours"].includes(kind))
      add(
        "resource_id",
        "Máquina física",
        select(
          [
            { value: "", label: "Selecionar máquina" },
            ...state.resources.map((r) => ({ value: r.id, label: r.name })),
          ],
          d.resource_id,
        ),
      );
    if (kind === "calendar") {
      add("year", "Ano ISO", input(d.year ?? state.data.year, "number"));
      add("week", "Semana ISO", input(d.week ?? state.data.week, "number"));
    }
    if (kind === "calendar") {
      add("calendar_mode", "Detalhe do calendário", select([
        {value:"weekly",label:"Disponibilidade semanal (sem horários)"},
        {value:"hourly",label:"Horários confirmados para Gantt"},
      ],Object.hasOwn(d,"weekly_windows")?"hourly":"weekly"));
      for (const [k, l, def] of [
        ["shifts", "Turnos na semana", null],
        ["hours_per_shift", "Horas por turno", null],
        ["exception_hours", "Horas indisponíveis / exceções", 0],
      ])
        add(k, l, input(d[k] ?? def));
      add("timezone", "Fuso horário", select([{value:"Europe/Lisbon",label:"Europe/Lisbon"}],d.timezone||"Europe/Lisbon"));
      const days=["Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"];
      for(let day=1;day<=7;day++){
        const windows=(d.weekly_windows||{})[String(day)]||[];
        add("window_"+day,days[day-1]+" · intervalos HH:MM-HH:MM separados por vírgula",input(windows.map(w=>w.start+"-"+w.end).join(", ")));
      }
      const exceptions=el("textarea");
      exceptions.value=Object.entries(d.date_overrides||{}).map(([date,windows])=>date+"="+windows.map(w=>w.start+"-"+w.end).join(",")).join("\n");
      exceptions.placeholder="2026-09-24=\n2026-09-25=08:00-12:00,13:00-17:00";
      add("date_overrides","Exceções — data=intervalos; data= encerra o dia",exceptions);
      const reservations=el("textarea");
      reservations.value=(d.reserved_windows||[]).map(r=>[r.start,r.end,r.area||""].join(" ; ")).join("\n");
      reservations.placeholder="2026-09-21T09:00:00+01:00 ; 2026-09-21T10:00:00+01:00 ; Cantoneiras";
      add("reserved_windows","Reservas horárias confirmadas — início ; fim ; área, uma por linha",reservations);
      const summary=el("p");summary.className="capacity-source-meta";wrap.append(summary);
      const parseWindows=value=>String(value||"").split(",").map(x=>x.trim()).filter(Boolean).map(x=>{
        const match=x.match(/^(\d{2}:\d{2})-(\d{2}:\d{2})$/);
        if(!match)throw Error("Usa HH:MM-HH:MM em cada intervalo.");
        return {start:match[1],end:match[2]};
      });
      const hourly=()=>{
        const weekly_windows={};for(let day=1;day<=7;day++)weekly_windows[String(day)]=parseWindows(controls["window_"+day].value);
        const date_overrides={};for(const line of controls.date_overrides.value.split("\n").filter(x=>x.trim())){
          const pos=line.indexOf("=");if(pos<0)throw Error("Usa data=intervalos nas exceções.");
          date_overrides[line.slice(0,pos).trim()]=parseWindows(line.slice(pos+1));
        }
        const reserved_windows=controls.reserved_windows.value.split("\n").filter(x=>x.trim()).map(line=>{
          const parts=line.split(";").map(x=>x.trim());
          if(parts.length<2||parts.length>3||!parts[0]||!parts[1])throw Error("Usa início ; fim ; área nas reservas horárias.");
          return {start:parts[0],end:parts[1],area:parts[2]||""};
        });
        return {weekly_windows,date_overrides,reserved_windows};
      };
      let previewSerial=0,previewTimer=null;
      const toggleCalendar=()=>{
        previewSerial++;
        if(previewTimer)clearTimeout(previewTimer);
        const hourlyMode=controls.calendar_mode.value==="hourly";
        for(const key of ["shifts","hours_per_shift","exception_hours"])controls[key].parentElement.hidden=hourlyMode;
        for(const key of ["timezone","date_overrides","reserved_windows",...Array.from({length:7},(_,i)=>"window_"+(i+1))])controls[key].parentElement.hidden=!hourlyMode;
        try{
          const slots=hourly();const minutes=s=>Number(s.slice(0,2))*60+Number(s.slice(3));
          const total=Object.values(slots.weekly_windows).flat().reduce((sum,w)=>sum+minutes(w.end)-minutes(w.start),0);
          summary.textContent=hourlyMode?`Padrão semanal: ${(total/60).toLocaleString("pt-PT")} h. A calcular exceções e mudança de hora…`:"Sem horas de início/fim confirmadas; este calendário só serve para a vista semanal.";
          if(hourlyMode){
            const serial=previewSerial;
            previewTimer=setTimeout(()=>api("raw/capacidade/calendario/preview",{definition:{
              year:Number(controls.year.value),week:Number(controls.week.value),
              timezone:controls.timezone.value,...slots,
            }}).then(result=>{
              if(serial===previewSerial)summary.textContent=`Disponibilidade resultante: ${fmt(result.available_hours)} h em ${result.timezone}, incluindo exceções, reservas e mudança de hora.`;
            }).catch(error=>{if(serial===previewSerial)summary.textContent=error.message}),350);
          }
        }catch(error){summary.textContent=error.message}
      };
      controls.calendar_mode.addEventListener("change",toggleCalendar);
      for(const key of ["year","week","date_overrides","reserved_windows",...Array.from({length:7},(_,i)=>"window_"+(i+1))])controls[key].addEventListener("input",toggleCalendar);
      controls.hourlyDefinition=hourly;
      toggleCalendar();
    }
    if (kind === "worked_hours") {
      const sheets = (await api("raw/horas/folhas")).sheets;
      add("mode", "Âmbito das horas", select([
        {value:"period",label:"Período da máquina"},
        {value:"sheet",label:"Folha de produção"},
      ], d.mode || "period"));
      add("sheet_key", "Folha", select([{value:"",label:"Selecionar folha"}, ...sheets.map(s=>({
        value:s.key,label:[s.area, "Folha " + (s.sheet ?? s.sheet_uid), s.machine || "Máquina por confirmar", s.date || "Sem data", fmt(s.hours) + " h"].join(" · ")
      }))],d.sheet_key));
      add("start_date", "Desde", input(d.start_date,"date"));
      add("end_date", "Até (mesma semana ISO)", input(d.end_date,"date"));
      add("hours", "Horas reais (h)", input(d.hours));
      add("operation", "Operação (vazio se o tempo abranger várias operações)", input(d.operation));
      const allocations=el("textarea");
      allocations.value=(d.operation_hours || []).map(a=>a.area+":"+a.operation+"="+a.hours).join("\n");
      allocations.placeholder="perfis:corte=4\ncantoneiras:112=2";
      add("operation_hours", "Repartição comprovada (opcional): área:operação=horas, uma por linha", allocations);
      const toggle=()=>{
        controls.sheet_key.parentElement.hidden=controls.mode.value!=="sheet";
        controls.start_date.parentElement.hidden=controls.mode.value!=="period";
        controls.end_date.parentElement.hidden=controls.mode.value!=="period";
      };
      controls.mode.addEventListener("change",toggle);toggle();
      wrap.append(el("p", "Horas reais são independentes do calendário de disponibilidade. Uma correção substitui as declarações OCR identificadas, preservando os originais."));
      const evidence=el("div");evidence.id="hours-evidence";
      const collect=()=>{
        const definition={...d};
        for(const [key,node] of Object.entries(controls))if(key!=="name")definition[key]=node.type==="checkbox"?node.checked:node.value;
        definition.operation_hours=parseHoursAllocations(controls.operation_hours.value);
        return definition;
      };
      wrap.append(button("Conferir declarações",async()=>{
        const result=await api("raw/horas/prever",{id:obj?.id,definition:collect()});
        d.basis_hash=result.basis_hash;
        evidence.replaceChildren(table(["Origem","Folha","Data","Máquina","Horas"],result.observations.map(o=>[o.origin,o.sheet ?? o.sheet_uid,o.date,o.machine,fmt(o.hours)])));
        if(!result.observations.length)evidence.append(el("p","Sem declarações OCR neste âmbito."));
        if(result.scope_conflict)evidence.append(el("p",result.scope_conflict,"warning-box"));
        for(const conflict of result.manual_overlaps)evidence.append(el("p","Sobreposição manual: "+conflict.name+". Corrige ou arquiva essa declaração.","warning-box"));
      }),evidence);
      const replace=input("","checkbox");replace.checked=!obj||d.replace_ocr===true;  // substituir é o defeito (07/10/2026)
      add("replace_ocr","Substituir integralmente as horas OCR apresentadas pelas horas reais acima",replace);
    }
    if (kind === "rate") {
      add(
        "area",
        "Área",
        select(["perfis", "cantoneiras"], d.area || state.area),
      );
      const cat = await api("catalogos?area=" + (d.area || state.area));
      add(
        "operation",
        "Operação",
        select(
          [
            { value: "", label: "Selecionar operação" },
            ...(cat.operations || []).filter((o) => o.countable !== false),
          ],
          d.operation,
        ),
      );
      controls.area.onchange = safe(async () => {
        const cat = await api("catalogos?area=" + controls.area.value);
        const n = select([
          { value: "", label: "Selecionar operação" },
          ...(cat.operations || []).filter((o) => o.countable !== false),
        ]);
        controls.operation.replaceWith(n);
        controls.operation = n;
      });
      add(
        "method",
        "Método e unidade",
        select(
          [
            { value: "area_hour", label: "Área de corte — mm²/h" },
            { value: "metres_hour", label: "Metros — m/h" },
            { value: "units_hour", label: "Unidades — un./h" },
            { value: "minutes_unit", label: "Minutos por unidade" },
            { value: "fixed_minutes", label: "Tempo fixo em minutos" },
          ],
          d.method,
        ),
      );
      add("value", "Taxa / valor", input(d.value));
      add(
        "setup_minutes",
        "Preparação fixa (min)",
        input(d.setup_minutes ?? 0),
      );
      add("valid_from", "Válido desde", input(d.valid_from, "date"));
      add("valid_until", "Válido até (opcional)", input(d.valid_until, "date"));
      add("material_type", "Família exata (opcional)", input(d.material_type));
      add("profile", "Perfil exato (opcional)", input(d.profile));
    }
    add("source", "Origem / justificação", input(d.source));
    const check = input("", "checkbox");
    check.checked = !obj || d.confirmed === true;  // marcada por defeito num registo novo (07/10/2026)
    const l = field(
      kind === "worked_hours" ? "Confirmo as horas reais, o âmbito e a origem indicados" : "Confirmo a máquina / o calendário / o parâmetro e a sua aplicação",
      check,
    );
    l.classList.add("check");
    wrap.append(l);
    controls.confirmed = check;
    const saveId = crypto.randomUUID();
    $("edit-form").onsubmit = safe(async (e) => {
      e.preventDefault();
      $("edit-error").textContent = "";
      const definition = { ...d };
      for (const [k, i] of Object.entries(controls)) {
        if (k === "name" || k === "hourlyDefinition" || k === "calendar_mode" || k.startsWith("window_") || k === "date_overrides" || k === "reserved_windows") continue;
        definition[k] = i.type === "checkbox" ? i.checked : i.value;
      }
      if(kind==="calendar"){
        if(controls.calendar_mode.value==="hourly")Object.assign(definition,controls.hourlyDefinition());
        else{delete definition.weekly_windows;delete definition.date_overrides;delete definition.reserved_windows;delete definition.timezone;}
      }
      if (kind === "worked_hours")definition.operation_hours=parseHoursAllocations(controls.operation_hours.value);
      // Sem «Conferir declarações» antes, a conferência faz-se ao gravar (07/10/2026).
      if (kind === "worked_hours" && !definition.basis_hash)
        definition.basis_hash = (await api("raw/horas/prever", { id: obj?.id, definition })).basis_hash;
      if (kind === "resource") {
        definition.aliases = controls.aliases.value
          .split("\n")
          .filter((x) => x.trim())
          .map((x) => {
            const pos = x.indexOf(":");
            if (pos < 0) throw new Error("Usa área:nome em cada linha.");
            return {
              area: x.slice(0, pos).trim().toLowerCase(),
              name: x.slice(pos + 1).trim(),
            };
          });
        definition.operations = controls.operations.value
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
      }
      await api("raw/objects/" + kind, {
        request_id: saveId,
        id: obj?.id,
        expected_revision: obj?.revision || 0,
        name: controls.name.value,
        area: obj?.area || state.area,
        definition,
      });
      state.editing = false;
      $("edit-panel").close();
      $("notice").textContent =
        "Guardado. Agregados em processamento; os valores serão atualizados automaticamente.";
      await configuration(kind);
    });
    if (obj) {
      wrap.append(
        button("Arquivar", async () => {
          if (
            !confirm("Arquivar esta configuração? O histórico será conservado.")
          )
            return;
          await api(
            "raw/objects/" + kind,
            req({
              id: obj.id,
              expected_revision: obj.revision,
              name: obj.name,
              area: obj.area,
              definition: obj.definition,
              archived: true,
            }),
          );
          state.editing = false;
          $("edit-panel").close();
          await configuration(kind);
        }),
      );
      if (kind === "calendar")
        wrap.append(
          button("Copiar para outras semanas", () => {
            state.editing = false;
            $("edit-panel").close();
            copyCalendar(obj);
          }),
        );
    }
    state.editing = true;
    $("edit-panel").showModal();
  }
  async function suggestions() {
    const b = panel("Sugestões importadas"),
      r = await api("raw/capacidade/propostas"),
      search = input(""),
      content = el("div");
    b.append(
      el("p", r.notice),
      field("Pesquisar máquina / ano / semana / perfil", search),
      content,
    );
    const show = () => {
      content.replaceChildren();
      const matched = r.proposals.filter(
        (p) =>
          p.area === state.area &&
          [
            p.machine,
            p.definition.year,
            p.definition.week,
            p.definition.profile,
            p.definition.source,
          ]
            .join(" ")
            .toLowerCase()
            .includes(search.value.toLowerCase()),
      );
      content.append(
        table(
          ["Tipo", "Máquina", "Valor / período", "Origem", "Ação"],
          matched.map((p) => [
            p.kind === "calendar" ? "Calendário" : "Taxa",
            p.machine,
            p.kind === "calendar"
              ? `W${p.definition.week}/${p.definition.year} · ${fmt(p.definition.shifts * p.definition.hours_per_shift)} h${p.conflict ? " · conflito" : ""}`
              : fmt(p.definition.value) +
                " · " +
                p.definition.method +
                " · " +
                (p.definition.profile || ""),
            p.definition.source,
            button("Rever", async () => {
              const resources = (await api("raw/objects/resource")).items,
                resource = resources.find((x) =>
                  x.definition.aliases.some(
                    (a) => a.area === p.area && a.name === p.machine,
                  ),
                );
              if (!resource) {
                await editConfig(
                  "resource",
                  null,
                  {
                    aliases: [{ area: p.area, name: p.machine }],
                    operations: p.definition.operation
                      ? [p.definition.operation]
                      : [],
                    confirmed: false,
                  },
                  p.machine,
                );
                return;
              }
              await editConfig(
                p.kind,
                null,
                {
                  ...p.definition,
                  resource_id: resource.id,
                  source_evidence: p.provenance,
                },
                p.machine +
                  (p.kind === "calendar"
                    ? ` · W${p.definition.week}/${p.definition.year}`
                    : " · taxa"),
              );
            }),
          ]),
        ),
      );
    };
    search.oninput = show;
    show();
  }
  async function copyCalendar(obj) {
    const b = panel("Copiar calendário · " + obj.name),
      fields = {};
    for (const [k, l] of [
      ["start_year", "Ano inicial"],
      ["start_week", "Semana inicial"],
      ["end_year", "Ano final"],
      ["end_week", "Semana final"],
    ]) {
      fields[k] = input("", "number");
      b.append(field(l, fields[k]));
    }
    const out = el("div");
    b.append(
      button("Comparar alterações", async () => {
        const p = {
            source_id: obj.id,
            expected_revision: obj.revision,
            ...Object.fromEntries(
              Object.entries(fields).map(([k, i]) => [k, i.value]),
            ),
          },
          r = await api("raw/capacidade/copiar", req(p));
        out.replaceChildren(
          table(
            ["Ano", "Semana", "Ação"],
            r.changes.map((x) => [
              x.definition.year,
              x.definition.week,
              x.existing ? "Substituir calendário existente" : "Criar",
            ]),
          ),
        );
        out.append(
          button(
            "Confirmar cópia",
            async () => {
              await api(
                "raw/capacidade/copiar",
                req({ ...p, confirm: true, evidence_hash: r.evidence_hash }),
              );
              await configuration("calendar");
            },
            "primary",
          ),
        );
      }),
      out,
    );
  }
  async function saveReference() {
    if ($("unscheduled")?.checked)
      throw new Error("Escolhe uma semana com ano conhecido.");
    const p = {
      area: state.area,
      version: state.data.version,
      year: +$("year").value,
      week: +$("week").value,
    };
    const r = await api("raw/capacidade/referencia/preview", p),
      b = panel("Guardar referência do plano semanal"),
      name = input(`Plano W${p.week}/${p.year} · ${state.area}`);
    b.append(
      el(
        "p",
        `${r.count} operações, ${r.known} com quantidade conhecida. Quantidade abrangida: ${fmt(r.quantity)}.`,
      ),
      el("p", r.notice, "warning-box"),
      field("Nome", name),
      table(
        ["OF", "Referência", "Operação", "Quantidade"],
        r.examples.map((x) => [
          x.values.of,
          x.values.component_ref,
          x.values.operation,
          fmt(x.values.quantity),
        ]),
      ),
    );
    b.append(
      button(
        "Confirmar e guardar referência",
        async () => {
          const saved = await api(
            "raw/capacidade/referencia",
            req({
              ...p,
              token: r.token,
              name: name.value,
              confirmed: true,
              expected_revision: 0,
            }),
          );
          await compliance(saved.id);
        },
        "primary",
      ),
    );
  }
  async function references() {
    const b = panel("Referências e cumprimento semanal"),
      r = await api("raw/capacidade/referencias?area=" + state.area);
    if (!r.items.length)
      b.append(
        el(
          "p",
          "Ainda não existe uma referência semanal guardada. Guarda o plano da semana para poder comparar produção e previsão.",
        ),
      );
    b.append(
      table(
        ["Referência", "Período", "Operações", "Criada em", "Revisão"],
        r.items.map((x) => [
          button(x.name, () => compliance(x.id)),
          `W${x.week}/${x.year}`,
          x.lines,
          stamp(x.created_at),
          x.revision,
        ]),
      ),
    );
  }
  async function compliance(id, page = 1, revision) {
    const d = await api("raw/capacidade/cumprimento", { id, page, revision }),
      b = panel("Cumprimento · " + d.reference.name),
      cov = d.coverage;
    b.append(el("p", d.notice, "warning-box"));
    const versions = await api("raw/objects/" + id + "/historico"),
      vselect = select(
        versions.versions.map((v) => ({
          value: v.revision,
          label: "Revisão " + v.revision,
        })),
        d.revision,
      );
    vselect.onchange = safe(() => compliance(id, 1, +vselect.value));
    b.append(field("Plano usado na comparação", vselect));
    b.append(
      el(
        "p",
        `${cov.known}/${cov.total} operações com evidência compatível · Cumprimento da parte conhecida: ${fmt(cov.percent)}% · Fora do plano: ${d.outside_plan.records} registos · Por associar/conferir: ${d.unmatched_records}.`,
      ),
    );
    b.append(
      table(
        [
          "OF",
          "Referência",
          "Operação",
          "Planeado",
          "Produzido OCR",
          "Cumprido",
          "Evidência",
        ],
        d.rows.map((r) => [
          r.of,
          r.reference,
          r.operation,
          fmt(r.planned),
          fmt(r.produced),
          fmt(r.fulfilled),
          r.compatibility
            ? button(r.evidence.length + " registos", () => {
                const out = el("div");
                out.append(
                  table(
                    ["Folha", "Data", "Quantidade"],
                    r.evidence.map((e) => [
                      e.values.sheet,
                      datePt(e.values.production_date),
                      fmt(e.values.quantity),
                    ]),
                  ),
                );
                b.append(out);
              })
            : "Revisão técnica por conferir",
        ]),
      ),
    );
    const nav = el("div", null, "actions");
    if (page > 1)
      nav.append(
        button("← Anterior", () => compliance(id, page - 1, d.revision)),
      );
    if (page * 100 < d.total)
      nav.append(
        button("Seguinte →", () => compliance(id, page + 1, d.revision)),
      );
    b.append(nav);
    if (d.outside_evidence.length)
      b.append(
        el("h3", "Produção fora da referência (até 100 registos)"),
        table(
          ["OF", "Referência", "Operação", "Data", "Quantidade"],
          d.outside_evidence.map((e) => [
            e.values.of,
            e.values.component_ref,
            e.values.operation,
            datePt(e.values.production_date),
            fmt(e.values.quantity),
          ]),
        ),
      );
  }
  $("area").value = state.area;
  $("area").onchange = safe(async () => {
    state.area = $("area").value;
    state.page = 1;
    await load();
  });
  $("filters").onsubmit = safe(async (e) => {
    e.preventDefault();
    state.page = 1;
    await load();
  });
  $("refresh").onclick = safe(load);
  $("size").onchange = safe(async () => {
    state.size = +$("size").value;
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
  $("files").onclick = safe(files);
  $("configure").onclick = safe(() => configuration());
  $("references").onclick = safe(references);
  $("new-reference").onclick = safe(saveReference);
  $("close-panel").onclick = () => $("panel").close();
  function closeEdit() {
    if (!confirm("Descartar as alterações deste formulário?")) return;
    state.editing = false;
    $("edit-panel").close();
  }
  $("close-edit").onclick = closeEdit;
  $("cancel-edit").onclick = closeEdit;
  $("edit-panel").addEventListener("cancel", (e) => {
    e.preventDefault();
    closeEdit();
  });
  window.addEventListener("beforeunload", (e) => {
    if (state.editing) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  const poll = safe(async () => {
      let delay = 1000;
      try {
      if (!state.data || state.editing || state.polling) return;
      state.polling=true;
      const d=await api("raw/workspace/atualizacao?area="+state.area+"&dataset="+(mode==="weekly"?"capacity":"capacity_machines")+"&version="+state.data.version);
      if (d.pending) delay = 250;
      if(d.available&&!state.editing)await load();
      } finally {
        state.polling=false;
        setTimeout(poll, delay);
      }
  });
  setTimeout(poll, 1000);
  safe(load)();
})();
