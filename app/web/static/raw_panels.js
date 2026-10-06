"use strict";
window.RawPanels = (() => {
  const R = Raw,
    {
      $,
      state,
      el,
      api,
      request,
      safe,
      fmt,
      drawer,
      field,
      button,
      input,
      select,
      smallTable,
    } = R;
  let conversation = null,
    chatScope = null,
    chatBox = null,
    activeAnalysis = null;
  async function views() {
    const box = drawer("Guardar e gerir vistas"),
      name = input(state.view?.name || ""),
      actions = el("div", undefined, "actions");
    box.append(
      field("Nome da vista", name),
      el(
        "p",
        "Guarda colunas, ordem, larguras, densidade, filtros e ordenação. Os dados continuam a atualizar.",
        "muted",
      ),
      actions,
    );
    async function save(duplicate = false, archived = false) {
      const p = {
        name: name.value,
        area: state.area,
        definition: R.config(),
        archived,
      };
      if (state.view && !duplicate) {
        p.id = state.view.id;
        p.expected_revision = state.view.revision;
      }
      const result = await api("raw/objects/view", request(p));
      await R.refreshViews();
      state.view = state.views.find((v) => v.id === result.id) || null;
      $("views").value = state.view?.id || "";
      $("drawer").close();
      $("notice").textContent = archived
        ? "Vista arquivada."
        : "Vista guardada.";
    }
    actions.append(
      button(
        state.view ? "Atualizar vista" : "Criar vista",
        () => save(),
        "primary",
      ),
    );
    if (state.view)
      actions.append(
        button("Duplicar", () => save(true)),
        button("Arquivar", () => save(false, true)),
      );
    if (state.view)
      box.append(
        button("Ver versões anteriores", async () => {
          const data = await api("raw/objects/" + state.view.id + "/historico");
          box.append(
            smallTable(
              ["Revisão", "Nome", "Data"],
              data.versions.map((v) => [v.revision, v.name, v.created_at]),
            ),
          );
        }),
      );
  }
  async function formula(format = false, proposal = null) {
    const box = drawer(format ? "Formatação condicional" : "Coluna calculada"),
      name = input(proposal?.title || ""),
      expr = el("textarea"),
      unit = input(proposal?.column_unit || ""),
      style = select(["warning", "success", "danger", "accent"], "warning");
    expr.value = proposal?.column_expression || "";
    expr.placeholder = format
      ? "[remaining] > 0"
      : "[remaining] * [length_mm] / 1000";
    const list = el("datalist");
    list.id = "formula-fields";
    for (const f of state.fields) {
      const o = el("option");
      o.value = "[" + f.id + "]";
      o.label = f.label;
      list.append(o);
    }
    const pick = select(
      [
        { value: "", label: "Inserir campo…" },
        ...state.fields.map((f) => ({ value: f.id, label: f.label })),
      ],
      "",
    );
    pick.onchange = () => {
      expr.setRangeText(
        "[" + pick.value + "]",
        expr.selectionStart,
        expr.selectionEnd,
        "end",
      );
      expr.focus();
      pick.value = "";
    };
    box.append(
      field("Nome", name),
      field("Fórmula / condição", expr),
      pick,
      list,
      el(
        "p",
        "Usa campos entre [ ]. A divisão por zero e entradas desconhecidas devolvem valor desconhecido. As somas exigem unidades compatíveis.",
        "muted",
      ),
    );
    box.append(
      format ? field("Destaque", style) : field("Unidade apresentada", unit),
    );
    const previewBox = el("div");
    box.append(
      button("Validar e pré-visualizar", async () => {
        const v = await api(
          "raw/formulas/preview",
          R.params({ expression: expr.value, unit: unit.value || null }),
        );
        previewBox.replaceChildren(
          el(
            "p",
            v.coverage.known +
              " de " +
              v.coverage.total +
              " linhas com resultado conhecido · " +
              (v.unit || "sem unidade"),
          ),
          el("p", v.unknowns, "muted"),
          smallTable(
            ["OF", "Referência", "Resultado"],
            v.examples.map((x) => [x.of, x.reference, fmt(x.value)]),
          ),
        );
      }),
      previewBox,
    );
    box.append(
      button(
        "Guardar e ativar",
        async () => {
          if (proposal && !previewBox.children.length)
            throw Error("Pré-visualiza a fórmula proposta antes de a ativar.");
          const definition = {
            expression: expr.value,
            unit: unit.value || null,
            style: style.value,
          };
          const result = await api(
            "raw/objects/" + (format ? "format" : "formula"),
            request({
              name: name.value,
              area: state.area,
              definition,
              confirmed: true,
            }),
          );
          if (!format)
            state.columns.push("calc_" + result.id.replaceAll("-", ""));
          else (state.format_ids ||= []).push(result.id);
          await R.load();
          $("drawer").close();
          $("notice").textContent = "Definição validada e ativada.";
        },
        "primary",
      ),
    );
    expr.addEventListener("input", () => previewBox.replaceChildren());
    unit.addEventListener("input", () => previewBox.replaceChildren());
    const existing = await api(
      "raw/objects/" + (format ? "format" : "formula") + "?area=" + state.area,
    );
    box.append(el("h3", "Definições guardadas"));
    for (const obj of existing.items)
      box.append(
        button(obj.name, () => {
          name.value = obj.name;
          expr.value = obj.definition.expression || "";
          unit.value = obj.definition.unit || "";
          box.append(
            button(
              "Guardar nova revisão",
              async () => {
                await api(
                  "raw/objects/" + (format ? "format" : "formula"),
                  request({
                    id: obj.id,
                    expected_revision: obj.revision,
                    name: name.value,
                    area: state.area,
                    definition: {
                      ...obj.definition,
                      ast: undefined,
                      expression: expr.value,
                      unit: unit.value,
                      style: style.value,
                    },
                    confirmed: true,
                  }),
                );
                $("drawer").close();
                await R.load();
              },
              "primary",
            ),
          );
        }),
      );
  }
  async function sources() {
    const box = drawer("Fontes e atualização");
    box.append(el("p", state.data.cpis_mode || ""));
    if (state.data.cpis_checked_at)
      box.append(
        el("p", "Última confirmação CPIS: " + state.data.cpis_checked_at),
      );
    box.append(
      el(
        "p",
        "Versão da tabela: " +
          state.data.version +
          " · " +
          state.data.created_at,
        "muted",
      ),
    );
    const files = await api("raw/ficheiros");
    box.append(
      smallTable(
        ["Macro", "Drive consultado", "Importação", "Geração RAW", "Estado"],
        files.sources.map((x) => [
          x.area,
          fmt(x.drive?.checked_at),
          fmt(x.imported?.loaded_at),
          x.generation?.id ?? "Por preparar",
          x.drive?.error ||
            (x.newer_available
              ? x.newer_folder
                ? `Versão mais recente na pasta «${x.newer_folder}» do Drive; a carga automática só lê a raiz`
                : "Versão no Drive ainda não importada"
              : x.drive?.checked_at
                ? "Hash do Drive e importação coincidem"
                : "Drive por verificar"),
        ]),
      ),
    );
    box.append(el("p", files.notice, "muted"));
    const worker = await api("raw/workspace/fontes");
    box.append(
      smallTable(
        ["Consulta", "Última tentativa", "Última confirmação", "Estado"],
        worker.sources.map((x) => [
          {
            perfis: "Planeamento / OCR Perfis",
            cantoneiras: "Planeamento / OCR Cantoneiras",
            capacity: "Capacidade",
            original: "OCR original",
          }[x.source] || x.source,
          fmt(x.attempted_at),
          fmt(x.confirmed_at),
          x.error || (x.stale ? "Atualização em atraso" : "Confirmado"),
        ]),
      ),
    );
    const data = await api("fontes");
    function flatten(obj, prefix = "") {
      const rows = [];
      for (const [k, v] of Object.entries(obj || {})) {
        if (v && typeof v === "object" && !Array.isArray(v))
          rows.push(...flatten(v, prefix + k + " · "));
        else if (!Array.isArray(v)) rows.push([prefix + k, fmt(v)]);
      }
      return rows;
    }
    box.append(smallTable(["Fonte / indicador", "Informação"], flatten(data)));
    const link = el("a", "Consultar OCR original separadamente");
    link.href = "/planeamento/ocr-original";
    link.target = "_blank";
    box.append(
      link,
      el(
        "p",
        "Atualizar lista consulta os dados disponíveis. Não força a leitura direta do CPIS.",
        "muted",
      ),
    );
  }
  async function exportTable(format) {
    const r = await fetch("/planeamento/api/raw/exportar/" + format, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(R.params({ columns: state.columns })),
    });
    if (!r.ok) {
      const x = await r.json();
      throw Error(x.error || x.detail);
    }
    const a = el("a");
    a.href = URL.createObjectURL(await r.blob());
    a.download = "raw." + format;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  function more() {
    const box = drawer("Ferramentas da tabela");
    box.append(
      button("Exportar tabela filtrada · CSV", () => exportTable("csv")),
      button("Exportar tabela filtrada · XLSX", () => exportTable("xlsx")),
      button("Formatação condicional", () => formula(true)),
      button("Análises e resultados guardados", reports),
      button("Conversas guardadas", conversations),
      button("Consultar produção por dia / semana", () =>
        chat(
          "Mostra a produção validada por máquina e semana, com a cobertura dos dados.",
        ),
      ),
    );
    box.append(
      el(
        "p",
        "Seleciona células com Shift e copia com Ctrl+C. Cola com Ctrl+V em campos editáveis: o lote é validado integralmente antes de guardar.",
        "muted",
      ),
    );
  }
  async function capacity() {
    const box = drawer("Capacidade semanal", undefined, true),
      tabs = el("div", undefined, "tabs"),
      content = el("div");
    box.append(tabs, content);
    tabs.append(
      button("Máquina × semana", matrix),
      button("Máquinas físicas", () => config("resource")),
      button("Calendários", () => config("calendar")),
      button("Parâmetros de tempo", () => config("rate")),
      button("Fontes importadas", sourceRows),
    );
    let resources = [];
    async function matrix() {
      content.replaceChildren(
        el(
          "p",
          "Recursos físicos das duas áreas. Rascunhos e horas reais são apresentados separadamente.",
          "muted",
        ),
      );
      const search = input(),
        year = input(),
        week = input(),
        draft = el("input"),
        controls = el("div", undefined, "field-grid"),
        wrap = el("div"),
        nav = el("div", undefined, "actions");
      draft.type = "checkbox";
      let page = 1;
      controls.append(
        field("Máquina", search),
        field("Ano ISO", year),
        field("Semana ISO", week),
        field("Incluir rascunhos no cenário", draft),
        button(
          "Consultar",
          () => {
            page = 1;
            return paint();
          },
          "primary",
        ),
      );
      content.append(controls, wrap, nav);
      async function paint() {
        const filters = [];
        if (search.value)
          filters.push({
            field: "machine",
            op: "contains",
            value: search.value,
          });
        if (year.value)
          filters.push({ field: "year", op: "eq", value: year.value });
        if (week.value)
          filters.push({ field: "week", op: "eq", value: week.value });
        const d = await api("raw/consultas", {
          area: state.area,
          dataset: "capacity",
          page_size: 100,
          page,
          filters,
          order: [
            { field: "year", direction: "desc" },
            { field: "week", direction: "asc" },
            { field: "machine", direction: "asc" },
          ],
        });
        wrap.replaceChildren(
          smallTable(
            [
              "Máquina",
              "Semana",
              "Disponíveis (h)",
              "Carga (h)",
              "Horas reais declaradas",
              "Cobertura das horas",
              "Livres (h)",
              "Ocupação",
              "Cobertura",
            ],
            d.rows.map((r) => {
              const v = r.values,
                ds = draft.checked ? r.draft_lines : [],
                unknown =
                  (v.unknown_load || 0) +
                  ds.filter((x) => x.hours == null).length,
                load = unknown
                  ? null
                  : (v.planned_hours ?? 0) +
                    ds.reduce((n, x) => n + (x.hours || 0), 0);
              return [
                v.machine,
                v.year ? v.year + " · " + v.week : "Por calendarizar",
                fmt(v.available_hours),
                fmt(load),
                fmt(v.actual_hours),
                (r.actual_coverage?.known || 0) +
                  "/" +
                  (r.actual_coverage?.total || 0) +
                  " folhas",
                load != null && v.available_hours != null
                  ? fmt(v.available_hours - load)
                  : "Por confirmar",
                load != null && v.available_hours > 0
                  ? fmt((load / v.available_hours) * 100) + "%"
                  : "—",
                (r.coverage?.known || 0) + "/" + (r.coverage?.total || 0),
              ];
            }),
            (i) => {
              const r = d.rows[i],
                lines = [...r.lines, ...(draft.checked ? r.draft_lines : [])];
              wrap.append(
                el("h3", r.values.machine + " · peças abrangidas"),
                smallTable(
                  ["OF", "Referência", "Operação", "Horas", "Motivo"],
                  lines.map((x) => [
                    x.of,
                    x.component_ref,
                    x.operation,
                    fmt(x.hours),
                    x.reason || "Taxa confirmada",
                  ]),
                  (j) =>
                    window.open(
                      "/planeamento/raw?area=" +
                        lines[j].area +
                        "&need=" +
                        encodeURIComponent(lines[j].key),
                      "_blank",
                    ),
                ),
              );
            },
          ),
        );
        nav.replaceChildren(
          el("span", d.total + " períodos · página " + page),
          button("Anterior", () => {
            if (page > 1) {
              page--;
              return paint();
            }
          }),
          button("Seguinte", () => {
            if (page * 100 < d.total) {
              page++;
              return paint();
            }
          }),
        );
      }
      draft.onchange = safe(paint);
      await paint();
    }
    async function config(kind) {
      const data = await api("raw/objects/" + kind);
      resources = (await api("raw/objects/resource")).items;
      content.replaceChildren(
        button(
          "Adicionar " +
            { resource: "máquina", calendar: "semana", rate: "parâmetro" }[
              kind
            ],
          () => edit(kind),
        ),
      );
      content.append(
        smallTable(
          ["Nome", "Área", "Revisão", "Confirmação"],
          data.items.map((x) => [
            x.name,
            x.area,
            x.revision,
            x.definition.confirmed ? "Confirmado" : "Por confirmar",
          ]),
          (i) => edit(kind, data.items[i]),
        ),
      );
    }
    async function edit(kind, obj, initial) {
      content.replaceChildren();
      const name = input(obj?.name || ""),
        d = obj?.definition || initial || {},
        form = el("div", undefined, "field-grid"),
        controls = {};
      content.append(field("Nome", name), form);
      function add(key, label, node) {
        controls[key] = node;
        form.append(field(label, node));
      }
      const choices = resources.map((r) => ({ value: r.id, label: r.name }));
      if (kind === "resource") {
        const aliases = el("textarea");
        aliases.value = (d.aliases || [{ area: state.area, name: "" }])
          .map((a) => a.area + ":" + a.name)
          .join("\n");
        add("aliases", "Nomes equivalentes: uma área:nome por linha", aliases);
        add(
          "operations",
          "Operações suportadas (separadas por vírgula)",
          input((d.operations || []).join(",")),
        );
      } else {
        add(
          "resource_id",
          "Máquina física",
          select(
            [{ value: "", label: "Selecionar" }, ...choices],
            d.resource_id,
          ),
        );
        if (kind === "calendar") {
          add("year", "Ano ISO", input(d.year || ""));
          add("week", "Semana ISO", input(d.week || ""));
          add("shifts", "Turnos na semana", input(d.shifts ?? ""));
          add(
            "hours_per_shift",
            "Horas por turno",
            input(d.hours_per_shift ?? ""),
          );
          add(
            "exception_hours",
            "Horas indisponíveis (exceções)",
            input(d.exception_hours ?? 0),
          );
        } else {
          add(
            "area",
            "Área",
            select(["perfis", "cantoneiras"], d.area || state.area),
          );
          add("operation", "Código da operação", input(d.operation || ""));
          add(
            "material_type",
            "Família aplicável (vazio: todas)",
            input(d.material_type || ""),
          );
          add(
            "profile",
            "Perfil aplicável (vazio: todos)",
            input(d.profile || ""),
          );
          add(
            "method",
            "Método",
            select(
              [
                { value: "area_hour", label: "Área de corte por hora · mm²/h" },
                { value: "metres_hour", label: "Velocidade · m/h" },
                { value: "units_hour", label: "Unidades por hora" },
                { value: "minutes_unit", label: "Minutos por unidade" },
                {
                  value: "fixed_minutes",
                  label: "Minutos fixos de preparação",
                },
              ],
              d.method || "area_hour",
            ),
          );
          add("value", "Valor confirmado", input(d.value ?? ""));
          add(
            "setup_minutes",
            "Preparação adicional (min)",
            input(d.setup_minutes ?? 0),
          );
          add("valid_from", "Válido desde", input(d.valid_from || "", "date"));
          add(
            "valid_until",
            "Válido até (opcional)",
            input(d.valid_until || "", "date"),
          );
        }
      }
      add("source", "Origem / justificação", input(d.source || ""));
      const confirmed = el("input");
      confirmed.type = "checkbox";
      confirmed.checked = !!d.confirmed;
      add("confirmed", "Parâmetros conferidos para utilização", confirmed);
      const actions = el("div", undefined, "actions");
      content.append(actions);
      actions.append(
        button(
          "Guardar",
          async () => {
            const definition = { ...d };
            for (const [k, c] of Object.entries(controls))
              definition[k] = k === "confirmed" ? c.checked : c.value;
            if (kind === "resource") {
              definition.aliases = controls.aliases.value
                .split("\n")
                .filter(Boolean)
                .map((x) => {
                  const i = x.indexOf(":");
                  return {
                    area: x.slice(0, i).trim(),
                    name: x.slice(i + 1).trim(),
                  };
                });
              definition.operations = controls.operations.value
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean);
            }
            await api(
              "raw/objects/" + kind,
              request({
                id: obj?.id,
                expected_revision: obj?.revision || 0,
                name: name.value,
                area: state.area,
                definition,
              }),
            );
            await config(kind);
          },
          "primary",
        ),
        button("Voltar", () => config(kind)),
      );
      if (kind === "calendar" && obj)
        actions.append(
          button("Copiar para outras semanas", () => copyCalendar(obj)),
        );
      if (obj)
        actions.append(
          button("Arquivar", async () => {
            await api(
              "raw/objects/" + kind,
              request({
                id: obj.id,
                expected_revision: obj.revision,
                name: obj.name,
                area: obj.area,
                definition: obj.definition,
                archived: true,
              }),
            );
            await config(kind);
          }),
        );
    }
    async function copyCalendar(obj) {
      content.replaceChildren();
      const fields = {};
      for (const [k, label] of [
        ["start_year", "Ano inicial"],
        ["start_week", "Semana inicial"],
        ["end_year", "Ano final"],
        ["end_week", "Semana final"],
      ]) {
        fields[k] = input();
        content.append(field(label, fields[k]));
      }
      content.append(
        button(
          "Comparar alterações",
          async () => {
            const p = {
              source_id: obj.id,
              expected_revision: obj.revision,
              ...Object.fromEntries(
                Object.entries(fields).map(([k, i]) => [k, i.value]),
              ),
            };
            const comparison = await api("raw/capacidade/copiar", request(p));
            const table = smallTable(
              ["Ano", "Semana", "Situação"],
              comparison.changes.map((x) => [
                x.definition.year,
                x.definition.week,
                x.existing
                  ? "Substituir calendário existente"
                  : "Criar calendário",
              ]),
            );
            if (await R.confirm("Confirmar cópia do calendário", table)) {
              await api(
                "raw/capacidade/copiar",
                request({
                  ...p,
                  confirm: true,
                  evidence_hash: comparison.evidence_hash,
                }),
              );
              await config("calendar");
            }
          },
          "primary",
        ),
      );
    }
    async function sourceRows() {
      const data = await api("raw/capacidade/propostas");
      resources = (await api("raw/objects/resource")).items;
      content.replaceChildren(el("p", data.notice, "muted"));
      const search = input(),
        list = el("div");
      content.append(field("Filtrar máquina ou fonte", search), list);
      function paint() {
        const found = data.proposals.filter((p) =>
          (p.machine + " " + p.area + " " + p.definition.source)
            .toLowerCase()
            .includes(search.value.toLowerCase()),
        );
        list.replaceChildren(
          smallTable(
            ["Área", "Máquina", "Tipo", "Valor / semana", "Origem"],
            found
              .slice(0, 200)
              .map((p) => [
                p.area,
                p.machine,
                p.kind === "calendar" ? "Calendário" : "Taxa",
                p.kind === "calendar"
                  ? p.definition.year +
                    " · S" +
                    p.definition.week +
                    " · " +
                    p.definition.shifts +
                    " turnos × " +
                    p.definition.hours_per_shift +
                    " h"
                  : fmt(p.definition.value) +
                    " " +
                    (p.definition.method === "area_hour" ? "mm²/h" : "m/h"),
                p.definition.source,
              ]),
            (i) => {
              const p = found[i],
                resource = resources.find((r) =>
                  r.definition.aliases.some(
                    (a) => a.area === p.area && a.name === p.machine,
                  ),
                );
              if (!resource) {
                $("drawer-error").textContent =
                  "Define primeiro a máquina física e associa o nome «" +
                  p.machine +
                  "».";
                return;
              }
              edit(p.kind, null, { ...p.definition, resource_id: resource.id });
            },
          ),
        );
        if (found.length > 200)
          list.append(
            el(
              "p",
              found.length +
                " propostas. Refina a pesquisa para selecionar a fonte.",
              "muted",
            ),
          );
      }
      search.oninput = paint;
      paint();
    }

    await matrix();
  }
  async function conversations() {
    const box = drawer("Conversas guardadas"),
      data = await api("raw/objects/conversation?area=" + state.area);
    for (const c of data.items)
      box.append(
        button(c.name, async () => {
          conversation = c;
          await chat();
        }),
      );
    box.append(
      button(
        "Nova conversa",
        async () => {
          conversation = null;
          await chat();
        },
        "primary",
      ),
    );
  }
  async function chat(initial = "") {
    const box = drawer("Analisar os dados");
    chatScope = R.params({
      page: undefined,
      page_size: undefined,
      version: undefined,
      selected: state.selected.size ? [...state.selected] : undefined,
    });
    const scope = el(
      "p",
      state.selected.size
        ? "Âmbito: " + state.selected.size + " linhas selecionadas."
        : "Âmbito: todos os " +
            (state.data?.total || 0).toLocaleString("pt-PT") +
            " resultados dos filtros, incluindo outras páginas.",
      "muted",
    );
    const tools = el("div", undefined, "tabs");
    tools.append(
      button("Conversas", conversations),
      button("Análises guardadas", reports),
      button("Nova conversa", () => {
        conversation = null;
        return chat();
      }),
    );
    chatBox = el("div");
    const text = el("textarea");
    text.placeholder = "Pergunta sobre o planeamento, produção ou capacidade…";
    text.value = initial;
    const send = button("Enviar", submit, "primary"),
      line = el("div", undefined, "chat-input");
    line.append(text, send);
    box.append(scope, tools, chatBox, line);
    if (conversation) {
      const data = await api("raw/conversas/" + conversation.id);
      conversation = data.conversation;
      chatScope = conversation.definition.scope || chatScope;
      scope.textContent =
        "Âmbito guardado da conversa: " +
        (chatScope.selected?.length
          ? chatScope.selected.length + " linhas selecionadas"
          : chatScope.q || "filtros confirmados na conversa");
      tools.append(
        button("Usar os filtros atuais da tabela", () => {
          chatScope = R.params({
            version: undefined,
            selected: state.selected.size ? [...state.selected] : undefined,
          });
          scope.textContent =
            "Âmbito atualizado com os filtros atuais da tabela.";
        }),
      );
      for (const m of data.messages) showMessage(m.role, m.content, m.proposal);
    }
    async function submit() {
      send.disabled = true;
      try {
        const r = await api(
          "raw/chat",
          request({
            conversation_id: conversation?.id,
            expected_revision: conversation?.revision,
            area: state.area,
            message: text.value,
            scope: chatScope,
          }),
        );
        conversation = r.conversation;
        showMessage("user", text.value);
        text.value = "";
        const target = chatBox,
          currentConversation = conversation.id,
          waiting = el("p", "A preparar a definição da análise…", "busy");
        target.append(waiting);
        const job = await waitJob(r.job_id);
        waiting.remove();
        if (
          conversation?.id !== currentConversation ||
          !document.contains(target)
        )
          return;
        if (job.status === "failed") throw Error(job.error);
        showMessage(
          "assistant",
          job.result.proposal.clarification || job.result.proposal.explanation,
          job.result.proposal,
        );
      } finally {
        send.disabled = false;
      }
    }
  }
  function showMessage(role, content, proposal) {
    const m = el("div", content, "message " + role);
    chatBox.append(m);
    if (proposal && !proposal.clarification)
      m.append(
        button("Rever fontes, fórmula e resultados", () =>
          reviewProposal(proposal),
        ),
      );
  }
  async function waitJob(id) {
    for (let i = 0; i < 180; i++) {
      const job = await api("raw/jobs/" + id);
      if (["done", "failed"].includes(job.status)) return job;
      await new Promise((r) => setTimeout(r, 2000));
    }
    throw Error(
      "A análise continua em processamento. Podes reabri-la nas conversas ou execuções guardadas.",
    );
  }
  async function reviewProposal(definition, existing = null) {
    if (["formula", "format"].includes(definition.kind))
      return formula(definition.kind === "format", definition);
    const box = drawer("Confirmar a definição da análise"),
      name = input(definition.title || ""),
      scope = el(
        "p",
        "Fonte: " + definition.dataset + " · " + definition.area,
        "pill",
      );
    box.append(
      scope,
      field("Nome da análise", name),
      el("p", definition.explanation || "", "muted"),
    );
    const metrics = [];
    for (const m of definition.metrics) {
      const e = input(m.expression || "");
      metrics.push(e);
      box.append(field(m.name + " · fórmula", e));
    }
    const groups = input(
      (definition.group_by || [])
        .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
        .join(";"),
    );
    box.append(
      field("Agrupamentos (separados por ponto e vírgula)", groups),
      el(
        "p",
        "Desconhecidos mantêm-se desconhecidos. A cobertura mostra quantas linhas sustentam cada medida.",
        "muted",
      ),
    );
    const previewBox = el("div"),
      actions = el("div", undefined, "actions");
    box.append(previewBox, actions);
    let preview = null;
    for (const control of [name, groups, ...metrics])
      control.addEventListener("input", () => {
        preview = null;
        previewBox.replaceChildren(
          el(
            "p",
            "Definição alterada. Volta a pré-visualizar antes de confirmar.",
            "muted",
          ),
        );
      });
    async function calculate() {
      const d = {
        ...definition,
        title: name.value,
        group_by: groups.value
          .split(";")
          .map((x) => x.trim())
          .filter(Boolean),
        metrics: definition.metrics.map((m, i) => ({
          ...m,
          ast: undefined,
          expression: metrics[i].value,
        })),
      };
      preview = await api("raw/analises/preview", { definition: d });
      previewBox.replaceChildren();
      renderReport(preview.preview, previewBox);
      previewBox.prepend(
        el(
          "p",
          "Filtros: " +
            (preview.definition.filters || [])
              .map(
                (f) =>
                  f.field +
                  " " +
                  f.op +
                  " " +
                  (f.value || f.values?.join(",") || f.min || ""),
              )
              .join(" · "),
          "muted",
        ),
      );
    }
    actions.append(
      button("Pré-visualizar", calculate),
      button(
        "Confirmar e atualizar automaticamente",
        async () => {
          if (!preview) await calculate();
          const r = await api(
            "raw/analises/confirmar",
            request({
              id: existing?.id,
              expected_revision: existing?.revision || 0,
              name: name.value,
              definition: preview.definition,
              evidence_hash: preview.evidence_hash,
              automatic: true,
            }),
          );
          box.replaceChildren(el("p", "Definição confirmada. A calcular…"));
          const job = await waitJob(r.job_id);
          if (job.status === "failed") throw Error(job.error);
          showRun(job, box);
        },
        "primary",
      ),
    );
    await calculate();
  }
  function renderReport(result, box, jobId) {
    const d = result.definition;
    const groups = result.groups || [];
    const heading = d.metrics.map(
      (m) => m.name + (m.unit ? " (" + m.unit + ")" : ""),
    );
    const count = d.groups?.length || 0;
    const details = (i) => {
      if (jobId) return drill(jobId, groups[i], count);
    };
    box.append(
      el(
        "p",
        result.rows.toLocaleString("pt-PT") +
          " linhas · " +
          fmt(result.created_at),
        "muted",
      ),
    );
    if (d.visual === "metric" && groups.length === 1)
      box.append(el("div", fmt(groups[0].m0), "metric"));
    RawCharts.render(box, result, details);
    const tableBox = el("div"),
      pageLabel = el("span");
    let page = 0;
    function paint() {
      tableBox.replaceChildren(
        smallTable(
          [
            ...Array.from({ length: count }, (_, i) => "Grupo " + (i + 1)),
            ...heading,
            "Cobertura",
          ],
          groups
            .slice(page * 100, page * 100 + 100)
            .map((r) => [
              ...Array.from({ length: count }, (_, i) => fmt(r["g" + i])),
              ...d.metrics.map((m, i) => fmt(r["m" + i])),
              d.metrics
                .map((m, i) => r["known" + i] + "/" + r.rows)
                .join(" · "),
            ]),
          (i) => details(page * 100 + i),
        ),
      );
      pageLabel.textContent =
        page + 1 + " / " + Math.max(1, Math.ceil(groups.length / 100));
    }
    box.append(
      tableBox,
      button("Anterior", () => {
        if (page > 0) {
          page--;
          paint();
        }
      }),
      pageLabel,
      button("Seguinte", () => {
        if ((page + 1) * 100 < groups.length) {
          page++;
          paint();
        }
      }),
    );
    paint();
    if (d.explanation)
      box.append(el("p", "Interpretação do modelo: " + d.explanation, "muted"));
  }
  async function drill(id, row, count) {
    const box = drawer("Linhas que suportam o resultado", undefined, true);
    let page = 1;
    async function paint() {
      const r = await api("raw/jobs/" + id + "/evidencia", {
        groups: Array.from({ length: count }, (_, i) => row["g" + i]),
        page,
      });
      box.replaceChildren(
        el("p", r.total + " linhas da execução guardada.", "muted"),
      );
      const keys = [...new Set(r.rows.flatMap((x) => Object.keys(x.values)))];
      box.append(
        smallTable(
          keys,
          r.rows.map((x) => keys.map((k) => fmt(x.values[k]))),
        ),
      );
      box.append(
        button("Anterior", () => {
          if (page > 1) {
            page--;
            return paint();
          }
        }),
        button("Seguinte", () => {
          if (page * 100 < r.total) {
            page++;
            return paint();
          }
        }),
      );
    }
    await paint();
  }
  function showRun(job, box) {
    box.replaceChildren();
    $("drawer-title").textContent =
      job.result?.definition?.title || "Resultado da análise";
    if (job.status !== "done") {
      box.append(el("p", job.error || "Execução " + job.status));
      if (job.status === "failed")
        box.append(
          button("Repetir execução", async () => {
            await api("raw/jobs/repetir", request({ id: job.id }));
            box.replaceChildren(el("p", "A repetir…"));
            showRun(await waitJob(job.id), box);
          }),
        );
      return;
    }
    renderReport(job.result, box, job.id);
    const actions = el("div", undefined, "actions");
    for (const type of ["json", "html"]) {
      const a = el("a", "Exportar " + type.toUpperCase());
      a.href = "/planeamento/api/raw/jobs/" + job.id + "/exportar/" + type;
      actions.append(a);
    }
    box.append(actions);
  }
  async function reports() {
    const box = drawer("Análises guardadas"),
      data = await api("raw/objects/analysis?area=" + state.area);
    for (const obj of data.items) {
      const card = el("div", undefined, "card");
      card.append(
        el("h3", obj.name),
        el(
          "p",
          obj.definition.automatic
            ? "Atualização automática ativa"
            : "Resultado fixo",
          "muted",
        ),
        button("Abrir resultados e histórico", async () => {
          const runs = await api("raw/execucoes/" + obj.id);
          const sub = drawer(obj.name);
          for (const run of runs.runs)
            sub.append(
              button(fmt(run.created_at) + " · " + run.status, async () => {
                activeAnalysis = null;
                showRun(await api("raw/jobs/" + run.id), sub);
              }),
            );
          if (runs.runs.length) {
            const done = runs.runs.find((r) => r.status === "done"),
              result = el("div"),
              status = el("p", undefined, "muted");
            sub.append(status, result);
            if (done) showRun(await api("raw/jobs/" + done.id), result);
            status.textContent =
              runs.runs[0].status === "failed"
                ? "Atualização falhou. Último resultado conservado."
                : runs.runs[0].status === "done"
                  ? "Resultado atualizado automaticamente."
                  : "A atualizar; último resultado conservado.";
            activeAnalysis = {
              id: obj.id,
              holder: result,
              status,
              last: done?.id,
            };
            if (!done)
              showRun(await api("raw/jobs/" + runs.runs[0].id), result);
          }
        }),
        button("Rever definição", () => reviewProposal(obj.definition, obj)),
        button(
          obj.definition.automatic
            ? "Suspender atualização automática"
            : "Ativar atualização automática",
          async () => {
            await api(
              "raw/analises/estado",
              request({
                id: obj.id,
                expected_revision: obj.revision,
                automatic: !obj.definition.automatic,
              }),
            );
            await reports();
          },
        ),
        button("Arquivar análise", async () => {
          await api(
            "raw/analises/estado",
            request({
              id: obj.id,
              expected_revision: obj.revision,
              archived: true,
            }),
          );
          await reports();
        }),
      );
      box.append(card);
    }
    if (!data.items.length)
      box.append(
        el(
          "p",
          "Pede uma análise no chat e confirma a definição para a guardar.",
        ),
      );
    const old = await api("raw/analises");
    if (old.analyses?.length) {
      box.append(el("h3", "Relatórios anteriores (fixos)"));
      for (const r of old.analyses) {
        const a = el("a", r.title);
        a.href = "/planeamento/api/raw/analises/" + r.id + "/html";
        a.target = "_blank";
        box.append(el("p")).append(a);
      }
    }
  }
  async function associations(row) {
    const box = drawer("Produção e quantidade em falta"),
      of = row.values.of;
    box.append(el("p", of + " · " + row.values.component_ref));
    if (!row.need_id) {
      box.append(
        el(
          "p",
          "Guarda primeiro uma ficha desta peça para associar a produção à sua identidade permanente.",
        ),
      );
      const a = el("a", "Abrir formulário");
      a.href =
        "/planeamento/manual?area=" +
        state.area +
        "&of=" +
        encodeURIComponent(of) +
        "&linha=" +
        encodeURIComponent(row.plan_key || "");
      a.target = "_blank";
      box.append(a);
      return;
    }
    const detail = await api("necessidades/" + row.need_id),
      ops = detail.operations.filter((x) => x.area === state.area),
      op = select(
        ops.map((x) => ({ value: x.id, label: x.code })),
        row.operation_id || ops[0]?.id,
      ),
      proofBox = el("div");
    box.append(field("Operação da peça", op), proofBox);
    async function proof() {
      const e = (
        await api(
          "necessidades/" + row.need_id + "/evidencia?operacao=" + op.value,
        )
      ).evidence;
      proofBox.replaceChildren(
        smallTable(
          ["Necessário", "Saldo macro", "OCR associado"],
          [[fmt(e.required), fmt(e.macro_remaining), fmt(e.ocr_quantity)]],
        ),
      );
      const req = input(e.required),
        remaining = input(),
        reason = input();
      proofBox.append(
        field("Quantidade total confirmada", req),
        field("Quantidade em falta confirmada", remaining),
        field("Justificação", reason),
        button(
          "Guardar confirmação",
          async () => {
            await api(
              "conferencias",
              request({
                need_id: row.need_id,
                operation_id: op.value,
                expected_revision: detail.need.revision,
                evidence_hash: e.evidence_hash,
                accepted_required: req.value,
                accepted_remaining: remaining.value,
                reason: reason.value,
              }),
            );
            proofBox.append(el("p", "Confirmação guardada."));
          },
          "primary",
        ),
      );
    }
    op.onchange = safe(proof);
    await proof();
    box.append(el("h3", "Associações de produção"));
    const status = select(
        [
          { value: "pending", label: "Por associar / rever" },
          { value: "associated", label: "Associações guardadas" },
          { value: "unrelated", label: "Sem correspondência" },
          { value: "all", label: "Todos os registos" },
        ],
        "pending",
      ),
      list = el("div"),
      nav = el("div", undefined, "actions");
    let page = 1;
    box.append(status, list, nav);
    async function load() {
      const pending = await api(
        "producao/pendencias?of=" +
          encodeURIComponent(of) +
          "&area=" +
          state.area +
          "&estado=" +
          status.value +
          "&pagina=" +
          page,
      );
      list.replaceChildren();
      for (const r of pending.records) {
        const card = el("div", undefined, "card");
        card.append(
          el(
            "p",
            "Folha " +
              r.sheet_no +
              " · linha " +
              r.row_index +
              " · " +
              r.machine +
              " · " +
              fmt(r.quantity) +
              " un.",
          ),
          el("p", r.reason, "muted"),
          button("Conferir associação / distribuição", () => distribute(r)),
        );
        list.append(card);
      }
      nav.replaceChildren(
        el("span", pending.total + " registos · página " + page),
        button("Anterior", () => {
          if (page > 1) {
            page--;
            return load();
          }
        }),
        button("Seguinte", () => {
          if (page * 50 < pending.total) {
            page++;
            return load();
          }
        }),
      );
    }
    status.onchange = safe(() => {
      page = 1;
      return load();
    });
    await load();
    async function distribute(r) {
      const panel = drawer("Distribuir produção validada", undefined, true),
        allocations = [],
        details = new Map([[row.need_id, detail]]),
        candidates = [...r.candidates];
      if (!candidates.some((x) => x.id === row.need_id))
        candidates.push(detail.need);
      const reason = input(),
        rows = el("div");
      panel.append(
        el(
          "p",
          "Folha " +
            r.sheet_no +
            " · linha " +
            r.row_index +
            " · " +
            fmt(r.quantity) +
            " un.",
        ),
        el(
          "p",
          "Cada quantidade só conta numa distribuição. As referências filhas usam as quantidades congeladas. Guardar substitui a associação anterior, sem alterar o OCR.",
          "muted",
        ),
        rows,
      );
      async function add(prior = {}) {
        const line = el("div", undefined, "card"),
          need = select(
            candidates.map((n) => ({
              value: n.id,
              label:
                n.component_ref +
                " · " +
                (n.specification?.profile || "perfil por confirmar") +
                " · " +
                fmt(n.specification?.length_mm) +
                " mm",
            })),
            prior.need_id || row.need_id,
          ),
          operation = select([], ""),
          child = select(
            [
              {
                value: "",
                label: r.children?.length
                  ? "Selecionar referência filha"
                  : "Registo simples",
              },
              ...(r.children || []).map((x) => ({
                value: x.plan_key,
                label:
                  (x.component_ref || x.plan_key) +
                  " · " +
                  fmt(x.assumed_quantity) +
                  " un.",
              })),
            ],
            prior.child_key || "",
          ),
          quantity = input(
            prior.quantity ?? (r.children?.length ? "" : r.quantity),
          ),
          item = { need, operation, child, quantity, line };
        allocations.push(item);
        rows.append(line);
        line.append(field("Peça", need), field("Operação", operation));
        if (r.children?.length)
          line.append(field("Referência congelada", child));
        line.append(
          field("Quantidade associada (vazio: desconhecida)", quantity),
          button("Retirar distribuição", () => {
            allocations.splice(allocations.indexOf(item), 1);
            line.remove();
          }),
        );
        async function operations() {
          if (!details.has(need.value))
            details.set(need.value, await api("necessidades/" + need.value));
          const d = details.get(need.value);
          operation.replaceChildren();
          for (const o of d.operations.filter((o) => o.area === state.area)) {
            const choice = el("option", o.code);
            choice.value = o.id;
            operation.append(choice);
          }
          operation.value =
            prior.operation_id || operation.options[0]?.value || "";
        }
        need.onchange = safe(operations);
        child.onchange = () => {
          quantity.value =
            r.children.find((x) => x.plan_key === child.value)
              ?.assumed_quantity ?? "";
        };
        await operations();
      }
      for (const a of r.decision?.allocations || []) await add(a);
      if (!allocations.length) await add();
      panel.append(
        button("Adicionar outra distribuição", () => add()),
        field("Justificação", reason),
      );
      async function save(status) {
        const values =
          status === "associated"
            ? allocations.map((a) => ({
                need_id: a.need.value,
                operation_id: a.operation.value,
                expected_need_revision: details.get(a.need.value).need.revision,
                child_key: a.child.value || null,
                quantity: a.quantity.value === "" ? null : a.quantity.value,
              }))
            : [];
        await api(
          "associacoes",
          request({
            production_record_id: r.id,
            expected_revision: r.decision?.revision || 0,
            evidence_hash: r.evidence_hash,
            status,
            reason: reason.value,
            allocations: values,
          }),
        );
        await associations(row);
      }
      panel.append(
        button("Guardar distribuição", () => save("associated"), "primary"),
        button("Manter pendente / revogar associação", () => save("pending")),
        button("Nenhuma das peças corresponde", () => save("unrelated")),
      );
    }
  }
  $("view-actions").onclick = safe(views);
  $("formula").onclick = safe(() => formula());
  $("capacity").onclick = () => {
    location.href = "/planeamento/capacidades?area=" + state.area;
  };
  $("chat").onclick = safe(() => chat());
  $("sources").onclick = safe(sources);
  $("more").onclick = more;
  setInterval(
    safe(async () => {
      const a = activeAnalysis;
      if (!a || !$("drawer").open || !document.contains(a.holder)) return;
      const r = await api("raw/execucoes/" + a.id),
        latest = r.runs[0],
        done = r.runs.find((x) => x.status === "done");
      if (latest)
        a.status.textContent =
          latest.status === "failed"
            ? "Atualização falhou; resultado anterior conservado."
            : latest.status === "done"
              ? "Atualizado em " + fmt(latest.finished_at)
              : "A atualizar…";
      if (done && done.id !== a.last) {
        showRun(await api("raw/jobs/" + done.id), a.holder);
        a.last = done.id;
      }
    }),
    15000,
  );
  return { associations, chat, capacity, reports, formula };
})();
