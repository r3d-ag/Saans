const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const API = "";
const COLOURS = {"Good":"#16a276","Satisfactory":"#81ad56","Moderately Polluted":"#d5b33e","Poor":"#e68843","Very Poor":"#d4545d","Severe":"#7950a1"};
const POLLUTANTS = ["PM2.5","PM10","NO2","SO2","CO","O3","NH3","Pb"];
const UNITS = {"PM2.5":"µg/m³","PM10":"µg/m³","NO2":"µg/m³","SO2":"µg/m³","CO":"mg/m³","O3":"µg/m³","NH3":"µg/m³","Pb":"µg/m³"};
let stationId = localStorage.getItem("saans-station") || "demo-ambala";
let current = null;
let stations = [];
let lang = localStorage.getItem("saans-lang") || "en";
let toastTimer;

const text = {
  en: {title:"Know the air around you.", details:"Pollutant readings", causes:"What’s driving it?", forecast:"Forecast outlook", plan:"A little planning helps.", updated:"Updated", loading:"Loading air…", noCause:"No strong source signal today. Check back as more data arrives.", sample:"Sample view", noData:"Waiting for enough hourly data", alertSaved:"Alert saved.", alertFailed:"Could not save this alert."},
  hi: {title:"अपने आसपास की हवा जानें।", details:"प्रदूषक रीडिंग", causes:"हवा को क्या प्रभावित कर रहा है?", forecast:"आगे का अनुमान", plan:"थोड़ी योजना मददगार है।", updated:"अपडेट", loading:"हवा लोड हो रही है…", noCause:"आज किसी स्रोत का मज़बूत संकेत नहीं मिला।", sample:"नमूना दृश्य", noData:"पर्याप्त प्रति-घंटा डेटा की प्रतीक्षा", alertSaved:"अलर्ट सेव हो गया।", alertFailed:"अलर्ट सेव नहीं हो सका।"}
};
const tr = key => (text[lang] && text[lang][key]) || text.en[key] || key;

async function api(path, options={}) {
  const response = await fetch(`${API}${path}`, {headers:{"Content-Type":"application/json", ...(options.headers||{})}, ...options});
  if (!response.ok) { const data = await response.json().catch(()=>({})); throw new Error(data.detail || `Request failed (${response.status})`); }
  return response.headers.get("content-type")?.includes("json") ? response.json() : response.text();
}

function showToast(message) {
  const el = $("#toast"); el.textContent = message; el.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(()=>el.classList.remove("show"), 2800);
}
function fmtTime(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {hour:"numeric", minute:"2-digit", timeZone:"Asia/Kolkata"}).format(new Date(iso));
}
function fmtDate() {
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {weekday:"long", day:"numeric", month:"long", timeZone:"Asia/Kolkata"}).format(new Date());
}
function safe(value, fallback="—") { return value === null || value === undefined ? fallback : value; }
function stationDisplayName(station) {
  const name = String(station?.name || "").trim();
  const city = String(station?.city || "").trim();
  if (name && (!city || /^(unknown|india|—)$/i.test(city) || name.toLowerCase() !== city.toLowerCase())) return name;
  return city || name || "Saans station";
}
function stationLocation(station) {
  const city = String(station?.city || "").trim();
  const state = String(station?.state || "").trim();
  const usefulCity = city && !/^(unknown|india|—)$/i.test(city);
  const usefulState = state && !/^(unknown|india|—)$/i.test(state);
  if (usefulCity && usefulState && city.toLowerCase() !== state.toLowerCase()) return `${city} · ${state}`;
  return usefulCity || usefulState || station?.source || "";
}

async function loadStations() {
  const data = await api("/v1/stations"); stations = data.stations;
  const select = $("#station-select");
  select.innerHTML = stations.map(s=>{
    const location=stationLocation(s), label=stationDisplayName(s);
    return `<option value="${escapeHtml(s.id)}">${escapeHtml(label)}${location&&location!==label?` · ${escapeHtml(location)}`:""}</option>`;
  }).join("");
  if (!stations.some(s=>s.id===stationId)) stationId = stations[0]?.id;
  select.value = stationId;
  renderStations(stations);
}
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch])); }

