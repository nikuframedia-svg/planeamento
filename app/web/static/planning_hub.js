(()=>{
  'use strict';
  const $=id=>document.getElementById(id);
  const state={page:1,pages:0,version:null,selected:null,sources:null,outputRecords:[],listRequest:0};
  const text=(tag,value,cls)=>{const el=document.createElement(tag);if(cls)el.className=cls;el.textContent=value??'';return el};
  const fmtDate=value=>{if(!value)return 'Não disponível';const raw=String(value),hasTime=raw.includes('T'),hasZone=/Z$|[+-]\d\d:\d\d$/.test(raw);if(hasTime&&!hasZone){const date=new Date(raw.slice(0,10)+'T12:00:00');return new Intl.DateTimeFormat('pt-PT',{dateStyle:'medium'}).format(date)+', '+raw.slice(11,16)+' · fuso não indicado'}const date=new Date(hasTime?raw:raw+'T12:00:00');if(Number.isNaN(date.getTime()))return raw;const options={dateStyle:'medium'};if(hasTime)options.timeStyle='short';if(hasZone)options.timeZone=state.sources?.display_timezone||'Europe/Lisbon';return new Intl.DateTimeFormat('pt-PT',options).format(date)+(hasZone?' · '+(state.sources?.display_timezone||'Europe/Lisbon'):'')};
  const fmt=value=>value===null||value===undefined||value===''?'—':new Intl.NumberFormat('pt-PT',{maximumFractionDigits:2}).format(value);
  const api=async(path,options)=>{const response=await fetch('/planeamento/api/'+path,{cache:'no-store',...options});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error||'Não foi possível obter os dados.');return data};
  const uuid=()=>crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(16).slice(2);
  function sourceCard(label,status,detail,kind='warn'){
    const card=text('div',null,'source '+kind),description=text('span',detail);description.title=detail;card.append(text('b',status),text('strong',label),description);return card;
  }
  async function loadSources(){
    const data=await api('fontes');state.sources=data;const rail=$('source-rail');rail.replaceChildren();
    const cp=data.cpis||{};
    const failed=data.last_attempt&&data.last_attempt.success===false,cpState=failed?'Ligação indisponível':cp.fresh?'Confirmado agora':cp.mode==='direct'?'Confirmação atrasada':'Sem confirmação direta';
    const cpDetail=(cp.checked_at?'Consulta confirmada: '+fmtDate(cp.checked_at):cp.imported_at?'Cópia importada: '+fmtDate(cp.imported_at):'Sem consulta direta confirmada')+(failed?' · tentativa falhada: '+fmtDate(data.last_attempt.finished_at):'');
    rail.append(sourceCard(cp.label||'CPIS',cpState,cpDetail,cp.fresh?'ok':'warn'));
    const macros=data.macros||{};
    rail.append(sourceCard('Macro de Perfis',macros.perfis?'Importada':'Indisponível',macros.perfis?fmtDate(macros.perfis.loaded_at):'Sem versão',macros.perfis?'ok':'bad'));
    rail.append(sourceCard('Macro de Cantoneiras',macros.cantoneiras?'Importada':'Indisponível',macros.cantoneiras?fmtDate(macros.cantoneiras.loaded_at):'Sem versão',macros.cantoneiras?'ok':'bad'));
    for(const [key,label] of [['perfis','OCR Perfis'],['cantoneiras','OCR Cantoneiras']]){
      const item=(data.ocr||{})[key];rail.append(sourceCard(label,item?'Produção validada':'Sem dados',item?('Última produção: '+fmtDate(item.last_production_date)+' · validação: '+fmtDate(item.last_validation)):'Sem validações',item?'ok':'warn'));
    }
  }
  function badge(value,kind=''){return text('span',value,'status '+kind)}
  function orderRow(order){
    const tr=document.createElement('tr');
    const identity=document.createElement('td');identity.append(text('strong',order.of||'OF por identificar'),text('small',(order.ovs||[]).join(', ')||'OV não disponível'),badge(order.cpis_status||((order.status_values||[]).length>1?'Estado em conflito':'Sem estado CPIS'),order.cpis_status?'':'review'));
    if(order.administrative_origin)identity.append(text('small',order.administrative_origin));
    if((order.status_values||[]).length>1)identity.append(text('small',order.status_values.join(' / '),'conflict'));
    for(const unknown of order.population_unknown_states||[])identity.append(text('small','Estado desconhecido ('+unknown.source+'): '+unknown.value+' · não interpretado como fechado','conflict'));
    const customer=document.createElement('td');customer.append(text('strong',order.customer_name||'Cliente não disponível'),text('small',order.observations||'Sem descrição no CPIS'));
    const area=document.createElement('td'),planLines=Object.values(order.plan||{}).reduce((sum,value)=>sum+Number(value||0),0);area.append(badge(({perfis:'MTG2 Perfis',cantoneiras:'MTG3 Cantoneiras',ambas:'MTG2 e MTG3',por_identificar:'Setor por identificar'})[order.area]||order.area,order.area==='por_identificar'?'review':''),text('small',planLines?planLines+' peça(s) no plano':'Sem linha no plano'));
    const prep=document.createElement('td');const preparation=order.preparation;
    prep.append(preparation?badge((preparation.statuses||[]).includes('ready')?'Preparada':'Rascunho',(preparation.statuses||[]).includes('ready')?'ready':'review'):badge('Sem ficha de preparação'));if(order.documents)prep.append(text('small',order.documents+' PDF associado(s)'));
    const execution=document.createElement('td');execution.append(order.execution_complete?badge('Plano fechado na macro','ready'):order.production_records?badge(order.production_records+' registos OCR','review'):badge('Sem registos OCR encontrados','review'));if(order.production_records&&order.execution_complete)execution.append(text('small',order.production_records+' registo(s) OCR'));if(order.conferences)execution.append(text('small',order.conferences+' conferência(s)'));
    const action=document.createElement('td'),button=text('button','Abrir','open-order');button.type='button';button.addEventListener('click',()=>loadDetail(order.of));if(order.unidentified){for(const raw of order.raw_links||[]){const link=text('a','Ver '+(raw.reference||'peça')+' na RAW','open-order');link.href=raw.href;action.append(link)}}else action.append(button);
    tr.append(identity,customer,area,prep,execution,action);return tr;
  }
  async function loadOrders(resetVersion=false){
    const request=++state.listRequest;
    const params=new URLSearchParams({q:$('query').value.trim(),pagina:state.page,tamanho:50,estado:$('state').value,por_fazer:$('pending-only').checked?'true':'false'});
    if($('population'))params.set('populacao',$('population').value);
    if(state.version&&!resetVersion)params.set('versao',state.version);
    $('orders').replaceChildren(Object.assign(document.createElement('tr'),{innerHTML:'<td colspan="6" class="empty">A carregar ordens…</td>'}));
    try{
      const data=await api('ordens?'+params);if(request!==state.listRequest)return;state.version=data.version;state.pages=data.pages;
      $('orders').replaceChildren(...(data.orders.length?data.orders.map(orderRow):[(()=>{const tr=document.createElement('tr');const td=text('td','Nenhuma OF corresponde a estes filtros.','empty');td.colSpan=6;tr.append(td);return tr})()]));
      const populationLabel=({active:'Ativos',history:'Histórico / fechados',all:'Todos'})[data.population];
      $('count').textContent=data.total+' ordens · '+(populationLabel?populationLabel+' · ':'')+(data.mode==='direct'?'CPIS direto':'cópia importada da macro');
      $('origin-note').textContent=data.mode==='direct'?'Lista vinculada à versão '+data.version.slice(0,8):'Sem confirmação direta do CPIS';
      $('page').textContent=data.pages?'Página '+data.page+' de '+data.pages:'Sem páginas';$('prev').disabled=data.page<=1;$('next').disabled=data.page>=data.pages;
    }catch(error){if(request!==state.listRequest)return;$('orders').replaceChildren();const tr=document.createElement('tr'),td=text('td',error.message,'empty');td.colSpan=6;tr.append(td);$('orders').append(tr);}
  }
  function fact(label,value,conflict=false){const el=text('div',null,'fact'+(conflict?' conflict':''));el.append(text('span',label),text('strong',value||'Não disponível'));return el}
  function planItem(line,detail){
    const box=text('article',null,'item'),top=text('div',null,'item-top');top.append(text('strong',line.component_ref||'Sem referência'),badge(line.source_app==='kanban-mes-mtg2'?'MTG2 Perfis':'MTG3 Cantoneiras'));
    box.append(top,text('p',[line.material_type,line.profile_type,line.length_mm?fmt(line.length_mm)+' mm':null].filter(Boolean).join(' · ')||'Dados técnicos por preencher'));
    box.append(text('p','Necessário: '+(line.quantity_planned==null?'Por confirmar':fmt(line.quantity_planned)+' un.')+(line.cutting_machine?' · '+line.cutting_machine:'')));
    for(const operation of line.operations||[]){
      const block=text('div',null,'operation-evidence'),metrics=text('div',null,'metrics');
      block.append(text('h4',operation.label));
      metrics.append(metric('Registado na macro',operation.macro_quantity==null?'Por confirmar':fmt(operation.macro_quantity)),metric('Saldo da macro',operation.macro_remaining==null?'Por confirmar':fmt(operation.macro_remaining)),metric('Validado no OCR',operation.ocr_quantity==null?'Por confirmar':fmt(operation.ocr_quantity)));
      block.append(metrics);
      if(operation.requires_operation_review)block.append(text('p','Produção encontrada; falta confirmar a operação a que pertence.','conflict'));
      if(operation.requires_need_review)block.append(text('p','O OCR regista esta operação, mas a macro não indica a respetiva necessidade. Confere antes de planear.','conflict'));
      if(operation.ocr_partial)block.append(text('p','Há registos com quantidade desconhecida. O total fica por conferir.','conflict'));
      else if(!operation.ocr_records.length)block.append(text('p','Sem registo OCR associado a esta operação. A produção não é assumida como zero.'));
      if(operation.ocr_records.length){const evidence=document.createElement('details');evidence.append(text('summary','Ver '+operation.ocr_records.length+' registo(s) de suporte'));for(const fact of operation.ocr_records){const record=detail.production.find(p=>p.id===fact.record_id),link=text('a','Folha '+(record?.sheet_no||fact.sheet_uid)+' · '+(fact.quantity==null?'quantidade desconhecida':fmt(fact.quantity)+' un.'));link.href=(line.source_app==='kanban-mes-mtg2'?'https://perfis.nikufra.ai':'https://cantoneiras.nikufra.ai')+'/sheet/'+encodeURIComponent(fact.sheet_uid);link.target='_blank';link.rel='noopener';const paragraph=text('p');paragraph.append(link);evidence.append(paragraph)}block.append(evidence)}
      if(operation.conference_allowed){const reconcile=text('button','Conferir '+operation.label.toLowerCase(),'mini-action');reconcile.type='button';reconcile.addEventListener('click',()=>openReconcile(line,detail,operation));block.append(reconcile)}
      box.append(block);
    }
    return box;
  }
  function metric(label,value){const el=text('div',null,'metric');el.append(text('span',label),text('strong',value));return el}
  function productionItem(row){
    const box=text('article',null,'item'),top=text('div',null,'item-top'),association={explicit:'Ligação validada',technical_unique:'Correspondência técnica única',ambiguous:'Associação ambígua',unmatched:'Sem associação',incomplete:'Identidade incompleta'}[row.association_status]||'Por conferir';top.append(text('strong',row.model_ref||'Referência não associada'),badge(association,['explicit','technical_unique'].includes(row.association_status)?'ready':'review'));
    box.append(top,text('p',[row.machine,row.sheet_date?'Produção '+fmtDate(row.sheet_date):null,'Folha '+(row.sheet_no||'—')].filter(Boolean).join(' · ')));
    const quantity=row.plan_refs.length?(row.plan_refs.every(r=>r.assumed_quantity!=null)?row.plan_refs.reduce((sum,r)=>sum+Number(r.assumed_quantity),0):null):row.quantity;
    box.append(text('p',(quantity===null||quantity===undefined?'Quantidade desconhecida':fmt(quantity)+' un.')+' · '+(row.plan_refs.length?'distribuição congelada da validação':'registo principal')));
    return box;
  }
  function reconciliationItem(row){
    const box=text('article',null,'item'),top=text('div',null,'item-top');top.append(text('strong',(row.component_ref||'Sem referência')+' · '+row.operation),badge(row.valid?'Válida':'Rever',row.valid?'ready':'review'));box.append(top,text('p','Necessário aceite: '+fmt(row.accepted_required)+' · saldo aceite: '+fmt(row.accepted_remaining)),text('p',row.actor+' · '+row.reason));if(row.review_reason)box.append(text('p',row.review_reason,'conflict'));return box;
  }
  function section(title,content){const el=text('section',null,'detail-section');el.append(text('h3',title));if(Array.isArray(content))el.append(...content);else el.append(content);return el}
  async function loadDetail(of){
    state.selected=of;$('detail').replaceChildren(text('div','A carregar a OF…','detail-empty'));
    try{
      const data=await api('ordens/'+encodeURIComponent(of)+'?versao='+encodeURIComponent(state.version||''));if(state.selected!==of)return;
      const context=data.context,head=text('header',null,'detail-head');head.append(text('p','ORDEM DE FABRICO · '+(context.cpis_status||'estado por confirmar'),'eyebrow'),text('h2',of),text('p',(context.ovs||[]).join(', ')||'OV não disponível'),text('p',context.customer_name||'Cliente não disponível'));
      const actions=text('div',null,'detail-actions'),area=context.sources?.length===1?context.sources[0]:'';
      if(context.administrative_origin||['Em Aberto','Em Produção'].includes(context.cpis_status)){const prepare=text('a','Preencher manualmente');prepare.href='/planeamento/manual?of='+encodeURIComponent(of)+'&area='+encodeURIComponent(area==='perfis'||area==='cantoneiras'?area:'')+'&new=1&cpis_version='+encodeURIComponent(data.version);actions.append(prepare)}else actions.append(text('span','OF apenas para consulta','status review'));const pdf=text('a','Carregar PDF');pdf.href='/planeamento/dossies?of='+encodeURIComponent(of);actions.append(pdf);head.append(actions);
      const facts=text('div',null,'facts'),conflicts=new Set(context.conflicts||[]);
      facts.append(fact('Descrição da obra',context.observations,conflicts.has('observations')),fact('Família de Produto',context.work_type_description,conflicts.has('work_type_description')),fact('Unidade fabril',context.factory_unit,conflicts.has('factory_unit')),fact('Responsável DP',context.responsible_dp,conflicts.has('responsible_dp')),fact('Fim previsto da Produção',fmtDate(context.planned_finish_date),conflicts.has('planned_finish_date')),fact('Data de entrega',fmtDate(context.delivery_date),conflicts.has('delivery_date')));
      const notice=text('p',context.administrative_origin?context.administrative_origin+'; sem estado CPIS confirmado.':data.cpis_mode==='direct'?'Contexto lido da versão CPIS indicada no topo.':'Contexto importado das macros; falta confirmação direta do CPIS.',data.cpis_mode==='direct'?'':'conflict');
      if((context.status_values||[]).length>1)notice.append(text('strong',' Estados em conflito: '+context.status_values.join(' / ')+'. É necessário confirmar o estado atual.'));
      const plan=data.plan_lines.length?data.plan_lines.map(line=>planItem(line,data)):[text('p','Esta OF ainda não tem linhas técnicas no planeamento. Usa “Preencher manualmente” ou “Carregar PDF” para registar a primeira peça.','empty')];
      const prod=data.production.length?data.production.map(productionItem):[text('p','Não existe produção OCR associada com segurança. Isto não prova que a quantidade produzida seja zero.','empty')];
      const reconciliations=data.reconciliations.map(reconciliationItem);for(const c of data.need_conferences||[]){const item=text('article',null,'item'),link=text('a','Abrir conferência e verificar evidência atual');link.href='/planeamento/preparar?necessidade='+c.need_id+'&area='+c.area;item.append(text('strong',c.component_ref+' · '+c.operation),text('p','Saldo registado: '+fmt(c.accepted_remaining)+' · '+c.actor),link);reconciliations.push(item)}if(!reconciliations.length)reconciliations.push(text('p','Ainda não existem saldos conferidos para esta OF.','empty'));
      const docs=data.documents.length?data.documents.map(d=>{const item=text('article',null,'item'),link=text('a',d.filename);link.href='/planeamento/dossies?document='+encodeURIComponent(d.id);item.append(link,text('p',d.status+' · '+fmtDate(d.updated_at)));return item}):[text('p','Nenhum dossiê PDF associado.','empty')];
      const readyPerfis=[];
      const preps=data.preparations.length?data.preparations.map(p=>{const item=text('article',null,'item'),label=text('label',null,'prep-select');if(p.record_status==='ready'&&p.area==='perfis'){const check=document.createElement('input');check.type='checkbox';check.checked=true;check.value=p.id;check.dataset.outputRecord='1';label.append(check);readyPerfis.push(p.id)}label.append(text('strong',p.component_ref||'Referência por preencher'));item.append(label,text('p',(p.record_status==='ready'?'Preparada':'Rascunho')+' · '+p.actor));const a=text('a','Abrir registo');a.href='/planeamento/manual?registo='+p.id;item.append(a);return item}):[text('p','Ainda não existem preparações guardadas.','empty')];
      if(readyPerfis.length){const output=text('div',null,'output-action'),button=text('button','Comparar saída de Perfis','primary');button.type='button';button.disabled=!state.sources?.completion_allowed;button.addEventListener('click',openOutput);output.append(button);if(button.disabled)output.append(text('small','Bloqueada até existir uma confirmação CPIS direta com menos de 15 minutos.'));preps.push(output)}
      $('detail').replaceChildren(head,section(context.administrative_origin?'Contexto da ordem':'Contexto CPIS',[notice,facts]),section('Preparação',preps),section('Referências do plano',plan),section('Produção validada',prod),section('Conferências',reconciliations),section('Dossiês PDF',docs));
      if(matchMedia('(max-width:1100px)').matches)$('detail').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){const empty=text('div',null,'detail-empty');empty.append(text('h2','Não foi possível abrir a OF'),text('p',error.message));$('detail').replaceChildren(empty);}
  }
  function openReconcile(line,detail,operation){
    const form=$('reconcile-form');form.reset();form.elements.of.value=detail.context.of;form.elements.area.value=line.source_app==='kanban-mes-mtg2'?'perfis':'cantoneiras';form.elements.component_ref.value=line.component_ref||'';form.elements.operation.value=operation.operation;form.elements.accepted_required.value=line.quantity_planned??'';form.elements.accepted_remaining.value=operation.macro_remaining??'';
    form.dataset.planKey=line.plan_key;form.dataset.fingerprint=operation.evidence_fingerprint;form.dataset.version=detail.version;$('reconcile-title').textContent=(line.component_ref||'Peça sem referência')+' · '+operation.label+' · '+detail.context.of;$('reconcile-evidence').textContent='Macro: '+fmt(operation.macro_quantity)+' · saldo: '+fmt(operation.macro_remaining)+' · OCR: '+fmt(operation.ocr_quantity);$('reconcile-error').hidden=true;$('reconcile-dialog').showModal();
  }
  function openOutput(){
    state.outputRecords=[...document.querySelectorAll('[data-output-record]:checked')].map(item=>item.value);
    if(!state.outputRecords.length)return;
    $('output-form').reset();$('output-error').hidden=true;$('output-comparison').hidden=true;$('output-comparison').replaceChildren();$('compare-output').hidden=false;$('output-dialog').showModal();
  }
  $('filters').addEventListener('submit',event=>{event.preventDefault();state.page=1;state.version=null;loadOrders(true)});
  $('prev').addEventListener('click',()=>{if(state.page>1){state.page--;loadOrders()}});$('next').addEventListener('click',()=>{if(state.page<state.pages){state.page++;loadOrders()}});
  $('refresh').addEventListener('click',async()=>{state.version=null;await Promise.allSettled([loadSources(),loadOrders(true)]);if(state.selected)loadDetail(state.selected)});
  $('close-dialog').addEventListener('click',()=>$('reconcile-dialog').close());
  $('close-output').addEventListener('click',()=>$('output-dialog').close());
  $('reconcile-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,values=Object.fromEntries(new FormData(form));values.request_id=uuid();values.cpis_version=form.dataset.version;values.plan_key=form.dataset.planKey;values.evidence_fingerprint=form.dataset.fingerprint;try{await api('conferencias',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});$('reconcile-dialog').close();if(state.selected)loadDetail(state.selected)}catch(error){$('reconcile-error').textContent=error.message;$('reconcile-error').hidden=false}});
  $('output-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,error=$('output-error');error.hidden=true;try{const proposal=await api('saida-propostas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:uuid(),record_ids:state.outputRecords})});const target=$('output-comparison');target.replaceChildren(text('h3',proposal.cells.length+' células propostas'));const list=text('div',null,'cell-list');for(const cell of proposal.cells){const row=text('p',null,'cell-change');row.append(text('strong',cell.column+cell.row+' · '+cell.field),text('span',(cell.before??'vazio')+' → '+(cell.after??'vazio')));list.append(row)}target.append(list);const link=text('a','Descarregar cópia XLSM','primary download');link.href='/planeamento/api/saida-planeamento.xlsm?proposta='+encodeURIComponent(proposal.id)+'&assinatura='+encodeURIComponent(proposal.proposal_fingerprint);target.append(link);target.hidden=false;$('compare-output').hidden=true}catch(reason){error.textContent=reason.message;error.hidden=false}});
  Promise.allSettled([loadSources(),loadOrders()]);
})();
