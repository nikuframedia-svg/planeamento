(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const base = "/planeamento/api/raw/gantt";
  const data = {scenarios: [], scenario: null, definition: null, operations: [], resources: {},
                liveOperations: [], liveResources: {}, sourcePlan: null, proposal: null, snapshot: null, accepted: null, acceptedSnapshot: null,
                acceptEligible: false, jobId: null, selected: null, stale: false, proposalStale: false};
  const sourceView = () => $("compare").value === "source";
  const viewOperations = () => sourceView() ? data.liveOperations : $("compare").value === "accepted" ? (data.acceptedSnapshot?.operations || []) : data.operations;
  const viewResources = () => sourceView() ? data.liveResources : $("compare").value === "accepted" ? (data.acceptedSnapshot?.resources || {}) : data.resources;
  const uuid = () => crypto.randomUUID();
  const format = (instant, options={}) => instant ? new Intl.DateTimeFormat("pt-PT",{timeZone:"Europe/Lisbon",dateStyle:"short",timeStyle:"short",...options}).format(new Date(instant)) : "—";
  const coverage = value => value==="complete"?"completa":value==="partial"?"parcial":value||"parcial";
  const text = (tag, value, cls="") => {const node=document.createElement(tag);node.textContent=value ?? "";if(cls)node.className=cls;return node};
  const notice = (message, error=false) => {$("notice").textContent=message;$("notice").classList.toggle("error",error)};
  async function api(path, body) {
    const response=await fetch(`${base}/${path}`,{method:body===undefined?"GET":"POST",headers:body===undefined?{}:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),cache:"no-store"});
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(result.error||result.detail||`HTTP ${response.status}`);
    return result;
  }
  const safe = fn => async (...args) => {try{await fn(...args)}catch(error){notice(error.message||"Não foi possível concluir a ação.",true)}};
  function setAcceptance(value) {data.acceptEligible=Boolean(value);$("accept").disabled=!data.acceptEligible||sourceView()}
  function renderFreshness() {
    $("source-state").textContent=data.proposalStale?"Proposta desatualizada · recalcular":"Fontes publicadas atuais";
    $("source-state").classList.toggle("stale",data.proposalStale);
    const accepted=$("accepted-state");
    accepted.hidden=!data.scenario?.definition?.accepted;
    accepted.textContent=data.stale?"Plano aceite desatualizado · recalcular":"Plano aceite atual";
    accepted.classList.toggle("stale",data.stale);
  }
  function currentDefinition() {
    return {horizon_weeks:Number($("horizon").value),urgent:data.definition?.urgent||[],
      pins:data.definition?.pins||{},picking_year_by_of:data.definition?.picking_year_by_of||{},
      picking_deadline_by_of:data.definition?.picking_deadline_by_of||{},alternatives:data.definition?.alternatives||{}};
  }
  async function loadScenarios(keep) {
    const response=await api("scenarios");data.scenarios=response.scenarios||[];
    const choice=$("scenario");choice.replaceChildren(new Option("Novo cenário",""));
    for(const scenario of data.scenarios)choice.add(new Option(`${scenario.name} · r${scenario.revision}${scenario.stale?" · desatualizado":""}`,scenario.id));
    if(keep&&data.scenarios.some(s=>s.id===keep))choice.value=keep;
    data.scenario=data.scenarios.find(s=>s.id===choice.value)||null;
    data.stale=Boolean(data.scenario?.stale);
    renderFreshness();
  }
  async function loadOperations() {
    const info=await api("operations"+(data.scenario?`?scenario_id=${encodeURIComponent(data.scenario.id)}`:""));
    data.operations=info.operations||[];data.resources=info.resources||{};
    data.liveOperations=data.operations;data.liveResources=data.resources;data.sourcePlan=info.source_plan;
    populateWeeks();
    const machines=$("source-machine-filter"),keepMachine=machines.value;
    machines.replaceChildren(new Option("Todas as máquinas",""),...Object.entries(data.liveResources).sort((a,b)=>a[1].name.localeCompare(b[1].name)).map(([rid,r])=>new Option(r.name,rid)));
    machines.value=data.liveResources[keepMachine]?keepMachine:"";
    renderSummary();renderOperations();
    if(info.orphaned_pins?.length)notice(`${info.orphaned_pins.length} fixações pedem revisão antes da aceitação.`,true);
  }
  async function loadAccepted() {
    data.accepted=null;data.acceptedSnapshot=null;
    const id=data.scenario?.definition?.accepted?.job_id;
    if(!id)return;
    const previous=await api(`jobs/${id}`);
    data.accepted=previous.result?.proposal||null;
    data.acceptedSnapshot=previous.input?.snapshot||null;
  }
  async function choose() {
    data.scenario=data.scenarios.find(s=>s.id===$("scenario").value)||null;
    data.definition=data.scenario?.definition?structuredClone(data.scenario.definition):null;
    $("scenario-name").value=data.scenario?.name||"Plano de Perfis";
    $("horizon").value=String(data.definition?.horizon_weeks||12);
    $("selected-detail").replaceChildren();
    data.proposal=null;data.snapshot=null;data.selected=null;data.proposalStale=false;
    await Promise.all([loadOperations(),loadAccepted()]);
    if(data.scenario?.latest_job_id){
      $("compare").value="proposal";
      data.jobId=data.scenario.latest_job_id;
      const latest=await api(`jobs/${data.jobId}`);
      data.proposalStale=Boolean(latest.stale);if(latest.stale)$("compare").value="source";renderFreshness();
      if(latest.input?.snapshot){
        data.snapshot=latest.input.snapshot;data.operations=data.snapshot.operations;data.resources=data.snapshot.resources;
      }
      data.proposal=latest.result?.proposal||latest.result?.initial||null;
      setAcceptance(latest.status==="done"&&!latest.stale&&latest.result?.phase==="done"&&latest.result?.validation?.valid);
      if(latest.status==="queued"||latest.status==="running")pollJob(data.jobId).catch(error=>notice(error.message,true));
    }else{setAcceptance(false);data.jobId=null;$("compare").value=data.accepted?"accepted":"source"}
    renderTimeline();renderSummary();
    renderOperations();
    if(data.proposalStale)notice("A proposta usa fontes anteriores. Gera uma nova proposta.",true);
    else if(data.stale)notice("O plano aceite usa fontes anteriores. Gera uma nova proposta.",true);
  }
  async function saveScenario() {
    const payload={request_id:uuid(),id:data.scenario?.id,expected_revision:data.scenario?.revision||0,
      name:$("scenario-name").value.trim(),area:"perfis",definition:currentDefinition()};
    const saved=await api("scenarios",payload);
    await loadScenarios(saved.id);
    data.definition=structuredClone(data.scenario.definition);
    if(data.proposal){data.proposalStale=true;setAcceptance(false);renderFreshness()}
    notice(`Cenário guardado · revisão ${saved.revision}.`);
    return saved;
  }
  async function generate() {
    $("compare").value="proposal";
    const saved=await saveScenario();
    const result=await api("solve",{request_id:uuid(),id:saved.id,expected_revision:saved.revision});
    data.jobId=result.job_id;data.proposal=null;data.snapshot=null;data.proposalStale=false;renderFreshness();
    notice("Proposta na fila. A sequência inicial aparecerá primeiro.");
    await pollJob(result.job_id);
  }
  async function pollJob(id) {
    for(;;){
      const run=await api(`jobs/${id}`);
      data.proposalStale=Boolean(run.stale);renderFreshness();
      if(run.result?.snapshot){data.snapshot=run.result.snapshot;data.operations=data.snapshot.operations;data.resources=data.snapshot.resources}
      if(run.result?.proposal||run.result?.initial){data.proposal=run.result.proposal||run.result.initial;renderSummary();renderOperations();renderTimeline()}
      if(run.status==="done"){
        notice(run.stale?"A proposta ficou desatualizada durante o cálculo. Gera uma nova proposta.":run.result?.phase==="diagnostic" ? (run.result.diagnostic?.message||"Proposta com fixações para rever.") :
          `Proposta ${run.result?.proposal?.origin||"inicial"} concluída · ${coverage(run.result?.proposal?.coverage)}.`,run.stale||run.result?.phase==="diagnostic");
        setAcceptance(run.result?.phase==="done"&&!run.stale&&run.result?.validation?.valid);
        return;
      }
      if(run.status==="failed"){notice(run.error||"O cálculo falhou.",true);return}
      await new Promise(resolve=>setTimeout(resolve,1100));
    }
  }
  async function accept() {
    if(sourceView()||!data.acceptEligible||!data.scenario||!data.jobId)throw Error("Gera uma proposta válida antes de aceitar.");
    const response=await api("accept",{request_id:uuid(),job_id:data.jobId,expected_revision:data.scenario.revision});
    await loadScenarios(response.id);await loadAccepted();
    data.proposalStale=false;renderFreshness();
    setAcceptance(false);
    notice(`Plano aceite e guardado na revisão ${response.revision}.`);
  }
  function renderSummary() {
    const ops=viewOperations();const shown=sourceView()?null:$("compare").value==="accepted"?data.accepted:data.proposal;
    const states=shown?.states||{};
    const values=sourceView() ? [
      [ops.length,"Operações no plano ativo"],
      [data.sourcePlan?.completed||0,"Concluídas · sem carga futura"],
      [data.sourcePlan?.entries.length||0,"Com máquina e previsão"],
      [data.sourcePlan?.pending.length||0,"Sem máquina / previsão utilizável"]] : [
      [ops.length,"Operações no plano ativo"],
      [ops.filter(x=>x.state==="complete").length,"Concluídas · sem carga futura"],
      [Object.values(states).filter(x=>x==="scheduled").length,"Calendarizadas"],
      [ops.filter(x=>x.state==="blocked").length+Object.values(states).filter(x=>x==="overflow").length,"Pendentes / fora do horizonte"]];
    $("summary").replaceChildren(...values.map(([n,label])=>{const card=text("div","","metric");card.append(text("strong",n),text("span",label));return card}));
  }
  function renderOperations() {
    const term=$("search").value.trim().toLocaleLowerCase("pt-PT");
    const shown=sourceView()?null:$("compare").value==="accepted"?data.accepted:data.proposal;
    const bars=shown?.bars||{};
    const rows=viewOperations().filter(x=>!term||[x.of,x.reference,x.operation,x.key,x.source_machine,...(x.blocking_reasons||[])].join(" ").toLocaleLowerCase("pt-PT").includes(term));
    rows.sort((a,b)=>(a.state==="blocked"?0:a.state==="ready"?1:2)-(b.state==="blocked"?0:b.state==="ready"?1:2)||a.priority_group-b.priority_group||(a.deadline||"").localeCompare(b.deadline||"")||a.key.localeCompare(b.key));
    const wrap=$("operations");wrap.replaceChildren();
    $("pending-count").textContent=`${rows.length} de ${viewOperations().length} operações · seleção visual não altera o cálculo`;
    if(!rows.length){wrap.append(text("p","Sem operações neste filtro.","operations-empty"));return}
    for(const op of rows){
      const state=shown?.states?.[op.key]||op.state;
      const provisional=Boolean(bars[op.key]?.provisional||op.provisional);
      let status=(state==="complete"?"Concluída":state==="scheduled"?"Calendarizada":state==="overflow"?(shown?.unplaced_reasons?.[op.key]||"Fora do horizonte"):op.blocking_reasons?.join("; ")||"A aguardar proposta")+
        (op.milestones?.picking_provisional?" · Picking: ano 2026 assumido":"");
      if(sourceView() && state!=="complete")status=`${op.source_machine||"Máquina por indicar"} · ${op.source_duration?.hours==null?"Duração por confirmar":Number(op.source_duration.hours).toFixed(2)+" h"} · previsão ${op.milestones?.operation_forecast|| (op.milestones?.period_week?`W${op.milestones.period_week}/${op.milestones.period_year}`:"por indicar")} · ${status}`;
      const row=text("button","","operation-row"+(data.selected===op.key?" selected":""));row.type="button";
      row.append(text("span",op.of,"of"),text("span",`${op.reference||"Sem referência"} · ${op.operation}`),
        text("span",`${op.planning_remaining??"?"} un.`),text("span",provisional?"Provisório":"Confirmado",provisional?"provisional":""),
        text("span",status,state==="complete"?"done":"reason"));
      row.title=`${op.key}\nMáquina no planeamento: ${op.source_machine||"—"}\nDuração calculada: ${op.source_duration?.hours??"—"} h · ${op.source_duration?.origin||"—"}\nOrigem do saldo: ${op.balance_origin||"desconhecida"}\n${(bars[op.key]?.provisional_reasons||[]).join("; ")}\nPrevisão: ${op.milestones?.operation_forecast||"—"}\nPicking: ${format(op.milestones?.picking)}\nFim Produção: ${op.milestones?.planned_finish_date||"—"}\nEntrega: ${op.milestones?.delivery_date||"—"}\nObservações Kanban: ${op.observations?.length||0}`;
      row.addEventListener("click",()=>selectOperation(op.key));wrap.append(row);
    }
  }
  function localLisbon(iso) {
    if(!iso)return "";
    const parts=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Lisbon",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(iso));
    return parts.replace(" ","T");
  }
  function toUTCFromLisbon(local) {
    if(!local)return null;
    const target=Date.parse(local+"Z");
    const zone=new Intl.DateTimeFormat("en-US",{timeZone:"Europe/Lisbon",timeZoneName:"shortOffset"});
    const offsetAt=ms=>{const value=zone.formatToParts(new Date(ms)).find(x=>x.type==="timeZoneName")?.value||"GMT";const m=value.match(/^GMT(?:([+-])(\d{1,2})(?::(\d{2}))?)?$/);return m?.[1]?(m[1]==="-"?-1:1)*(Number(m[2])*60+Number(m[3]||0)):0};
    const candidates=[target-offsetAt(target)*60000,target-offsetAt(target-3600000)*60000,target-offsetAt(target+3600000)*60000];
    const found=candidates.find(ms=>localLisbon(new Date(ms).toISOString())===local);
    if(found===undefined)throw Error("Esta hora local não existe em Lisboa devido à mudança de hora.");
    return new Date(found).toISOString();
  }
  function selectOperation(key) {
    const op=viewOperations().find(x=>x.key===key);if(!op)return;
    const detail=$("selected-detail");detail.replaceChildren();
    const known=sourceView()?data.sourcePlan?.entries.find(e=>e.key===key):null;
    const details=[['Máquina',op.source_machine||'Por indicar'],['Referência / linha',`${op.reference||'—'} / ${op.line||op.planning_key}`],
      ['Saldo',`${op.planning_remaining??'?'} un. · ${op.balance_origin||'origem desconhecida'}`],
      ['Carga',`${known?.hours!=null?Number(known.hours).toFixed(2)+' h':op.source_duration?.hours!=null?Number(op.source_duration.hours).toFixed(2)+' h':'Por confirmar'} · ${op.source_duration?.origin||'—'}`],
      ['Previsão',known?`${known.start_date} · ${known.precision==='week'?'semana':'dia'} · ${known.forecast_origin||'planeamento'}`:op.milestones?.operation_forecast||'Por indicar'],
      ['Picking',`${format(op.milestones?.picking)}${op.milestones?.picking_provisional?' · ano assumido':''}`],
      ['Fim Produção',op.milestones?.planned_finish_date||'—'],['Entrega',op.milestones?.delivery_date||'—']];
    for(const [label,value] of details){const line=text('p','');line.append(text('strong',label+' '),text('span',value));detail.append(line)}
    if(op.provisional||known?.provisional)detail.append(text('p','Estimativa provisória','provisional'));
    if(op.blocking_reasons?.length)detail.append(text('p','Para calendarizar ao minuto: '+op.blocking_reasons.join('; '),'hint'));
    data.selected=key;$("selected-key").value=key;$("selected-of").value=op.of;
    $("urgent").checked=(data.definition?.urgent||[]).includes(key);
    $("picking-year").value=data.definition?.picking_year_by_of?.[op.of]||"";
    $("picking-deadline").value=localLisbon(data.definition?.picking_deadline_by_of?.[op.of])||"";
    const select=$("pin-resource");select.replaceChildren(new Option("Sem fixação",""));
    for(const option of op.options||[])select.add(new Option(viewResources()[option.resource_id]?.name||option.resource_id,option.resource_id));
    const pin=data.definition?.pins?.[key];select.value=pin?.resource_id||"";
    $("pin-start").value=localLisbon(pin?.start)||"";
    renderOperations();
    $("edit-title").scrollIntoView({block:"nearest",behavior:"smooth"});
  }
  async function applyAdjustment() {
    const key=data.selected;if(!key)throw Error("Seleciona uma operação.");
    data.definition=data.definition||currentDefinition();
    const urgent=new Set(data.definition.urgent||[]);$("urgent").checked?urgent.add(key):urgent.delete(key);data.definition.urgent=[...urgent];
    const years={...(data.definition.picking_year_by_of||{})};
    if($("picking-year").value)years[$("selected-of").value]=Number($("picking-year").value);
    else delete years[$("selected-of").value];
    data.definition.picking_year_by_of=years;
    const deadlines={...(data.definition.picking_deadline_by_of||{})};
    if($("picking-deadline").value)deadlines[$("selected-of").value]=toUTCFromLisbon($("picking-deadline").value);
    else delete deadlines[$("selected-of").value];
    data.definition.picking_deadline_by_of=deadlines;
    const pins={...(data.definition.pins||{})};
    if($("pin-resource").value){if(!$("pin-start").value)throw Error("Indica o início fixo.");pins[key]={resource_id:$("pin-resource").value,start:toUTCFromLisbon($("pin-start").value)}}
    else delete pins[key];
    data.definition.pins=pins;
    await generate();
  }
  function weekStart(value) {
    const day=new Date(value.slice(0,10)+"T12:00:00Z");day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
    return day.toISOString().slice(0,10);
  }
  function isoMonday(year,week) {
    const day=new Date(`${year}-01-04T12:00:00Z`);day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7)+(week-1)*7);
    return day.toISOString().slice(0,10);
  }
  function populateWeeks() {
    const select=$("source-week"),previous=select.value;
    const weeks=new Set([weekStart(new Date().toISOString().slice(0,10))]);
    for(const entry of data.sourcePlan?.entries||[])weeks.add(weekStart(entry.start_date));
    for(const row of data.sourcePlan?.weekly_load||[])weeks.add(isoMonday(row.year,row.week));
    select.replaceChildren(...[...weeks].sort().reverse().map(day=>new Option(`A partir de ${day.split("-").reverse().join("/")}`,day)));
    select.value=weeks.has(previous)?previous:weekStart(new Date().toISOString().slice(0,10));
  }
  function renderSourcePlan() {
    const plan=data.sourcePlan,box=$("timeline");box.replaceChildren();$("weekly-capacity").replaceChildren();
    if(!plan)return;
    const first=$("source-week").value,start=Date.parse(first+"T00:00:00Z"),days=Number($("horizon").value)*7;
    const span=days*86400000,end=start+span,scale=$("scale").value,unit=scale==="day"?1:7,width=scale==="day"?72:96,total=days/unit*width;
    const entries=plan.entries.filter(e=>Date.parse(e.end_date_exclusive)>start&&Date.parse(e.start_date)<end);
    const before=plan.entries.filter(e=>Date.parse(e.end_date_exclusive)<=start).length,after=plan.entries.length-entries.length-before;
    $("schedule-hint").textContent="Previsões do planeamento: cada barra marca o dia ou a semana escolhida. As horas são carga estimada; a largura não indica duração de execução. Seleciona uma barra para consultar ou ajustar a operação.";
    const selectedResource=$("source-machine-filter").value;
    const visible=entries.filter(e=>!selectedResource||e.resource_id===selectedResource);
    $("source-range").textContent=`${visible.length} de ${entries.length} previsões nesta janela · ${before} anteriores · ${after} posteriores · muda a semana para as consultar`;
    const ops=new Map(data.liveOperations.map(op=>[op.key,op]));
    const capacity=$("weekly-capacity");
    capacity.append(text("p",`Carga e disponibilidade na semana de ${first.split("-").reverse().join("/")}`,"hint"));
    const cards=text("div","","capacity-cards");
    for(const [rid,resource] of Object.entries(data.liveResources).sort((a,b)=>a[1].name.localeCompare(b[1].name))){
      const load=plan.weekly_load.find(r=>r.resource_id===rid&&isoMonday(r.year,r.week)===first);
      const avail=load?.availability,known=avail?.hours!=null;
      const card=text("div","","capacity-card"+(avail?.status==="conflict"?" conflict":""));
      card.append(text("strong",resource.name),text("span",`${Number(load?.hours||0).toFixed(2)} h previstas · ${load?.operations||0} operações`));
      card.append(text("span",avail?.status==="conflict"?`Disponibilidade em conflito: ${avail.alternatives.join(" / ")} h`:known?`${avail.hours} h disponíveis · ${avail.status==="confirmed"?"confirmadas":"Excel"}`:"Disponibilidade semanal por indicar"));
      if(load?.unknown_durations)card.append(text("span",`+ ${load.unknown_durations} durações desconhecidas`));
      if(known&&load?.hours>avail.hours)card.append(text("b",`${(load.hours-avail.hours).toFixed(2)} h acima da disponibilidade`));
      if(load?.provisional_operations)card.append(text("small",`${load.provisional_operations} estimativas provisórias`));
      card.title=(avail?.evidence||[]).map(e=>e.sheet?`${e.file||"Excel"} · ${e.sheet} · linha ${e.row}: ${e.hours} h`:`Calendário ${e.object_id} · revisão ${e.revision}`).join("\n");
      const see=text("button","Ver previsões");see.type="button";see.addEventListener("click",()=>{$("source-machine-filter").value=rid;renderTimeline()});card.append(see);
      cards.append(card);
    }
    capacity.append(cards);
    const wrapper=text("div","","timeline-inner");wrapper.style.width=`${175+total}px`;
    const head=text("div","","time-head");head.append(text("div","Máquina / OF","resource-label"));
    function lane(){const node=text("div","","time-track");node.style.width=`${total}px`;node.style.setProperty("--unit-width",`${width}px`);return node}
    const track=lane();
    for(let i=0;i<days/unit;i++){
      const day=new Date(start+i*unit*86400000).toISOString().slice(0,10);
      const label=text("span",day.slice(8,10)+"/"+day.slice(5,7),"tick");label.style.left=`${i*width}px`;track.append(label);
    }
    head.append(track);wrapper.append(head);
    for(const [rid,resource] of Object.entries(data.liveResources).sort((a,b)=>a[1].name.localeCompare(b[1].name))){
      if(selectedResource&&selectedResource!==rid)continue;
      const rows=visible.filter(e=>e.resource_id===rid);
      const group=text("div","","source-machine");group.append(text("strong",resource.name),text("span",`${rows.length} previsões nesta janela`));wrapper.append(group);
      for(const entry of rows){
        const op=ops.get(entry.key);if(!op)continue;
        const row=text("div","","resource-row source-operation");
        const label=text("button",`${op.of} · L${op.line||op.planning_key}`,"resource-label");label.type="button";label.title=`${op.reference||""} · linha ${op.line||op.key}`;label.addEventListener("click",()=>selectOperation(op.key));row.append(label);
        const bar=text("button","","forecast-bar"+(entry.provisional?" provisional":""));
        bar.append(text("span",`${op.planning_remaining??"?"} un.`),text("small",entry.hours==null?"? h":Number(entry.hours).toFixed(2)+" h"));
        const low=Math.max(start,Date.parse(entry.start_date)),high=Math.min(end,Date.parse(entry.end_date_exclusive));
        bar.type="button";bar.style.left=`${(low-start)/86400000/unit*width}px`;bar.style.width=`${Math.max(4,(high-low)/86400000/unit*width-2)}px`;
        bar.title=`${resource.name}\n${op.of} · ${op.reference||""} · ${op.operation} · linha ${op.line||op.key}\nPrevisão: ${entry.start_date} (${entry.precision==="week"?"semana":"dia"}) · ${entry.forecast_origin||"planeamento"}\nSaldo: ${op.planning_remaining??"?"} un. · ${op.balance_origin}\nCarga: ${entry.hours==null?"desconhecida":Number(entry.hours).toFixed(2)+" h"} · ${entry.duration_origin||"origem por confirmar"}${entry.provisional?" · provisória":""}\nPicking: ${format(op.milestones.picking)}\nFim Produção: ${op.milestones.planned_finish_date||"—"}\nEntrega: ${op.milestones.delivery_date||"—"}\nCalendarização horária: ${entry.hourly_reasons.join("; ")||"disponível para cálculo"}`;
        bar.addEventListener("click",()=>selectOperation(op.key));const slot=lane();slot.append(bar);
        for(const [title,field,cls] of [["Picking","picking","picking"],["Fim Produção","planned_finish_date","fim"],["Entrega","delivery_date","entrega"]]){
          const at=op.milestones[field];if(!at)continue;
          const instant=Date.parse(at.slice(0,10));if(instant<start||instant>=end)continue;
          const marker=text("span","","milestone milestone-"+cls);marker.style.left=`${(instant-start)/86400000/unit*width}px`;marker.title=`${title}: ${at}`;slot.append(marker);
        }
        row.append(slot);wrapper.append(row);
      }
    }
    if(!visible.length)wrapper.append(text("p","Sem previsões nesta janela. Escolhe outra semana; as operações sem previsão continuam na lista abaixo.","operations-empty"));
    box.append(wrapper);
  }
  function renderTimeline() {
    setAcceptance(data.acceptEligible);
    $("source-controls").hidden=!sourceView();$("weekly-capacity").hidden=!sourceView();
    if(sourceView()){renderSourcePlan();return}
    const proposal=$("compare").value==="accepted"?data.accepted:data.proposal;
    const snapshot=$("compare").value==="accepted"?data.acceptedSnapshot:data.snapshot;
    const box=$("timeline");box.replaceChildren();
    if(!proposal||!snapshot){$("schedule-hint").textContent="Aguarda uma proposta. Máquinas sem horários confirmados aparecem nas pendências.";return}
    $("schedule-hint").textContent=`${proposal.origin||"Proposta"} · ${coverage(proposal.coverage)} · início ${format(snapshot.started_at)} · barras apenas nos minutos úteis`; 
    const start=Date.parse(snapshot.started_at),span=snapshot.horizon_minutes;
    const scale=$("scale").value,unit=scale==="day"?1440:10080,width=scale==="day"?64:78,total=span/unit*width;
    const wrapper=text("div","","timeline-inner");wrapper.style.width=`${175+total}px`;
    const head=text("div","","time-head");head.append(text("div","Máquina física","resource-label"));
    const track=text("div","","time-track");track.style.width=`${total}px`;track.style.setProperty("--unit-width",`${width}px`);
    for(let i=0;i<span/unit;i++){const at=new Date(start+i*unit*60000);const label=text("span",scale==="day"?new Intl.DateTimeFormat("pt-PT",{timeZone:"Europe/Lisbon",day:"2-digit",month:"short"}).format(at):`Semana ${i+1}`,"tick");label.style.left=`${i*width}px`;track.append(label)}
    head.append(track);wrapper.append(head);
    const ops=new Map(snapshot.operations.map(op=>[op.key,op]));
    const grouped=new Map();for(const [key,bar] of Object.entries(proposal.bars||{})){if(!grouped.has(bar.resource_id))grouped.set(bar.resource_id,[]);grouped.get(bar.resource_id).push([key,bar])}
    for(const [rid,resource] of Object.entries(snapshot.resources)){
      const line=text("div","","resource-row");line.append(text("div",resource.name,"resource-label"));
      const lane=text("div","","time-track");lane.style.width=`${total}px`;lane.style.setProperty("--unit-width",`${width}px`);
      for(const [key,bar] of grouped.get(rid)||[]){
        const op=ops.get(key);if(!op)continue;
        for(const [index,[from,to]] of (bar.segments||[]).entries()){
          const button=text("button",index===0?`${op.of} · ${op.operation}`:"","bar"+(bar.provisional?" provisional":"")+($("compare").value==="accepted"?" accepted":""));
          button.style.left=`${from/unit*width}px`;button.style.width=`${Math.max(3,(to-from)/unit*width)}px`;
          button.title=`${op.of} · ${op.reference||""} · ${op.operation}\n${op.planning_remaining} peças · ${bar.duration_minutes} min úteis\n${format(new Date(start+from*60000))}–${format(new Date(start+to*60000))}\n${op.balance_origin||""}\n${bar.provisional?`Estimativa provisória: ${(bar.provisional_reasons||[]).join("; ")}`:"Estimativa confirmada"}`;
          button.addEventListener("click",()=>selectOperation(key));lane.append(button);
        }
        for(const [kind,at] of Object.entries({Picking:op.milestones?.picking,Previsão:op.milestones?.operation_forecast,Fim:op.milestones?.planned_finish_date,Entrega:op.milestones?.delivery_date})){
          if(!at)continue;const value=Date.parse(at);if(!Number.isFinite(value))continue;const pos=(value-start)/60000;
          if(pos<0||pos>span)continue;
          const marker=text("span","","milestone milestone-"+kind.toLocaleLowerCase("pt-PT").normalize("NFD").replace(/[\u0300-\u036f]/g,""));marker.style.left=`${pos/unit*width}px`;marker.title=`${kind}: ${format(at)}`;lane.append(marker);
        }
      }
      line.append(lane);wrapper.append(line);
    }
    const milestoneKinds=[
      ["Picking","picking"],["Previsão","operation_forecast"],
      ["Período","period_deadline"],["Fim Produção","planned_finish_date"],["Entrega","delivery_date"]];
    for(const [kind,field] of milestoneKinds){
      const buckets=new Map();
      for(const op of snapshot.operations){
        const at=op.milestones?.[field];if(!at)continue;
        const instant=Date.parse(at);if(!Number.isFinite(instant))continue;
        const elapsed=(instant-start)/60000;
        const index=elapsed<0?-1:elapsed>=span?Math.ceil(span/unit):Math.floor(elapsed/unit);
        if(!buckets.has(index))buckets.set(index,[]);
        buckets.get(index).push({op,at});
      }
      if(!buckets.size)continue;
      const line=text("div","","resource-row milestone-row");
      line.append(text("div",`${kind} · ${[...buckets.values()].reduce((sum,items)=>sum+items.length,0)}`,"resource-label"));
      const lane=text("div","","time-track");lane.style.width=`${total}px`;lane.style.setProperty("--unit-width",`${width}px`);
      for(const [index,items] of [...buckets].sort((a,b)=>a[0]-b[0])){
        const outside=index<0?"Antes do horizonte":index>=Math.ceil(span/unit)?"Depois do horizonte":null;
        const marker=text("button",index<0?`← ${items.length}`:index>=Math.ceil(span/unit)?`${items.length} →`:String(items.length),"milestone-bucket milestone-"+kind.toLocaleLowerCase("pt-PT").normalize("NFD").replace(/[\u0300-\u036f]/g,""));
        marker.type="button";marker.style.left=`${outside?(index<0?3:Math.max(3,total-26)):Math.min(total-26,Math.max(3,index*width+4))}px`;
        marker.title=`${kind} · ${outside||"prazo/previsão"}\n${items.slice(0,8).map(({op,at})=>`${op.of} · ${op.operation}: ${at.length===10?at:format(at)}`).join("\n")}${items.length>8?`\n+${items.length-8} operações`:""}`;
        marker.setAttribute("aria-label",`${kind}: ${items.length} operações${outside?` · ${outside}`:""}`);
        marker.addEventListener("click",()=>selectOperation(items[0].op.key));lane.append(marker);
      }
      line.append(lane);wrapper.append(line);
    }
    box.append(wrapper);
  }
  $("source-machine-filter").addEventListener("change",renderTimeline);
  $("source-week").addEventListener("change",renderTimeline);
  $("source-today").addEventListener("click",()=>{$("source-week").value=weekStart(new Date().toISOString().slice(0,10));renderTimeline()});
  $("refresh").addEventListener("click",safe(async()=>{await loadScenarios(data.scenario?.id);await choose();if(!data.stale&&!data.proposalStale)notice("Fontes e pendências atualizadas.")}));
  $("scenario").addEventListener("change",safe(choose));
  $("save").addEventListener("click",safe(saveScenario));
  $("generate").addEventListener("click",safe(generate));
  $("accept").addEventListener("click",safe(accept));
  $("horizon").addEventListener("change",()=>{if(sourceView())renderTimeline()});
  $("scale").addEventListener("change",renderTimeline);$("compare").addEventListener("change",()=>{renderTimeline();renderSummary();renderOperations()});
  $("search").addEventListener("input",renderOperations);
  $("edit-form").addEventListener("submit",event=>{event.preventDefault();safe(applyAdjustment)()});
  $("clear-pin").addEventListener("click",()=>{$("pin-resource").value="";$("pin-start").value=""});
  setAcceptance(false);
  safe(async()=>{await loadScenarios();await choose()})();
})();