async function loadCurrent() {
  const cached = localStorage.getItem(`saans-now-${stationId}`);
  if (cached) { try { current=JSON.parse(cached); renderCurrent(current, true); } catch {} }
  try {
    const data = await api(`/v1/stations/${encodeURIComponent(stationId)}/now`);
    current=data; localStorage.setItem(`saans-now-${stationId}`, JSON.stringify(data));
    renderCurrent(data, false);
    const historyEnd = new Date();
    const historyStart = new Date(historyEnd.getTime() - 24 * 60 * 60 * 1000);
    const history = await api(`/v1/stations/${encodeURIComponent(stationId)}/history?step=hour&from=${encodeURIComponent(historyStart.toISOString())}&to=${encodeURIComponent(historyEnd.toISOString())}`);
    drawHistory(history.points || []);
  } catch (error) {
    if (!current) $("#aqi-category").textContent = "Offline · no saved reading";
    $("#freshness-label").textContent = "Offline";
    showToast("Showing saved data where available.");
  }
}

function renderCurrent(data, fromCache) {
  const number = data.aqi;
  const label=stationDisplayName(data.station), location=stationLocation(data.station);
  $("#station-heading").textContent = location && location !== label ? `${label} · ${location}` : label;
  $("#updated-time").textContent = `${fromCache ? "Saved · " : ""}${fmtTime(data.as_of)} IST`;
  $("#freshness-label").textContent = fromCache ? "Offline cache" : tr("updated");
  $("#date-label").textContent = `${fmtDate().toUpperCase()} · AIR QUALITY`;
  $("#aqi-number").textContent = safe(number);
  $("#ring-value").textContent = safe(number);
  $("#aqi-category").textContent = data.category || data.reason || tr("loading");
  $("#dominant-pollutant").textContent = data.dominant_pollutant || "Not enough data";
  const color = COLOURS[data.category] || "#a9b3ac";
  $("#aqi-panel").style.setProperty("--aqi-color", color);
  $("#aqi-number").style.color = color;
  $("#aqi-category").style.color = color;
  const ring = Math.max(0,Math.min(500,Number(number)||0))*0.72;
  $("#aqi-ring").style.background = `conic-gradient(${color} 0deg ${ring}deg,#e7eee3 ${ring}deg 360deg)`;
  const trust = data.trust || {};
  $("#trust-label").textContent = `${trust.level || "Low"} trust · ${Math.round((trust.score || 0)*100)}%`;
  $("#trust-badge").className = `trust-badge ${(trust.level||"low").toLowerCase()}`;
  renderPollutants(data.subindices || {});
  renderCauses(data.causes || []);
  renderForecast(data.forecasts || []);
  renderMath(data);
  const demo = data.source === "demo";
  $("#demo-banner").hidden = !demo || Boolean(localStorage.getItem("saans-banner-dismissed"));
  if (demo) $("#demo-banner span:nth-child(2)").innerHTML = `<strong>${tr("sample")}</strong> — these are illustrative readings until you connect live sources.`;
  $("#action-copy").textContent = advice(data.aqi);
  $("#best-time").textContent = bestTime(data);
}

