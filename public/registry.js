"use strict";
const $=id=>document.getElementById(id);
const types={cargo:"Carga",tanker:"Navio-tanque",fishing:"Pesca",tug:"Rebocador / reboque",passenger:"Passageiros",sailing:"Veleiro",pleasure:"Recreio",other:"Outros",unknown:"Não informado"};
const statuses={pending:"Pendente",running:"Consultando",matched:"Encontrado",not_found:"Não encontrado",ambiguous:"Correspondência ambígua",error:"Falha / nova tentativa"};
const escape=value=>String(value??"—").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=value=>value?new Date(value).toLocaleString('pt-BR'):"—";
const sourceLink=url=>{try{const parsed=new URL(url);return ['https:','http:'].includes(parsed.protocol)?`<a href="${escape(parsed.href)}" target="_blank" rel="noopener noreferrer">Ver fonte</a>`:"";}catch{return "";}};
let offset=0,total=0,rows=[],selected=null,sequence=0;
function field(v,key){const manual=v.manual?.[key];return `${escape(manual||v.enrichment?.[key]||"Não informado")}${manual?'<small>Preenchimento manual</small>':''}`;}
async function load(){
  const ticket=++sequence;
  try{
    const params=new URLSearchParams({q:$("query").value,type:$("type").value,status:$("status").value,limit:100,offset});
    const response=await fetch('/api/registry?'+params,{signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('Não foi possível carregar o cadastro. Reinicie o aplicativo para ativar esta versão.');
    const data=await response.json();if(ticket!==sequence)return;
    rows=data.vessels;total=data.total;
    if(offset>=total&&offset>0){offset=Math.max(0,Math.floor((total-1)/100)*100);return load();}
    $('rows').innerHTML=rows.map(v=>`<tr><td><strong>${escape(v.name)}</strong><small>MMSI ${escape(v.mmsi)}</small><small>IMO ${escape(v.imo)}</small><small>Indicativo ${escape(v.callsign)}</small></td><td>${escape(types[v.type]||'Não informado')}</td><td>${field(v,'model')}</td><td>${field(v,'manufacturer')}</td><td>${field(v,'vessel_class')}</td><td>Comprimento: ${escape(v.length)} m<br>Largura: ${escape(v.width)} m<br>Destino: ${escape(v.destination)}<small>Última coleta AIS: ${escape(date(v.last_seen))}</small></td><td>${escape(v.enrichment?.country||'País não informado')}<small>${escape(v.enrichment?.source||'Sem dados públicos associados')}</small>${sourceLink(v.enrichment?.source_url)}${v.manual?.source_url?'<small>Fonte manual: '+sourceLink(v.manual.source_url)+'</small>':''}<small>${escape(v.manual?.notes||'')}</small></td><td><span class="badge">${escape(statuses[v.crawl_status]||v.crawl_status)}</span><small>${escape(date(v.checked_at))}</small><small>${escape(v.error||'')}</small>${v.enrichment?.matched_by?'<small>Identificado por '+escape(v.enrichment.matched_by.toUpperCase())+'</small>':''}</td><td><button data-edit="${escape(v.mmsi)}">Editar</button></td></tr>`).join('')||'<tr><td colspan="9">Nenhuma embarcação cadastrada nesta consulta. O cadastro é preenchido pela coleta AIS real.</td></tr>';
    $('summary').textContent=`${total.toLocaleString('pt-BR')} embarcações nesta consulta. Cadastro persistente no computador.`;
    $('page').textContent=`Página ${Math.floor(offset/100)+1} de ${Math.max(1,Math.ceil(total/100))}`;
    $('previous').disabled=offset===0;$('next').disabled=offset+100>=total;
  }catch(error){if(ticket===sequence)$('summary').textContent=error.message;}
}
$('filters').addEventListener('submit',event=>{event.preventDefault();offset=0;load();});
for(const id of ['type','status'])$(id).addEventListener('change',()=>{offset=0;load();});
$('refresh').addEventListener('click',load);
$('previous').addEventListener('click',()=>{offset=Math.max(0,offset-100);load();});
$('next').addEventListener('click',()=>{offset+=100;load();});
$('rows').addEventListener('click',event=>{
  const button=event.target.closest('[data-edit]');if(!button)return;
  selected=button.dataset.edit;const vessel=rows.find(v=>v.mmsi===selected);
  $('edit-title').textContent=`Editar ${vessel.name||selected}`;
  for(const key of ['model','manufacturer','vessel_class','notes','source_url'])$(key).value=vessel.manual?.[key]||'';
  $('edit-status').textContent='';$('editor').showModal();
});
$('cancel').addEventListener('click',()=>$('editor').close());
$('edit-form').addEventListener('submit',async event=>{
  event.preventDefault();$('save').disabled=true;
  try{
    const fields=Object.fromEntries(['model','manufacturer','vessel_class','notes','source_url'].map(key=>[key,$(key).value]));
    const response=await fetch('/api/registry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mmsi:selected,fields}),signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('Não foi possível salvar. Revise os campos e tente novamente.');
    $('editor').close();await load();
  }catch(error){$('edit-status').textContent=error.message;}finally{$('save').disabled=false;}
});
load();setInterval(load,50000);
