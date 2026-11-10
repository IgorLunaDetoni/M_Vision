"use strict";
const $=id=>document.getElementById(id);
const types={cargo:"Carga",tanker:"Navio-tanque",fishing:"Pesca",tug:"Rebocador / reboque",passenger:"Passageiros",sailing:"Veleiro",pleasure:"Recreio",other:"Outros",unknown:"Não informado"};
const statuses={pending:"Pendente",running:"Consultando",matched:"Encontrado",not_found:"Não encontrado",ambiguous:"Correspondência ambígua",error:"Falha / nova tentativa",not_applicable:"Cadastro ANTAQ"};
const linkStatuses={matched:"Vinculado ao AIS",unmatched:"Aguardando AIS correspondente",needs_identifier:"Revisar identificadores",ambiguous:"Vínculo ambíguo",conflict:"Conflito de identificadores"};
const escape=value=>String(value??"—").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=value=>value?new Date(value).toLocaleString('pt-BR'):"—";
const sourceLink=url=>{try{const parsed=new URL(url);return ['https:','http:'].includes(parsed.protocol)?`<a href="${escape(parsed.href)}" target="_blank" rel="noopener noreferrer">Ver fonte</a>`:"";}catch{return "";}};
let offset=0,total=0,rows=[],selected=null,sequence=0;