function renderPollutants(values) {
  $("#pollutant-grid").innerHTML = POLLUTANTS.map((p,i)=>{
    const item=values[p];
    if (!item) return `<article class="pollutant-card"><div class="p-head">${p}<i class="p-dot" style="background:#cbd2cc"></i></div><div class="p-missing">Not available</div></article>`;
    return `<article class="pollutant-card"><div class="p-head">${p}<i class="p-dot" style="background:${COLOURS[item.category]||"#a9c85e"}"></i></div><div class="p-value">${Number(item.value).toFixed(item.value<10?1:0)}<span class="p-unit">${item.unit || UNITS[p]}</span></div><div class="p-index">Sub-index ${Math.round(item.sub_index)} · ${item.hours} hrs</div></article>`;
  }).join("");
}
function renderCauses(causes) {
  const target=$("#causes-list");
  if (!causes.length) { target.innerHTML=`<div class="cause-empty">${tr("noCause")}</div>`; return; }
  target.innerHTML=causes.map(c=>`<div class="cause-card"><div class="cause-card-head"><strong>${escapeHtml(c.label)}</strong><span class="confidence">${Math.round(c.confidence*100)}% signal match</span></div><p>${(c.evidence||[]).map(escapeHtml).join(" · ")}</p></div>`).join("");
}
function renderForecast(items) {
  $("#forecast-cards").innerHTML=items.map(f=>{
    if (!f.available) return `<div class="forecast-card"><span>${f.horizon_h} HOURS</span><b>—</b><small>Waiting for valid AQI</small></div>`;
    const label=categoryAt(f.aqi_p50);
    const likelihood=Math.round(Math.max(...Object.values(f.category_probs||{}))*100);
    return `<div class="forecast-card"><span>${f.horizon_h} HOURS</span><b>${f.aqi_p50}</b><small>${label} · baseline</small><div class="forecast-range">Indicative band ${f.aqi_p10}–${f.aqi_p90}</div><div class="range-track"><i style="width:${Math.min(100,(f.aqi_p90/500)*100)}%"></i></div><div class="forecast-range">Indicative category share ${likelihood}%*</div></div>`;
  }).join("");
}
function categoryAt(aqi) { return [[50,"Good"],[100,"Satisfactory"],[200,"Moderately Polluted"],[300,"Poor"],[400,"Very Poor"],[500,"Severe"]].find(([max])=>aqi<=max)?.[1]||"Severe"; }
function advice(aqi) {
  if (aqi==null) return "Not enough recent measurements to calculate an overall AQI.";
  if (aqi<=100) return "Air is in the CPCB Good or Satisfactory range. Check again before strenuous outdoor activity.";
  if (aqi<=200) return "Sensitive people may want to reduce prolonged exertion outdoors. Check local conditions.";
  if (aqi<=300) return "Consider reducing prolonged outdoor exertion, especially if you are sensitive to air pollution.";
  return "Consider limiting prolonged outdoor activity and follow local public health guidance.";
}
function bestTime(data) {
  const points=window.historyPoints||[];
  const valid=points.filter(x=>x.aqi!=null).slice(-12);
  if(valid.length<3) return "Check hourly trend";
  const best=valid.reduce((a,b)=>a.aqi<b.aqi?a:b);
  return `Lower recently · ${fmtTime(best.ts)} IST`;
}
function renderMath(data) {
  const rows=Object.entries(data.subindices||{});
  $("#math-details").innerHTML=rows.length?rows.map(([name,item])=>`<div class="math-row"><strong>${name} · ${item.value} ${item.unit}</strong><span>Sub-index ${item.sub_index}</span><span>${item.category}</span></div>`).join(""):`<div class="math-row">No valid pollutant sub-indices are available.</div>`;
}
function drawHistory(points) {
  window.historyPoints=points;
  const canvas=$("#history-chart"), empty=$("#chart-empty"), box=canvas.getBoundingClientRect();
  const valid=points.filter(p=>p.aqi!==null&&p.aqi!==undefined).slice(-36);
  if (valid.length<2) {empty.hidden=false;empty.textContent=tr("noData");return;}
  empty.hidden=true;
  const ratio=window.devicePixelRatio||1; canvas.width=box.width*ratio; canvas.height=box.height*ratio;
  const ctx=canvas.getContext("2d");ctx.scale(ratio,ratio);
  const w=box.width,h=box.height,pad={l:28,r:8,t:10,b:16};
  const vals=valid.map(p=>p.aqi), min=Math.max(0,Math.floor((Math.min(...vals)-25)/50)*50), max=Math.min(500,Math.ceil((Math.max(...vals)+25)/50)*50)||100;
  const y=v=>h-pad.b-(v-min)/(max-min||1)*(h-pad.t-pad.b), x=i=>pad.l+i*(w-pad.l-pad.r)/(valid.length-1);
  ctx.font="9px DM Mono, monospace";ctx.fillStyle="#99a39d";ctx.strokeStyle="#edf0ea";ctx.lineWidth=1;
  for(let i=0;i<3;i++){const value=min+(max-min)*i/2;const yy=y(value);ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillText(Math.round(value),1,yy+3);}
  const grad=ctx.createLinearGradient(0,pad.t,0,h);grad.addColorStop(0,"rgba(183,211,94,.31)");grad.addColorStop(1,"rgba(183,211,94,0)");
  ctx.beginPath();valid.forEach((p,i)=>i?ctx.lineTo(x(i),y(p.aqi)):ctx.moveTo(x(i),y(p.aqi)));ctx.lineTo(x(valid.length-1),h-pad.b);ctx.lineTo(x(0),h-pad.b);ctx.closePath();ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();valid.forEach((p,i)=>i?ctx.lineTo(x(i),y(p.aqi)):ctx.moveTo(x(i),y(p.aqi)));ctx.strokeStyle="#88a943";ctx.lineWidth=2;ctx.lineJoin="round";ctx.stroke();
  ctx.fillStyle="#79983c";ctx.beginPath();ctx.arc(x(valid.length-1),y(valid.at(-1).aqi),3,0,Math.PI*2);ctx.fill();
}
function renderStations(items) {
  const list=$("#station-list"), pins=$("#map-pins");
  list.innerHTML=items.map(s=>`<button class="station-row ${s.id===stationId?"active":""}" data-station="${escapeHtml(s.id)}"><i class="station-color"></i><span><strong>${escapeHtml(stationDisplayName(s))}</strong><small>${escapeHtml(stationLocation(s))}</small></span><b style="color:${COLOURS[s.category]||"#718077"}">${safe(s.aqi)}</b></button>`).join("");
  const minLat=29.5,maxLat=31.8,minLon=75.5,maxLon=78.2;
  pins.innerHTML=items.map(s=>{const left=7+(s.lon-minLon)/(maxLon-minLon)*86,top=90-(s.lat-minLat)/(maxLat-minLat)*78;return `<span class="map-pin ${s.id===stationId?"active":""}" style="left:${left}%;top:${top}%" data-label="${escapeHtml(stationDisplayName(s))} · ${safe(s.aqi)}"></span>`;}).join("");
  $$(".station-row",list).forEach(button=>button.addEventListener("click",()=>selectStation(button.dataset.station)));
}
async function selectStation(id) {
  stationId=id;localStorage.setItem("saans-station",id);$("#station-select").value=id;renderStations(stations);await loadCurrent();
}
async function saveAlert() {
  const channel=$("#alert-channel").value, threshold=Number($("#alert-threshold").value);
  try {
    if(channel==="telegram") {
      const destination=$("#alert-destination").value.trim();
      if(!destination) throw new Error("Enter the Telegram chat ID after starting your bot.");
      await api("/v1/subscriptions",{method:"POST",body:JSON.stringify({channel,destination,station_id:stationId,threshold})});
    } else {
      const config=await api("/v1/config");
      if(!config.vapid_public_key) throw new Error("Browser push is not configured by this deployment.");
      if(!("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("This browser does not support web push.");
      const registration=await navigator.serviceWorker.ready;
      const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(config.vapid_public_key)});
      const json=subscription.toJSON();
      await api("/v1/push-subscriptions",{method:"POST",body:JSON.stringify({endpoint:json.endpoint,keys:json.keys,station_id:stationId,threshold})});
    }
    $("#alert-feedback").textContent=tr("alertSaved");showToast(tr("alertSaved"));setTimeout(()=>$("#alert-modal").close(),600);
  } catch(error) { $("#alert-feedback").textContent=error.message||tr("alertFailed"); }
}
function urlBase64ToUint8Array(base64String) {
  const padding="=".repeat((4-base64String.length%4)%4),base64=(base64String+padding).replace(/-/g,"+").replace(/_/g,"/");
  const raw=atob(base64);return Uint8Array.from([...raw].map(char=>char.charCodeAt(0)));
}
function applyLanguage() {
  $("#page-title").textContent=tr("title");$(".section-heading h2").textContent=tr("details");
  $$(".why-panel h2")[0].textContent=tr("causes");$(".forecast-panel h2").textContent=tr("forecast");$(".action-copy h2").textContent=tr("plan");
  if(current) renderCurrent(current,false);
}
function setLanguage() { lang=lang==="en"?"hi":"en";localStorage.setItem("saans-lang",lang);applyLanguage(); }

