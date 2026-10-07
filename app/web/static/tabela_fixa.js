'use strict';
// Cabeçalho fixo das tabelas largas (P2, 08/10/2026): Carteira e grelhas da Carga.
// O position:sticky nos <th> não funcionava: a caixa com scroll horizontal passa a ser o contentor do sticky e
// nunca faz scroll vertical. Aqui fica uma cópia do cabeçalho (e de linhas extra, como o Subtotal) presa por baixo
// do menu, com as larguras das colunas do original e o mesmo scroll horizontal da caixa. A página mantém um só
// scroll vertical. O cabeçalho verdadeiro fica no sítio (leitores de ecrã, testes); a cópia é aria-hidden e inert.
// Uso: stickyHead(caixa, tabela, {extra: tbody}) → {refresh}. Chamar outra vez para a mesma tabela não duplica.
window.stickyHead = function stickyHead(box, table, {extra = null} = {}) {
  if (!box || !table) return null;
  if (table._stickyHead) return table._stickyHead;
  const root = document.documentElement;
  const menu = document.querySelector('.pl-header');
  const wrap = document.createElement('div');
  const inner = document.createElement('div');
  const copy = document.createElement('table');
  wrap.className = 'sticky-head';
  wrap.setAttribute('aria-hidden', 'true');
  wrap.setAttribute('inert', '');
  inner.className = 'sticky-head-in';
  copy.className = `${table.className} sticky-copy`;
  inner.append(copy);
  wrap.append(inner);
  box.before(wrap);
  root.classList.add('has-sticky-head'); // liga o scroll-padding-top (o foco e o scrollIntoView não ficam tapados)
  let frame = 0;

  const menuHeight = () => root.style.setProperty('--pl-head-h', `${Math.round(menu ? menu.getBoundingClientRect().height : 0)}px`);

  function place() {
    const top = menu ? menu.getBoundingClientRect().bottom : 0;
    const t = table.getBoundingClientRect();
    wrap.classList.toggle('on', t.height > 0 && t.top < top && t.bottom > top + copy.offsetHeight);
  }

  function widths(row) {
    // Largura de cada coluna pelas posições das células do original (uma célula com colspan reparte-se igual).
    const out = [];
    const cells = [...row.cells];
    cells.forEach((cell, i) => {
      const r = cell.getBoundingClientRect();
      const right = i + 1 < cells.length ? cells[i + 1].getBoundingClientRect().left : r.right;
      for (let k = 0; k < cell.colSpan; k += 1) out.push((right - r.left) / cell.colSpan);
    });
    return out;
  }

  function build() {
    frame = 0;
    const head = table.tHead;
    const t = table.getBoundingClientRect();
    if (!head || !head.rows.length || !t.height) { wrap.classList.remove('on'); return; }
    const parts = [head.cloneNode(true), ...(extra && extra.rows.length ? [extra.cloneNode(true)] : [])];
    for (const part of parts) {
      part.removeAttribute('id');
      part.querySelectorAll('[id]').forEach((n) => n.removeAttribute('id'));
    }
    const cols = document.createElement('colgroup');
    for (const w of widths(head.rows[0])) {
      const col = document.createElement('col');
      col.style.width = `${w}px`;
      cols.append(col);
    }
    copy.replaceChildren(cols, ...parts);
    copy.style.width = `${t.width}px`;
    // A janela da cópia = a área visível da caixa (sem as bordas).
    const b = box.getBoundingClientRect();
    inner.style.left = `${b.left - wrap.getBoundingClientRect().left + box.clientLeft}px`;
    inner.style.width = `${box.clientWidth}px`;
    inner.scrollLeft = box.scrollLeft;
    root.style.setProperty('--sticky-h', `${Math.round(copy.getBoundingClientRect().height)}px`);
    place();
  }

  const later = () => { if (!frame) frame = requestAnimationFrame(build); };
  box.addEventListener('scroll', () => { inner.scrollLeft = box.scrollLeft; }, {passive: true});
  addEventListener('scroll', place, {passive: true});
  addEventListener('resize', () => { menuHeight(); later(); });
  const resized = new ResizeObserver(later);
  resized.observe(table);
  resized.observe(box);
  // Linhas novas, títulos e subtotais mudam as larguras das colunas.
  new MutationObserver(later).observe(table, {subtree: true, childList: true, characterData: true});
  menuHeight();
  build();
  table._stickyHead = {refresh: later};
  return table._stickyHead;
};
