(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('record-form');
  const state = {area:'perfis', info:null, lines:[], source:null, record:null,
    order:null, cpisVersion:null, catalogs:null, requestId:null, dirty:false,
    generation:0, searchRequest:0, saving:false, sourceStatus:null};
  const uuid = () => {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes=crypto.getRandomValues(new Uint8Array(16)); bytes[6]=(bytes[6]&15)|64; bytes[8]=(bytes[8]&63)|128;
    const h=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
  };
  const field = name => form.elements.namedItem(name);
  const number = value => value === '' || value === null || value === undefined ? null : Number(value);
  const fmt = value => value === null || value === undefined ? '—' : Number(value).toLocaleString('pt-PT',{maximumFractionDigits:2});
  const displayDate = value => value ? new Date(value.length===10?value+'T12:00:00':value).toLocaleDateString('pt-PT') : '—';
  function node(tag, text, cls) {const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n;}
  function clearMessages() {$('error').hidden=true; $('message').hidden=true;}
  function error(message) {$('error').textContent=message; $('error').hidden=false; $('error').scrollIntoView({block:'nearest'});}
  function success(message) {$('message').textContent=message; $('message').hidden=false;}
  async function api(path, options={}) {
    const response=await fetch('/planeamento/api/'+path,{cache:'no-store',...options});
    let data; try {data=await response.json();} catch (_) {throw new Error('Não foi possível ler a resposta. Tenta novamente.');}
    if(!response.ok) throw new Error(data.error || 'Não foi possível concluir o pedido.');
    return data;
  }
  function replaceOptions(target, values, empty=false) {
    target.replaceChildren(); if(empty) target.append(new Option('Por definir',''));
    values.forEach(value=>target.append(new Option(value,value)));
  }
  function setInfo(info) {
    state.info=info;
    renderConnection();
  }
  function renderConnection(){
    if(!state.info)return;
    const cpis=state.sourceStatus?.cpis,label=cpis?.label||'CPIS por verificar';
    $('connection').replaceChildren(node('strong',label),document.createTextNode(' · '+state.info.source_filename+' · macro importada em '+displayDate(state.info.loaded_at)));
    $('ready-record').disabled=!state.sourceStatus?.completion_allowed;
    $('ready-record').title=state.sourceStatus?.completion_allowed?'':'Requer confirmação CPIS direta com menos de 15 minutos';
  }
  function showEditor() {
    $('editor').hidden=false; $('history').hidden=true;
    $('new-record').setAttribute('aria-current','page'); $('show-records').removeAttribute('aria-current');
  }
  function mayLeave() {return !state.saving && (!state.dirty || window.confirm('Existem alterações por guardar. Queres sair desta ficha?'));}
  function resetEditor() {
    state.source=null; state.record=null; state.order=null; state.lines=[]; state.dirty=false; state.requestId=uuid();
    form.reset(); form.hidden=true; $('selected-order').hidden=true; $('search-form').hidden=false;
    $('orders').hidden=false; $('change-order').hidden=true; $('refresh-source').hidden=true;
    $('versions').hidden=true; $('orders').replaceChildren(); $('query').value='';
  }
  async function context(area,generation=state.generation) {
    const data=await api('contexto?area='+encodeURIComponent(area));
    if(generation!==state.generation)return;
    setInfo(data.snapshot);
    state.catalogs=data;
    replaceOptions(field('machine'),data.machines,true);
    replaceOptions(field('material_type'),data.material_types,true);
    replaceOptions(field('team'),data.teams,true);
    replaceOptions(field('operation_detail'),data.operations||[],true);
    replaceOptions($('profile-options'),Object.values(data.profiles||{}).flat());
  }
  async function loadArea(area) {
    const generation=++state.generation; state.area=area; $('area').value=area;
    clearMessages(); resetEditor(); showEditor(); $('connection').textContent='A ligar ao planeamento…';
    $('area').disabled=true;
    try {
      await context(area);
      state.sourceStatus=await api('fontes');renderConnection();
      if(generation!==state.generation)return;
      await search();
    } catch(e){error(e.message); $('connection').textContent='Ligação indisponível';}
    finally {if(generation===state.generation)$('area').disabled=false;}
  }
  async function search() {
    const request=++state.searchRequest, generation=state.generation;
    $('orders').replaceChildren(node('p','A pesquisar OF abertas…','empty'));
    try {
      const data=await api('ofs?area='+encodeURIComponent(state.area)+'&q='+encodeURIComponent($('query').value.trim()));
      if(request!==state.searchRequest || generation!==state.generation)return;
      $('orders').replaceChildren();
      if(!data.orders.length) {$('orders').append(node('p','Nenhuma OF aberta encontrada. Pesquisa outro número, cliente ou designação.','empty'));return;}
      state.cpisVersion=data.cpis_version;
      data.orders.forEach(order=>{
        const button=node('button',undefined,'order-choice');button.type='button';
        button.append(node('strong',order.of),node('span',order.customer || 'Cliente por identificar'),node('small',order.designation || 'Sem designação'));
        button.addEventListener('click',()=>chooseOrder(order.of)); $('orders').append(button);
      });
    } catch(e){if(request===state.searchRequest && generation===state.generation){$('orders').replaceChildren();error(e.message);}}
  }
  function sourceSummary(source) {
    $('order-numbers').textContent=source.of+' / '+(source.ov || '—');
    $('order-customer').textContent=source.customer || '—'; $('order-designation').textContent=source.designation || '—';
    $('order-status').textContent=source.cpis_status||'Por confirmar';
    $('order-finish').textContent=displayDate(source.cpis_planned_finish_date);
    $('order-delivery').textContent=displayDate(source.cpis_delivery_date);
    $('source-line').textContent=source.plan_key?(state.info.source_filename+' · linha '+source.excel_row):'Referência nova · introdução manual';
    $('source-remaining').textContent=source.remaining_valid?fmt(source.source_remaining)+' un.':'Por confirmar';
    $('source-cpis').textContent=displayDate(source.cpis_planned_finish_date);
    const notices=[];
    if(source.closed_x)notices.push('Esta linha está marcada como fechada no ficheiro de origem.');
    if(source.source_quantity_aux!==null && source.source_quantity_aux!==undefined && source.source_quantity_aux!==source.values.quantity_required)notices.push('As duas quantidades do ficheiro diferem. Confirma a quantidade necessária.');
    if(source.plan_key && !source.remaining_valid)notices.push('O saldo importado não é válido.');
    $('source-notice').textContent=notices.join(' '); $('source-notice').hidden=!notices.length;
  }
  function setValues(values) {
    Object.entries(values).forEach(([name,value])=>{
      const input=field(name); if(!input)return;
      if(input.type==='checkbox')input.checked=!!value;
      else {
        if(input.tagName==='SELECT' && value && !Array.from(input.options).some(o=>o.value===value)) {
          input.add(new Option(value+' (valor guardado)',value));
        }
        input.value=value===null || value===undefined?'':String(value);
      }
    });
    updateGeometry();updateProfiles();
    updateCompletion();
  }
  function chooseLine(key) {
    const source=state.lines.find(line=>line.plan_key===key); if(!source)return;
    state.source=source; state.record=null; state.requestId=uuid(); state.dirty=false;
    form.hidden=false; setValues(source.values);sourceSummary(source);
    $('record-label').textContent='Nova preparação';$('save-record').textContent='Guardar rascunho';
    $('refresh-source').hidden=true;$('versions').hidden=true;
  }
  function lineLabel(source) {
    const v=source.values;
    return [v.component_ref,v.profile,fmt(v.length_mm)+' mm','saldo '+fmt(source.source_remaining),'linha '+source.excel_row].join(' · ');
  }
  function manualSource() {
    const order=state.order||{}, values={component_ref:'',identity_discriminator:'',material_type:'',material_description:'',profile:'',grade:'',custom_profile:false,
      outer_diameter_mm:null,width_mm:null,height_mm:null,thickness_mm:null,length_mm:null,angle_deg:null,
      operation:'corte',operation_detail:'',machine:'',abocardar:'',chanfro:'',ponteira:'',other_operations:'',team:'',pavilion:'',
      cut_date:'',expected_date:'',picking_week:null,picking_year:null,finish_week:null,finish_year:null,weekly_capacity_hours:null,
      material_request_date:'',material_available_date:'',material_lot:'',notes:'',quantity_required:null,quantity_to_plan:null,quantity_completed:null};
    return {plan_key:null,source_id:uuid(),of:order.of,ov:(order.ovs||[]).join(', '),customer:order.customer_name,
      designation:order.observations,cpis_status:order.cpis_status,cpis_planned_finish_date:order.planned_finish_date,
      cpis_delivery_date:order.delivery_date,source_remaining:null,remaining_valid:false,source_cut_completed:null,
      source_aboc_completed:null,values};
  }
  function chooseManualLine(){
    state.source=manualSource();state.record=null;state.requestId=uuid();state.dirty=false;
    $('reference').value='';form.reset();setValues(state.source.values);sourceSummary(state.source);form.hidden=false;
    $('record-label').textContent='Nova referência';$('refresh-source').hidden=true;$('versions').hidden=true;field('component_ref').focus();
  }
  async function chooseOrder(of) {
    const generation=++state.generation; clearMessages();
    $('orders').setAttribute('aria-busy','true');
    try {
      const data=await api('linhas?area='+encodeURIComponent(state.area)+'&of='+encodeURIComponent(of));
      if(generation!==state.generation)return;
      state.lines=data.lines;state.order=data.order;state.cpisVersion=data.cpis_version;setInfo(data.snapshot);
      $('reference').replaceChildren(new Option('Seleciona a referência / linha',''));
      state.lines.forEach(source=>$('reference').add(new Option(lineLabel(source),source.plan_key)));
      $('reference').disabled=false;
      const orderSource={of:data.order.of,ov:(data.order.ovs||[]).join(', '),customer:data.order.customer_name,
        designation:data.order.observations,cpis_status:data.order.cpis_status,
        cpis_planned_finish_date:data.order.planned_finish_date,cpis_delivery_date:data.order.delivery_date,
        source_remaining:null,remaining_valid:false,values:{quantity_required:null}};
      sourceSummary(orderSource); $('selected-order').hidden=false;$('search-form').hidden=true;
      $('orders').hidden=true;$('change-order').hidden=false; form.hidden=true;
      if(data.lines.length===1){$('reference').value=data.lines[0].plan_key;chooseLine(data.lines[0].plan_key);}
      else if(!data.lines.length)chooseManualLine();else $('reference').focus();
    } catch(e){if(generation===state.generation)error(e.message);}
    finally{$('orders').removeAttribute('aria-busy');}
  }
  function updateCompletion() {
    const required=number(field('quantity_required').value),done=number(field('quantity_completed').value);
    const percentage=required>0 && done!==null && Number.isFinite(done)?100*done/required:null;
    $('completion').textContent=percentage===null?'—':fmt(percentage)+'%';
    $('completion-progress').value=percentage===null?0:Math.max(0,Math.min(100,percentage));
  }
  function updateProfiles(){
    const catalogs=state.catalogs?.profiles||{},selected=field('material_type').value.casefold?.()||field('material_type').value.toLocaleLowerCase('pt-PT');
    const match=Object.entries(catalogs).find(([name])=>name.toLocaleLowerCase('pt-PT')===selected);
    const values=match?match[1]:Object.values(catalogs).flat();replaceOptions($('profile-options'),[...new Set(values)]);
  }
  function updateGeometry(){
    const kind=field('material_type').value.toLocaleLowerCase('pt-PT'),special=field('custom_profile').checked;
    const visible=new Set(['length','angle']);
    if(special||kind.includes('redond'))visible.add('diameter');
    if(special||kind.includes('quadrad')||kind.includes('retang')||kind.includes('barra')||kind.includes('chapa')||kind.includes('cantoneira'))visible.add('width');
    if(special||kind.includes('retang')||kind.includes('barra')||kind.includes('chapa')||kind.includes('cantoneira'))visible.add('height');
    if(special||kind.includes('tubo')||kind.includes('chapa')||kind.includes('cantoneira')||kind.includes('calha'))visible.add('thickness');
    document.querySelectorAll('[data-dimension]').forEach(label=>{label.hidden=!visible.has(label.dataset.dimension)});
    $('geometry').open=special||[...visible].some(name=>!['length','angle'].includes(name));
  }
  function collectValues() {
    const values={};
    Array.from(form.elements).forEach(input=>{
      if(!input.name)return;
      values[input.name]=input.type==='checkbox'?input.checked:input.type==='number'?number(input.value):input.value.trim();
    });
    return values;
  }
  async function save(event) {
    event.preventDefault();if(state.saving || !state.source)return;
    const recordStatus=event.submitter?.dataset.status||'draft';
    clearMessages();state.saving=true;form.inert=true;$('save-record').disabled=true;$('ready-record').disabled=true;
    const values=collectValues();
    const payload={area:state.area,request_id:state.requestId,actor:$('actor').value.trim(),
      snapshot_id:state.info.snapshot_id,plan_key:state.source.plan_key,source_id:state.source.source_id,
      source_kind:state.source.plan_key?'plan_line':'cpis_manual',production_order_no:state.source.of,
      cpis_version:state.cpisVersion,record_status:recordStatus,values};
    if(state.record){payload.record_id=state.record.id;payload.revision=state.record.revision;}
    try {
      const saved=await api('registos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      state.record={id:saved.id,revision:saved.revision};state.dirty=false;state.requestId=uuid();
      $('record-label').textContent=(saved.record_status==='ready'?'Preparada':'Rascunho')+' · revisão '+saved.revision;
      $('change-order').hidden=true;$('reference').disabled=true;$('refresh-source').hidden=false;
      success((saved.record_status==='ready'?'Preparação concluída':'Rascunho guardado')+' · revisão '+saved.revision+'.');
      history.replaceState(null,'','/planeamento/manual?registo='+encodeURIComponent(saved.id));
    } catch(e){error(e.message);}
    finally{state.saving=false;form.inert=false;$('save-record').disabled=false;$('ready-record').disabled=!state.sourceStatus?.completion_allowed;$('save-record').textContent='Guardar rascunho';}
  }
  async function showRecords() {
    if(!mayLeave())return;
    ++state.generation; state.dirty=false;clearMessages();
    $('editor').hidden=true;$('history').hidden=false;
    $('new-record').removeAttribute('aria-current');$('show-records').setAttribute('aria-current','page');
    $('records').replaceChildren(node('p','A carregar registos…','empty'));
    try {
      const records=await api('registos?area='+encodeURIComponent(state.area));
      $('records').replaceChildren();
      if(!records.length){$('records').append(node('p','Ainda não existem registos nesta área. Escolhe Nova ficha para guardar o primeiro.','empty'));return;}
      records.forEach(record=>{
        const row=node('div',undefined,'record-row'), identity=node('div'), detail=node('div'), meta=node('div',undefined,'record-meta');
        identity.append(node('strong',record.production_order_no),node('p',record.component_ref));
        detail.append(node('p',record.values_json.profile || record.values_json.material_type),node('p','Corte previsto: '+displayDate(record.values_json.cut_date)));
        meta.append(node('p',(record.record_status==='ready'?'Preparada':'Rascunho')+' · '+record.actor),node('p',displayDate(record.updated_at)+' · revisão '+record.revision));
        const open=node('button','Abrir');open.type='button';open.addEventListener('click',()=>openRecord(record.id));
        row.append(identity,detail,meta,open);$('records').append(row);
      });
    } catch(e){$('records').replaceChildren();error(e.message);}
  }
  async function openRecord(id) {
    if(!mayLeave())return;
    clearMessages(); const generation=++state.generation;
    try {
      const data=await api('registos/'+encodeURIComponent(id));if(generation!==state.generation)return;
      const record=data.record;state.area=record.area;$('area').value=record.area;
      await context(record.area);if(generation!==state.generation)return;
      state.record=record;state.source=record.source_payload;state.source.source_id=record.source_id;state.cpisVersion=record.source_version;state.requestId=uuid();state.dirty=false;
      const current=state.info;
      state.info={...current,snapshot_id:record.source_snapshot_id,source_filename:record.source_filename};
      $('reference').replaceChildren(new Option(state.source.plan_key?lineLabel(state.source):'Referência nova',state.source.plan_key||''));$('reference').disabled=true;
      $('search-form').hidden=true;$('orders').hidden=true;$('selected-order').hidden=false;$('change-order').hidden=true;
      sourceSummary(state.source);setValues(record.values_json);$('actor').value=record.actor;
      $('record-label').textContent=(record.record_status==='ready'?'Preparada':'Rascunho')+' · revisão '+record.revision;
      $('refresh-source').hidden=false;
      $('versions').replaceChildren(node('strong','Histórico de revisões'));
      data.versions.forEach(v=>$('versions').append(node('p','Rev. '+v.revision+' · '+v.actor+' · '+displayDate(v.created_at))));
      $('versions').hidden=false;form.hidden=false;showEditor();
      history.replaceState(null,'','/planeamento/manual?registo='+encodeURIComponent(id));
      if(record.source_snapshot_id&&record.source_snapshot_id!==current.snapshot_id)success('Existe uma importação mais recente. Atualiza a ligação ao ficheiro antes de guardar alterações.');
    } catch(e){error(e.message);}
  }
  $('refresh-source').addEventListener('click',async()=>{
    if(!state.record)return;clearMessages();$('refresh-source').disabled=true;
    try {
      const current=await api('registos/'+encodeURIComponent(state.record.id)+'/origem');
      state.source=current.source;setInfo(current.snapshot);sourceSummary(current.source);
      if(current.cpis_version)state.cpisVersion=current.cpis_version;
      state.requestId=uuid();state.dirty=true;
      success('Ligação atualizada. Os valores que introduziste na ficha foram conservados.');
    } catch(e){error(e.message);}finally{$('refresh-source').disabled=false;}
  });
  $('area').addEventListener('change',()=>{if(mayLeave()){history.replaceState(null,'','/planeamento');loadArea($('area').value);}else $('area').value=state.area;});
  $('search-form').addEventListener('submit',e=>{e.preventDefault();clearMessages();search();});
  $('reference').addEventListener('change',()=>{if(mayLeave())chooseLine($('reference').value);else $('reference').value=state.source?.plan_key || '';});
  $('new-reference').addEventListener('click',()=>{if(mayLeave())chooseManualLine();});
  $('change-order').addEventListener('click',()=>{if(mayLeave()){resetEditor();search();}});
  $('new-record').addEventListener('click',()=>{if(mayLeave()){history.replaceState(null,'','/planeamento');loadArea(state.area);}});
  $('show-records').addEventListener('click',showRecords);$('reload-records').addEventListener('click',showRecords);
  form.addEventListener('submit',save);
  form.addEventListener('input',()=>{state.dirty=true;updateCompletion();});
  field('custom_profile').addEventListener('change',updateGeometry);
  field('material_type').addEventListener('change',()=>{updateGeometry();updateProfiles()});
  field('operation').addEventListener('change',()=>{
    if(!state.source)return;
    const value=field('operation').value==='abocardar'?state.source.source_aboc_completed:state.source.source_cut_completed;
    field('quantity_completed').value=value===null?'':String(value);
    if(field('operation').value==='abocardar' && Array.from(field('machine').options).some(o=>o.value==='Abocardar'))field('machine').value='Abocardar';
    else if(field('operation').value==='corte')field('machine').value=state.source.values.machine || '';
    state.dirty=true;updateCompletion();
  });
  window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
  const params=new URLSearchParams(location.search),initial=params.get('registo'),initialArea=params.get('area')||'perfis',initialOf=params.get('of');
  if(initial)openRecord(initial);else loadArea(initialArea).then(()=>{if(initialOf)chooseOrder(initialOf);});
})();
