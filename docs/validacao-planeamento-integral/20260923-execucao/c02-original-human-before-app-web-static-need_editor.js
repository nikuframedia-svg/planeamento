(() => {
'use strict';
const $=id=>document.getElementById(id), params=new URLSearchParams(location.search);
const state={area:'',cat:null,need:null,op:null,source:null,of:null,detail:null,order:null,decisions:{},proof:null,pending:null,page:1,dirty:false,pdf:null,piece:null,raw:{},references:[],sourceStatus:null,opDrafts:{},operationCode:'',saving:false};
function el(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
function fmt(v){return v==null||v===''?'Não disponível':Array.isArray(v)?v.join(', '):typeof v==='object'?JSON.stringify(v):String(v)}
function safe(fn){return (...args)=>Promise.resolve().then(()=>fn(...args)).catch(fail)}
async function api(path,body){const r=await fetch('/planeamento/api/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok){const err=new Error(data.error||'Não foi possível concluir o pedido.');err.fields=data.fields||{};throw err}return data}
function request(body){return {request_id:crypto.randomUUID(),...body}}
function openParents(node){for(let p=node?.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true}
function clearErrors(){$('error').hidden=true;for(const e of document.querySelectorAll('.field-error'))e.textContent='';for(const e of document.querySelectorAll('[aria-invalid]'))e.removeAttribute('aria-invalid')}
function fail(error){$('error').textContent=error.message;$('error').hidden=false;let first;for(const [name,message] of Object.entries(error.fields||{})){const target=$('error-'+name),input=$('field-'+name)||$(name);if(target){target.textContent=message;openParents(target);if(target.closest('.field'))target.closest('.field').hidden=false}if(input){input.setAttribute('aria-invalid','true');first??=input}}(first||$('error')).scrollIntoView({block:'center'});first?.focus()}
function fieldError(name,message){const e=new Error(message);e.fields={[name]:message};return e}
function val(id){const node=$('field-'+id);if(id==='material_requested'&&node)return node.value===''?null:node.value==='true';if(id==='abocardar'&&node?.indeterminate)return state.raw.abocardar;return node?(node.type==='checkbox'?node.checked:node.value):state.raw[id]??null}
const baseFields=JSON.parse($('field-contract').textContent);
function values(){return {...state.raw,...Object.fromEntries((state.cat?.fields||baseFields).filter(f=>f.editor_visible).map(f=>[f.id,val(f.id)]))}}
function fillOptions(node,options,current){node.replaceChildren(new Option('Por definir',''));for(const opt of options||[])node.add(new Option(typeof opt==='object'?opt.label:opt,typeof opt==='object'?opt.value:opt));if(current&&!Array.from(node.options).some(x=>x.value===String(current)))node.add(new Option(current+' — opção a rever',current));node.value=current??''}
function key(v){return String(v||'').toLocaleLowerCase('pt-PT').replace('rectangular','retangular')}
function mark(name,type){state.decisions[name]=type;state.dirty=true;$('after-save').hidden=true;schedulePreview()}
function showConditional(){if(!state.cat)return;const material=key(val('material_type')),custom=val('custom_profile'),geometry=val('geometry')||material,dims=state.cat.geometries[geometry]||[];
 $('wrap-custom_profile').hidden=true;$('wrap-special_profile').hidden=!custom||!state.cat.profiles[material]?.length;$('wrap-geometry').hidden=!custom&&(Boolean(state.cat.geometries[material])||!material||Boolean(state.cat.profiles[material]?.length));
 for(const name of ['outer_diameter_mm','width_mm','height_mm','thickness_mm'])$('wrap-'+name).hidden=!dims.includes(name)&&!val(name);
 $('wrap-identity_discriminator').hidden=!val('identity_discriminator');
}
function profileChange(){const input=$('field-profile'),custom=input.value==='__custom__';$('field-custom_profile').checked=custom;mark('custom_profile','write');mark('profile',input.tagName==='SELECT'?'select':'write');showConditional()}
function profiles(){if(!state.cat)return;const current=val('profile'),custom=val('custom_profile'),family=key(val('material_type')),options=state.cat.profiles[family]||[],manual=!options.length;
 let input=$('field-profile');const tag=manual?'INPUT':'SELECT';if(input.tagName!==tag){const next=el(tag.toLowerCase());next.id=input.id;next.name=input.name;next.setAttribute('aria-describedby','help-profile error-profile');input.replaceWith(next);input=next}
 if(manual){input.type='text';input.value=custom?(val('special_profile')||current||''):current||'';$('help-profile').textContent=family?'Preenchimento manual: esta família não tem uma lista no Excel.':'Escolhe primeiro o tipo de perfil nível 1.';input.disabled=!family}
 else{fillOptions(input,options,custom?null:current);input.add(new Option('Outra designação…','__custom__'));if(custom)input.value='__custom__';$('help-profile').textContent='Escolhe uma designação da família selecionada.'}
 input.oninput=()=>{if(manual){$('field-custom_profile').checked=false;mark('custom_profile','write');showConditional()}mark('profile',manual?'write':'select')};input.onchange=profileChange;showConditional();
}
function registrationView(){const r=state.registration;$('material-forecast').textContent=r?new Intl.DateTimeFormat('pt-PT',{timeZone:'UTC'}).format(new Date(r.predicted_material_request_date+'T12:00:00Z')):'Calculada ao guardar';const old=state.raw.material_request_date;$('historical-request').hidden=!old;$('historical-request').textContent=old?'Data manual histórica: '+old+' (preservada).':''}
function attention(field,message){const box=$('wrap-'+field);if(!box)return;box.hidden=false;box.classList.add('field-attention');box.append(el('p',message,'help'));openParents(box)}
function render(raw={}){
 raw={...raw};if(state.area==='perfis'&&!raw.operation)raw.operation='corte';state.raw={...raw};state.operationCode=raw.operation||'';
 for(const id of ['cut-fields','piece-fields','operation-fields','extra-fields'])$(id).replaceChildren();
 const groups={cut:'cut-fields',piece:'piece-fields',work:'operation-fields',extra:'extra-fields'};
 for(const f of [...(state.cat?.fields||baseFields)].filter(f=>f.editor_visible&&(state.cat||f.group==='cut'||f.group==='extra')).sort((a,b)=>a.order-b.order)){if(!state.cat&&f.type==='select')continue;const box=el('div',null,'field');box.id='wrap-'+f.id;const label=el('label',f.label+(f.unit?' ('+f.unit+')':''));label.htmlFor='field-'+f.id;
  const readonlyOperation=f.id==='operation'&&state.area==='perfis';const input=document.createElement(readonlyOperation?'input':(f.type==='select'||f.type==='tristate')?'select':f.type==='textarea'?'textarea':'input');input.id='field-'+f.id;input.name=f.id;
  if(readonlyOperation){input.type='hidden';input.value=raw.operation||'corte';}
  else if(f.type==='tristate'){fillOptions(input,[{value:'true',label:'Sim'},{value:'false',label:'Não'}],raw[f.id]===true?'true':raw[f.id]===false?'false':'')}
  else if(f.type==='select')fillOptions(input,f.id==='operation'?[...state.cat.operations,...state.cat.additional_operations.filter(o=>o.countable)]:f.options||[],raw[f.id]);
  else if(f.type==='boolean'||f.type==='checkbox'){input.type='checkbox';input.checked=f.id==='abocardar'?(raw[f.id]===true||String(raw[f.id]).toUpperCase()==='X'):raw[f.id]===true;if(f.id==='abocardar'&&raw[f.id]!=null&&!['','X','-','true','false'].includes(String(raw[f.id]))){input.indeterminate=true;box.append(el('p','Indicação anterior: '+fmt(raw[f.id])+'. Confirma sim ou não.','help'));const no=el('button','Não abocardar');no.type='button';no.onclick=()=>{input.indeterminate=false;input.checked=false;mark(f.id,'write')};box.append(no)}}
  else{if(f.type!=='textarea')input.type=f.type==='date'?'date':'text';if(f.type==='number')input.inputMode='decimal';input.value=raw[f.id]??''}
  box.append(label,input);if(readonlyOperation)box.append(el('p',input.value==='abocardar'?'Abocardar · ficha histórica preservada':'Corte'));const help=el('p',f.help||'','help');help.id='help-'+f.id;if(f.help)box.append(help);const error=el('span','','field-error');error.id='error-'+f.id;box.append(error);input.setAttribute('aria-describedby',[f.help?help.id:null,error.id].filter(Boolean).join(' '));
  input.addEventListener('input',()=>mark(f.id,input.type==='checkbox'?'write':input.value===''?'clear':f.type==='select'?'select':'write'));
  $(groups[f.group]||'extra-fields').append(box);
  const suggestion=(state.detail?.fields||[]).find(s=>s.field===f.id&&(s.scope==='piece'||s.scope===state.op));
  if(suggestion?.requires_review){attention(f.id,'A origem mudou. Confirma o valor que queres utilizar.');const diff=el('div','Sugestão atual: '+fmt(suggestion.suggestion),'suggestion');
   for(const [action,title] of [['accept','Usar sugestão'],['write','Manter o meu valor']]){const b=el('button',title);b.type='button';b.onclick=()=>{if(action==='accept'){const current=$('field-'+f.id);if(current.type==='checkbox'){current.checked=suggestion.suggestion===true||suggestion.suggestion==='X';current.indeterminate=false}else current.value=suggestion.suggestion??''}mark(f.id,action);box.classList.remove('field-attention');diff.remove();profiles()};diff.append(b)}box.append(diff);
  }
 }
 registrationView();
 if(!state.cat){$('catalog-fields').hidden=true;$('work-sections').hidden=true;$('area-help').hidden=false;return}
 $('field-material_type').onchange=()=>{const next=key(val('material_type')),opts=state.cat.profiles[next]||[];if(!opts.includes(val('profile'))){$('field-profile').value='';$('field-custom_profile').checked=false;mark('profile','clear');mark('custom_profile','write')}$('field-geometry').value='';mark('geometry','clear');profiles()};$('field-geometry').onchange=profiles;
 $('field-profile').onchange=()=>{const custom=val('profile')==='__custom__';$('field-custom_profile').checked=custom;mark('custom_profile','write');showConditional()};
 $('field-operation').onchange=safe(async()=>{const code=val('operation'),old=state.operationCode;
  if(old&&old!==code&&state.dirty){$('field-operation').value=old;if(!await mayLeave())return;}
  const raw=values(),next=state.detail?.operations.find(o=>o.area===state.area&&o.code===code);state.op=next?.id||null;
  const record=state.detail?.records.find(r=>r.operation_id===state.op),piece=Object.fromEntries(state.cat.fields.filter(f=>f.scope==='piece').map(f=>[f.id,raw[f.id]]));
  state.decisions={...Object.fromEntries(Object.entries(state.decisions).filter(([name])=>!old||state.cat.fields.some(f=>f.id===name&&f.scope==='piece'))),operation:'select'};render({...(!old?raw:{}),...piece,...(record?.values_json||{}),...piece,operation:code});state.dirty=true;await evidence();
 });
 profiles();$('catalog-fields').hidden=false;$('work-sections').hidden=false;$('area-help').hidden=true;
 for(const issue of state.piece?.issues||[]){const name=({machine_group:'machine',material_description:'special_profile',operations:'operation_detail',variant:'identity_discriminator'})[issue.field]||issue.field;const chosen=state.detail?.fields.find(f=>f.field===name&&(f.scope==='piece'||f.scope===state.op));if(name&&(!chosen?.human_decision||chosen.requires_review))attention(name,issue.message);}

 $('history-field').replaceChildren(new Option('Todos os campos',''));for(const f of state.cat.fields)$('history-field').add(new Option(f.label,f.id));
 updateReady();schedulePreview();
}
function submittedValues(){const raw=Object.fromEntries(Object.entries(values()).filter(([id])=>state.cat.fields.some(f=>f.id===id&&f.editor_visible)));if(raw.custom_profile)raw.profile=raw.special_profile||'';return raw}
let previewTimer,previewSerial=0;
function schedulePreview(){
 clearTimeout(previewTimer);const serial=++previewSerial;
 if(!$('preview-status'))return;
 $('preview-summary').replaceChildren();$('preview-results').replaceChildren();
 const of=state.localMode&&!state.need?$('local-of').value.trim():state.of;
 if(!state.cat||!of){$('preview-status').textContent='Preenche a OF e escolhe a área para calcular.';return}
 $('preview-status').textContent='A calcular os valores com as fontes disponíveis…';
 previewTimer=setTimeout(()=>updatePreview(serial,of),300);
}
function previewOrigin(value){
 if(!value)return '';if(Array.isArray(value))return value.map(previewOrigin).join('; ');
 if(typeof value==='string')return value;
 return value.rule||[value.sheet,value.cell||(value.row?'linha '+value.row:''),value.designation,value.kg_m!=null?value.kg_m+' kg/m':''].filter(Boolean).join(' · ')||fmt(value);
}
async function updatePreview(serial,of){
 try{
  const result=await api('necessidades/prever',{area:state.area,production_order_no:of,
   ...(state.need?{need_id:state.need,expected_revision:state.detail?.need.revision}:{}),
   ...(state.source?{source:state.source}:{}),catalog_version:state.cat.version,values:submittedValues(),
   ...(state.localMode?{local_order:{values:{delivery_date:$('local-delivery_date').value}}}:{})});
  if(serial!==previewSerial)return;
  if(result.needs_decision){$('preview-status').textContent=result.reason;return}
  $('preview-status').textContent='Pré-visualização calculada no servidor · alterações ainda não guardadas.';
  const principal=state.area==='perfis'?'cut':'made';
  const prominent=new Set([principal,'remaining','quantity_to_plan','bars','theoretical_hours','hours_pct']);
  const table=el('table'),head=el('tr');for(const text of ['Resultado','Valor','Origem / motivo'])head.append(el('th',text));table.append(head);
  for(const r of result.results){
   const value=(typeof r.value==='boolean'?(r.value?'Sim':'Não'):fmt(r.value))+(r.value!=null&&r.unit?' '+r.unit:'');
   const tr=el('tr');tr.dataset.previewField=r.field;
   tr.append(el('td',r.label),el('td',value),el('td',r.reason||previewOrigin(r.source)));table.append(tr);
   if(prominent.has(r.field))$('preview-summary').append(metric(r.label,value));
  }
  $('preview-results').append(table);
 }catch(error){if(serial===previewSerial)$('preview-status').textContent=error.message}
}
for(const id of ['local-of','local-delivery_date'])$(id).addEventListener('input',schedulePreview);
async function loadCatalog(area){state.area=['perfis','cantoneiras'].includes(area)?area:'';$('area').value=state.area;state.cat=state.area?await api('catalogos?contrato=3&area='+state.area):null}
function modeLinks(){const suffix=state.of?'?of='+encodeURIComponent(state.of):'';$('manual-link').href='/planeamento/manual'+suffix;$('pdf-link').href='/planeamento/dossies'+suffix;for(const [id,pdf] of [['manual-link',false],['pdf-link',true]]){const a=$(id);if(Boolean(state.pdf||state.source?.kind==='pdf')===pdf)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')}}
async function orderContext(of){state.of=of;modeLinks();$('context').replaceChildren();$('order-facts').replaceChildren();$('change-order').hidden=!of;$('order-details').hidden=!of;$('search').hidden=Boolean(of);
 if(!of){$('search').hidden=false;return}
 try{state.order=await api('ordens/'+encodeURIComponent(of));const c=state.order.context,box=el('div',null,'order-context');box.append(el('strong',c.of),el('span','OV: '+fmt(c.ovs)),el('span',fmt(c.customer_name)));$('context').append(box);
  for(const [label,value] of [['Estado CPIS',c.cpis_status],['Fim previsto da Produção',c.planned_finish_date],['Data de entrega',c.delivery_date]])$('order-facts').append(el('p',label+': '+fmt(value)));
  const source=state.sourceStatus?.cpis;$('order-facts').append(el('p',c.administrative_origin?c.administrative_origin+'; sem estado CPIS confirmado.':state.order.cpis_mode==='direct'?'Última confirmação CPIS: '+fmt(source?.checked_at):'CPIS importado da macro — sem confirmação direta.'));
 }catch(error){state.order=null;$('context').append(el('strong',of));$('order-facts').append(el('p',error.message));$('order-details').open=true}
 state.registration=(await api('ordens/'+encodeURIComponent(of)+'/registo')).registration;registrationView();
 $('title').textContent='Registar peça · '+of;$('orders').replaceChildren();
}
function resetPiece(){state.need=null;state.op=null;state.detail=null;state.source=null;state.pdf=null;state.piece=null;state.raw={};state.decisions={};state.opDrafts={};state.dirty=false;state.proof=null;$('sources').replaceChildren();$('drawing-open').hidden=true;$('duplicates').hidden=true;$('after-save').hidden=true;$('pdf-conflict').hidden=true;$('quantity-notice').hidden=true;clearErrors()}
async function selectOrder(of){state.localMode=false;$('new-order-fields').hidden=true;resetPiece();await orderContext(of);if(!state.area&&state.order?.context.sources?.length===1)await loadCatalog(state.order.context.sources[0]);render({});$('preparation').hidden=false;$('next-step').textContent='Preenche os dados da peça e guarda o rascunho.';await evidence();history.replaceState(null,'','/planeamento/manual?of='+encodeURIComponent(of)+(state.area?'&area='+state.area:''));}
async function referenceList(showDialog=true){
 const suffix='of='+encodeURIComponent(state.of)+'&area='+encodeURIComponent(state.area);
 const all=await api('necessidades/lista?'+suffix+'&populacao=active');
 state.references=all.needs.map(n=>({label:n.component_ref+' · '+fmt(n.specification.profile)+' · '+fmt(n.specification.length_mm)+' mm',open:()=>loadNeed(n.id)}));
 const active=await api('linhas?'+suffix+'&populacao=active');
 const available=new Map(active.lines.map(line=>[line.plan_key,line]));
 for(const line of state.order?.plan_lines||[]){
  const source=available.get(line.plan_key);
  if(!source||(source.planning_key&&!source.planning_key.startsWith('macro:')))continue;
  state.references.push({plan_key:line.plan_key,label:line.component_ref+' · '+fmt(line.profile_type)+' · '+fmt(line.length_mm)+' mm · plano importado',open:async()=>{
   const data=await api('linhas?'+suffix+'&populacao=active');
   const row=data.lines.find(l=>l.plan_key===line.plan_key);
   if(!row)throw new Error('A linha já não está ativa. Atualiza a lista de referências.');
   resetPiece();state.source={kind:'plan_line',id:line.plan_key,version:data.snapshot.snapshot_id};
   const raw={...row.values};if(state.area==='cantoneiras'){raw.operation='';raw.operation_detail=''}raw.quantity_to_plan=null;render(raw);state.dirty=true;await evidence();
  }});
 }
 renderReferences();if(showDialog)$('references-dialog').showModal();
}
function renderReferences(){const q=key($('reference-query').value);$('references').replaceChildren();for(const item of state.references.filter(r=>key(r.label).includes(q))){const b=el('button',item.label);b.type='button';b.onclick=safe(async()=>{if(!await mayLeave())return;$('references-dialog').close();await item.open()});$('references').append(b)}if(!$('references').children.length)$('references').append(el('p','Não foram encontradas peças. Podes escrever uma nova referência no formulário.'))}
async function loadNeed(id){state.need=id;state.detail=await api('necessidades/'+id);state.localMode=Boolean(state.detail.local_order);$('new-order-fields').hidden=!state.localMode;if(state.localMode){$('local-of').value=state.detail.need.production_order_no;$('local-of').readOnly=true;for(const k of ['ov','customer','designation','delivery_date'])$('local-'+k).value=state.detail.local_order.values_json[k]||'';}const areas=[...new Set(state.detail.operations.map(o=>o.area))];if(!state.area&&areas.length===1)await loadCatalog(areas[0]);const record=state.detail.records.find(r=>r.area===state.area&&r.operation_id===state.op)||state.detail.records.find(r=>r.area===state.area);state.op=record?.operation_id||null;state.decisions={};state.opDrafts={};await orderContext(state.detail.need.production_order_no);render({...record?.values_json,...state.detail.need.specification});$('preparation').hidden=false;$('title').textContent=state.of+' · '+(state.detail.need.component_ref||'Nova peça');$('next-step').textContent='Confirma os dados e guarda as alterações.';renderSources();state.dirty=false;await evidence();history.replaceState(null,'','/planeamento/preparar?necessidade='+id+(state.area?'&area='+state.area:'')+(state.pdf?'&document='+encodeURIComponent(state.pdf.id)+'&piece='+encodeURIComponent(state.piece.id):''));}
function renderSources(){$('sources').replaceChildren();const sources=state.detail?.sources||[];for(const s of sources){$('sources').append(el('p',s.kind==='pdf'?'PDF · revisão '+s.version:'Plano importado · versão '+s.version))}if(!sources.length)$('sources').append(el('p',state.pdf?state.pdf.filename:'Dados introduzidos manualmente.'));$('drawing-open').hidden=!state.pdf&&!sources.some(s=>s.kind==='pdf');modeLinks()}
function pdfUrl(piece){return '/planeamento/preparar?document='+encodeURIComponent(state.pdf.id)+'&piece='+encodeURIComponent(piece.id)+(state.of?'&of='+encodeURIComponent(state.of):'')}
async function sourcePdf(){state.pdf=await api('dossies/'+encodeURIComponent(params.get('document')));state.piece=state.pdf.pieces.find(p=>p.id===params.get('piece'));if(!state.piece)throw new Error('A peça não foi encontrada no PDF. Volta à lista de peças.');const requested=params.get('of');
 if(requested&&requested!==state.pdf.production_order){$('pdf-conflict').hidden=false;$('pdf-conflict-text').textContent='Selecionaste '+requested+', mas o PDF indica '+fmt(state.pdf.production_order)+'. Confirma a ordem antes de continuar.';$('use-pdf-order').disabled=!state.pdf.production_order;$('preparation').hidden=true;return}
 await acceptPdf();
}
async function acceptPdf(){const doc=state.pdf,piece=state.piece;$('pdf-conflict').hidden=true;if(!doc.production_order)throw new Error('Falta identificar a OF do PDF. Abre o PDF guardado e escolhe Resolver identificação.');
 if(['queued','indexing','extracting','matching'].includes(doc.status))throw new Error('A leitura do PDF está em curso. Volta à lista para acompanhar o progresso.');
 if(!state.area&&['Serrote','Vanguard'].includes(piece.machine_group))await loadCatalog('perfis');
 state.source={kind:'pdf',id:doc.id+'/'+piece.id,document_id:doc.id,piece_id:piece.id,version:doc.revision+':'+piece.revision};
 const linked=await api('necessidades/por-origem?document='+encodeURIComponent(doc.id)+'&piece='+encodeURIComponent(piece.id));if(linked.need_id){await loadNeed(linked.need_id);return}
 await orderContext(doc.production_order);render({...piece.values,operation:piece.values.operation||(state.area==='perfis'?'corte':'')});$('preparation').hidden=false;renderSources();$('next-step').textContent='Os dados vieram do PDF. Confirma-os e preenche o que falta.';await evidence();
}
function metric(label,value){const row=el('div',null,'metric');row.append(el('span',label),el('strong',fmt(value)));return row}
function quantityNotice(){const p=state.proof?.evidence,conf=state.proof?.conferences.find(c=>c.valid),notices=[];if(p?.warnings.length)notices.push(...p.warnings);if(p?.balance_reason&&!conf)notices.push(p.balance_reason);if(state.proof?.conferences.some(c=>!c.valid)&&!conf)notices.push('A quantidade em falta precisa de nova confirmação.');const balance=conf?.accepted_remaining??p?.macro_remaining,stored=state.raw.quantity_to_plan;
 $('quantity-summary').textContent=balance==null?'Para concluir, confirma a quantidade em falta. Podes guardar o rascunho.':'Ao concluir: '+balance+' un. — '+(conf?'quantidade em falta confirmada.':'saldo do plano importado.');
 if(stored!=null)$('quantity-summary').textContent+=' Preparação guardada: '+stored+' un.';
 if(balance===0)$('quantity-summary').textContent+=' Sem nova linha a gerar.';
 $('quantity-notice').textContent=notices.join(' ');$('quantity-notice').hidden=!notices.length}
async function evidence(){state.proof=null;$('evidence').replaceChildren();$('conference-open').hidden=true;$('evidence-help').textContent='Guarda o rascunho para consultar as quantidades desta peça.';
 if(state.need&&state.op){state.proof=await api('necessidades/'+state.need+'/evidencia?operacao='+state.op);const p=state.proof.evidence;$('evidence-help').textContent=p.macro.length?'Quantidades da operação escolhida.':'Sem linha na macro. A quantidade em falta pode ser confirmada aqui.';$('evidence').append(metric('Quantidade total necessária',p.required),metric('Em falta no plano importado',p.macro_remaining),metric('Produção validada no OCR',p.ocr_quantity));if(p.ocr_quantity==null)$('evidence').append(el('p','Sem produção OCR associada. Isto não significa produção igual a zero.'));const conf=state.proof.conferences[0];if(conf)$('evidence').append(metric(conf.valid?'Quantidade em falta confirmada':'Confirmação a rever',conf.accepted_remaining));for(const warning of p.warnings)$('evidence').append(el('p',warning));$('conference-open').hidden=false}
 quantityNotice();updateReady();
}
function updateReady(){const allowed=state.sourceStatus?.completion_allowed===true;$('preparation').elements.ready.disabled=!allowed;$('ready-reason').textContent=allowed?'Concluir confirma os dados para preparar a saída. Os campos obrigatórios e as quantidades são verificados.':'Podes guardar o rascunho. Para concluir, falta uma confirmação direta recente do CPIS.'}
async function resolveCandidate(extra={}){const result=await api('necessidades/resolver',request({...state.pending,...extra}));if(result.needs_decision){$('duplicates').hidden=false;$('candidates').replaceChildren();for(const n of result.candidates){const b=el('button',n.component_ref+' · '+fmt(n.specification.profile)+' · '+fmt(n.specification.length_mm)+' mm · '+fmt(n.quantity_required)+' un.');b.type='button';b.onclick=safe(async()=>{if(await resolveCandidate({need_id:n.id,expected_revision:n.revision,reason:$('identity-reason').value}))await persist(state.pending.values,state.pendingStatus)});$('candidates').append(b)}$('duplicates').scrollIntoView({block:'center'});return false}state.need=result.need_id;state.detail=await api('necessidades/'+state.need);
 if(result.reused&&state.pending.source){const operation=state.detail.operations.find(o=>o.area===state.area&&o.code===state.pending.values.operation);for(const field of state.detail.fields){if(field.scope!=='piece'&&field.scope!==operation?.id)continue;if(state.cat.fields.some(f=>f.id===field.field&&f.editor_visible)&&!state.decisions[field.field]&&(field.human_decision||field.source?.kind==='manual'))state.pending.values[field.field]=field.value;}}
 $('duplicates').hidden=true;return true}
async function finishSaved(saved,raw,status){state.need=saved.need_id;state.op=saved.operation_id;await loadNeed(state.need);$('status').textContent=(status==='ready'?'Preparação concluída':'Rascunho guardado')+' · '+(raw.component_ref||state.of)+'.';if(saved.publication?.areas?.[state.area])$('status').textContent+=' Linha atualizada na RAW; agregados em processamento.';$('after-save').hidden=false;let link=document.getElementById('see-raw');if(!link){link=el('a','Ver na RAW');link.id='see-raw';$('after-save').append(link)}link.href=saved.raw_url||('/planeamento/raw?area='+state.area+'&need='+state.need);const index=state.pdf?.pieces.findIndex(p=>p.id===state.piece?.id);state.nextPiece=state.pdf?.pieces.slice(index+1).find(p=>!['excluded','superseded'].includes(p.state));$('next-piece').hidden=!state.nextPiece;return true}
async function persist(raw,status){return atomicSave(raw,status)}
async function atomicSave(raw,status,choice={}){const payload={...(state.localMode?{local_order:{expected_revision:state.detail?.local_order?.revision||0,values:Object.fromEntries(['ov','customer','designation','delivery_date'].map(k=>[k,$('local-'+k).value]))}}:{}),area:state.area,production_order_no:state.of,source:state.source,need_id:state.need||undefined,expected_revision:state.detail?.need.revision,catalog_version:state.cat.version,record_status:status,values:raw,decisions:state.decisions,...choice};const result=await api('necessidades/registar',request(payload));if(result.needs_decision){state.pending={...payload};state.pendingStatus=status;$('duplicates').hidden=false;$('candidates').replaceChildren();for(const n of result.candidates){const b=el('button',n.component_ref+' · '+fmt(n.specification.profile)+' · '+fmt(n.specification.length_mm)+' mm · '+fmt(n.quantity_required)+' un.');b.type='button';b.onclick=safe(()=>atomicSave(raw,status,{...(n.plan_key?{selected_plan_key:n.plan_key}:{need_id:n.id,expected_revision:n.revision}),reason:$('identity-reason').value}));$('candidates').append(b)}$('duplicates').scrollIntoView({block:'center'});return false}return finishSaved(result,raw,status)}
async function save(status='draft'){if(state.saving)return false;clearErrors();if(!state.area)throw fieldError('area','Escolhe a área de trabalho.');if(state.localMode&&!state.need)state.of=$('local-of').value.trim();if(!state.of)throw new Error('Indica o número da OF antes de guardar.');const raw=submittedValues();if(status==='ready'&&!raw.operation)throw fieldError('operation','Escolhe a operação antes de concluir.');state.saving=true;try{return await atomicSave(raw,status)}finally{state.saving=false}}
async function mayLeave(){if(!state.dirty)return true;return new Promise(resolve=>{const d=$('leave-dialog');$('leave-error').textContent='';d.showModal();function done(value){d.close();resolve(value)}$('leave-cancel').onclick=()=>done(false);$('leave-discard').onclick=()=>{state.dirty=false;done(true)};$('leave-save').onclick=async()=>{try{if(await save())done(true);else done(false)}catch(e){$('leave-error').textContent=e.message}};d.oncancel=e=>{e.preventDefault();done(false)}})}
async function showHistory(){const field=$('history-field').value;$('history-content').replaceChildren();renderSources();if(!state.need){$('history-content').append(el('p','As alterações ficam registadas quando guardares o rascunho.'))}else{const data=await api('necessidades/'+state.need+'/historico');const labels={pdf:'PDF',plan_line:'Plano importado',manual:'Introdução manual',historical:'Valor histórico'},actions={write:'Escrito',select:'Escolhido',accept:'Sugestão aceite',clear:'Limpo'};
 for(const s of data.fields.filter(s=>(!field||s.field===field)&&(s.scope==='piece'||s.scope===state.op))){const box=el('section',null,'item');box.append(el('h3',state.cat?.fields.find(f=>f.id===s.field)?.label||s.field),el('p','Valor guardado: '+fmt(s.value)),el('p','Sugestão: '+fmt(s.suggestion)+' · '+(labels[s.source.kind]||fmt(s.source.kind))),el('p',(actions[s.human_decision]||'Valor recebido')+' · '+fmt(s.actor)+' · '+fmt(s.decided_at)));$('history-content').append(box)}
 for(const event of data.events)for(const c of event.detail.changes||[]){if(field&&c.field!==field)continue;$('history-content').append(el('p',event.actor+' · '+event.created_at+' · '+(state.cat?.fields.find(f=>f.id===c.field)?.label||c.field)+': '+fmt(c.before)+' → '+fmt(c.after)))}}
 if(!$('history-dialog').open)$('history-dialog').showModal();
}
function showDrawing(){const link=state.detail?.sources.find(s=>s.kind==='pdf'),doc=state.pdf?.id||link?.payload.document_id;if(!doc)return;const frame=el('iframe');frame.title='Desenho da peça';frame.src='/planeamento/api/dossies/'+encodeURIComponent(doc)+'/pdf';$('drawing-content').replaceChildren(frame);$('drawing-dialog').showModal()}
function openConference(proof){state.conferenceProof=proof;const p=proof.evidence;$('conference-values').replaceChildren(metric('Quantidade total necessária',p.required),metric('Em falta no plano importado',p.macro_remaining),metric('Produção validada no OCR',p.ocr_quantity));const form=$('conference-form');form.elements.accepted_required.value=p.required??'';form.elements.accepted_remaining.value=proof.conferences.find(c=>c.valid)?.accepted_remaining??'';$('conference-dialog').showModal()}
$('conference-open').onclick=()=>openConference(state.proof);
$('evidence-conference').onclick=()=>openConference(state.dialogProof);
async function operationEvidence(){const id=$('evidence-operation').value;if(!state.need||!id)return;state.dialogProof=await api('necessidades/'+state.need+'/evidencia?operacao='+id);const p=state.dialogProof.evidence;$('evidence').replaceChildren(metric('Quantidade total necessária',p.required),metric('Em falta no plano importado',p.macro_remaining),metric('Produção validada no OCR',p.ocr_quantity));if(p.ocr_quantity==null)$('evidence').append(el('p','Sem produção OCR associada. Isto não significa produção igual a zero.'));for(const c of state.dialogProof.conferences.slice(0,1))$('evidence').append(metric(c.valid?'Quantidade em falta confirmada':'Confirmação a rever',c.accepted_remaining));for(const warning of p.warnings)$('evidence').append(el('p',warning));$('evidence-conference').hidden=false;}
$('evidence-operation').onchange=safe(operationEvidence);
$('conference-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;try{await api('conferencias',request({need_id:state.need,operation_id:state.conferenceProof.evidence.operation_id,expected_revision:state.conferenceProof.need_revision,evidence_hash:state.conferenceProof.evidence.evidence_hash,accepted_required:form.elements.accepted_required.value,accepted_remaining:form.elements.accepted_remaining.value,reason:form.elements.reason.value}));$('conference-dialog').close();await evidence();if($('evidence-dialog').open)await operationEvidence()}catch(err){form.querySelector('.dialog-error').textContent=err.message}};
async function production(){
 const data=await api('producao/pendencias?of='+encodeURIComponent(state.of)+'&area='+state.area+'&pagina='+state.page+'&estado='+$('production-filter').value+'&motivo='+$('production-reason').value+'&incluir_sem_of='+$('production-unknown').checked);
 $('production-content').replaceChildren();
 for(const record of data.records){
  const item=el('section',null,'item');
  item.append(el('p','OF registada: '+fmt(record.production_order)));
  item.append(el('h3','Folha '+record.sheet_no+' · '+fmt(record.model_ref)),el('p',record.reason+' · '+fmt(record.quantity)+' un. · '+fmt(record.length_mm)+' mm'));
  const link=el('a','Abrir folha validada');link.href=(state.area==='perfis'?'https://perfis.nikufra.ai':'https://cantoneiras.nikufra.ai')+'/sheet/'+encodeURIComponent(record.sheet_uid);link.target='_blank';link.rel='noopener';item.append(link);
  const allocationBox=el('div'), entries=[];
  async function addAllocation(initial={}){
   const box=el('fieldset'),target=el('select'),operation=el('select'),child=el('select'),quantity=el('input');
   box.append(el('legend','Distribuição da produção'));
   target.setAttribute('aria-label','Peça');operation.setAttribute('aria-label','Operação');child.setAttribute('aria-label','Referência filha');quantity.setAttribute('aria-label','Quantidade atribuída');quantity.inputMode='numeric';quantity.value=initial.quantity??(entries.length?'':record.quantity??'');
   fillOptions(target,record.candidates.map(n=>({value:n.id,label:n.component_ref+' · '+fmt(n.specification.length_mm)+' mm'})),initial.need_id||state.need);
   fillOptions(child,record.children.map(c=>({value:c.plan_key,label:fmt(c.component_ref)+' · '+fmt(c.assumed_quantity)+' un.'})),initial.child_key);
   const entry={box,target,operation,child,quantity,detail:null};
   async function options(){if(!target.value)return;entry.detail=target.value===state.need?state.detail:await api('necessidades/'+target.value);fillOptions(operation,entry.detail.operations.filter(o=>o.area===state.area).map(o=>({value:o.id,label:o.code})),initial.operation_id||state.op)}
   target.onchange=safe(options);child.onchange=()=>{quantity.value=record.children.find(c=>c.plan_key===child.value)?.assumed_quantity??''};await options();
   box.append(el('label','Peça'),target,el('label','Operação'),operation);
   if(record.children.length)box.append(el('label','Referência filha congelada'),child);
   box.append(el('label','Quantidade atribuída'),quantity);
   const remove=el('button','Remover distribuição');remove.type='button';remove.onclick=()=>{entries.splice(entries.indexOf(entry),1);box.remove()};box.append(remove);entries.push(entry);allocationBox.append(box);
  }
  item.append(allocationBox);
  for(const initial of record.decision?.allocations?.length?record.decision.allocations:[{}])await addAllocation(initial);
  const more=el('button','Adicionar distribuição');more.type='button';more.onclick=safe(()=>addAllocation());item.append(more);
  const reason=el('textarea');reason.setAttribute('aria-label','Justificação');item.append(el('label','Justificação'),reason);const error=el('p','','dialog-error');item.append(error);
  for(const [status,label] of [['associated','Guardar associação'],['pending','Manter pendente'],['unrelated','Sem correspondência']]){
   const button=el('button',label);button.type='button';button.onclick=async()=>{try{
    const allocations=entries.map(e=>({need_id:e.target.value,operation_id:e.operation.value,expected_need_revision:e.detail?.need.revision,child_key:e.child.value||null,quantity:e.quantity.value===''?null:e.quantity.value}));
    const saved=await api('associacoes',request({production_record_id:record.id,expected_revision:record.decision?.revision||0,evidence_hash:record.evidence_hash,status,reason:reason.value,allocations:status==='associated'?allocations:[]}));
    record.decision={...saved,allocations};error.textContent='Decisão guardada.';await evidence();
   }catch(err){error.textContent=err.message}};item.append(button);
  }
  $('production-content').append(item);
 }
 $('production-prev').disabled=state.page<=1;$('production-next').disabled=state.page*50>=data.total;
}
$('production-unknown').onchange=safe(async()=>{state.page=1;await production()});
$('production-reason').onchange=safe(async()=>{state.page=1;await production()});
$('production-filter').onchange=safe(async()=>{state.page=1;await production()});
$('production-open').onclick=safe(async()=>{if(!state.of||!state.area)throw new Error('Seleciona a OF e a área de trabalho.');await production();$('production-dialog').showModal()});$('production-prev').onclick=safe(async()=>{state.page--;await production()});$('production-next').onclick=safe(async()=>{state.page++;await production()});
async function newLocalOrder(){resetPiece();state.localMode=true;state.of=null;state.order=null;state.registration=null;$('local-of').readOnly=false;for(const k of ['of','ov','customer','designation','delivery_date'])$('local-'+k).value='';$('new-order-fields').hidden=false;$('search').hidden=true;$('context').replaceChildren();$('order-details').hidden=true;$('change-order').hidden=true;$('title').textContent='Registo de planeamento';$('next-step').textContent='Indica a nova OF, a OV e os dados da peça.';render({});$('preparation').hidden=false;history.replaceState(null,'','/planeamento/manual'+(state.area?'?area='+state.area:''));}
$('new-local-order').onclick=safe(async()=>{if(await mayLeave())await newLocalOrder()});
$('existing-order').onclick=()=>{$('search').hidden=false;$('query').focus()};
for(const k of ['of','ov','customer','designation','delivery_date'])$('local-'+k).oninput=()=>{state.dirty=true};
$('preparation').onsubmit=safe(async e=>{e.preventDefault();await save(e.submitter?.name==='ready'?'ready':'draft')});
$('preparation').addEventListener('input',quantityNotice);
$('search').onsubmit=safe(async e=>{e.preventDefault();const data=await api('ordens?q='+encodeURIComponent($('query').value));$('orders').replaceChildren();for(const o of data.orders||[]){const b=el('button',o.of+' · '+fmt(o.customer_name));b.type='button';b.onclick=safe(async()=>{if(await mayLeave())await selectOrder(o.of)});$('orders').append(b)}if(!$('orders').children.length)$('orders').append(el('p','Nenhuma OF encontrada. Confirma o número ou pesquisa pelo cliente.'))});
$('change-order').onclick=()=>{$('search').hidden=!$('search').hidden;if(!$('search').hidden)$('query').focus()};
$('references-open').onclick=safe(referenceList);$('reference-query').oninput=renderReferences;
$('area').onchange=safe(async()=>{const area=$('area').value,previous=state.area;if(previous&&state.dirty&&!await mayLeave()){$('area').value=previous;return}await loadCatalog(area);if(state.need)await loadNeed(state.need);else{render(state.pdf?{...state.piece.values,operation:state.area==='perfis'?'corte':''}:{...values(),operation:state.area==='perfis'?'corte':''});await evidence()}modeLinks()});
$('distinct').onclick=safe(async()=>{state.pending.values={...state.pending.values,identity_discriminator:$('distinct-variant').value};await atomicSave(state.pending.values,state.pendingStatus,{create_distinct:true,reason:$('identity-reason').value})});
$('history-open').onclick=safe(showHistory);$('history-field').onchange=safe(showHistory);$('drawing-open').onclick=showDrawing;
$('evidence-open').onclick=safe(async()=>{await evidence();fillOptions($('evidence-operation'),(state.detail?.operations||[]).filter(o=>o.area===state.area).map(o=>({value:o.id,label:o.code==='corte'?'Corte':o.code==='abocardar'?'Abocardar':o.code})),state.op);$('evidence-conference').hidden=true;if(state.op)await operationEvidence();$('evidence-dialog').showModal()});
$('another-piece').onclick=safe(async()=>{if(await mayLeave())await selectOrder(state.of)});
$('next-piece').onclick=safe(async()=>{if(await mayLeave())location.assign(pdfUrl(state.nextPiece))});
$('use-pdf-order').onclick=safe(acceptPdf);
$('keep-selected-order').onclick=safe(()=>selectOrder(params.get('of')));
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>b.closest('dialog').close();
document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(!a||a.target||e.ctrlKey||e.metaKey||!state.dirty)return;const url=new URL(a.href,location.href);if(url.origin!==location.origin)return;e.preventDefault();safe(async()=>{if(await mayLeave())location.assign(a.href)})()});
window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue=''}});
safe(async()=>{await loadCatalog(params.get('area'));try{state.sourceStatus=await api('fontes')}catch{state.sourceStatus=null}updateReady();
 if(params.get('document')&&params.get('piece'))await sourcePdf();
 else if(params.get('necessidade'))await loadNeed(params.get('necessidade'));
 else if(params.get('registo')){const response=await api('registos/'+params.get('registo')),record=response.record;if(record.need_id){await loadCatalog(record.area);state.op=record.operation_id;await loadNeed(record.need_id)}else throw new Error('Esta ficha histórica ainda precisa de ser ligada a uma peça.');}
 else if(params.get('of')){await selectOrder(params.get('of'));if(params.get('linha')){await referenceList(false);const reference=state.references.find(r=>r.plan_key===params.get('linha'));if(!reference)throw new Error('A linha já não está disponível. Volta à vista RAW e atualiza a lista.');await reference.open();}}
 else await newLocalOrder();
})();
})();
