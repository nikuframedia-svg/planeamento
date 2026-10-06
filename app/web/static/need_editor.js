(() => {
'use strict';
const $=id=>document.getElementById(id), params=new URLSearchParams(location.search);
const state={area:'',cat:null,need:null,op:null,source:null,of:null,detail:null,order:null,decisions:{},proof:null,page:1,dirty:false,pdf:null,piece:null,raw:{},references:[],sourceStatus:null,opDrafts:{},operationCode:'',saving:false,suggested:{},areaAuto:false,base:{},orderChanged:new Set()};
// Registo só com o essencial (07/10/2026): grava sempre; avisos discretos ao lado do campo; sem confirmações.
const QTD_WARNING='QTD tem de ser um número inteiro (senão não entra na Carteira)',ORDER_FIELDS=['ov','customer','designation','delivery_date'];
function el(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
function fmt(v){return v==null||v===''?'Não disponível':Array.isArray(v)?v.join(', '):typeof v==='object'?JSON.stringify(v):String(v)}
function safe(fn){return (...args)=>Promise.resolve().then(()=>fn(...args)).catch(fail)}
async function api(path,body){const r=await fetch('/planeamento/api/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok){const err=new Error(data.error||'Não foi possível concluir o pedido.');err.fields=data.fields||{};err.status=r.status;throw err}return data}
function request(body){return {request_id:crypto.randomUUID(),...body}}
function openParents(node){for(let p=node?.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true}
function clearErrors(){$('error').hidden=true;for(const e of document.querySelectorAll('.field-error'))e.textContent='';for(const e of document.querySelectorAll('[aria-invalid]'))e.removeAttribute('aria-invalid')}
function fail(error){$('error').textContent=error.message;$('error').hidden=false;let first;for(const [name,message] of Object.entries(error.fields||{})){const target=$('error-'+name),input=$('field-'+name)||$(name);if(target){target.textContent=message;openParents(target);if(target.closest('.field'))target.closest('.field').hidden=false}if(input){input.setAttribute('aria-invalid','true');first??=input}}(first||$('error')).scrollIntoView({block:'center'});first?.focus()}
function fieldError(name,message){const e=new Error(message);e.fields={[name]:message};return e}
// Registo manual (06/10/2026): datas também em dd/mm/aaaa; ajuda dos campos no cursor; setor lembrado.
function isoDate(v){const s=String(v??'').trim();let m=s.match(/^(\d{4})-(\d{2})-(\d{2})/);if(m)return m[0];m=s.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);return m?m[3]+'-'+m[2].padStart(2,'0')+'-'+m[1].padStart(2,'0'):null}
function setHelp(id,text){const help=$('help-'+id);if(help)help.textContent=text;else{const input=$('field-'+id);if(input&&!input.classList.contains('suggested'))input.title=text}}
const AREA_KEY='planeamento.manual.setor';
function lastArea(){try{const v=localStorage.getItem(AREA_KEY);return ['perfis','cantoneiras'].includes(v)?v:''}catch{return ''}}
function rememberArea(area){try{if(area)localStorage.setItem(AREA_KEY,area)}catch{}}
function val(id){const node=$('field-'+id);if(id==='material_requested'&&node)return node.value===''?null:node.value==='true';return node?(node.type==='checkbox'?node.checked:node.value):state.raw[id]??null}
const baseFields=JSON.parse($('field-contract').textContent);
function values(){return {...state.raw,...Object.fromEntries((state.cat?.fields||baseFields).filter(f=>f.editor_visible).map(f=>[f.id,val(f.id)]))}}
function fillOptions(node,options,current){node.replaceChildren(new Option('Por definir',''));for(const opt of options||[])node.add(new Option(typeof opt==='object'?opt.label:opt,typeof opt==='object'?opt.value:opt));if(current&&!Array.from(node.options).some(x=>x.value===String(current)))node.add(new Option(current+' — opção a rever',current));node.value=current??''}
function key(v){return String(v||'').toLocaleLowerCase('pt-PT').replace('rectangular','retangular')}
function mark(name,type){state.decisions[name]=type;state.dirty=true;$('after-save').hidden=true;unsuggest(name);schedulePreview();if(['component_ref','profile','team','material_type'].includes(name))scheduleSuggest()}
function showConditional(){if(!state.cat)return;const material=key(val('material_type')),custom=val('custom_profile'),wrap=id=>$('wrap-'+id)||{};
 wrap('custom_profile').hidden=true;wrap('special_profile').hidden=!custom||!state.cat.profiles[material]?.length;wrap('geometry').hidden=!custom&&(Boolean(state.cat.geometries[material])||!material||Boolean(state.cat.profiles[material]?.length));
 // Como no Excel: Ø, Largura, Altura e Espessura sempre visíveis, seja qual for o tipo de material.
 for(const name of ['outer_diameter_mm','width_mm','height_mm','thickness_mm'])if($('wrap-'+name))$('wrap-'+name).hidden=false;
 wrap('identity_discriminator').hidden=!val('identity_discriminator');
}
function profiles(){if(!state.cat)return;let input=$('field-profile');if(!input)return;if(input.tagName!=='INPUT'){const n=el('input');n.id=input.id;n.name=input.name;n.value=input.value;input.replaceWith(n);input=n}input.type='text';input.disabled=false;input.oninput=()=>mark('profile','write');setHelp('profile','Designação livre; o catálogo serve de referência.');showConditional()}
function attention(field,message){const box=$('wrap-'+field);if(!box)return;box.hidden=false;box.classList.add('field-attention');box.append(el('p',message,'help'));openParents(box)}
function render(raw={}){
 raw={...raw};if(state.area==='perfis'&&!raw.operation)raw.operation='corte';state.raw={...raw};state.operationCode=raw.operation||'';state.suggested={};
 for(const id of ['cut-fields','piece-fields','operation-fields','extra-fields'])$(id).replaceChildren();
 const groups={cut:'cut-fields',piece:'piece-fields',work:'operation-fields',extra:'extra-fields'};
 for(const f of [...(state.cat?.fields||baseFields)].filter(f=>f.editor_visible&&(state.cat||f.group==='cut'||f.group==='extra')).sort((a,b)=>a.order-b.order)){if(!state.cat&&f.type==='select')continue;const box=el('div',null,'field');box.id='wrap-'+f.id;const label=el('label',f.label+(f.unit&&!(f.group==='piece'&&f.unit==='un.')?' ('+f.unit+')':''));label.htmlFor='field-'+f.id;
  let input=document.createElement(f.type==='tristate'?'select':f.type==='textarea'?'textarea':'input');input.id='field-'+f.id;input.name=f.id;
  if(f.type==='tristate'){fillOptions(input,[{value:'true',label:'Sim'},{value:'false',label:'Não'}],raw[f.id]===true?'true':raw[f.id]===false?'false':'')}
  else if(f.type==='select'){
   const options=f.id==='operation'?[...state.cat.operations,...state.cat.additional_operations.filter(o=>o.countable)]:f.options||[];
   const list=el('datalist');list.id='options-'+f.id;for(const option of options){const o=el('option');o.value=typeof option==='object'?option.value:option;list.append(o)}box.append(list);input.type='text';input.setAttribute('list',list.id);input.value=raw[f.id]??'';
  }
  // Abocardar só tem dois estados: X ou «-» (o desconhecido conta como «-»).
  else if(f.type==='boolean'||f.type==='checkbox'){input.type='checkbox';input.checked=f.id==='abocardar'?(raw[f.id]===true||String(raw[f.id]).trim().toUpperCase()==='X'):raw[f.id]===true}
  else if(f.type==='date'){const iso=isoDate(raw[f.id]),empty=raw[f.id]==null||raw[f.id]==='';input.type=empty||iso?'date':'text';input.value=input.type==='date'?(iso||''):raw[f.id]}
  else{if(f.type!=='textarea')input.type='text';if(f.type==='number')input.inputMode=['quantity_required','quantity_to_plan','remaining_declared','picking_week','picking_year'].includes(f.id)?'numeric':'decimal';input.value=raw[f.id]??''}
  box.append(label,input);const inline=f.help&&f.group!=='piece';const help=el('p',f.help||'','help');help.id='help-'+f.id;if(inline)box.append(help);else if(f.help){input.title=f.help;label.title=f.help}const error=el('span','','field-error');error.id='error-'+f.id;const note=el('p','','help field-note');note.id='note-'+f.id;box.append(error,note);input.setAttribute('aria-describedby',[inline?help.id:null,error.id,note.id].filter(Boolean).join(' '));
  input.addEventListener('input',()=>mark(f.id,input.type==='checkbox'?'write':input.value===''?'clear':f.type==='select'?'select':'write'));
  if(f.id==='quantity_required')input.addEventListener('input',()=>wholeNumber(f.id));
  $(groups[f.group]||'extra-fields').append(box);
  const suggestion=(state.detail?.fields||[]).find(s=>s.field===f.id&&(s.scope==='piece'||s.scope===state.op));
  // A origem mudou e o valor é teu: fica o teu, com o da origem em nota (07/10/2026).
  if(suggestion?.requires_review)box.append(el('p','('+(suggestion.source?.kind==='pdf'?'PDF':'Excel')+': '+fmt(suggestion.suggestion)+')','help'));
 }
 $('cut-section').hidden=!$('cut-fields').children.length;
 if(!state.cat){$('catalog-fields').hidden=true;$('work-sections').hidden=true;$('area-help').hidden=false;return}
 for(const id of ['material_type','geometry'])if($('field-'+id))$('field-'+id).onchange=profiles;
 $('field-operation').onchange=safe(async()=>{const code=val('operation'),old=state.operationCode;
  if(old&&old!==code&&state.dirty){$('field-operation').value=old;if(!await mayLeave())return;}
  const raw=values(),next=state.detail?.operations.find(o=>o.area===state.area&&o.code===code);state.op=next?.id||null;
  const record=state.detail?.records.find(r=>r.operation_id===state.op),piece=Object.fromEntries(state.cat.fields.filter(f=>f.scope==='piece').map(f=>[f.id,raw[f.id]]));
  state.decisions={...Object.fromEntries(Object.entries(state.decisions).filter(([name])=>!old||state.cat.fields.some(f=>f.id===name&&f.scope==='piece'))),operation:'select'};render({...(!old?raw:{}),...piece,...(record?.values_json||{}),...(record?.input_values||{}),...piece,operation:code});state.dirty=true;await evidence();
 });
 profiles();$('catalog-fields').hidden=false;$('work-sections').hidden=false;$('area-help').hidden=true;
 for(const issue of state.piece?.issues||[]){const name=({machine_group:'machine',material_description:'special_profile',operations:'operation_detail',variant:'identity_discriminator'})[issue.field]||issue.field;const chosen=state.detail?.fields.find(f=>f.field===name&&(f.scope==='piece'||f.scope===state.op));if(name&&(!chosen?.human_decision||chosen.requires_review))attention(name,issue.message);}

 $('history-field').replaceChildren(new Option('Todos os campos',''));for(const f of state.cat.fields)$('history-field').add(new Option(f.label,f.id));
 state.base=submittedValues();updateReady();schedulePreview();scheduleSuggest();
}
function wholeNumber(id){const input=$('field-'+id),note=$('note-'+id);if(!input||!note)return;const v=input.value.trim().replace(',','.');note.textContent=v===''||/^\d+(\.0+)?$/.test(v)?'':QTD_WARNING}
// Avisos essenciais do servidor (pré-visualização): texto discreto ao lado do campo, nunca a impedir de gravar.
function showWarnings(list){for(const note of document.querySelectorAll('.field-note'))note.textContent='';for(const w of list||[]){const note=$('note-'+w.field);if(note)note.textContent=w.message}}
// Preencher sozinho (06/10/2026): GET ordens/{of}/sugestoes. O valor sugerido fica com outro tom e o título
// «sugerido: origem»; nunca escreve por cima do que o utilizador escreveu nem de valores já preenchidos.
let suggestTimer,suggestSerial=0;
function currentOf(){return state.localMode&&!state.need?$('local-of').value.trim():state.of}
function scheduleSuggest(){clearTimeout(suggestTimer);if(!state.cat||!state.area||!currentOf())return;suggestTimer=setTimeout(()=>{suggestions().catch(()=>{})},350)}
function unsuggest(name){const node=$('field-'+name);if(state.suggested[name]){delete state.suggested[name];if(node){node.classList.remove('suggested');node.removeAttribute('data-suggested-from');const f=(state.cat?.fields||[]).find(x=>x.id===name);node.title=f?.group==='piece'?(f.help||''):''}}}
async function suggestions(){
 const of=currentOf(),serial=++suggestSerial;if(!of||!state.area)return;
 const q=new URLSearchParams({setor:state.area}),typed=n=>state.suggested[n]?'':String(val(n)??'').trim();
 for(const [param,name] of [['ref','component_ref'],['perfil','profile'],['equipa','team'],['material','material_type']]){const v=typed(name);if(v&&v!=='__custom__')q.set(param,v)}
 if(state.localMode&&!state.need){if($('local-customer').value.trim())q.set('cliente',$('local-customer').value.trim());if($('local-designation').value.trim())q.set('designacao',$('local-designation').value.trim())}
 let data;try{const r=await fetch('/planeamento/api/ordens/'+encodeURIComponent(of)+'/sugestoes?'+q);if(!r.ok)return;data=await r.json()}catch{return}
 if(serial!==suggestSerial||!state.cat)return;applySuggestions(data.fields||{});
}
function applySuggestions(fields){
 let changed=false;
 for(const f of state.cat.fields){if(!f.editor_visible)continue;const node=$('field-'+f.id);if(!node||node.type==='checkbox'||node.type==='hidden'||node.disabled||node.readOnly)continue;
  const s=fields[f.id],mine=state.suggested[f.id];
  if(!mine&&(state.decisions[f.id]||String(node.value??'')!==''))continue;
  if(!s||s.value==null||s.value===''){if(mine){node.value='';unsuggest(f.id);changed=true}continue}
  let value=f.type==='date'?(isoDate(s.value)||''):String(s.value);if(!value)continue;
  if(node.tagName==='SELECT'&&!Array.from(node.options).some(o=>o.value===value))continue;
  if(node.value!==value){node.value=value;changed=true}
  state.suggested[f.id]=true;node.classList.add('suggested');node.dataset.suggestedFrom=s.source_pt||'';node.title='sugerido: '+(s.source_pt||'');
 }
 if(changed){showConditional();schedulePreview()}
}
function showCalculated(v){let host=$('piece-calc');if(!host&&$('catalog-fields')){host=el('p',null,'piece-calc');host.id='piece-calc';$('catalog-fields').append(host)}if(!host)return;const n=x=>typeof x==='number'&&isFinite(x)?x.toLocaleString('pt-PT',{maximumFractionDigits:x<10?3:1}):null,parts=[];
 if(n(v?.section_unit))parts.push('Área de secção: '+n(v.section_unit)+' mm²');if(n(v?.weight_unit))parts.push('Peso por peça: '+n(v.weight_unit)+' kg');host.textContent=parts.join(' · ');host.hidden=!parts.length}
function submittedValues(){const raw=Object.fromEntries(Object.entries(values()).filter(([id])=>state.cat.fields.some(f=>f.id===id&&f.editor_visible)));if(raw.custom_profile)raw.profile=raw.special_profile||'';for(const name of ['picking_week','picking_year'])if(!state.decisions[name])delete raw[name];return raw}
let previewTimer,previewSerial=0;
function schedulePreview(){
 clearTimeout(previewTimer);const serial=++previewSerial;
 if(!$('preview-status'))return;
 $('preview-summary').replaceChildren();$('preview-results').replaceChildren();
 const of=state.localMode&&!state.need?$('local-of').value.trim():state.of;
 const picking=$('picking-summary');picking.hidden=state.area!=='perfis';picking.textContent=of?'A procurar Picking desta OF…':'O Picking será recuperado automaticamente pela OF.';
 if(!state.decisions.picking_week&&$('field-picking_week'))$('field-picking_week').value='';
 if(!state.cat||!of){$('preview-status').textContent='Preenche a OF e escolhe o setor para calcular.';return}
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
   ...(state.source?{source:state.source}:{}),catalog_version:state.cat.version,values:submittedValues(),decisions:state.decisions,
   ...(state.localMode?{local_order:{values:{delivery_date:$('local-delivery_date').value}}}:{})});
  if(serial!==previewSerial)return;
  showCalculated(result.row?.values);showWarnings(result.registration_warnings);
  if(state.area==='perfis'){
   const v=result.row.values,host=$('picking-summary');host.hidden=false;host.replaceChildren();
   if(!state.decisions.picking_week&&$('field-picking_week'))$('field-picking_week').value=v.picking_week??'';
   if(!state.decisions.picking_year&&$('field-picking_year'))$('field-picking_year').value=v.picking_year??v.picking_year_inferred??'';
   const day=v.picking_date?new Intl.DateTimeFormat('pt-PT',{timeZone:'UTC'}).format(new Date(v.picking_date+'T12:00:00Z')):null;
   host.append(el('strong',v.picking_conflict?'Picking em conflito':day?`Data de Picking: ${day}`:'Sem data de Picking disponível'));
   host.append(el('p',v.picking_conflict?'Existem semanas contraditórias na origem. Confirma a semana nos campos de Picking.':day?`Semana ${v.picking_week} · ${v.picking_origin||'Planeamento'}${v.picking_deadline_provisional?(v.picking_year_inferred?' · ano '+v.picking_year_inferred+' deduzido pela semana; podes indicar outro ano.':' · ano 2026 assumido; podes confirmar outro ano.'):''}`:'Sem semana utilizável para esta OF; podes indicá-la nos campos de Picking.','help'));
   if(v.picking_evidence?.length)host.append(el('p',v.picking_evidence.map(e=>`${e.sheet} · linha ${e.row}: W${e.week}`).join('; '),'help'));
  }
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
 }catch(error){if(serial===previewSerial){$('preview-status').textContent=error.message;$('picking-summary').textContent='Picking por confirmar: '+error.message}}
}
for(const id of ['local-of','local-delivery_date'])$(id).addEventListener('input',schedulePreview);
for(const id of ['local-customer','local-designation'])$(id).addEventListener('change',scheduleSuggest);
async function loadCatalog(area){state.area=['perfis','cantoneiras'].includes(area)?area:'';$('area').value=state.area;state.cat=state.area?await api('catalogos?contrato=3&area='+state.area):null;rememberArea(state.area);const d=$('local-delivery_date'),v=d.value;d.type=!v||isoDate(v)?'date':'text';if(d.type==='date')d.value=isoDate(v)||''}
// O setor escolhido automaticamente (último usado) segue a OF, o PDF ou a peça; o escolhido à mão fica.
function areaFollows(areas){return (!state.area||state.areaAuto)&&areas.length===1&&areas[0]!==state.area}
function modeLinks(){const suffix=state.of?'?of='+encodeURIComponent(state.of):'';$('manual-link').href='/planeamento/manual'+suffix;$('pdf-link').href='/planeamento/dossies'+suffix;for(const [id,pdf] of [['manual-link',false],['pdf-link',true]]){const a=$(id);if(Boolean(state.pdf||state.source?.kind==='pdf')===pdf)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')}}
function orderFields(context){for(const k of ['ov','customer','designation','delivery_date'])$('local-'+k).readOnly=Boolean(context);
 if(context){$('local-ov').value=(context.ovs||[]).join(', ');$('local-customer').value=context.customer_name||'';$('local-designation').value=context.observations||'';$('local-delivery_date').value=String(context.delivery_date||'').slice(0,10);state.orderFilled=true}
 else if(state.orderFilled){for(const k of ['ov','customer','designation','delivery_date'])$('local-'+k).value='';state.orderFilled=false}}
async function orderContext(of,order){state.of=of;modeLinks();$('order-facts').replaceChildren();$('order-details').hidden=!of||state.localMode;
 if(!of)return;$('local-of').value=of;state.lookedUp=of;$('title').textContent='Registar peça · '+of;
 if(state.localMode)return;
 try{state.order=order||await api('ordens/'+encodeURIComponent(of));const c=state.order.context;orderFields(c);
  for(const [label,value] of [['Estado CPIS',c.cpis_status],['Fim previsto da Produção',c.planned_finish_date],['Data de entrega',c.delivery_date]])$('order-facts').append(el('p',label+': '+fmt(value)));
  const source=state.sourceStatus?.cpis;$('order-facts').append(el('p',c.administrative_origin?c.administrative_origin+'; sem estado CPIS confirmado.':state.order.cpis_mode==='direct'?'Última confirmação CPIS: '+fmt(source?.checked_at):'CPIS importado da macro — sem confirmação direta.'));
  $('of-status').textContent='OF encontrada'+(c.sources?.length?' · '+c.sources.map(a=>a==='perfis'?'MTG2 Perfis':'MTG3 Cantoneiras').join(' e '):'')+'.';
 }catch(error){state.order=null;$('order-facts').append(el('p',error.message));$('order-details').open=true}
}
function resetPiece(){state.need=null;state.op=null;state.detail=null;state.source=null;state.pdf=null;state.piece=null;state.raw={};state.decisions={};state.opDrafts={};state.dirty=false;state.orderChanged.clear();state.proof=null;$('sources').replaceChildren();$('drawing-open').hidden=true;$('after-save').hidden=true;$('quantity-notice').hidden=true;clearErrors()}
async function selectOrder(of,order,keep={}){state.localMode=false;$('local-of').readOnly=false;resetPiece();await orderContext(of,order);if(areaFollows(state.order?.context.sources||[]))await loadCatalog(state.order.context.sources[0]);render(keep);state.dirty=Object.values(keep).some(v=>v!==''&&v!=null&&v!==false);$('preparation').hidden=false;$('next-step').textContent='Escolhe a peça desta OF ou preenche os dados.';await evidence();history.replaceState(null,'','/planeamento/manual?of='+encodeURIComponent(state.of)+(state.area?'&area='+state.area:''));await showPieces(true);}
async function showPieces(auto){$('order-pieces').hidden=true;if(!state.of||!state.area||state.localMode||state.need)return;await referenceList(false);$('order-pieces').hidden=!state.references.length;if(auto&&!state.dirty&&state.references.length===1)await state.references[0].open();}
function cantoneirasLine(raw){const text=String(raw.other_operations||''),pick=(n,list)=>{const m=text.match(new RegExp(n+'ª Oper\\.:\\s*([^;]+)'));const v=m?m[1].trim():'';return (list||[]).some(o=>String(o.value)===v)?v:''};
 raw.operation=pick(1,state.cat.operations);raw.operation_detail=pick(2,state.cat.additional_operations);
 const description=String(raw.material_description||'').trim();if(!raw.profile&&description){const flat=description.toUpperCase().replace(/\s+/g,''),options=state.cat.profiles[key(raw.material_type)]||Object.values(state.cat.profiles).flat();raw.profile=options.filter(p=>flat.startsWith(String(p).toUpperCase().replace(/\s+/g,''))).sort((a,b)=>b.length-a.length)[0]||description.split(/\s+/)[0]}
 if(!raw.grade){const grade=description.match(/\bS\d{3}[A-Z0-9]*\b/i);if(grade)raw.grade=grade[0].toUpperCase()}}
async function referenceList(showDialog=true){
 const suffix='of='+encodeURIComponent(state.of)+'&area='+encodeURIComponent(state.area);
 const all=await api('necessidades/lista?'+suffix+'&populacao=active');
 state.references=all.needs.map(n=>({label:n.component_ref+' · '+fmt(n.specification.profile)+' · '+fmt(n.specification.length_mm)+' mm',open:()=>loadNeed(n.id)}));
 const active=await api('linhas?'+suffix+'&populacao=active');
 const available=new Map(active.lines.map(line=>[line.plan_key,line]));
 for(const line of state.order?.plan_lines||[]){
  const source=available.get(line.plan_key);
  if(!source||(source.planning_key&&!source.planning_key.startsWith('macro:')))continue;
  state.references.push({plan_key:line.plan_key,label:line.component_ref+' · '+fmt(line.profile_type||line.material_description)+' · '+fmt(line.length_mm)+' mm · plano importado',open:async()=>{
   const data=await api('linhas?'+suffix+'&populacao=active');
   const row=data.lines.find(l=>l.plan_key===line.plan_key);
   if(!row)throw new Error('A linha já não está ativa. Atualiza a lista de referências.');
   resetPiece();state.source={kind:'plan_line',id:line.plan_key,version:data.snapshot.snapshot_id};
   const raw={...row.values};if(state.area==='cantoneiras')cantoneirasLine(raw);raw.quantity_to_plan=null;render(raw);$('next-step').textContent='Dados preenchidos a partir do Excel. Confirma e guarda.';await evidence();
  }});
 }
 renderReferences();
}
function renderReferences(){const q=key($('reference-query').value);$('references').replaceChildren();for(const item of state.references.filter(r=>key(r.label).includes(q))){const b=el('button',item.label);b.type='button';b.onclick=safe(async()=>{if(!await mayLeave())return;await item.open()});$('references').append(b)}if(!$('references').children.length)$('references').append(el('p','Não foram encontradas peças. Podes escrever uma nova referência no formulário.'))}
async function loadNeed(id){state.need=id;state.detail=await api('necessidades/'+id);state.localMode=Boolean(state.detail.local_order);$('order-pieces').hidden=true;$('local-of').value=state.detail.need.production_order_no;$('local-of').readOnly=true;if(state.localMode){orderFields(null);for(const k of ['ov','customer','designation'])$('local-'+k).value=state.detail.local_order.values_json[k]||'';const d=$('local-delivery_date'),v=state.detail.local_order.values_json.delivery_date||'';d.type=!v||isoDate(v)?'date':'text';d.value=d.type==='date'?(isoDate(v)||''):v;}const areas=[...new Set(state.detail.operations.map(o=>o.area))];if(areaFollows(areas))await loadCatalog(areas[0]);const record=state.detail.records.find(r=>r.area===state.area&&r.operation_id===state.op)||state.detail.records.find(r=>r.area===state.area);state.op=record?.operation_id||null;state.decisions={};state.opDrafts={};state.orderChanged.clear();await orderContext(state.detail.need.production_order_no);render({...record?.values_json,...state.detail.need.specification,...record?.input_values,...state.detail.need.input_values});$('preparation').hidden=false;$('title').textContent=state.of+' · '+(state.detail.need.component_ref||'Nova peça');$('next-step').textContent='Confirma os dados e guarda as alterações.';renderSources();state.dirty=false;await evidence();history.replaceState(null,'','/planeamento/preparar?necessidade='+id+(state.area?'&area='+state.area:'')+(state.pdf?'&document='+encodeURIComponent(state.pdf.id)+'&piece='+encodeURIComponent(state.piece.id):'')+($('production-source').value==='original'?'&ocr_source=original':''));}
function renderSources(){$('sources').replaceChildren();const sources=state.detail?.sources||[];for(const s of sources){$('sources').append(el('p',s.kind==='pdf'?'PDF · revisão '+s.version:'Plano importado · versão '+s.version))}if(!sources.length)$('sources').append(el('p',state.pdf?state.pdf.filename:'Dados introduzidos manualmente.'));$('drawing-open').hidden=!state.pdf&&!sources.some(s=>s.kind==='pdf');modeLinks()}
function pdfUrl(piece){return '/planeamento/preparar?document='+encodeURIComponent(state.pdf.id)+'&piece='+encodeURIComponent(piece.id)+(state.of?'&of='+encodeURIComponent(state.of):'')}
async function sourcePdf(){state.pdf=await api('dossies/'+encodeURIComponent(params.get('document')));state.piece=state.pdf.pieces.find(p=>p.id===params.get('piece'));if(!state.piece)throw new Error('A peça não foi encontrada no PDF. Volta à lista de peças.');const requested=params.get('of');
 await acceptPdf();
 if(requested&&requested!==state.pdf.production_order)$('status').textContent='O PDF é da OF '+state.pdf.production_order+' (pediste '+requested+'): foi usada a OF do PDF.';
}
async function acceptPdf(){const doc=state.pdf,piece=state.piece;if(!doc.production_order)throw new Error('Falta identificar a OF do PDF. Abre o PDF guardado e escolhe Resolver identificação.');
 if(['queued','indexing','extracting','matching'].includes(doc.status))throw new Error('A leitura do PDF está em curso. Volta à lista para acompanhar o progresso.');
 if(['Serrote','Vanguard'].includes(piece.machine_group)&&areaFollows(['perfis']))await loadCatalog('perfis');
 state.source={kind:'pdf',id:doc.id+'/'+piece.id,document_id:doc.id,piece_id:piece.id,version:doc.revision+':'+piece.revision};
 const linked=await api('necessidades/por-origem?document='+encodeURIComponent(doc.id)+'&piece='+encodeURIComponent(piece.id));if(linked.need_id){await loadNeed(linked.need_id);return}
 await orderContext(doc.production_order);render({...piece.values,operation:piece.values.operation||(state.area==='perfis'?'corte':'')});$('preparation').hidden=false;renderSources();$('next-step').textContent='Os dados vieram do PDF. Confirma-os e preenche o que falta.';await evidence();
}
function metric(label,value){const row=el('div',null,'metric');row.append(el('span',label),el('strong',fmt(value)));return row}
// A «Quantidade a preparar agora» saiu do ecrã; aqui fica só a «Qtd em falta» e os avisos da produção registada.
function quantityNotice(){const notices=state.proof?.evidence?.warnings||[];$('quantity-summary').textContent='';$('quantity-notice').textContent=notices.join(' ');$('quantity-notice').hidden=!notices.length}
async function evidence(){state.proof=null;$('evidence').replaceChildren();$('evidence-help').textContent='Guarda para consultar as quantidades desta peça.';
 if(state.need&&state.op){state.proof=await api('necessidades/'+state.need+'/evidencia?operacao='+state.op);const p=state.proof.evidence;$('evidence-help').textContent=p.macro.length?'Quantidades da operação escolhida.':'Sem linha na macro.';$('evidence').append(metric('Quantidade total necessária',p.required),metric('Em falta no plano importado',p.macro_remaining),metric('Produção validada no OCR',p.ocr_quantity));if(p.ocr_quantity==null)$('evidence').append(el('p','Sem produção OCR associada. Isto não significa produção igual a zero.'));for(const warning of p.warnings)$('evidence').append(el('p',warning))}
 quantityNotice();updateReady();
}
// Só existe «Guardar» (07/10/2026); a conclusão que dependia do CPIS direto saiu.
function updateReady(){const form=$('preparation').elements;form.ready.disabled=false;form.ready.textContent='Guardar';if(form.draft)form.draft.hidden=true;if($('ready-reason'))$('ready-reason').textContent=''}
async function finishSaved(saved,raw,status){state.need=saved.need_id;state.op=saved.operation_id;await loadNeed(state.need);$('status').textContent='Registo guardado · '+(raw.component_ref||state.of)+'.';if(saved.publication?.areas?.[state.area])$('status').textContent+=' Linha atualizada na RAW; agregados em processamento.';$('after-save').hidden=false;let link=document.getElementById('see-raw');if(!link){link=el('a','Ver na RAW');link.id='see-raw';$('after-save').append(link)}link.href=saved.raw_url||('/planeamento/raw?area='+state.area+'&need='+state.need);const index=state.pdf?.pieces.findIndex(p=>p.id===state.piece?.id);state.nextPiece=state.pdf?.pieces.slice(index+1).find(p=>!['excluded','superseded'].includes(p.state));$('next-piece').hidden=!state.nextPiece;return true}
// Campos que este formulário mudou: se a peça mudou entretanto (importação do Excel), o servidor grava só estes
// por cima da versão atual em vez de recusar.
function changedFields(raw){return [...new Set([...Object.keys(raw).filter(k=>String(raw[k]??'')!==String(state.base[k]??'')),...Object.keys(state.decisions)])]}
async function atomicSave(raw,status){const payload={...(state.localMode?{local_order:{expected_revision:state.detail?.local_order?.revision||0,values:Object.fromEntries(ORDER_FIELDS.map(k=>[k,$('local-'+k).value]))},local_order_changed_fields:[...state.orderChanged]}:{}),area:state.area,production_order_no:state.of,source:state.source,need_id:state.need||undefined,expected_revision:state.detail?.need.revision,catalog_version:state.cat.version,record_status:status,values:raw,decisions:state.decisions,changed_fields:changedFields(raw)};return finishSaved(await api('necessidades/registar',request(payload)),raw,status)}
async function save(status='ready'){if(state.saving)return false;clearErrors();if(!state.area)throw fieldError('area','Escolhe o setor.');if(state.localMode&&!state.need)state.of=$('local-of').value.trim();if(!state.of)throw new Error('Indica o número da OF antes de guardar.');const raw=submittedValues();state.saving=true;try{return await atomicSave(raw,status)}finally{state.saving=false}}
async function mayLeave(){if(!state.dirty)return true;return new Promise(resolve=>{const d=$('leave-dialog');$('leave-error').textContent='';d.showModal();function done(value){d.close();resolve(value)}$('leave-cancel').onclick=()=>done(false);$('leave-discard').onclick=()=>{state.dirty=false;done(true)};$('leave-save').onclick=async()=>{try{if(await save())done(true);else done(false)}catch(e){$('leave-error').textContent=e.message}};d.oncancel=e=>{e.preventDefault();done(false)}})}
async function showHistory(){const field=$('history-field').value;$('history-content').replaceChildren();renderSources();if(!state.need){$('history-content').append(el('p','As alterações ficam registadas quando guardares.'))}else{const data=await api('necessidades/'+state.need+'/historico');const labels={pdf:'PDF',plan_line:'Plano importado',manual:'Introdução manual',historical:'Valor histórico'},actions={write:'Escrito',select:'Escolhido',accept:'Sugestão aceite',clear:'Limpo'};
 for(const s of data.fields.filter(s=>(!field||s.field===field)&&(s.scope==='piece'||s.scope===state.op))){const box=el('section',null,'item');box.append(el('h3',state.cat?.fields.find(f=>f.id===s.field)?.label||s.field),el('p','Valor guardado: '+fmt(s.value)),el('p','Sugestão: '+fmt(s.suggestion)+' · '+(labels[s.source.kind]||fmt(s.source.kind))),el('p',(actions[s.human_decision]||'Valor recebido')+' · '+fmt(s.actor)+' · '+fmt(s.decided_at)));$('history-content').append(box)}
 for(const event of data.events)for(const c of event.detail.changes||[]){if(field&&c.field!==field)continue;$('history-content').append(el('p',event.actor+' · '+event.created_at+' · '+(state.cat?.fields.find(f=>f.id===c.field)?.label||c.field)+': '+fmt(c.before)+' → '+fmt(c.after)))}}
 if(!$('history-dialog').open)$('history-dialog').showModal();
}
function showDrawing(){const link=state.detail?.sources.find(s=>s.kind==='pdf'),doc=state.pdf?.id||link?.payload.document_id;if(!doc)return;const frame=el('iframe');frame.title='Desenho da peça';frame.src='/planeamento/api/dossies/'+encodeURIComponent(doc)+'/pdf';$('drawing-content').replaceChildren(frame);$('drawing-dialog').showModal()}
async function operationEvidence(){const id=$('evidence-operation').value;if(!state.need||!id)return;state.dialogProof=await api('necessidades/'+state.need+'/evidencia?operacao='+id);const p=state.dialogProof.evidence;$('evidence').replaceChildren(metric('Quantidade total necessária',p.required),metric('Em falta no plano importado',p.macro_remaining),metric('Produção validada no OCR',p.ocr_quantity));if(p.ocr_quantity==null)$('evidence').append(el('p','Sem produção OCR associada. Isto não significa produção igual a zero.'));for(const warning of p.warnings)$('evidence').append(el('p',warning))}
$('evidence-operation').onchange=safe(operationEvidence);
async function production(){
 const sequence=state.productionSequence=(state.productionSequence||0)+1;
 $('production-content').replaceChildren(el('p','A carregar produção…'));
 const data=await api('producao/pendencias?of='+encodeURIComponent(state.of)+'&area='+state.area+'&pagina='+state.page+'&estado='+$('production-filter').value+'&motivo='+$('production-reason').value+'&incluir_sem_of='+$('production-unknown').checked+'&origem='+$('production-source').value);
 if(sequence!==state.productionSequence)return;
 const content=document.createDocumentFragment();
 for(const record of data.records){
  const item=el('section',null,'item');
  item.append(el('p','OF registada: '+fmt(record.production_order)));
  item.append(el('h3','Folha '+record.sheet_no+' · '+fmt(record.model_ref)),el('p',record.reason+' · '+fmt(record.quantity)+' un. · '+fmt(record.length_mm)+' mm'));
  const link=el('a','Abrir folha validada');link.href=record.source_url||((state.area==='perfis'?'https://perfis.nikufra.ai':'https://cantoneiras.nikufra.ai')+'/sheet/'+encodeURIComponent(record.sheet_uid));link.target='_blank';link.rel='noopener';item.append(link);
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
   const button=el('button',label);button.type='button';button.onclick=async()=>{for(const control of item.querySelectorAll('input,select,textarea,button'))control.disabled=true;try{
    const allocations=entries.map(e=>({need_id:e.target.value,operation_id:e.operation.value,expected_need_revision:e.detail?.need.revision,child_key:e.child.value||null,quantity:e.quantity.value===''?null:e.quantity.value}));
    const saved=await api('associacoes',request({production_record_id:record.id,expected_revision:record.decision?.revision||0,evidence_hash:record.evidence_hash,status,reason:reason.value,allocations:status==='associated'?allocations:[]}));
    record.decision={...saved,allocations};error.textContent='Decisão guardada.';await evidence();if($('evidence-dialog').open)await operationEvidence();schedulePreview();await production();
   }catch(err){error.textContent=err.message}finally{if(item.isConnected)for(const control of item.querySelectorAll('input,select,textarea,button'))control.disabled=false}};item.append(button);
  }
  content.append(item);
 }
 if(sequence!==state.productionSequence)return;
 $('production-content').replaceChildren(content);
 $('production-prev').disabled=state.page<=1;$('production-next').disabled=state.page*50>=data.total;
}
$('production-unknown').onchange=safe(async()=>{state.page=1;await production()});
$('production-reason').onchange=safe(async()=>{state.page=1;await production()});
$('production-source').value=params.get('ocr_source')==='original'?'original':'mes';
$('production-source').onchange=safe(async()=>{const url=new URL(location.href);if($('production-source').value==='original')url.searchParams.set('ocr_source','original');else url.searchParams.delete('ocr_source');history.replaceState(null,'',url);state.page=1;await production()});
$('production-filter').onchange=safe(async()=>{state.page=1;await production()});
$('production-open').onclick=safe(async()=>{if(!state.of||!state.area)throw new Error('Seleciona a OF e o setor.');await production();$('production-dialog').showModal()});$('production-prev').onclick=safe(async()=>{state.page--;await production()});$('production-next').onclick=safe(async()=>{state.page++;await production()});
async function newLocalOrder(){resetPiece();state.localMode=true;state.of=null;state.order=null;state.lookedUp='';$('local-of').readOnly=false;orderFields(null);for(const k of ['of','ov','customer','designation','delivery_date'])$('local-'+k).value='';$('order-details').hidden=true;$('order-pieces').hidden=true;$('title').textContent='Registo de planeamento';$('next-step').textContent='Escreve a OF e preenche os dados da peça.';render({});$('preparation').hidden=false;history.replaceState(null,'','/planeamento/manual'+(state.area?'?area='+state.area:''));}
async function lookupOrder(){const typed=$('local-of').value.trim();if($('local-of').readOnly||!typed||typed===state.lookedUp)return;state.lookedUp=typed;const serial=state.lookupSerial=(state.lookupSerial||0)+1;$('of-status').textContent='A procurar a OF…';
 let order=null;try{order=await api('ordens/'+encodeURIComponent(typed))}catch(error){if(serial!==state.lookupSerial)return;if(error.status!==404&&error.status!==400){$('of-status').textContent=error.message;state.lookedUp='';return}}
 if(serial!==state.lookupSerial)return;
 if(order){const keep=state.dirty?values():{};await selectOrder(order.context.of,order,keep);return}
 state.localMode=true;state.of=null;state.order=null;orderFields(null);$('order-details').hidden=true;$('order-pieces').hidden=true;$('title').textContent='Registo de planeamento';
 $('of-status').textContent='OF nova: não está no Excel nem no CPIS. Preenche a OV, o cliente e a data de entrega.';schedulePreview();scheduleSuggest();}
let lookupTimer;
$('local-of').addEventListener('input',()=>{clearTimeout(lookupTimer);if($('local-of').value.trim().length>=6)lookupTimer=setTimeout(safe(lookupOrder),700)});
$('local-of').addEventListener('change',()=>{clearTimeout(lookupTimer);safe(lookupOrder)()});
$('local-of').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(lookupTimer);safe(lookupOrder)()}});
const busyPdf=['queued','indexing','extracting','matching'];
async function uploadPdf(file){if(!file)return;if(!/\.pdf$/i.test(file.name))throw new Error('Escolhe um ficheiro PDF.');if(file.size>80*1024*1024)throw new Error('O limite por PDF é 80 MB.');
 $('pdf-progress').hidden=false;$('pdf-progress').textContent='A enviar '+file.name+'…';$('pdf-pieces').replaceChildren();
 const form=new FormData();form.append('file',file);const r=await fetch('/planeamento/api/dossies',{method:'POST',body:form});const data=await r.json();if(!r.ok)throw new Error(data.error||'Não foi possível guardar o PDF.');await watchPdf(data.id);}
