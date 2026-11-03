/* Provider credentials stay on the local server. Downloads use server-side filters. */
"use strict";
const $ = id => document.getElementById(id);
const TYPES = {aircraft:"Aeronave",tanker:"Tanker · navio-tanque",gas:"Gaseiro · LNG / LPG",container:"Porta-contêineres",bulk:"Graneleiro",cargo:"Carga geral",fishing:"Pesca",tug:"Rebocador / reboque",passenger:"Passageiros",sailing:"Veleiro",pleasure:"Embarcação de recreio",other:"Outros",unknown:"Não informado"};
const COLORS = {aircraft:"#3486d9",tanker:"#e09b3b",gas:"#25a39b",container:"#4585cf",bulk:"#a477c5",cargo:"#638878",fishing:"#16806a",tug:"#b55a38",passenger:"#9254a5",sailing:"#277b96",pleasure:"#c04f83",other:"#80929d",unknown:"#80929d"};
const state = {objects:[],selected:null,favorites:new Set(),favoritesOnly:false,markers:new Map(),source:"demo",at:null,area:null,drawing:false,corner:null,total:0};
let map, areaLayer, trackLayer, toastTimer, queryTimer, request, generation=0, trajectoryGeneration=0, hasLoaded=false;
const key = object => `${object.source}:${object.object_id}`;
try {const saved=JSON.parse(localStorage.getItem("mvision:favorites") || "[]");if(Array.isArray(saved))state.favorites=new Set(saved.filter(v=>typeof v==="string").map(v=>v.includes(":")?v:`${v.startsWith("DEMO-")?"demo":"aisstream"}:${v}`));} catch {}
const escapeHTML = value => String(value ?? "—").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (value,digits=1) => typeof value==="number" && Number.isFinite(value) ? value.toLocaleString("pt-BR",{maximumFractionDigits:digits,minimumFractionDigits:digits}) : "—";
const kind = object => Object.hasOwn(TYPES,object.type) ? object.type : "unknown";
const dateLabel = value => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString("pt-BR",{timeZone:"UTC"})+" UTC" : "Não informado";
function ageLabel(value) {
  const minutes=Math.max(0,Math.floor(((state.at ? Date.parse(state.at) : Date.now())-Date.parse(value))/60000));
  if(!Number.isFinite(minutes))return "Idade desconhecida";
  if(minutes<1)return "Há menos de 1 min";
  return minutes<60 ? `Há ${minutes} min` : minutes<1440 ? `Há ${Math.floor(minutes/60)} h ${minutes%60} min` : `Há ${Math.floor(minutes/1440)} dias`;
}
function notify(message) {$("toast").textContent=message;$("toast").hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").hidden=true,5000);}
function clockTick() {$("clock").textContent=new Date().toLocaleTimeString("pt-BR",{timeZone:"UTC"})+" UTC";}
clockTick();setInterval(clockTick,1000);
const localInput = date => new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,19);
function setDateLimits() {
  const now=new Date(),cutoff=new Date(now.getTime()-30*86400000);
  for(const id of ["history-at","export-start","export-end"]){$(id).min=localInput(cutoff);$(id).max=localInput(now);}
}
setDateLimits();setInterval(setDateLimits,60000);
function readDate(id) {
  const input=$(id);if(!input.value)return null;const date=new Date(input.value);
  if(!input.checkValidity() || !Number.isFinite(date.getTime()))throw new Error("Escolha uma data dentro dos últimos 30 dias.");
  return date.toISOString();
}
function initMap() {
  if(!window.L){$("map-warning").textContent="Não foi possível carregar o mapa. Verifique a conexão; a lista continua disponível.";$("map-warning").hidden=false;for(const id of ["bounds-filter","world-view","draw-area","go-coordinates"])$(id).disabled=true;return;}
  map=L.map("map",{zoomControl:false,minZoom:2,maxZoom:18,maxBounds:[[-85,-180],[85,180]],maxBoundsViscosity:1}).setView([15,12],2);
  L.control.zoom({position:"bottomright"}).addTo(map);
  const tiles=L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,noWrap:true,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(map);
  tiles.on("tileerror",()=>{$("map-warning").textContent="Mapa-base indisponível. A lista e os marcadores continuam disponíveis.";$("map-warning").hidden=false;});
  map.on("moveend",()=>{if($("bounds-filter").checked)queueLoad();});
  map.on("click",event=>{
    if(!state.drawing)return;
    if(!state.corner){state.corner=event.latlng;$("area-label").textContent="Agora clique no canto oposto.";return;}
    const bounds=L.latLngBounds(state.corner,event.latlng);state.area=[bounds.getSouth(),bounds.getWest(),bounds.getNorth(),bounds.getEast()];
    if(areaLayer)map.removeLayer(areaLayer);
    areaLayer=L.rectangle(bounds,{color:"#167e7a",weight:2,fillOpacity:.08,interactive:false}).addTo(map);
    state.drawing=false;state.corner=null;$("draw-area").textContent="Desenhar área";$("area-label").textContent="Área desenhada aplicada aos filtros.";
    $("bounds-filter").checked=false;$("bounds-filter").disabled=true;loadData();
  });
  new ResizeObserver(()=>map.invalidateSize()).observe($("map"));
}
function filterParams() {
  const params=new URLSearchParams();
  for(const [field,id] of [["q","search"],["object_type","object-filter"],["source","source-filter"],["type","type-filter"],["size","size-filter"],["motion","motion-filter"]]){
    const value=$(id).value.trim();if(value && value!=="all")params.set(field,value);
  }
  let bounds=state.area;
  if(!bounds && $("bounds-filter").checked && map){const b=map.getBounds();bounds=[Math.max(-90,b.getSouth()),Math.max(-180,b.getWest()),Math.min(90,b.getNorth()),Math.min(180,b.getEast())];}
  if(bounds)params.set("bounds",bounds.join(","));if(state.at)params.set("at",state.at);
  if(state.favoritesOnly)params.set("keys",[...state.favorites].join(",") || "__no_favorites__");
  return params;
}
function visibleObjects() {return state.objects.filter(v=>!state.favoritesOnly || state.favorites.has(key(v)) || state.favorites.has(v.object_id));}
function selectObject(id,focus=true) {
  const object=state.objects.find(v=>key(v)===id);if(!object)return;state.selected=id;render();loadTrajectory();
  if(focus && map){map.setView([object.latitude,object.longitude],Math.max(map.getZoom(),5),{animate:false});if(window.innerWidth>820)map.panBy([$("vessel-detail").offsetWidth/2,0],{animate:false});}
  if(window.innerWidth<=600)$("map").scrollIntoView({behavior:"auto",block:"center"});
}
function render() {
  const visible=visibleObjects().sort((a,b)=>Number(state.favorites.has(key(b)))-Number(state.favorites.has(key(a))) || String(a.name).localeCompare(String(b.name)));
  $("stat-total").textContent=state.objects.length.toLocaleString("pt-BR");$("stat-tanker").textContent=state.objects.filter(v=>v.object_type==="aircraft").length;
  $("stat-moving").textContent=state.objects.filter(v=>v.speed>.5).length;$("stat-favorites").textContent=state.objects.filter(v=>state.favorites.has(key(v))).length;
  $("result-count").textContent=visible.length;$("list-summary").textContent=`${visible.length} carregados · ${state.total} na consulta`;
  const listed=visible.slice(0,200);
  $("vessel-list").innerHTML=listed.length ? listed.map(v=>`<button class="vessel-row ${state.selected===key(v)?"selected":""}" data-object="${escapeHTML(key(v))}" aria-pressed="${state.selected===key(v)}"><span class="dot ${kind(v)}"></span><span class="vessel-info"><strong>${state.favorites.has(key(v))?"★ ":""}${escapeHTML(v.name)}</strong><small>${escapeHTML(v.object_id)} · ${escapeHTML(ageLabel(v.updated_at))}</small></span><span class="row-speed">${fmt(v.speed)}<small>kn</small></span></button>`).join("") : '<p class="empty-state">Nenhum objeto encontrado.<br>Altere os filtros ou o horário.</p>';
  if(visible.length>200)$("vessel-list").insertAdjacentHTML("beforeend",'<p class="empty-state">Lista limitada a 200 objetos. Refine a busca. A exportação consulta todos os registros que correspondem aos filtros.</p>');
  if(map){
    const ids=new Set(visible.map(key));for(const [id,marker]of state.markers)if(!ids.has(id)){map.removeLayer(marker);state.markers.delete(id);}
    for(const object of visible){
      const id=key(object);let marker=state.markers.get(id);
      if(!marker){marker=L.marker([object.latitude,object.longitude],{keyboard:true,title:object.name}).addTo(map);marker.on("click",()=>{if(!state.drawing)selectObject(id,false);});state.markers.set(id,marker);}
      const heading=Number.isFinite(object.heading)?object.heading:Number.isFinite(object.course)?object.course:0;
      marker.setLatLng([object.latitude,object.longitude]).setIcon(L.divIcon({className:`ship-marker ${object.object_type==="aircraft"?"aircraft":""} ${state.selected===id?"selected":""}`,html:`<span class="ship-pointer" style="--ship-color:${COLORS[kind(object)]};--heading:${heading}deg"></span>`,iconSize:[24,24],iconAnchor:[12,12]}));
      marker.setZIndexOffset(state.selected===id?1000:0);
      const tooltip=`<strong>${escapeHTML(object.name)}</strong><br>${TYPES[kind(object)]} · ${fmt(object.speed)} kn<br>${escapeHTML(ageLabel(object.updated_at))}`;
      if(marker.getTooltip())marker.setTooltipContent(tooltip);else marker.bindTooltip(tooltip,{direction:"top",offset:[0,-10]});
    }
  }
  if(state.selected && !visible.some(v=>key(v)===state.selected)){state.selected=null;clearTrajectory();}renderDetail();
}
function renderDetail() {
  const v=state.objects.find(v=>key(v)===state.selected);$("vessel-detail").hidden=!v;document.querySelector(".map-caption").hidden=Boolean(v);if(!v)return;
  const favorite=state.favorites.has(key(v));
  const fields=[["Identificador",v.object_id],["Fonte",v.source],["IMO",v.imo],["Indicativo",v.callsign],["Latitude",fmt(v.latitude,4)+"°"],["Longitude",fmt(v.longitude,4)+"°"],
    [v.object_type==="aircraft"?"Altitude":"Comprimento",v.object_type==="aircraft"?fmt(v.altitude,0)+" m":fmt(v.length,0)+" m"],["Horário da posição",dateLabel(v.updated_at)],["Posição coletada",dateLabel(v.position_collected_at)],["Última coleta",dateLabel(v.collected_at)],["Horário original",dateLabel(v.event_at)]];
  $("vessel-detail").innerHTML=`<div class="detail-top"><button class="close-detail" aria-label="Fechar detalhes">×</button><p class="detail-kicker">${v.object_type==="aircraft"?"AERONAVE":"EMBARCAÇÃO"}</p><h2>${escapeHTML(v.name)}</h2><span class="type-label"><i class="dot ${kind(v)}"></i>${TYPES[kind(v)]}</span></div><div class="detail-status"><span>${escapeHTML(v.status)}</span><small>${escapeHTML(ageLabel(v.updated_at))}${state.at?" do horário consultado":""}</small></div><div class="detail-numbers"><div><span>Velocidade</span><strong>${fmt(v.speed)}</strong><em>kn</em></div><div><span>Direção</span><strong>${fmt(v.course,0)}</strong><em>°</em></div></div><div class="detail-info"><dl>${fields.map(([label,value])=>`<dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd>`).join("")}</dl></div><p class="trajectory-caption" id="trajectory-status">Trajetória: selecione o objeto para consultar.</p><div class="detail-actions"><button class="button ${favorite?"primary":"secondary"}" id="favorite-object" aria-pressed="${favorite}">${favorite?"★ Remover dos favoritos":"☆ Adicionar aos favoritos"}</button><p class="detail-note">${v.source==="demo"?"Demonstração: identificadores e posições são fictícios.":v.timestamp_basis==="collection"?"O horário original não foi informado; usamos o recebimento da posição.":"A posição usa o horário informado pela fonte."}</p></div>`;
  $("vessel-detail").querySelector(".close-detail").addEventListener("click",()=>{state.selected=null;clearTrajectory();render();});
  $("favorite-object").addEventListener("click",()=>{if(favorite)state.favorites.delete(key(v));else state.favorites.add(key(v));try{localStorage.setItem("mvision:favorites",JSON.stringify([...state.favorites]));}catch{notify("Favorito salvo apenas nesta sessão.");}render();});
}
function clearTrajectory() {trajectoryGeneration++;if(trackLayer && map)map.removeLayer(trackLayer);trackLayer=null;}
async function loadTrajectory() {
  clearTrajectory();const id=state.selected;if(!id)return;const object=state.objects.find(v=>key(v)===id);if(!object)return;
  const ticket=trajectoryGeneration,params=new URLSearchParams({object_id:object.object_id,source:object.source,hours:"6"});if(state.at)params.set("at",state.at);
  if($("trajectory-status"))$("trajectory-status").textContent="Consultando trajetória das últimas 6 horas…";
  try{
    const response=await fetch("/api/trajectory?"+params,{signal:AbortSignal.timeout(15000)});if(!response.ok)throw new Error();const data=await response.json();
    if(ticket!==trajectoryGeneration || state.selected!==id)return;
    const points=data.points.filter(v=>Number.isFinite(v.latitude)&&Number.isFinite(v.longitude));const segments=[];let segment=[];
    for(const point of points){const previous=segment.at(-1);if(previous && (Math.abs(point.longitude-previous.longitude)>180 || Date.parse(point.updated_at)-Date.parse(previous.updated_at)>30*60000)){if(segment.length>1)segments.push(segment);segment=[];}segment.push(point);}
    if(segment.length>1)segments.push(segment);
    if(map)trackLayer=L.layerGroup(segments.map(s=>L.polyline(s.map(p=>[p.latitude,p.longitude]),{color:COLORS[kind(object)],weight:3}))).addTo(map);
    if($("trajectory-status"))$("trajectory-status").textContent=`${points.length} posições registradas nas últimas 6 h. Lacunas acima de 30 min ficam separadas.`;
  }catch{if(ticket===trajectoryGeneration && $("trajectory-status"))$("trajectory-status").textContent="Não foi possível consultar a trajetória.";}
}
async function loadData(manual=false) {
  request?.abort();const controller=new AbortController();request=controller;const ticket=++generation;$("refresh").disabled=true;
  const timeout=setTimeout(()=>controller.abort(),20000);
  try{
    const response=await fetch("/api/objects?"+filterParams(),{signal:controller.signal,cache:"no-store"});if(!response.ok)throw new Error("Falha na consulta");const data=await response.json();if(ticket!==generation)return;
    state.objects=data.objects.filter(v=>typeof v.object_id==="string"&&Number.isFinite(v.latitude)&&Number.isFinite(v.longitude));state.source=data.source;state.total=data.total;
    const labels={connected:"conectado",connecting:"conectando",reconnecting:"reconectando",error:"erro",rate_limited:"limite atingido",demo:"demonstração"};
    $("source-badge").textContent=data.source==="demo"?"Modo demonstração":Object.entries(data.connections).map(([source,status])=>`${source}: ${labels[status] || status}`).join(" · ") || "Aguardando fontes";
    $("data-notice").textContent=(data.source==="demo"?"DEMONSTRAÇÃO · 36 embarcações e 6 aeronaves fictícias, em posições fixas. ":"DADOS REAIS · Última posição conhecida; a cobertura depende das fontes. ")+"Histórico de 30 dias coletado enquanto o aplicativo estiver aberto. "+(data.truncated?`Mapa limitado aos ${data.objects.length.toLocaleString("pt-BR")} objetos mais recentes de ${data.total.toLocaleString("pt-BR")}; filtre a área. A exportação inclui todos os resultados. `:"")+(data.storage_error?"Falha no armazenamento local; verifique o disco.":"");
    $("history-label").textContent=state.at?"Histórico · "+new Date(state.at).toLocaleString("pt-BR"):"Agora · últimas posições conhecidas";
    $("last-sync").textContent="Consulta às "+new Date().toLocaleTimeString("pt-BR");hasLoaded=true;render();if(state.selected)loadTrajectory();if(manual)notify("Consulta atualizada.");
  }catch(error){if(ticket!==generation)return;$("source-badge").textContent="Consulta indisponível";$("data-notice").textContent=hasLoaded?"Falha na consulta. Os dados exibidos pertencem à consulta anterior. Clique em Atualizar para tentar novamente.":"Não foi possível carregar os objetos. Verifique o servidor local e clique em Atualizar.";if(manual)notify(error.name==="AbortError"?"Tempo de consulta excedido.":"Falha na consulta ao servidor.");}
  finally{clearTimeout(timeout);if(ticket===generation)$("refresh").disabled=false;}
}
function queueLoad() {clearTimeout(queryTimer);queryTimer=setTimeout(()=>loadData(),300);}
function setTab(favoritesOnly) {state.favoritesOnly=favoritesOnly;for(const[id,active]of [["tab-all",!favoritesOnly],["tab-favorites",favoritesOnly]]){$(id).classList.toggle("active",active);$(id).setAttribute("aria-pressed",String(active));}loadData();}
function clearArea() {state.area=null;state.corner=null;state.drawing=false;if(areaLayer && map)map.removeLayer(areaLayer);areaLayer=null;$("bounds-filter").disabled=!map;$("area-label").textContent="Nenhuma área desenhada";$("draw-area").textContent="Desenhar área";}
$("vessel-list").addEventListener("click",event=>{const row=event.target.closest("[data-object]");if(row)selectObject(row.dataset.object);});
$("tab-all").addEventListener("click",()=>setTab(false));$("tab-favorites").addEventListener("click",()=>setTab(true));$("search").addEventListener("input",queueLoad);
for(const id of ["object-filter","source-filter","type-filter","size-filter","motion-filter","bounds-filter"])$(id).addEventListener("change",()=>loadData());
$("reset").addEventListener("click",()=>{$("search").value="";for(const id of ["object-filter","source-filter","type-filter","size-filter","motion-filter"])$(id).value="all";$("bounds-filter").checked=false;clearArea();setTab(false);});
$("world-view").addEventListener("click",()=>map?.setView([15,12],2,{animate:false}));$("refresh").addEventListener("click",()=>loadData(true));
$("draw-area").addEventListener("click",()=>{state.drawing=!state.drawing;state.corner=null;$("draw-area").textContent=state.drawing?"Cancelar desenho":"Desenhar área";$("area-label").textContent=state.drawing?"Clique em dois cantos do mapa para definir a área.":state.area?"Área desenhada aplicada.":"Nenhuma área desenhada";});
$("clear-area").addEventListener("click",()=>{clearArea();loadData();});
$("go-coordinates").addEventListener("click",()=>{const parts=$("coordinates").value.split(",").map(v=>v.trim());const [lat,lon]=parts.map(Number);if(parts.length!==2 || parts.some(v=>!v) || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat)>90 || Math.abs(lon)>180)return notify("Informe latitude e longitude válidas, separadas por vírgula.");map?.setView([lat,lon],7,{animate:false});});
$("apply-history").addEventListener("click",()=>{try{const at=readDate("history-at");if(!at)return notify("Escolha a data e o horário.");state.at=at;loadData(true);}catch(error){notify(error.message);}});
$("live-view").addEventListener("click",()=>{state.at=null;$("history-at").value="";loadData(true);});
document.addEventListener("keydown",event=>{if(event.key==="/"&&!/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)){event.preventDefault();$("search").focus();}if(event.key==="Escape"){state.selected=null;clearTrajectory();render();}});
$("export").addEventListener("click",async()=>{
  const button=$("export");button.disabled=true;
  try{
    const params=filterParams(),start=readDate("export-start"),end=readDate("export-end");if(Boolean(start)!==Boolean(end))throw new Error("Preencha o início e o fim do período.");if(start && start>end)throw new Error("O início deve ser anterior ao fim.");if(start){params.set("start",start);params.set("end",end);params.delete("at");}
    params.set("dataset",$("export-dataset").value);params.set("format",$("export-format").value);
    const response=await fetch("/api/export?"+params,{signal:AbortSignal.timeout(120000)});if(!response.ok){const error=await response.json();throw new Error(error.error || "Falha na exportação.");}
    const name=response.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] || "mvision.csv";
    const url=URL.createObjectURL(await response.blob()),link=document.createElement("a");link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);notify("Exportação concluída e salva também na pasta exportacoes.");
  }catch(error){notify(error.message || "Falha na exportação.");}finally{button.disabled=false;}
});
if(window.innerWidth<=600)document.querySelector(".filters").open=false;
initMap();loadData();setInterval(()=>{if(!state.at)loadData();},50000);