const labels={name:"Nome",imo:"IMO",mmsi:"MMSI",callsign:"Indicativo",registration:"Inscrição",antaq_id:"Código ANTAQ",type:"Tipo AIS",length:"Comprimento",width:"Largura",destination:"Destino",model:"Modelo",manufacturer:"Estaleiro",vessel_class:"Classe/projeto",country:"País de registro",vessel_subtype:"Tipo declarado na fonte",operator:"Operador informado",inception:"Criação/construção (P571)",service_entry:"Entrada em serviço",gross_tonnage:"Arqueação bruta (GT)",deadweight:"Porte bruto (TPB)",year_built:"Ano de construção",navigation:"Navegação",authorization_status:"Situação na ANTAQ"};
function evidence(v){
  const entries=Object.entries(v.field_sources||{});
  if(!entries.length)return '';
  return `<details><summary>Histórico de fontes por campo</summary><p>Observações coletadas; podem incluir valores anteriores. Dados do Wikidata não confirmam vigência atual.</p>${entries.map(([key,items])=>`<p><strong>${escape(labels[key]||key)}</strong>${items.map(e=>`<small>${escape(e.value)} · ${escape(e.source)} · ${escape(date(e.collected_at))} ${sourceLink(e.source_url)} ${e.property?escape(e.property):''}</small>`).join('')}</p>`).join('')}</details>`;
}
function particulars(v){
  return ['vessel_subtype','operator','inception','service_entry','gross_tonnage','registration','year_built','deadweight','navigation','authorization_status'].filter(k=>v.resolved?.[k]||v.enrichment?.[k]).map(k=>`<small>${escape(labels[k])}: ${escape(v.resolved?.[k]||v.enrichment[k])}</small>`).join('')+
    (v.antaq?`<small>ANTAQ: ${escape(linkStatuses[v.antaq_match]||v.antaq_match)} · ${escape(date(v.antaq.imported_at))}</small>${sourceLink(v.antaq.source_url)}<small>${escape(v.antaq_match_reason||'')}</small>`:'')+
    (v.conflicts?.length?'<small>Valores manuais divergem da fonte pública: '+v.conflicts.map(k=>escape(labels[k]||k)).join(', ')+'</small>':'')+evidence(v);
}
async function diagnostics(){
  try{
    const response=await fetch('/api/registry/diagnostics',{signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('Não foi possível carregar o diagnóstico.');
    const d=await response.json();
    $('diagnostics').innerHTML=`<summary>Diagnóstico da coleta AIS: ${d.total} embarcações</summary><p>Consultadas: ${d.checked}. Com dados Wikidata: ${d.with_external_data}. Atualizado: ${escape(date(d.generated_at))}.</p><p>${Object.entries(d.statuses).map(([k,n])=>`${escape(statuses[k]||k)}: ${n}`).join(' · ')}</p><table><thead><tr><th>Campo</th><th>Preenchidos</th><th>Ausentes</th><th>Cobertura</th></tr></thead><tbody>${Object.entries(d.coverage).map(([k,c])=>`<tr><td>${escape(labels[k]||k)}</td><td>${c.filled}</td><td>${c.missing}</td><td>${c.percent}%</td></tr>`).join('')}</tbody></table>`;
    const a=d.antaq;
    if(a)$('antaq-summary').textContent=`ANTAQ: ${a.total} cadastros importados · ${a.statuses.matched||0} vinculados sem duplicar a linha AIS · ${a.total-(a.statuses.matched||0)} aguardando vínculo/revisão. Última importação: ${date(a.last_imported_at)}.`;
  }catch(error){$('diagnostics').textContent=error.message;}
}

function field(v,key){const manual=v.manual?.[key];return `${escape(manual||v.resolved?.[key]||v.enrichment?.[key]||"Não informado")}${manual?'<small>Preenchimento manual</small>':''}`;}
function registryRow(v){
  const r=v.resolved||v,standalone=v.origin==='antaq';
  return `<tr><td><strong>${escape(r.name)}</strong><small>MMSI ${escape(v.mmsi)}</small><small>IMO ${escape(r.imo)}</small><small>Indicativo ${escape(r.callsign)}</small><small>${standalone?'Cadastro ANTAQ · sem posição AIS':v.antaq?'AISStream + ANTAQ':'AISStream'}</small></td>
  <td>${escape(types[v.type]||'Não informado')}</td><td>${field(v,'model')}</td><td>${field(v,'manufacturer')}</td><td>${field(v,'vessel_class')}</td>
  <td>Comprimento: ${escape(r.length)} m<br>Largura: ${escape(r.width)} m<br>Destino: ${escape(v.destination)}<small>${standalone?'Sem telemetria associada':'Última coleta AIS: '+escape(date(v.last_seen))}</small></td>
  <td>${escape(r.country||'País não informado')}<small>${escape(v.enrichment?.source||'')}</small>${sourceLink(v.enrichment?.source_url)}${particulars(v)}${v.manual?.source_url?'<small>Fonte manual: '+sourceLink(v.manual.source_url)+'</small>':''}<small>${escape(v.manual?.notes||'')}</small></td>
  <td><span class="badge">${escape(statuses[v.crawl_status]||v.crawl_status)}</span><small>${escape(date(v.checked_at))}</small><small>${escape(v.error||'')}</small>${v.enrichment?.matched_by?'<small>Wikidata por '+escape(v.enrichment.matched_by.toUpperCase())+'</small>':''}</td>
  <td>${standalone?'<small>Aguardando identificação no AIS</small>':`<button data-edit="${escape(v.mmsi)}">Editar</button>`}</td></tr>`;
}
async function load(){
  const ticket=++sequence;
  try{
    const params=new URLSearchParams({q:$("query").value,type:$("type").value,status:$("status").value,origin:$("origin").value,limit:100,offset});
    const response=await fetch('/api/registry?'+params,{signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('Não foi possível carregar o cadastro. Reinicie o aplicativo para ativar esta versão.');
    const data=await response.json();if(ticket!==sequence)return;
    rows=data.vessels;total=data.total;
    if(offset>=total&&offset>0){offset=Math.max(0,Math.floor((total-1)/100)*100);return load();}
    $('rows').innerHTML=rows.map(registryRow).join('')||'<tr><td colspan="9">Nenhuma embarcação cadastrada nesta consulta.</td></tr>';
    $('summary').textContent=`${total.toLocaleString('pt-BR')} embarcações nesta consulta. Cadastro persistente no computador.`;
    $('page').textContent=`Página ${Math.floor(offset/100)+1} de ${Math.max(1,Math.ceil(total/100))}`;
    $('previous').disabled=offset===0;$('next').disabled=offset+100>=total;
  }catch(error){if(ticket===sequence)$('summary').textContent=error.message;}
}
$('filters').addEventListener('submit',event=>{event.preventDefault();offset=0;load();});
for(const id of ['type','status','origin'])$(id).addEventListener('change',()=>{offset=0;load();});
$('refresh').addEventListener('click',()=>{load();diagnostics();});
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
let antaqDraft=null,antaqVersion=0,antaqBusy=false;
function invalidateImport(){antaqDraft=null;antaqVersion++;$('antaq-apply').disabled=true;$('antaq-result').textContent='Confira a prévia antes de gravar.';}
$('import-antaq').addEventListener('click',()=>{$('antaq-importer').showModal();});
$('antaq-cancel').addEventListener('click',()=>$('antaq-importer').close());
$('antaq-file').addEventListener('change',invalidateImport);
$('antaq-url').addEventListener('input',invalidateImport);
function fileContent(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('Não foi possível ler o arquivo.'));reader.readAsDataURL(file);});}
async function runAntaqImport(commit){
  if(antaqBusy)return;
  antaqBusy=true;$('antaq-file').disabled=true;$('antaq-url').disabled=true;
  const version=antaqVersion;$('antaq-preview').disabled=true;$('antaq-apply').disabled=true;
  try{
    let draft=antaqDraft;
    if(!commit){
      const file=$('antaq-file').files[0];if(!file)throw Error('Selecione a exportação da ANTAQ.');
      if(file.size>16*1024*1024)throw Error('Use um arquivo de até 16 MB.');
      draft={filename:file.name,content:await fileContent(file),source_url:$('antaq-url').value};
    }
    if(!draft||version!==antaqVersion)return;
    $('antaq-result').textContent=commit?'Importando e cruzando identificadores…':'Analisando arquivo e conferindo vínculos…';
    const response=await fetch('/api/registry/antaq/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...draft,commit}),signal:AbortSignal.timeout(120000)});
    const report=await response.json();if(!response.ok)throw Error(report.error||'Não foi possível importar.');
    if(version!==antaqVersion)return;
    $('antaq-result').textContent=`${commit?'Importação concluída':'Prévia'}: ${report.input_rows} linhas · ${report.created} novos cadastros · ${report.updated} atualizados · ${report.duplicates_in_file} repetições no arquivo. ANTAQ na base: ${report.total}, sendo ${report.statuses.matched||0} vinculados e ${report.total-(report.statuses.matched||0)} aguardando vínculo/revisão. ${commit?'Arquivo original e fontes preservados.':'Nada foi gravado. Confira os totais antes de importar.'}`;
    antaqDraft=commit?null:draft;$('antaq-apply').disabled=commit;
    if(commit){offset=0;load();diagnostics();}
  }catch(error){if(version===antaqVersion)$('antaq-result').textContent=error.message;}
  finally{antaqBusy=false;$('antaq-preview').disabled=false;$('antaq-file').disabled=false;$('antaq-url').disabled=false;}
}
$('antaq-form').addEventListener('submit',event=>{event.preventDefault();runAntaqImport(false);});
$('antaq-apply').addEventListener('click',()=>runAntaqImport(true));
load();diagnostics();setInterval(()=>{load();diagnostics();},50000);