async function watchPdf(id){const serial=state.pdfWatch=(state.pdfWatch||0)+1;
 for(;;){const doc=await api('dossies/'+encodeURIComponent(id));if(serial!==state.pdfWatch)return;
  if(busyPdf.includes(doc.status)){$('pdf-progress').textContent=(doc.progress_label||'A ler o PDF')+' · '+(Number(doc.progress)||0)+'%. Podes continuar a preencher.';await new Promise(r=>setTimeout(r,3000));continue}
  if(doc.status==='waiting_api'){$('pdf-progress').textContent='O PDF ficou guardado, mas a leitura automática não está disponível agora. Fica em «Carregar PDF».';return}
  if(doc.status==='error'){$('pdf-progress').textContent='A leitura do PDF falhou: '+fmt(doc.error);return}
  const pieces=(doc.pieces||[]).filter(p=>!['excluded','superseded'].includes(p.state));
  if(!pieces.length){$('pdf-progress').textContent='Não foram encontradas peças neste PDF.';return}
  $('pdf-progress').textContent=pieces.length+(pieces.length===1?' peça lida':' peças lidas')+' do PDF'+(doc.production_order?' · '+doc.production_order:'')+'. Escolhe a peça:';
  const open=p=>safe(async()=>{if(await mayLeave())location.assign('/planeamento/preparar?document='+encodeURIComponent(doc.id)+'&piece='+encodeURIComponent(p.id))});
  for(const p of pieces){const v=p.values||{},b=el('button',[v.component_ref,v.profile,v.length_mm!=null?v.length_mm+' mm':null,v.quantity_required!=null?v.quantity_required+' un.':null].filter(Boolean).join(' · ')||'Peça');b.type='button';b.onclick=open(p);$('pdf-pieces').append(b)}
  if(pieces.length===1&&!state.dirty)open(pieces[0])();return}}
