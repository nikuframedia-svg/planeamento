"use strict";
window.RawCharts = {
  render(container, result, onGroup) {
    const d = result.definition;
    if (!["bar", "line"].includes(d.visual)) return;
    if (d.visual === "line" && d.groups.length > 1) {
      const series = new Map();
      result.groups.forEach((row, i) => {
        const key = JSON.stringify(
          d.groups.slice(1).map((_, n) => row["g" + (n + 1)]),
        );
        if (!series.has(key)) series.set(key, []);
        series.get(key).push({ row, i });
      });
      let shown = 0;
      for (const [key, items] of series) {
        if (shown++ >= 20) break;
        const title = document.createElement("h3");
        title.textContent = JSON.parse(key)
          .map((v) => v ?? "Por confirmar")
          .join(" · ");
        container.append(title);
        RawCharts.render(
          container,
          {
            ...result,
            definition: { ...d, groups: d.groups.slice(0, 1) },
            groups: items.map((x) => x.row),
          },
          (i) => onGroup?.(items[i].i),
        );
      }
      if (series.size > 20) {
        const p = document.createElement("p");
        p.textContent =
          "20 séries apresentadas; todas as séries permanecem na tabela.";
        container.append(p);
      }
      return;
    }
    const NS = "http://www.w3.org/2000/svg";
    const colors = [
      "#277e8c",
      "#d58a37",
      "#6878b7",
      "#a75375",
      "#489776",
      "#8b7159",
      "#557d90",
      "#9a873c",
    ];
    const byUnit = new Map();
    d.metrics.forEach((m, i) => {
      const unit = m.unit || "";
      if (!byUnit.has(unit)) byUnit.set(unit, []);
      byUnit.get(unit).push(i);
    });
    const make = (tag, attrs = {}, text) => {
      const x = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) x.setAttribute(k, v);
      if (text !== undefined) x.textContent = text;
      return x;
    };
    for (const [unit, metrics] of byUnit) {
      const wrap = document.createElement("div");
      const legend = document.createElement("p");
      legend.className = "muted";
      legend.textContent =
        metrics.map((i) => d.metrics[i].name).join(" · ") +
        (unit ? " (" + unit + ")" : "");
      wrap.append(legend);
      let rows = result.groups.map((r, i) => ({ r, i }));
      if (d.visual === "bar") {
        rows.sort(
          (a, b) =>
            Math.abs(b.r["m" + metrics[0]] || 0) -
            Math.abs(a.r["m" + metrics[0]] || 0),
        );
        rows = rows.slice(0, 20);
      }
      const vals = rows
        .flatMap(({ r }) => metrics.map((i) => r["m" + i]))
        .filter((x) => typeof x === "number");
      const min = Math.min(0, ...vals),
        max = Math.max(1, ...vals),
        range = max - min;
      const label = (r) =>
        Array.from(
          { length: d.groups.length },
          (_, i) => r["g" + i] ?? "Por confirmar",
        ).join(" · ") || "Total";
      const height =
        d.visual === "bar"
          ? Math.max(90, rows.length * (metrics.length * 18 + 20) + 25)
          : 300;
      const svg = make("svg", {
        viewBox: `0 0 850 ${height}`,
        role: "img",
        "aria-label": legend.textContent,
        style: "width:100%;height:auto",
      });
      const interact = (node, r, i, m, value) => {
        node.setAttribute("tabindex", "0");
        node.setAttribute("role", "button");
        node.setAttribute(
          "aria-label",
          label(r) + " " + d.metrics[m].name + " " + value,
        );
        node.append(
          make(
            "title",
            {},
            label(r) +
              " · " +
              d.metrics[m].name +
              ": " +
              value.toLocaleString("pt-PT"),
          ),
        );
        node.onclick = () => onGroup?.(i);
        node.onkeydown = (e) => {
          if (e.key === "Enter") onGroup?.(i);
        };
      };
      if (d.visual === "bar") {
        const scale = (v) => 220 + ((v - min) / range) * 500,
          zero = scale(0);
        rows.forEach(({ r, i }, n) => {
          const y = n * (metrics.length * 18 + 20) + 18;
          svg.append(
            make("text", { x: 0, y, "font-size": 12 }, label(r).slice(0, 29)),
          );
          metrics.forEach((m, j) => {
            const v = r["m" + m];
            if (v == null) return;
            const rect = make("rect", {
              x: Math.min(zero, scale(v)),
              y: y - 11 + j * 18,
              width: Math.max(1, Math.abs(scale(v) - zero)),
              height: 13,
              fill: colors[j % colors.length],
            });
            interact(rect, r, i, m, v);
            svg.append(
              rect,
              make(
                "text",
                { x: 730, y: y + j * 18, "font-size": 11 },
                v.toLocaleString("pt-PT", { maximumFractionDigits: 2 }),
              ),
            );
          });
        });
      } else {
        const x = (n) =>
          50 + (rows.length > 1 ? n / (rows.length - 1) : 0.5) * 750;
        const y = (v) => 250 - ((v - min) / range) * 205;
        for (let t = 0; t <= 4; t++) {
          const v = min + (range * t) / 4;
          svg.append(
            make("line", {
              x1: 50,
              x2: 800,
              y1: y(v),
              y2: y(v),
              stroke: "#e0e7e9",
            }),
            make(
              "text",
              { x: 0, y: y(v) + 4, "font-size": 10 },
              v.toLocaleString("pt-PT", { maximumFractionDigits: 1 }),
            ),
          );
        }
        metrics.forEach((m, j) => {
          let points = [];
          const flush = () => {
            if (points.length > 1)
              svg.append(
                make("polyline", {
                  points: points.join(" "),
                  fill: "none",
                  stroke: colors[j % colors.length],
                  "stroke-width": 2,
                }),
              );
            points = [];
          };
          rows.forEach(({ r, i }, n) => {
            const v = r["m" + m];
            if (v == null) {
              flush();
              return;
            }
            points.push(x(n) + "," + y(v));
            const circle = make("circle", {
              cx: x(n),
              cy: y(v),
              r: 3,
              fill: colors[j % colors.length],
            });
            interact(circle, r, i, m, v);
            svg.append(circle);
            if (n % Math.max(1, Math.ceil(rows.length / 7)) === 0)
              svg.append(
                make(
                  "text",
                  { x: x(n), y: 280, "font-size": 10, "text-anchor": "middle" },
                  label(r).slice(0, 18),
                ),
              );
          });
          flush();
        });
      }
      wrap.append(svg);
      if (d.visual === "bar" && result.groups.length > 20) {
        const note = document.createElement("p");
        note.className = "muted";
        note.textContent =
          "20 grupos principais; os restantes " +
          (result.groups.length - 20) +
          " estão na tabela completa.";
        wrap.append(note);
      }
      container.append(wrap);
    }
  },
};