$("#station-select").addEventListener("change",e=>selectStation(e.target.value));
$("#refresh-button").addEventListener("click",()=>loadCurrent());
$("#alerts-open").addEventListener("click",()=>$("#alert-modal").showModal());
$("#save-alert").addEventListener("click",saveAlert);
$("#alert-channel").addEventListener("change",e=>{$("#destination-label").hidden=e.target.value==="webpush";});
$("#language-toggle").addEventListener("click",setLanguage);
$("#banner-dismiss").addEventListener("click",()=>{$("#demo-banner").hidden=true;localStorage.setItem("saans-banner-dismissed","1");});
$("#about-button").addEventListener("click",()=>$("#about-modal").showModal());
$("#about-close").addEventListener("click",()=>$("#about-modal").close());
$("#show-math").addEventListener("click",()=>$("#math-details").classList.toggle("open"));
$$("[data-view]").forEach(button=>button.addEventListener("click",()=>{
  const target=button.dataset.view;const section=target==="now"?$("#now-view"):target==="forecast"?$("#forecast-view"):target==="map"?$("#map-view"):$("#method-view");
  section.scrollIntoView({behavior:"smooth",block:"start"});$$(".rail-link").forEach(x=>x.classList.toggle("active",x===button));
}));
window.addEventListener("resize",()=>drawHistory(window.historyPoints||[]));
window.addEventListener("online",()=>loadCurrent());
if(localStorage.getItem("saans-banner-dismissed")) $("#demo-banner").hidden=true;
if("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(()=>{});
if(lang==="hi") applyLanguage();
(async()=>{try{await loadStations();await loadCurrent();}catch(e){$("#freshness-label").textContent="Offline";$("#aqi-category").textContent="Start the Saans API to load data";}})();
