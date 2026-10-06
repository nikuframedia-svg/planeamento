// Explicação dos nomes (06/10/2026): qualquer elemento com data-nome="<chave>" recebe no cursor a explicação de
// static/nomes.json (nome, campo do CPIS e coluna do Excel). Um só sítio para todas as páginas.
(() => {
  'use strict';
  let fields = null;
  const explain = (key) => {
    const f = fields && fields[key];
    if (!f) return null;
    const excel = f.excel ? Object.entries(f.excel).map(([area, col]) => `${area === 'perfis' ? 'MTG2' : 'MTG3'}: ${col}`).join(' · ') : null;
    return [f.explicacao, f.cpis ? `CPIS: ${f.cpis}` : null, excel ? `Excel: ${excel}` : null].filter(Boolean).join('\n');
  };
  const apply = (root) => {
    if (!fields) return;
    for (const node of (root.querySelectorAll ? root.querySelectorAll('[data-nome]') : [])) {
      if (!node.title) { const text = explain(node.dataset.nome); if (text) { node.title = text; node.classList.add('com-nome'); } }
    }
  };
  window.Nomes = {title: explain};
  fetch('/static/nomes.json', {cache: 'force-cache'}).then((r) => r.ok ? r.json() : null).then((data) => {
    fields = data && data.campos;
    apply(document);
    new MutationObserver((changes) => { for (const c of changes) for (const n of c.addedNodes) if (n.nodeType === 1) { apply(n); if (n.dataset && n.dataset.nome) apply(n.parentNode || document); } })
      .observe(document.body, {childList: true, subtree: true});
  }).catch(() => {});
})();