$('pdf-file').onchange=safe(async()=>{try{await uploadPdf($('pdf-file').files[0])}finally{$('pdf-file').value=''}});
document.addEventListener('dragover',e=>{if(!e.dataTransfer?.types?.includes('Files'))return;e.preventDefault();$('pdf-drop').classList.add('dragging')});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget)$('pdf-drop').classList.remove('dragging')});
document.addEventListener('drop',e=>{if(!e.dataTransfer?.files?.length)return;e.preventDefault();$('pdf-drop').classList.remove('dragging');safe(uploadPdf)(e.dataTransfer.files[0])});
for(const k of ORDER_FIELDS)$('local-'+k).oninput=()=>{state.dirty=true;state.orderChanged.add(k)};
$('preparation').onsubmit=safe(async e=>{e.preventDefault();await save()});
$('preparation').addEventListener('input',quantityNotice);
$('reference-query').oninput=renderReferences;
$('area').onchange=safe(async()=>{const area=$('area').value,previous=state.area;if(previous&&state.dirty&&!await mayLeave()){$('area').value=previous;return}state.areaAuto=false;await loadCatalog(area);if(state.need)await loadNeed(state.need);else{render(state.pdf?{...state.piece.values,operation:state.area==='perfis'?'corte':''}:{...values(),operation:state.area==='perfis'?'corte':''});await evidence();if(!state.pdf)await showPieces(false)}modeLinks()});
$('history-open').onclick=safe(showHistory);$('history-field').onchange=safe(showHistory);$('drawing-open').onclick=showDrawing;
$('evidence-open').onclick=safe(async()=>{await evidence();fillOptions($('evidence-operation'),(state.detail?.operations||[]).filter(o=>o.area===state.area).map(o=>({value:o.id,label:o.code==='corte'?'Corte':o.code==='abocardar'?'Abocardar':o.code})),state.op);if(state.op)await operationEvidence();$('evidence-dialog').showModal()});
$('another-piece').onclick=safe(async()=>{if(await mayLeave())await selectOrder(state.of)});
$('next-piece').onclick=safe(async()=>{if(await mayLeave())location.assign(pdfUrl(state.nextPiece))});
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>b.closest('dialog').close();
document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(!a||a.target||e.ctrlKey||e.metaKey||!state.dirty)return;const url=new URL(a.href,location.href);if(url.origin!==location.origin)return;e.preventDefault();safe(async()=>{if(await mayLeave())location.assign(a.href)})()});
window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue=''}});
safe(async()=>{const asked=['perfis','cantoneiras'].includes(params.get('area'))?params.get('area'):'';state.areaAuto=!asked;await loadCatalog(asked||lastArea()||'cantoneiras');try{state.sourceStatus=await api('fontes')}catch{state.sourceStatus=null}const originalOption=$('production-source').querySelector('option[value=original]');originalOption.disabled=!state.sourceStatus?.ocr_original?.human_association_supported;if(originalOption.disabled)$('production-source').value='mes';updateReady();
 if(params.get('document')&&params.get('piece'))await sourcePdf();
 else if(params.get('necessidade'))await loadNeed(params.get('necessidade'));
 else if(params.get('registo')){const response=await api('registos/'+params.get('registo')),record=response.record;if(record.need_id){await loadCatalog(record.area);state.op=record.operation_id;await loadNeed(record.need_id)}else throw new Error('Esta ficha histórica ainda precisa de ser ligada a uma peça.');}
 else if(params.get('of')){await selectOrder(params.get('of'));if(params.get('linha')){await referenceList(false);const reference=state.references.find(r=>r.plan_key===params.get('linha'));if(!reference)throw new Error('A linha já não está disponível. Volta à vista RAW e atualiza a lista.');await reference.open();}}
 else await newLocalOrder();
})();
})();
