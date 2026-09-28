(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const storage = {get(k) {try {return localStorage.getItem(k);} catch {return null;}}, set(k,v) {try {localStorage.setItem(k,v);} catch {}}};
  const entryParams=new URLSearchParams(location.search), initialDocument=entryParams.get('document'), selectedOrder=entryParams.get('of');
  if(selectedOrder){$('selected-order').textContent='OF selecionada: '+selectedOrder+'. Se o PDF indicar outra OF, pedimos confirmação antes de associar.';$('selected-order').hidden=false;$('manual-entry').href='/planeamento/manual?of='+encodeURIComponent(selectedOrder)}
  function editorUrl(piece){return '/planeamento/preparar?document='+encodeURIComponent(state.doc.id)+'&piece='+encodeURIComponent(piece.id)+(selectedOrder?'&of='+encodeURIComponent(selectedOrder):'')}
  function editorLink(piece,label='Abrir formulário'){return '<a class="button primary" href="'+editorUrl(piece)+'">'+label+'</a>'}
  const state = {documents:[], active:initialDocument||storage.get('planning-document'), doc:null, piece:null, page:1, sourceOpen:false, view:'documents', polling:false, loading:0, review:null, modelConfigured:false, pendingExport:null};
  const labels = {waiting_api:'Aguarda API',queued:'Em fila',indexing:'A identificar',extracting:'A ler desenhos',matching:'A cruzar',ready:'Preparado',review:'Conferir',error:'Interrompido',existing:'Já no plano',duplicate:'Já preparado',blocked:'Por resolver',superseded:'Substituído',excluded:'Excluído'};
  const busy = new Set(['queued','indexing','extracting','matching']);
  const fieldLabels = {component_ref:'Referência da peça',drawing_ref:'Desenho',drawing_revision:'Revisão do desenho',identity_discriminator:'Discriminador da peça',material_type:'Tipo de material',profile:'Perfil',grade:'Qualidade',quantity_required:'Quantidade necessária',length_mm:'Comprimento (mm)',outer_diameter_mm:'Diâmetro exterior (mm)',width_mm:'Largura (mm)',height_mm:'Altura (mm)',thickness_mm:'Espessura (mm)',angle_deg:'Ângulo indicado (°)',abocardar:'Abocardar',chanfro:'Chanfrar',ponteira:'Ponteira',variant:'Variante selecionada',material_description:'Designação do material',operations:'Operações',notes:'Observações'};
  const evidenceSources = {document:'leitura do documento',derived:'derivação verificável',catalog:'catálogo',human:'correção humana'};
  const numeric = new Set(['quantity_required','length_mm','outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg']);
  const base = '/planeamento/api';
  let sourceStatus=null,sourceChecked=0;
  const canExport=()=>{const age=Date.now()-Date.parse(sourceStatus?.cpis?.checked_at);return Boolean(sourceStatus?.completion_allowed&&age>=0&&age<900000)};
  const exportBlock='Falta uma consulta direta ao CPIS com menos de 15 minutos. A preparação fica guardada; a saída está bloqueada.';
  async function refreshSources(){if(Date.now()-sourceChecked<30000)return;sourceChecked=Date.now();try{sourceStatus=await api('/fontes')}catch{sourceStatus=null}if(state.doc){renderSummary(state.doc);for(const id of ['export-macro','export-csv']){if($(id)){$(id).disabled=state.doc.status!=='ready'||!canExport();$(id).title=canExport()?'':exportBlock}}}if($('export-all'))$('export-all').disabled=!canExport()}
  const fmt = (v) => v == null ? '—' : new Intl.NumberFormat('pt-PT',{maximumFractionDigits:3}).format(v);
  const badge = (status) => `<span class="badge ${esc(status)}">${esc(labels[status] || status)}</span>`;
  const effectiveValues = (piece) => piece.match?.effective_values || piece.values;
  const effectiveGroup = (piece) => piece.match?.machine_group || piece.machine_group || 'Por atribuir';
  const activePieces = (d) => (d.pieces || []).filter(p=>!['excluded','superseded'].includes(p.state));
  const closedOrder = (d) => (d.context?.issues || []).some(i=>i.code==='of_closed') || d.context?.status?.toLowerCase()==='fechada';
  const closedPiece = (p) => (p.issues || []).some(i=>['of_closed','plan_row_closed'].includes(i.code));
  const statusBadge = (text, style='') => `<span class="badge ${esc(style)}">${esc(text)}</span>`;
  function documentBadge(d) {
    if(closedOrder(d))return statusBadge('OF fechada · consulta','closed');
    if(['review','ready'].includes(d.status) && !(d.piece_count ?? d.pieces?.length))return statusBadge('Sem peças identificadas','review');
    return d.status==='review'?statusBadge('Há decisões pendentes','review'):badge(d.status);
  }
  function sourceText(source) {
    if(!source)return '';
    if(source.source==='plan')return `Plano, linha ${fmt(source.excel_row)}`;
    if(source.source==='catalog')return 'Catálogo da macro';
    if(source.source==='calculation')return 'Cálculo verificável';
    if(source.source==='document_or_user')return 'Documento ou escolha guardada';
    return source.page?`PDF, p. ${fmt(source.page)}`:'PDF';
  }

  async function api(path, options={}) {
    const response = await fetch(base + path, {...options, headers:{...(options.body instanceof FormData ? {} : {'Content-Type':'application/json'}),...(options.headers || {})}});
    let value;
    try {value = await response.json();} catch {throw new Error('Não foi possível concluir o pedido. Atualiza a página e tenta novamente.');}
    if (!response.ok) throw new Error(value.error || 'O pedido não foi concluído.');
    return value;
  }
  function notice(message, error=false) {
    const target = $(error ? 'alert' : 'notice');
    $(error ? 'notice' : 'alert').hidden = true;
    target.textContent = message; target.hidden = false;
  }
  function dialogResult(id, message, error=false) {
    $(id).textContent = message; $(id).hidden = false; $(id).classList.toggle('error', error);
  }
  function modalOpen() {return Boolean(document.querySelector('dialog[open]'));}

  function renderSummary(d) {
    const pieces=activePieces(d), quantity=pieces.reduce((sum,p)=>sum+(effectiveValues(p).quantity_required||0),0);
    const unknownQuantities=pieces.some(p=>effectiveValues(p).quantity_required==null);
    const waiting=pieces.filter(p=>p.issues?.some(i=>i.code==='machine_unresolved'));
    const disputed=pieces.filter(p=>p.issues?.length && !closedPiece(p));
    const docIssues=[...(d.issues||[]),...(d.context?.issues||[])];
    const found=`${fmt(pieces.length)} ${pieces.length===1?'referência encontrada':'referências encontradas'}`;
    let title=found, description=`${fmt(quantity)} unidades a fabricar${unknownQuantities?' · há quantidades por ler':''}`, tone='info', heading='Próximo passo', message='', button='';
    if(busy.has(d.status)) {
      title='A ler o PDF';description=`${fmt(d.checkpoint_counts?.inventory||0)} de ${fmt(d.page_count)} páginas lidas`;
      heading='Leitura em curso';message='Podes continuar a trabalhar. O resultado fica guardado.';
    } else if(d.status==='waiting_api') {
      title='PDF recebido';description='A leitura ainda não começou.';
      heading=state.modelConfigured?'Iniciar a leitura':'Ligar a leitura automática';
      message=state.modelConfigured?'O PDF está pronto para ser processado.':'É necessário configurar o modelo para ler as peças.';
      button=`<button class="button primary" data-next="${state.modelConfigured?'process':'configure'}">${state.modelConfigured?'Ler PDFs pendentes':'Configurar leitura'}</button>`;
    } else if(d.status==='error') {
      title='A leitura foi interrompida';description=pieces.length?`${found} até ao momento.`:'O PDF e as páginas já lidas estão guardados.';tone='error';
      heading='Retomar de onde parou';message=d.error || 'Não foi possível concluir a leitura.';
      button='<button class="button primary" data-next="resume">Retomar leitura</button>';
    } else if(closedOrder(d)) {
      title='OF fechada · apenas consulta';description=`${found} · ${fmt(quantity)} unidades no documento`;tone='closed';
      heading='Produção encerrada';message='Esta OF está fechada no CPIS. Podes consultar as peças; não será criada uma nova necessidade de produção.';
    } else if(!pieces.length) {
      title='Ainda não foram identificadas peças';description='O PDF foi recebido, mas a leitura não produziu peças para planear.';tone='review';
      heading='Voltar a ler o documento';message='Abre o PDF para localizar as peças. Uma nova leitura pode recuperar informação que ficou em falta.';
      button='<button class="button primary" data-next="reread">Ler novamente o PDF</button>';
    } else if(waiting.length && !docIssues.length) {
      tone='review';heading=waiting.length===1?'Falta escolher onde cortar':'Falta escolher o destino de corte';
      const v=effectiveValues(waiting[0]);
      message=`${v.component_ref || 'Peça sem referência'} · ${fmt(v.quantity_required)} unidades. O desenho e o plano não indicam uma máquina atribuída.`;
      button=`<button class="button primary" data-machine="${esc(waiting[0].id)}">Escolher destino de corte</button>`;
    } else if(d.status==='ready') {
      tone=canExport()?'ready':'review';heading=canExport()?'Pronto para o planeamento':'Preparação guardada · falta confirmar CPIS';message=canExport()?'Confere as alterações propostas antes de descarregar a cópia Excel.':exportBlock;
      button=`<button class="button primary" data-next="export" ${canExport()?'':'disabled'}>Preparar cópia Excel</button>`;
    } else if(docIssues.length) {
      tone='review';heading='Há informação a rever';message=docIssues[0].message;
      button=(d.issues||[]).length?'<button class="button primary" data-next="document">Rever dúvida do documento</button>':'<button class="button primary" data-next="refresh">Atualizar dados do plano</button>';
    } else if(disputed.length) {
      tone='review';heading=`${fmt(disputed.length)} ${disputed.length===1?'peça precisa de revisão':'peças precisam de revisão'}`;
      message=disputed[0].issues[0].message;
      button=`<button class="button primary" data-review="${esc(disputed[0].id)}">Rever ${esc(effectiveValues(disputed[0]).component_ref || 'peça')}</button>`;
    } else {
      tone='closed';heading='Linhas fechadas no plano';message='As peças estão disponíveis para consulta. As linhas já fechadas não podem ser alteradas automaticamente.';
    }
    if(d.common_preparation&&pieces.length&&!busy.has(d.status)&&!['error','waiting_api'].includes(d.status)&&!closedOrder(d)&&!docIssues.length){
      heading='Confirmar os dados das peças';message='Abre o formulário para rever os dados do PDF e indicar o trabalho a preparar.';button=editorLink(pieces[0]);
    }
    if(d.common_preparation&&!pieces.length&&!busy.has(d.status))button+=` <a class="button secondary" href="/planeamento/manual${d.production_order?'?of='+encodeURIComponent(d.production_order):selectedOrder?'?of='+encodeURIComponent(selectedOrder):''}">Preencher manualmente</a>`;
    $('document-summary').className=`document-summary ${tone}`;
    $('document-summary').innerHTML=`<div class="result-copy"><p class="eyebrow">${busy.has(d.status)?'Progresso':'Resultado da leitura'}</p><h3>${esc(title)}</h3><p>${esc(description)}</p>${busy.has(d.status)?`<progress max="100" value="${Number(d.progress)||0}" aria-label="Progresso da leitura"></progress>`:''}</div><div class="next-action"><strong>${esc(heading)}</strong><p>${esc(message)}</p>${button}</div>`;
  }

  function showSource(open=true) {
    state.sourceOpen=open;
    $('source-panel').hidden=!open;
    $('reading-layout').classList.toggle('with-source',open);
    $('toggle-source').setAttribute('aria-expanded',String(open));
    $('toggle-source').textContent=open?'Ocultar desenho':'Ver desenho';
    if(open)setPage(state.page);
  }

  function renderList() {
    $('document-count').textContent = state.documents.length;
    $('document-list').innerHTML = state.documents.length ? state.documents.map(d => `
      <button class="document-item" data-document="${esc(d.id)}" ${d.id === state.active ? 'aria-current="true"' : ''}>
        <span class="item-top"><strong>${esc(d.production_order || d.filename.replace(/\.pdf$/i,''))}</strong></span>
        <span class="filename">${esc(d.context?.customer || d.filename)}</span><p>${fmt(d.page_count)} páginas${d.piece_count ? ` · ${fmt(d.piece_count)} ${d.piece_count===1?'referência':'referências'}` : ''}</p>
        <p>${documentBadge(d)}</p>
      </button>`).join('') : '<p class="empty-copy">Adiciona os PDFs das OF para começar.</p>';
  }
  async function refreshList(force=false) {
    const data = await api('/dossies');
    state.documents = data.documents;
    const modelChanged = state.modelConfigured !== data.model.configured;
    state.modelConfigured = data.model.configured;
    labels.waiting_api = state.modelConfigured ? 'Aguarda leitura' : 'Aguarda API';
    $('inbox-status').hidden=!data.inbox?.enabled;
    if(data.inbox?.enabled){$('inbox-status').textContent=data.inbox.errors?.length?data.inbox.errors.map(e=>`${e.filename}: ${e.message}`).join(' · '):`Entrada automática pela pasta ${data.inbox.directory_name || 'configurada'}. Os novos PDFs são guardados nesta lista.`;$('inbox-status').classList.toggle('error',Boolean(data.inbox.errors?.length));}
    $('model-dot').classList.toggle('connected', data.model.configured);
    $('open-model').title = data.model.configured ? `Modelo configurado: ${data.model.model}` : 'Configurar API do modelo';
    $('process-waiting').hidden = !data.model.configured || !state.documents.some(d => d.status === 'waiting_api');
    renderList();
    if (!state.active || !state.documents.some(d => d.id === state.active)) state.active = state.documents[0]?.id || null;
    const current = state.documents.find(d => d.id === state.active);
    if (current && !modalOpen() && (force || modelChanged || !state.doc || current.revision !== state.doc.revision)) await openDocument(current.id, true);
    else if (state.doc && modelChanged) renderDocument();
  }
  async function openDocument(uid, polling=false) {
    const ticket = ++state.loading;
    if (!polling || state.active !== uid) {state.page=1;state.piece=null;state.doc=null;state.sourceOpen=false;$('evidence-details').open=false;$('processing-details').open=false;}
    state.active = uid;storage.set('planning-document',uid);renderList();
    const data = await api('/dossies/' + encodeURIComponent(uid));
    if (ticket !== state.loading) return;
    state.doc = data;
    if (!data.pieces.some(p => p.id === state.piece)) {
      const first=activePieces(data)[0] || data.pieces[0];
      state.piece=first?.id || null;
      state.page=first?.drawing_pages?.[0] || first?.index_page || 1;
    }
    renderDocument();
  }
  function renderDocument() {
    const d = state.doc;
    $('empty-selection').hidden = Boolean(d);$('document-detail').hidden = !d;
    if (!d) return;
    $('document-filename').textContent = 'Ordem de fabrico';
    $('document-title').textContent = d.production_order || 'Dossiê recebido';
    const ctx = d.context || {};
    $('document-customer').textContent = [ctx.customer,ctx.sales_order].filter(Boolean).join(' · ');
    $('document-metadata').textContent=[d.filename,ctx.designation,...(ctx.document_identifiers?.production_orders||[])].filter(Boolean).join(' · ');
    renderSummary(d);
    $('original-pdf').href = base + '/dossies/' + encodeURIComponent(d.id) + '/pdf';
    $('retry-document').hidden = !['error','waiting_api'].includes(d.status);
    $('refresh-context').hidden = !['ready','review','error'].includes(d.status) || !d.production_order;
    const readDone = ['ready','review','matching'].includes(d.status) && (d.checkpoint_counts?.inventory||0)===d.page_count;
    const imported = ctx.snapshot?.loaded_at ? new Date(ctx.snapshot.loaded_at).toLocaleDateString('pt-PT') : '';
    const exportDate = d.latest_export?.created_at ? new Date(d.latest_export.created_at).toLocaleString('pt-PT') : '';
    $('workflow').innerHTML = [
      ['PDF recebido',`${d.page_count} páginas`,'done'],
      ['Leitura do PDF',readDone ? `${d.pieces.length} ${d.pieces.length===1?'referência':'referências'}` : d.status==='waiting_api' ? (state.modelConfigured ? 'Leitura por iniciar' : 'API por configurar') : `${d.progress}%`,readDone && d.pieces.length ? 'done' : busy.has(d.status) ? 'active' : ''],
      ['CPIS importado da macro',ctx.status ? `${ctx.status} · importação ${imported} · sem confirmação direta neste contexto` : 'A aguardar',d.status==='matching' ? 'active' : ''],
      [d.latest_export?'Cópia Excel gerada':'Cópia Excel',d.latest_export?exportDate:closedOrder(d)?'Não aplicável · OF fechada':!canExport()?'Bloqueada · falta confirmar CPIS':d.status==='ready'?'Pronta para preparar':'Disponível após resolver as dúvidas',d.latest_export?'done':''],
    ].map(([title,description,className]) => `<div class="${className}"><strong>${esc(title)}</strong><p>${esc(description)}</p></div>`).join('');
    const docIssues = [...(d.issues||[]),...(ctx.issues||[])];
    const reviewable = (d.issues||[]).filter(i=>i.code!=='no_work_items');
    const noItems = (d.issues||[]).some(i=>i.code==='no_work_items');
    $('document-issues').hidden = !docIssues.length;
    $('document-issues').innerHTML = docIssues.length ? `<strong>${ctx.issues?.some(i=>i.code==='of_closed')?'Estado e dados do dossiê':'Dados a resolver'}</strong><ul>${docIssues.map(i=>`<li>${esc(i.message)}</li>`).join('')}</ul>${reviewable.length?'<button class="button secondary" id="open-document-review">Resolver identificação</button>':''}${noItems?'<button class="button secondary" id="restart-document-direct">Ler novamente o PDF</button>':''}` : '';
    $('piece-count').textContent = d.pieces.length;
    $('reading-state').hidden = d.pieces.length > 0 && d.status !== 'error' && !busy.has(d.status);
    if (d.status==='waiting_api') $('reading-state').innerHTML = state.modelConfigured
      ? '<strong>PDF guardado. A leitura ainda não começou.</strong><p>A API está configurada. Usa «Processar PDFs pendentes» para iniciar a leitura.</p>'
      : '<strong>PDF guardado. Falta ligar o modelo.</strong><p>Depois de configurares a API, o sistema identifica os desenhos e prepara as linhas.</p><button class="button secondary" id="configure-from-document">Configurar modelo</button>';
    else if (d.status==='error') {
      const completed=d.checkpoint_counts?.inventory||0,last=d.attempts?.[0];
      $('reading-state').innerHTML = `<strong>A leitura foi interrompida.</strong><p>${esc(d.error)}</p><p>${completed?`${completed} de ${d.page_count} páginas de inventário ficaram guardadas.`:'Nenhuma página de inventário ficou concluída nesta leitura.'}</p>${last?`<p class="diagnostic">Última tentativa: ${esc(last.stage)} · ${esc(last.status)}${last.metadata?.finish_reason?` · ${esc(last.metadata.finish_reason)}`:''}${last.metadata?.duration_ms?` · ${fmt(last.metadata.duration_ms/1000)} s`:''}</p>`:''}`;
    }
    else if (busy.has(d.status)) $('reading-state').innerHTML = `<strong>${esc(d.progress_label || 'PDF em fila para processamento')}</strong><p>Podes deixar esta página. O progresso fica guardado.</p><progress max="100" value="${Number(d.progress)||0}" aria-label="Progresso da leitura"></progress>`;
    else $('reading-state').innerHTML = '<strong>As peças encontradas vão aparecer aqui.</strong><p>Usa «Ler novamente o PDF» acima para repetir uma leitura sem resultados.</p>';
    $('piece-table').innerHTML = d.pieces.length ? pieceTable(d.pieces) : '';
    $('export-actions').hidden = d.status !== 'ready' || !d.pieces.length;
    for(const id of ['export-macro','export-csv']){$(id).disabled=!canExport();$(id).title=canExport()?'':exportBlock}
    $('reread-current-page').hidden=busy.has(d.status)||d.status==='waiting_api';
    showSource(state.sourceOpen);renderEvidence();
  }
  function pieceTable(pieces) {
    return `<table class="pieces-table"><thead><tr><th>Referência</th><th>Perfil / qualidade</th><th class="number">Quantidade</th><th class="number">Comprimento</th><th>Destino de corte</th><th>Estado</th></tr></thead><tbody>${pieces.map(p=>{
      const v=effectiveValues(p),g=effectiveGroup(p),sources=p.match?.field_sources||{},closed=closedPiece(p);
      const inactive=['superseded','excluded'].includes(p.state),editable=!inactive&&!busy.has(state.doc.status);
      const needsMachine=editable&&!closed&&p.issues.some(i=>i.code==='machine_unresolved');
      const status=inactive?badge(p.state):closed?statusBadge('Fechada · consulta','closed'):needsMachine?statusBadge('Falta destino','review'):badge(p.state);
      return `<tr class="${p.id===state.piece?'selected-row':''}"><td data-label="Referência"><button class="reference" data-piece="${esc(p.id)}" aria-label="Ver desenho de ${esc(v.component_ref||'peça sem referência')}">${esc(v.component_ref || 'Por identificar')}</button><small>${esc(sourceText(sources.component_ref)||'PDF')} · <button class="page-link" data-piece="${esc(p.id)}">Ver desenho</button></small></td>
        <td data-label="Perfil">${esc(v.profile || 'Por ler')}<small>${esc(v.grade || 'Qualidade por ler')}${sources.profile?` · ${esc(sourceText(sources.profile))}`:''}</small></td>
        <td data-label="Quantidade" class="number">${fmt(v.quantity_required)} <span class="unit">un.</span>${sources.quantity_required?.source==='plan'?`<small>${esc(sourceText(sources.quantity_required))}</small>`:''}</td>
        <td data-label="Comprimento" class="number">${fmt(v.length_mm)} <span class="unit">mm</span>${sources.length_mm?.source==='plan'?`<small>${esc(sourceText(sources.length_mm))}</small>`:''}</td>
        <td data-label="Destino">${needsMachine&&!state.doc.common_preparation?`<button class="row-action choose-machine" data-machine="${esc(p.id)}">Escolher destino</button>`:`<span class="route ${g==='Serrote'?'serrote':''}">${esc(g)}</span>`}<small>${esc(p.match?.assigned_machine||p.match?.machine_resolution?.assigned_machine||sourceText(sources.machine_group))}</small></td>
        <td data-label="Estado">${status}<small>${state.doc.common_preparation?(editable?`<a class="row-action" href="${editorUrl(p)}">Abrir formulário</a>`:''):`<button class="row-action" data-review="${esc(p.id)}" ${editable?'':'disabled'}>${closed?'Ver dados':needsMachine?'Ver / corrigir':p.issues.length?'Rever campos':'Ver / corrigir'}</button>`}</small></td></tr>`;
      }).join('')}</tbody></table>`;
  }
  function setPage(number) {
    if (!state.doc) return;
    state.page = Math.min(state.doc.page_count, Math.max(1, Math.trunc(Number(number)||1)));
    $('page-number').value=state.page;$('page-number').max=state.doc.page_count;
    $('page-total').textContent='/ '+state.doc.page_count;
    $('previous-page').disabled=state.page<=1;$('next-page').disabled=state.page>=state.doc.page_count;
    const url=base+'/dossies/'+encodeURIComponent(state.doc.id)+'/pagina/'+state.page;
    if (state.sourceOpen && $('page-image').getAttribute('src')!==url) $('page-image').src=url;
    $('page-image').alt=`${state.doc.filename} · página ${state.page}`;
    $('page-full').href=url;
  }
  function renderEvidence() {
    const p=state.doc?.pieces.find(p=>p.id===state.piece);
    $('piece-evidence').hidden=!p;
    $('evidence-details').hidden=!p;
    if (!p) return;
    const sources=p.match?.field_sources||{},selection=p.selection||{};
    $('piece-evidence').innerHTML=`<div class="evidence-heading"><h3>${esc(p.values.component_ref || 'Origem da linha')}</h3><button class="page-link" data-page="${p.index_page}">Índice · p. ${p.index_page}</button></div>
      ${selection.source?`<div class="evidence-item"><strong>Seleção da peça</strong><button class="page-link" data-page="${Number(selection.page||p.index_page)}">p. ${Number(selection.page||p.index_page)}</button><p>${esc(selection.evidence||selection.source)}</p><small>${esc(selection.source)}${selection.source_id?` · ${esc(selection.source_id)}`:''}</small></div>`:''}
      ${p.issues.length?`<ul class="evidence-issues">${p.issues.map(i=>`<li>${esc(i.message)}</li>`).join('')}</ul>`:''}
      ${Object.entries(p.values.evidence || {}).map(([field,ev])=>`<div class="evidence-item"><strong>${esc(fieldLabels[field]||field)}</strong><button class="page-link" data-page="${Number(ev.page)}">p. ${Number(ev.page)}</button><p>${esc(ev.text)}</p><small>${esc(evidenceSources[ev.source]||ev.source||'leitura do documento')}${ev.derivation?` · ${esc(ev.derivation)}`:''}</small></div>`).join('')}
      ${Object.entries(sources).filter(([,source])=>source.source!=='pdf').map(([field,source])=>`<div class="evidence-item"><strong>${esc(fieldLabels[field]||field)}</strong><p>${esc(effectiveValues(p)[field]??'—')}</p><small>${esc(sourceText(source))}</small></div>`).join('')}
      ${p.match?.excel_row?`<div class="evidence-item"><strong>Linha ${fmt(p.match.excel_row)} da macro importada</strong><p>Quantidade executada registada: ${fmt(p.match.quantity_completed)}. A extração preserva este registo.</p></div>`:''}`;
  }

  async function uploadFiles(files) {
    const pdfs=Array.from(files);
    if (!pdfs.length) return;
    $('pdf-files').disabled=true;$('upload-progress').hidden=false;
    let last=null,added=0,duplicates=0;
    try {
      for(let i=0;i<pdfs.length;i++) {
        const file=pdfs[i];
        if(!file.name.toLowerCase().endsWith('.pdf')) throw new Error(`${file.name}: seleciona apenas ficheiros PDF.`);
        if(file.size>80*1024*1024) throw new Error(`${file.name}: o limite por PDF é 80 MB.`);
        $('upload-progress').textContent=`A guardar ${i+1} de ${pdfs.length} · ${file.name}`;
        const form=new FormData();form.append('file',file);
        const result=await api('/dossies',{method:'POST',body:form});
        last=result.id;result.duplicate?duplicates++:added++;
      }
      notice([added?`${added} ${added===1?'dossiê guardado':'dossiês guardados'}.`:'',duplicates?`${duplicates} ${duplicates===1?'PDF já estava guardado':'PDFs já estavam guardados'}.`:''].filter(Boolean).join(' '));
    } catch(e) {notice(e.message,true);}
    finally {
      $('pdf-files').disabled=false;$('pdf-files').value='';$('upload-progress').hidden=true;
      if(last) {state.active=last;state.doc=null;state.page=1;}
      await refreshList(true);
    }
  }
  async function openModel() {
    const config=await api('/modelo');
    $('model-url').value=config.base_url;$('model-name').value=config.model;$('model-format').value=config.api_format;
    $('model-reasoning').value=config.reasoning_effort||'';$('model-reasoning-label').hidden=config.api_format==='bedrock_converse';
    $('model-key').value='';$('model-key').placeholder=config.has_key?'Chave guardada · deixa vazio para manter':'Cola aqui a chave';
    $('key-status').textContent=config.has_key?'A chave está guardada no servidor e não é devolvida ao browser.':'A chave é guardada apenas no servidor.';
    $('model-managed').hidden=!config.environment_managed;$('admin-code-label').hidden=config.can_configure;
    for(const id of ['model-url','model-name','model-format','model-reasoning','model-key','save-model']) $(id).disabled=config.environment_managed;
    $('model-result').hidden=true;$('model-dialog').showModal();
  }
  function openReview(pieceId) {
    if(state.doc.common_preparation){location.assign(editorUrl({id:pieceId}));return;}
    const p=state.doc.pieces.find(p=>p.id===pieceId);if(!p) return;
    state.review={piece:structuredClone(p),document:state.doc.id,initialValues:structuredClone(effectiveValues(p))};
    state.piece=p.id;setPage(p.drawing_pages[0]||p.index_page);renderEvidence();
    $('review-context').textContent=`${state.doc.production_order || state.doc.filename} · ${effectiveGroup(p)}`;
    $('review-title').textContent=`${p.issues.length&&!closedPiece(p)?'Rever':'Dados de'} ${p.values.component_ref || 'peça'}`;
    $('review-issues').hidden=!p.issues.length;
    $('review-issues').innerHTML=p.issues.length?`<ul>${p.issues.map(i=>`<li>${esc(i.message)}</li>`).join('')}</ul>`:'';
    const resolution=p.match?.material_resolution;
    $('resolution-details').hidden=!resolution;
    $('resolution-details').open=false;
    $('material-resolution').hidden=!resolution;
    if(resolution){const raw=resolution.raw||{},out=resolution.export||{},derived=resolution.derived||{},candidates=resolution.candidates||[],machine=p.match?.machine_resolution;
      const derivedText=Object.entries(derived).map(([key,value])=>`${fieldLabels[key]||key}: ${fmt(value)}`).join(' · ');
      const version=resolution.catalog_version?String(resolution.catalog_version).slice(0,12):'';
      $('material-resolution').innerHTML=`<strong>Resolução para a macro</strong><p>Leitura: ${esc(raw.material_type||'—')} · ${esc(raw.profile||'—')}</p><p>Valor efetivo: ${esc(out.material_type||'—')} · ${esc(out.profile||'—')} <span class="badge">${esc(resolution.status)}</span></p>${derivedText?`<p>Dimensões resolvidas: ${esc(derivedText)}</p>`:''}${machine?.assigned_machine?`<p>Máquina no plano: ${esc(machine.assigned_machine)}</p>`:''}${machine?.suggestions?.length?`<p>Sugestões históricas compatíveis: ${machine.suggestions.map(s=>esc(s.machine)).join(' · ')}</p>`:''}${version?`<p><small>Regra ${esc(resolution.version)} · catálogo ${esc(version)}</small></p>`:''}${candidates.length>1?`<p>Candidatos: ${candidates.map(c=>`${esc(c.family)} / ${esc(c.profile)}`).join(' · ')}</p>`:''}`;}
    $('review-machine-group').value=effectiveGroup(p);
    const primaryFields=new Set(['component_ref','material_type','profile','grade','quantity_required','length_mm',...p.issues.map(i=>i.field).filter(Boolean)]);
    const renderField=([key,label])=>{
      const value=state.review.initialValues[key],attention=p.issues.some(i=>i.field===key),cls=attention?' class="field-attention"':'';
      const difference=(p.match.differences||[]).find(d=>d.field===key);
      const comparison=difference?`<span class="field-help">PDF: ${esc(difference.pdf??'—')} · valor efetivo: ${esc(difference.resolved??difference.pdf??'—')} · plano: ${esc(difference.plan??'vazio')}</span>${difference.kind==='change'?`<span class="field-choices"><button type="button" class="row-action" data-value-choice="pdf" data-field="${esc(key)}">Usar PDF</button><button type="button" class="row-action" data-value-choice="plan" data-field="${esc(key)}" data-plan="${esc(difference.plan??'')}">Manter plano</button></span>`:''}`:(p.match?.field_sources?.[key]?`<span class="field-help">Valor efetivo: ${esc(effectiveValues(p)[key]??'—')} · ${esc(sourceText(p.match.field_sources[key]))}</span>`:'');
      if(['abocardar','chanfro','ponteira'].includes(key)) return `<label${cls}>${esc(label)}<select name="${key}"><option value="" ${value==null?'selected':''}>Não indicado</option><option value="X" ${value==='X'?'selected':''}>Indicado</option><option value="-" ${value==='-'?'selected':''}>Ausência explícita</option></select>${comparison}</label>`;
      if(key==='operations'||key==='notes') return `<label class="wide">${esc(label)}<textarea name="${key}" rows="2">${esc(Array.isArray(value)?value.join('\n'):value||'')}</textarea>${key==='operations'?'<span class="field-help">Uma operação por linha.</span>':''}</label>`;
      return `<label${cls}>${esc(label)}<input name="${key}" ${numeric.has(key)?`type="number" step="${key==='quantity_required'?'1':'any'}" ${key==='angle_deg'?'min="-360" max="360"':'min="0"'}`:'type="text"'} value="${esc(value??'')}" autocomplete="off">${comparison}</label>`;
    };
    const fields=Object.entries(fieldLabels);
    $('review-fields').innerHTML=`<div class="form-grid">${fields.filter(([key])=>primaryFields.has(key)).map(renderField).join('')}</div><details class="additional-fields"><summary>Mais dimensões, operações e observações</summary><div class="form-grid">${fields.filter(([key])=>!primaryFields.has(key)).map(renderField).join('')}</div></details>`;
    $('use-pdf').checked=false;$('confirm-chamfer').checked=false;$('replace-revision').checked=false;
    $('confirm-chamfer-label').hidden=!p.issues.some(i=>i.code==='chanfro_mapping');
    $('replace-label').hidden=!p.issues.some(i=>i.code==='revision_conflict');
    $('review-result').hidden=true;
    $('review-dialog').showModal();
  }
  function openMachine(pieceId) {
    if(state.doc.common_preparation){location.assign(editorUrl({id:pieceId}));return;}
    const p=state.doc.pieces.find(p=>p.id===pieceId);if(!p)return;
    state.machine={piece:structuredClone(p),document:state.doc.id};
    const v=effectiveValues(p);
    $('machine-form').reset();
    $('machine-context').textContent=state.doc.production_order || state.doc.filename;
    $('machine-piece-summary').textContent=`${v.component_ref || 'Peça sem referência'} · ${v.profile || 'Perfil por ler'} · ${fmt(v.quantity_required)} un. × ${fmt(v.length_mm)} mm`;
    $('machine-result').hidden=true;
    $('machine-dialog').showModal();
  }
  function openDocumentReview() {
    const d=state.doc;
    state.reviewDocument=structuredClone(d);
    $('review-of').value=d.production_order||'';
    $('document-review-checks').innerHTML=d.issues.map(i=>{
      const blocked=/^(unresolved_|empty_|no_work_items)/.test(i.code);
      return blocked?`<p class="notice">${esc(i.message)} É necessária nova leitura do desenho.</p>`:`<label class="checkbox"><input name="issue" type="checkbox" value="${esc(i.code)}">${esc(i.message)} — conferido no PDF.</label>`;
    }).join('');
    $('document-result').hidden=true;
    $('document-dialog').showModal();
  }
  async function download(format, uid=null, proposal=null) {
    const buttons=[$('export-macro'),$('export-csv'),$('export-all')];buttons.forEach(b=>b.disabled=true);
    notice(format==='xlsm'?'A conferir o CPIS e a preparar a cópia da macro…':'A conferir e a preparar as linhas…');
    try {
      const params=new URLSearchParams();if(uid)params.set('document',uid);if(proposal)params.set('proposal',proposal);
      const common=state.pendingExport?.id;const downloadUrl=common?base+'/saida-planeamento.'+format+'?proposta='+encodeURIComponent(common)+'&assinatura='+encodeURIComponent(state.pendingExport.proposal):base+'/saida/'+format+(params.size?'?'+params.toString():'');
      const response=await fetch(downloadUrl);
      if(!response.ok) {const data=await response.json();throw new Error(data.error||'Não foi possível gerar o ficheiro.');}
      const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download='Planeamento_preenchido.'+format;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
      notice(format==='xlsm'?'Cópia da macro gerada. Abre o ficheiro no Excel para recalcular as fórmulas.':'CSV das linhas preparado.');
    }catch(e){notice(e.message,true);}
    finally{buttons.forEach(b=>b.disabled=!canExport());await refreshList(true);}
  }
  async function previewExport(uid=null,format='xlsm') {
    const query=uid?'?document='+encodeURIComponent(uid):'';
    notice('A conferir o CPIS e a preparar a comparação por célula…');
    let proposal;
    if(state.doc?.common_preparation){
      if(!uid)throw new Error('Seleciona as preparações na OF para comparar a saída.');
      const refs=activePieces(state.doc).map(p=>({id:state.doc.id+'/'+p.id,version:state.doc.revision+':'+p.revision}));
      proposal=await api('/saida-propostas',{method:'POST',body:JSON.stringify({request_id:crypto.randomUUID(),pdf_refs:refs})});
    }else proposal=await api('/saida-proposta'+query);
    state.pendingExport={uid,proposal:proposal.proposal_fingerprint,id:proposal.id,format};
    $('export-summary').textContent=`${proposal.added} linhas novas, ${proposal.updated} linhas atualizadas e ${proposal.unchanged} sem alterações. ${proposal.cells.length} células serão escritas.`;
    $('export-change-table').innerHTML=proposal.cells.length?`<table><thead><tr><th>Linha / célula</th><th>Campo</th><th>Antes</th><th>Proposto</th><th>Motivo</th></tr></thead><tbody>${proposal.cells.map(c=>`<tr><td class="number">${fmt(c.row)} / ${esc(c.column)}</td><td>${esc(fieldLabels[c.field]||c.field)}</td><td>${esc(c.before??'vazio')}</td><td>${esc(c.after??'vazio')}</td><td><small>${esc(c.reason)}</small></td></tr>`).join('')}</tbody></table>`:'<p class="empty-copy">A cópia não altera células de entrada.</p>';
    $('export-result').hidden=true;$('export-dialog').showModal();
  }
  async function showNeeds() {
    state.view='needs';$('documents-view').hidden=true;$('needs-view').hidden=false;
    $('tab-documents').removeAttribute('aria-current');$('tab-needs').setAttribute('aria-current','page');
    const data=await api('/necessidades');const {rows}=data;
    if(data.needs){$('export-all').hidden=true;$('needs-table').innerHTML=data.needs.map(n=>`<p><a href="/planeamento/preparar?necessidade=${encodeURIComponent(n.id)}">${esc(n.production_order_no)} · ${esc(n.component_ref||'Rascunho')}</a> · ${fmt(n.quantity_required)} un.</p>`).join('')||'<p>Ainda não existem preparações comuns. Abre uma peça PDF ou seleciona uma OF para começar.</p>';return;}
    $('export-all').disabled=!rows.length||!canExport();$('export-all').title=canExport()?'':exportBlock;
    $('needs-table').innerHTML=rows.length?`<table><thead><tr><th>OF / cliente</th><th>Referência</th><th>Distribuição</th><th>Perfil</th><th class="number">Quantidade</th><th class="number">Comprimento mm</th><th>Origem</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.production_order)}</strong><small>${esc(r.context.customer||'')}</small></td><td>${esc(r.values.component_ref)}</td><td><span class="route ${r.machine_group==='Serrote'?'serrote':''}">${esc(r.machine_group)}</span></td><td>${esc(r.values.profile)}<small>${esc(r.values.grade)}</small></td><td class="number">${fmt(r.values.quantity_required)}</td><td class="number">${fmt(r.values.length_mm)}</td><td><button class="reference" data-open-document="${esc(r.document_id)}">${esc(r.filename)}</button><small>${badge(r.state)}</small></td></tr>`).join('')}</tbody></table>`:'<p class="empty-copy">As linhas aparecem aqui quando a leitura e o cruzamento estiverem concluídos e as dúvidas resolvidas.</p>';
  }
  function showDocuments() {
    state.view='documents';$('documents-view').hidden=false;$('needs-view').hidden=true;
    $('tab-needs').removeAttribute('aria-current');$('tab-documents').setAttribute('aria-current','page');
  }
  function run(action) {Promise.resolve().then(action).catch(e=>notice(e.message,true));}

  $('document-list').addEventListener('click',e=>{const b=e.target.closest('[data-document]');if(b)run(()=>openDocument(b.dataset.document));});
  $('piece-table').addEventListener('click',e=>{
    const machine=e.target.closest('[data-machine]');if(machine){openMachine(machine.dataset.machine);return;}
    const review=e.target.closest('[data-review]');if(review){openReview(review.dataset.review);return;}
    const b=e.target.closest('[data-piece]');if(!b)return;
    state.piece=b.dataset.piece;const p=state.doc.pieces.find(p=>p.id===state.piece);setPage(p.drawing_pages[0]||p.index_page);showSource();renderEvidence();$('piece-table').innerHTML=pieceTable(state.doc.pieces);
  });
  $('toggle-source').addEventListener('click',()=>showSource(!state.sourceOpen));
  $('piece-evidence').addEventListener('click',e=>{const b=e.target.closest('[data-page]');if(b){setPage(b.dataset.page);showSource();}});
  $('document-summary').addEventListener('click',e=>{
    const machine=e.target.closest('[data-machine]');if(machine){openMachine(machine.dataset.machine);return;}
    const review=e.target.closest('[data-review]');if(review){openReview(review.dataset.review);return;}
    const button=e.target.closest('[data-next]');if(!button)return;
    run(async()=>{
      const action=button.dataset.next;
      if(action==='document'){openDocumentReview();return;}
      if(action==='configure'){await openModel();return;}
      if(action==='export'){await previewExport(state.doc.id);return;}
      button.disabled=true;
      try {
        const paths={process:'/processar',resume:`/dossies/${state.doc.id}/retomar`,reread:`/dossies/${state.doc.id}/reler`,refresh:`/dossies/${state.doc.id}/cruzar`};
        await api(paths[action],{method:'POST',body:'{}'});
        await refreshList(true);
      } finally {button.disabled=false;}
    });
  });
  $('machine-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=e.submitter;button.disabled=true;
    try {
      const selected=$('machine-form').querySelector('input[name="machine_group"]:checked');
      if(!selected)return;
      const {piece,document:uid}=state.machine;
      await api(`/dossies/${uid}/linhas/${piece.id}`,{method:'PATCH',body:JSON.stringify({revision:piece.revision,values:{},machine_group:selected.value})});
      $('machine-dialog').close();notice(`Destino de corte guardado: ${selected.value}.`);await refreshList(true);
    } catch(error) {dialogResult('machine-result',error.message,true);}
    finally {button.disabled=false;}
  });
  $('document-issues').addEventListener('click',e=>{
    if(e.target.closest('#open-document-review'))openDocumentReview();
    if(e.target.closest('#restart-document-direct'))run(async()=>{await api('/dossies/'+state.doc.id+'/reler',{method:'POST',body:'{}'});notice('Nova leitura preparada; a anterior ficou no histórico.');await refreshList(true);});
  });
  $('reading-state').addEventListener('click',e=>{if(e.target.closest('#configure-from-document'))run(openModel);});
  $('pdf-files').addEventListener('change',e=>run(()=>uploadFiles(e.target.files)));
  for(const type of ['dragenter','dragover']) $('drop-zone').addEventListener(type,e=>{e.preventDefault();$('drop-zone').classList.add('dragging');});
  $('drop-zone').addEventListener('dragleave',()=> $('drop-zone').classList.remove('dragging'));
  $('drop-zone').addEventListener('drop',e=>{e.preventDefault();$('drop-zone').classList.remove('dragging');run(()=>uploadFiles(e.dataTransfer.files));});
  $('open-model').addEventListener('click',()=>run(openModel));
  for(const button of document.querySelectorAll('.close-dialog')) button.addEventListener('click',()=>{const d=button.closest('dialog');d.close();if(d.id==='model-dialog')$('model-key').value='';});
  $('model-dialog').addEventListener('close',()=>{$('model-key').value='';$('admin-code').value='';});
  $('model-format').addEventListener('change',()=>{const converse=$('model-format').value==='bedrock_converse';$('model-reasoning-label').hidden=converse;if(converse)$('model-reasoning').value='';});
  $('model-form').addEventListener('submit',async e=>{
    e.preventDefault();$('save-model').disabled=true;
    try{await api('/modelo',{method:'PUT',headers:{'X-Planning-Admin':$('admin-code').value},body:JSON.stringify({base_url:$('model-url').value,model:$('model-name').value,api_format:$('model-format').value,reasoning_effort:$('model-reasoning').value,api_key:$('model-key').value})});$('model-key').value='';dialogResult('model-result','Ligação guardada. Testa a leitura de imagem e processa os PDFs pendentes.');await refreshList();}
    catch(e){dialogResult('model-result',e.message,true);}finally{$('save-model').disabled=false;}
  });
  $('test-model').addEventListener('click',async()=>{
    $('test-model').disabled=true;dialogResult('model-result','A testar o modelo com uma imagem de exemplo…');
    try{const result=await api('/modelo/testar',{method:'POST',headers:{'X-Planning-Admin':$('admin-code').value},body:'{}'});dialogResult('model-result',result.message);}
    catch(e){dialogResult('model-result',e.message,true);}finally{$('test-model').disabled=false;}
  });
  $('process-waiting').addEventListener('click',()=>run(async()=>{await api('/processar',{method:'POST',body:'{}'});notice('PDFs colocados na fila de leitura.');await refreshList(true);}));
  $('retry-document').addEventListener('click',()=>run(async()=>{await api('/dossies/'+state.doc.id+'/retomar',{method:'POST',body:'{}'});await refreshList(true);}));
  $('refresh-context').addEventListener('click',()=>run(async()=>{await api('/dossies/'+state.doc.id+'/cruzar',{method:'POST',body:'{}'});await refreshList(true);}));
  $('previous-page').addEventListener('click',()=>setPage(state.page-1));$('next-page').addEventListener('click',()=>setPage(state.page+1));$('page-number').addEventListener('change',e=>setPage(e.target.value));
  $('review-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=e.submitter;button.disabled=true;
    try{
      const original=state.review.piece,values={};
      for(const [key] of Object.entries(fieldLabels)) {
        const raw=$('review-fields').querySelector(`[name="${key}"]`).value.trim();
        const value=numeric.has(key)?(raw===''?null:Number(raw)):key==='operations'?raw.split('\n').map(s=>s.trim()).filter(Boolean):key==='notes'?raw:(raw||null);
        if(JSON.stringify(value)!==JSON.stringify(state.review.initialValues[key]??null))values[key]=value;
      }
      const machineGroup=$('review-machine-group').value,machineChanged=machineGroup!==effectiveGroup(original);
      const payload={revision:original.revision,values,confirm_reading:Object.keys(values).length===0&&!machineChanged,use_pdf_values:$('use-pdf').checked,confirm_chamfer_mapping:$('confirm-chamfer').checked,replace_revision:$('replace-revision').checked};
      if(machineChanged)payload.machine_group=machineGroup;
      await api('/dossies/'+state.review.document+'/linhas/'+original.id,{method:'PATCH',body:JSON.stringify(payload)});
      $('review-dialog').close();notice('Alteração guardada e cruzamento atualizado.');await refreshList(true);
    }catch(e){dialogResult('review-result',e.message,true);}finally{button.disabled=false;}
  });
  $('document-review-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=e.submitter;button.disabled=true;
    try{await api('/dossies/'+state.reviewDocument.id+'/conferir',{method:'POST',body:JSON.stringify({revision:state.reviewDocument.revision,production_order:$('review-of').value,confirmed_codes:[...$('document-review-checks').querySelectorAll('input:checked')].map(i=>i.value)})});$('document-dialog').close();notice('Identificação do dossiê guardada.');await refreshList(true);}
    catch(e){dialogResult('document-result',e.message,true);}finally{button.disabled=false;}
  });
  $('exclude-piece').addEventListener('click',async()=>{
    const button=$('exclude-piece');button.disabled=true;
    try{await api('/dossies/'+state.review.document+'/linhas/'+state.review.piece.id+'/excluir',{method:'POST',body:JSON.stringify({revision:state.review.piece.revision})});$('review-dialog').close();notice('Linha excluída da preparação; a leitura original ficou no histórico.');await refreshList(true);}
    catch(e){dialogResult('review-result',e.message,true);}finally{button.disabled=false;}
  });
  $('reread-piece').addEventListener('click',async()=>{
    const button=$('reread-piece');button.disabled=true;
    try{await api('/dossies/'+state.review.document+'/linhas/'+state.review.piece.id+'/reler',{method:'POST',body:'{}'});$('review-dialog').close();notice('O desenho foi colocado em releitura; a extração anterior ficou no histórico.');await refreshList(true);}
    catch(e){dialogResult('review-result',e.message,true);}finally{button.disabled=false;}
  });
  $('restart-reading').addEventListener('click',async()=>{
    const button=$('restart-reading');button.disabled=true;
    try{await api('/dossies/'+state.reviewDocument.id+'/reler',{method:'POST',body:'{}'});$('document-dialog').close();notice('Nova leitura preparada. A extração anterior ficou guardada no histórico.');await refreshList(true);}
    catch(e){dialogResult('document-result',e.message,true);}finally{button.disabled=false;}
  });
  $('reread-current-page').addEventListener('click',()=>run(async()=>{if(!state.doc)return;const page=state.page;await api('/dossies/'+state.doc.id+'/paginas/'+page+'/reler',{method:'POST',body:'{}'});notice(`Página ${page} colocada em releitura; as linhas dependentes serão reconstruídas.`);await refreshList(true);}));
  $('review-fields').addEventListener('click',e=>{const button=e.target.closest('[data-value-choice]');if(!button)return;const input=$('review-fields').querySelector(`[name="${CSS.escape(button.dataset.field)}"]`);if(!input)return;if(button.dataset.valueChoice==='plan')input.value=button.dataset.plan||'';else {input.value=state.review.piece.values[button.dataset.field]??'';$('use-pdf').checked=true;}});
  $('export-confirm-form').addEventListener('submit',async e=>{e.preventDefault();const pending=state.pendingExport;if(!pending)return;$('export-dialog').close();await download(pending.format||'xlsm',pending.uid,pending.proposal);state.pendingExport=null;});
  $('export-macro').addEventListener('click',()=>run(()=>previewExport(state.doc.id)));
  $('export-csv').addEventListener('click',()=>run(()=>state.doc.common_preparation?previewExport(state.doc.id,'csv'):download('csv',state.doc.id)));
  $('export-all').addEventListener('click',()=>run(()=>previewExport()));
  $('tab-needs').addEventListener('click',()=>run(showNeeds));$('tab-documents').addEventListener('click',showDocuments);
  $('needs-table').addEventListener('click',e=>{const b=e.target.closest('[data-open-document]');if(b){showDocuments();run(()=>openDocument(b.dataset.openDocument));}});
  setInterval(async()=>{
    if(state.polling||document.hidden||modalOpen())return;
    state.polling=true;
    try{await refreshSources();await refreshList();}catch(e){if(!state.documents.length)notice(e.message,true);}finally{state.polling=false;}
  },3500);
  run(async()=>{await refreshSources();await refreshList(true)});
})();
