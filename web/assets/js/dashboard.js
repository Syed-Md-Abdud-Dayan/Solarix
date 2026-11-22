'use strict';
const $ = (s) => document.querySelector(s);
const state = { data: null, wards: [], city: '', horizon: 3 };
const fmt = n => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
const dateFmt = s => new Date(`${s}T00:00:00`).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
const toast = msg => { const el=$('#toast'); el.textContent=msg; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),2600); };

async function api(url){
  const r=await fetch(url); const txt=await r.text(); let body;
  try{ body=JSON.parse(txt); }catch(_){
    if(r.status===404) throw new Error('This server is outdated and has no prediction route ('+url.split('?')[0]+'). Stop the old server (Ctrl+C), then run the NEW app.py from the updated project folder: python app.py');
    throw new Error('Server returned a non-JSON reply (HTTP '+r.status+'): '+txt.slice(0,120));
  }
  if(!r.ok) throw new Error(body.error || `API error ${r.status}`); return body; }
function setConnection(ok, message){ $('#apiDot').className=ok?'connected':'error'; $('#apiStatus').textContent=ok?'Model API connected':'Model API unavailable'; $('#apiSub').textContent=message; }
function drawLineChart(el, values, opts={}){
  if(!values.length){el.innerHTML='<div class="loading">No observations available.</div>';return;}
  const w=760,h=240,p={l:48,r:18,t:18,b:36}, iw=w-p.l-p.r, ih=h-p.t-p.b;
  const max=Math.max(1,...values.map(d=>d.value))*1.15, min=0;
  const x=i=>p.l+(values.length===1?iw/2:i/(values.length-1)*iw), y=v=>p.t+ih-(v-min)/(max-min)*ih;
  let grid=''; for(let i=0;i<=4;i++){let gy=p.t+i*ih/4, val=max*(1-i/4);grid+=`<line class="chart-grid" x1="${p.l}" x2="${w-p.r}" y1="${gy}" y2="${gy}"/><text class="chart-label" x="${p.l-8}" y="${gy+3}" text-anchor="end">${fmt(val)}</text>`;}
  const pts=values.map((d,i)=>`${x(i)},${y(d.value)}`).join(' ');
  const labels=values.map((d,i)=>i===0||i===values.length-1||i%Math.max(1,Math.floor(values.length/6))===0?`<text class="chart-label" x="${x(i)}" y="${h-9}" text-anchor="middle">${d.label}</text>`:'').join('');
  const dots=values.map((d,i)=>`<circle class="${opts.history?'history-dot':'chart-point'}" cx="${x(i)}" cy="${y(d.value)}" r="3.4"><title>${d.label}: ${fmt(d.value)} ${opts.unit||'cases'}</title></circle>`).join('');
  el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${opts.aria||'Data chart'}">${grid}<polyline class="${opts.history?'history-line':'chart-line'}" points="${pts}"/>${dots}${labels}</svg>`;
}
function drawForecast(values, selected){
 const el=$('#forecastChart'); if(!values.length){el.innerHTML='<div class="loading">No model forecast available.</div>';return;}
 const w=760,h=250,p={l:50,r:18,t:18,b:39},iw=w-p.l-p.r,ih=h-p.t-p.b,max=Math.max(1,...values.map(x=>x.predicted_cases))*1.18;
 const x=i=>p.l+i/(values.length-1)*iw,y=v=>p.t+ih-v/max*ih;
 let grid='';for(let i=0;i<=4;i++){let yy=p.t+i*ih/4;grid+=`<line class="chart-grid" x1="${p.l}" x2="${w-p.r}" y1="${yy}" y2="${yy}"/><text class="chart-label" x="${p.l-8}" y="${yy+3}" text-anchor="end">${fmt(max*(1-i/4))}</text>`;}
 const bars=values.map((d,i)=>{let bh=ih-y(d.predicted_cases)+p.t;return `<rect class="bar ${d.horizon===selected?'selected':''}" x="${x(i)-13}" y="${y(d.predicted_cases)}" width="26" height="${bh}" rx="4"><title>Horizon ${d.horizon}: ${fmt(d.predicted_cases)} predicted cases · ${dateFmt(d.date)}</title></rect><text class="chart-label" x="${x(i)}" y="${h-10}" text-anchor="middle">${d.horizon}w</text>`;}).join('');
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Predicted dengue cases for horizons zero through twelve weeks">${grid}${bars}</svg>`;
}
function renderFactors(factors){const el=$('#factorList');if(!factors.length){el.innerHTML='<p class="small-note">No feature-importance record is available for this horizon.</p>';return;}const max=Math.max(...factors.map(f=>f.importance),.0001);el.innerHTML=factors.map(f=>`<div class="factor-row"><span class="factor-name">${escapeHtml(f.name)}</span><span class="factor-value">${(f.importance*100).toFixed(1)}%</span><div class="factor-track"><div class="factor-fill" style="width:${Math.max(2,f.importance/max*100)}%"></div></div></div>`).join('');}
function renderKPIs(d){$('#kpiGrid').innerHTML=`<article class="kpi"><div class="kpi-label">PREDICTED CITY TOTAL</div><div class="kpi-value kpi-accent">${fmt(d.predicted_total_cases)}</div><div class="kpi-sub">Expected cases · ${escapeHtml(d.horizon_label)}</div></article><article class="kpi"><div class="kpi-label">LATEST REPORTED TOTAL</div><div class="kpi-value">${fmt(d.actual_latest_week_cases)}</div><div class="kpi-sub">Observed in dataset · ${dateFmt(d.latest_observation)}</div></article><article class="kpi"><div class="kpi-label">WARDS IN REGION</div><div class="kpi-value">${fmt(d.ward_count)}</div><div class="kpi-sub">Actual ward identifiers in dataset</div></article><article class="kpi"><div class="kpi-label">HIGH-PRIORITY WARDS</div><div class="kpi-value">${fmt(d.priority_1_count)}</div><div class="kpi-sub">Top 10% by predicted cases in this city</div></article>`;}
function renderWards(wards){state.wards=wards;const q=$('#wardSearch').value.trim().toLowerCase();const filtered=wards.filter(w=>w.ward_id.toLowerCase().includes(q));$('#wardRows').innerHTML=filtered.map((w,i)=>{const c=w.priority==='Priority 1'?'p1':w.priority==='Priority 2'?'p2':'monitor';return `<tr><td class="rank">${i+1}</td><td class="ward-name">${escapeHtml(w.ward_id)}</td><td class="estimate">${fmt(w.predicted_cases)}</td><td>${fmt(w.last_reported_cases)}</td><td><span class="priority ${c}">${w.priority}</span> <span class="muted">${fmt(w.percentile)}th pct.</span></td><td>${fmt(w.rainfall_mm)}</td><td>${Number(w.water_logging_risk_index).toFixed(2)}</td></tr>`;}).join('')||'<tr><td colspan="7" class="loading">No matching wards.</td></tr>';$('#wardCount').textContent=`Showing ${filtered.length} of ${wards.length} wards · sorted by predicted cases`;
}
function renderModel(d){const m=d.test_metrics||{};const rows=[['Forecast model',d.best_model],['Training / test split','Train before 2023 · test 2023 onward'],['Evaluation MAE',m.MAE==null?'Not available':fmt(m.MAE)],['Evaluation RMSE',m.RMSE==null?'Not available':fmt(m.RMSE)],['Evaluation R²',m.R2==null?'Not available':Number(m.R2).toFixed(3)],['Dataset period',`${dateFmt(d.data_period.start)} – ${dateFmt(d.data_period.end)}`],['Model artifact',`model_h${d.horizon}.joblib`]];$('#modelDetails').innerHTML=rows.map(r=>`<div class="detail-row"><span>${r[0]}</span><b>${escapeHtml(String(r[1]))}</b></div>`).join('');}
function escapeHtml(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function loadDashboard(){const city=state.city||$('#citySelect').value;const horizon=Number($('#horizonSelect').value);if(!city)return;state.city=city;state.horizon=horizon;$('#applyBtn').disabled=true;$('#applyBtn').textContent='Loading model…';try{const d=await api(`/api/dashboard?city=${encodeURIComponent(city)}&horizon=${horizon}`);state.data=d;setConnection(true,`${d.ward_count} wards · ${d.best_model}`);$('#bannerText').textContent=`${d.horizon_label} for ${d.city}. Last source observation: ${dateFmt(d.latest_observation)}. Forecast target: ${dateFmt(d.forecast_date)}.`;$('#forecastCaption').textContent=`${d.city} · selected model horizon ${horizon} · target ${dateFmt(d.forecast_date)}`;$('#wardCaption').textContent=`${d.horizon_label} · target ${dateFmt(d.forecast_date)} · ranked by model-predicted cases`;
 renderKPIs(d);drawForecast(d.forecast_by_horizon,horizon);drawLineChart($('#historyChart'),d.historical.map(x=>({label:x.date.slice(5),value:x.cases})),{history:true,aria:'Historical reported dengue cases'});$('#historyRange').textContent=`${d.historical.length} weekly observations`;renderFactors(d.feature_importance);renderWards(d.wards);renderModel(d);$('#noticeText').textContent=d.notice;$('#exportBtn').disabled=false;
 }catch(e){setConnection(false,e.message);$('#dataBanner').style.background='#fff1ef';$('#dataBanner').style.borderColor='#f3cfca';$('#dataBanner b').textContent='Unable to load model predictions';$('#bannerText').textContent=e.message;toast(`API error: ${e.message}`);}finally{$('#applyBtn').disabled=false;$('#applyBtn').innerHTML='Update forecast <span>→</span>';}}
function exportCSV(){if(!state.wards.length){toast('No ward results to export.');return;}const cols=['ward_id','predicted_cases','last_reported_cases','priority','percentile','rainfall_mm','temperature_c','humidity_pct','population_density_sqkm','water_logging_risk_index','sanitation_score'];const lines=[cols.join(','),...state.wards.map(w=>cols.map(c=>JSON.stringify(w[c]??'')).join(','))];const blob=new Blob([lines.join('\n')],{type:'text/csv;charset=utf-8;'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`dengue_${state.city.replaceAll(' ','_')}_h${state.horizon}_forecast.csv`;a.click();URL.revokeObjectURL(url);}
async function init(){try{const health=await api('/api/health');setConnection(true,`${health.models_loaded} saved models · ${health.wards} wards`);$('#citySelect').innerHTML=health.cities.map(c=>`<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');state.city=health.cities[0];$('#subheadDate');$('#refreshBtn').addEventListener('click',loadDashboard);$('#applyBtn').addEventListener('click',loadDashboard);$('#citySelect').addEventListener('change',()=>{state.city=$('#citySelect').value;loadDashboard();});$('#horizonSelect').addEventListener('change',loadDashboard);$('#wardSearch').addEventListener('input',()=>renderWards(state.wards));$('#exportBtn').addEventListener('click',exportCSV);await loadDashboard();}catch(e){setConnection(false,e.message);$('#bannerText').textContent=`Could not connect to backend: ${e.message}. Start the Python server using the README instructions.`;$('#dataBanner').style.background='#fff1ef';$('#dataBanner').style.borderColor='#f3cfca';}}
document.addEventListener('DOMContentLoaded',init);

/* ================= Risk prediction engine UI ================= */
const rk = { h: 3, ready: false };
function rainLagChart(series, mult){
  const w=700,h=170,p={l:38,r:10,t:14,b:26},iw=w-p.l-p.r,ih=h-p.t-p.b,max=Math.max(10,...series.map(d=>d.mm))*1.15,n=series.length,bw=iw/n*.62;
  const x=i=>p.l+(i+.5)*iw/n,y=v=>p.t+ih-v/max*ih;
  let g='';for(let i=0;i<=3;i++){const yy=p.t+i*ih/3;g+=`<line class="chart-grid" x1="${p.l}" x2="${w-p.r}" y1="${yy}" y2="${yy}"/><text class="chart-label" x="${p.l-6}" y="${yy+3}" text-anchor="end">${Math.round(max*(1-i/3))}</text>`;}
  const bars=series.map((d,i)=>`<rect class="lag-bar ${i>=n-4?'recent':''}" x="${x(i)-bw/2}" y="${y(d.mm)}" width="${bw}" height="${p.t+ih-y(d.mm)}" rx="3"><title>${d.date}: ${d.mm} mm</title></rect><text class="chart-label" x="${x(i)}" y="${h-8}" text-anchor="middle">${d.date.slice(5)}</text>`).join('');
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Rainfall in the last 8 weeks">${g}${bars}</svg>`;
}
function wardCard(w, rank){
  const act = w.actual_cases==null ? '' : ` · actual <b>${w.actual_cases}</b>`;
  return `<article class="wcard rk-${w.risk}"><div class="wcard-h"><b>#${rank} ${escapeHtml(w.ward_id)}</b><span class="chip">${w.risk.toUpperCase()}</span></div>
  <div class="num">${fmt(w.predicted_cases)} <small>expected cases/week${act}</small></div>
  <ul class="drv">${w.drivers.slice(0,3).map(d=>`<li class="${d.level}"><b>${escapeHtml(d.label)}</b> — ${escapeHtml(d.detail)}</li>`).join('')}</ul></article>`;
}
async function runRisk(){
  const out=$('#riskOut'), btn=$('#rGo'); btn.disabled=true; btn.textContent='Predicting…';
  const q=new URLSearchParams({city:$('#rCity').value,as_of:$('#rDate').value,horizon:rk.h,rain_mult:$('#rRain').value});
  try{
    const d=await api('/api/risk?'+q);
    rk.last=d; if(typeof refreshInsights==='function') refreshInsights();
    $('#rDate').value=d.origin_date; $('#rDate').min=d.date_range.min; $('#rDate').max=d.date_range.max;
    const top=d.wards.slice(0,3).map(w=>w.ward_id).join(', ');
    const msgs={Critical:'Act now: deploy larvicide, fogging and bed/saline planning for the wards below.',High:'Prepare: target drains and waste hotspots in the top wards this week.',Medium:'Watch: increase inspections in the highest-ranked wards.',Low:'No outbreak signal in this window. Keep routine surveillance.'};
    out.innerHTML=`<div class="risk-hero">
      <div class="risk-big rk-${d.city_risk}"><small>${escapeHtml(d.city.toUpperCase())} · ${d.horizon}-WEEK OUTLOOK</small><b>${d.city_risk}</b><span>${msgs[d.city_risk]}</span></div>
      <div class="risk-side"><div class="risk-counts">${['Critical','High','Medium','Low'].map(k=>`<div class="rc rk-${k}"><b>${d.counts[k]}</b><span>${k.toUpperCase()}</span></div>`).join('')}</div>
      <div class="risk-cmp"><span>From<br><b>${dateFmt(d.origin_date)}</b></span><span>Predicts week of<br><b>${dateFmt(d.target_date)}</b></span><span>Expected cases<br><b>${fmt(d.city_expected_cases)}</b></span>${d.backtest?`<span title="${(d.backtest_warning||'').replace(/"/g,'')}">Actually reported (in-sample ⓘ)<br><b>${fmt(d.actual_total)}</b></span>`:`<span>Actual<br><b>not in data</b></span>`}</div></div>
      <div class="lag-box"><h4>Rainfall, last 8 weeks${d.rain_mult!==1?` (recent 4 wks ×${d.rain_mult})`:''}</h4>${rainLagChart(d.rainfall_8w,d.rain_mult)}</div></div>
      <div class="ward-cards">${d.wards.slice(0,6).map((w,i)=>wardCard(w,i+1)).join('')}</div>
      <div class="more-row"><p class="risk-note">${escapeHtml(d.risk_note)} Model: ${escapeHtml(d.model)}. Research decision-support only, not an official alert.</p><button class="link-btn" data-go="wards">All ${d.wards.length} wards →</button></div>`;
  }catch(e){ out.innerHTML=`<div class="risk-err"><b>Prediction failed.</b> ${escapeHtml(e.message)}</div>`; }
  finally{ btn.disabled=false; btn.innerHTML='Predict risk <span>→</span>'; }
}
async function initRisk(){
  try{
    const h=await api('/api/health');
    $('#rCity').innerHTML=h.cities.map(c=>`<option>${escapeHtml(c)}</option>`).join('');
    $('#rDate').value='2025-08-04';
    $('#rHorizon').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;rk.h=+b.dataset.h;document.querySelectorAll('#rHorizon button').forEach(x=>x.classList.toggle('on',x===b));runRisk();});
    document.querySelectorAll('.seg-presets button').forEach(b=>b.addEventListener('click',()=>{$('#rDate').value=b.dataset.d;runRisk();}));
    $('#rRain').addEventListener('input',()=>{const v=+$('#rRain').value;$('#rRainVal').textContent=v===1?'×1.0 (as recorded)':`×${v.toFixed(1)}`;});
    $('#rRain').addEventListener('change',runRisk);
    $('#rCity').addEventListener('change',runRisk); $('#rDate').addEventListener('change',runRisk); $('#rGo').addEventListener('click',runRisk);
    runRisk();
  }catch(e){ $('#riskOut').innerHTML=`<div class="risk-err"><b>Cannot reach the model API.</b> Start it with <code>python app.py</code> and open http://127.0.0.1:5000 (not the HTML file directly). ${escapeHtml(e.message)}</div>`; }
}
document.addEventListener('DOMContentLoaded',initRisk);

/* ================= page router ================= */
const PAGES={home:'Risk prediction',map:'Risk map',alerts:'Alerts',actions:'Action plan',ask:'Ask Dengue Watch',forecast:'Forecasts & history',wards:'Ward explorer',method:'Model & data',accuracy:'Model accuracy'};
function showPage(){
  let pg=(location.hash||'#home').slice(1); if(!PAGES[pg]) pg='home';
  document.querySelectorAll('[data-page]').forEach(el=>el.classList.toggle('hide',el.dataset.page!=='all'&&el.dataset.page!==pg));
  document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===pg));
  $('#pageTitle').textContent=PAGES[pg]; window.scrollTo(0,0);
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-go]');if(b){location.hash='#'+b.dataset.go;}});
window.addEventListener('hashchange',showPage);
document.addEventListener('DOMContentLoaded',showPage);

/* ================= Alerts, Action plan, Ask (generated from model output) ================= */
const store={get(k,f){try{return JSON.parse(localStorage.getItem(k))??f}catch(e){return f}},set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}};
const SEV={Critical:'rk-Critical',High:'rk-High',Medium:'rk-Medium',Low:'rk-Low'};
let readAlerts=new Set(store.get('dw.read',[])), doneTasks=new Set(store.get('dw.done',[]));
const ctxKey=d=>`${d.city}|${d.origin_date}|${d.horizon}`;
const topDriver=w=>(w.drivers.find(x=>x.level==='high')||w.drivers[0]);
function buildAlerts(d){
  const out=[],k=ctxKey(d),hi=d.wards.filter(w=>w.risk==='Critical'||w.risk==='High');
  if(d.city_risk!=='Low') out.push({id:k+'|city',sev:d.city_risk,title:`${d.city} outlook: ${d.city_risk}`,text:`${hi.length} of ${d.wards.length} wards are High or Critical for the week of ${dateFmt(d.target_date)}. Expected city total: ${fmt(d.city_expected_cases)} cases.`});
  const surge=d.wards.filter(w=>w.drivers.some(x=>x.label==='Rainfall surge'));
  if(surge.length) out.push({id:k+'|rain',sev:'High',title:`Rainfall surge in ${surge.length} ward${surge.length>1?'s':''}`,text:`Heavy rain in the last 4 weeks starts the 1–2 week mosquito breeding clock. Start drain and container checks now (${surge.slice(0,3).map(w=>w.ward_id).join(', ')}${surge.length>3?'…':''}).`});
  hi.slice(0,8).forEach(w=>{const t=topDriver(w);out.push({id:k+'|'+w.ward_id,sev:w.risk,ward:w.ward_id,title:`${w.ward_id} is ${w.risk}`,text:`${fmt(w.predicted_cases)} expected cases/week. Main driver: ${t.label.toLowerCase()} — ${t.detail}.`});});
  if(!out.length) out.push({id:k+'|ok',sev:'Low',title:'No outbreak signal',text:'All wards are Low or Medium in this window. Keep routine surveillance.'});
  return out;
}
function buildActions(d){
  const k=ctxKey(d),hi=d.wards.filter(w=>w.risk==='Critical'||w.risk==='High'),t=hi.length?hi:d.wards.slice(0,2),A=[];
  const wl=d.wards.slice(0,6).sort((a,b)=>b.water_logging_risk_index-a.water_logging_risk_index)[0];
  if(t[0]) A.push({id:k+'|c1',p:1,title:'Standing-water inspection',where:t[0].ward_id,owner:'Field team A',due:'Within 48 h'});
  if(t[1]) A.push({id:k+'|c2',p:1,title:'Larval survey and larvicide in drains',where:t[1].ward_id,owner:'Vector control',due:'Within 3 days'});
  if(hi.length) A.push({id:k+'|c3',p:1,title:'Community alert: empty containers, cover water tanks',where:hi.slice(0,3).map(w=>w.ward_id).join(', '),owner:'Outreach',due:'Within 3 days'});
  if(wl&&wl.water_logging_risk_index>=0.7) A.push({id:k+'|c4',p:2,title:'Request drain-clearing crews',where:wl.ward_id,owner:'City services',due:'Within 4 days'});
  if(d.city_risk==='Critical'||d.city_risk==='High') A.push({id:k+'|c5',p:2,title:'Hospital readiness: beds, saline and test kits',where:`${d.city} hospitals`,owner:'Clinical lead',due:'Within 5 days'});
  A.push({id:k+'|c6',p:3,title:'Re-run this forecast next week and compare',where:d.city,owner:'Analyst',due:'Weekly'});
  return A;
}
function renderAlerts(){
  const d=rk.last; if(!d) return; const L=buildAlerts(d);
  $('#alertsSub').textContent=`${d.city} · from ${dateFmt(d.origin_date)} · ${d.horizon}-week window`;
  $('#alertList').innerHTML=L.map(a=>`<div class="al ${SEV[a.sev]} ${readAlerts.has(a.id)?'read':''}"><div class="body"><b>${escapeHtml(a.title)}</b> <span class="chip">${a.sev.toUpperCase()}</span><p>${escapeHtml(a.text)}</p></div><button data-read="${escapeHtml(a.id)}">${readAlerts.has(a.id)?'Mark unread':'Mark read'}</button></div>`).join('');
  document.querySelectorAll('[data-read]').forEach(b=>b.addEventListener('click',()=>{const id=b.dataset.read;readAlerts.has(id)?readAlerts.delete(id):readAlerts.add(id);store.set('dw.read',[...readAlerts]);renderAlerts();}));
  const n=L.filter(a=>!readAlerts.has(a.id)&&a.sev!=='Low').length; const el=$('#navAlerts'); el.textContent=n||''; el.classList.toggle('zero',!n);
}
function renderActions(){
  const d=rk.last; if(!d) return; const A=buildActions(d),done=A.filter(a=>doneTasks.has(a.id)).length,pct=Math.round(done/A.length*100);
  $('#actionsTitle').textContent=`${d.city} · actions for the ${d.horizon}-week window`;
  $('#progText').textContent=`${done}/${A.length}`; $('#progRing').style.background=`conic-gradient(var(--teal) 0 ${pct}%,var(--line) ${pct}% 100%)`;
  $('#actionList').innerHTML=A.map(a=>`<button class="action ${doneTasks.has(a.id)?'done':''}" data-id="${escapeHtml(a.id)}"><span class="check">✓</span><span class="action-body"><strong>${escapeHtml(a.title)}</strong><span class="meta"><span>⌖ ${escapeHtml(a.where)}</span><span>👤 ${a.owner}</span><span>◷ ${a.due}</span></span></span><span class="prio p${a.p}">${['','PRIORITY','SOON','ROUTINE'][a.p]}</span></button>`).join('');
  document.querySelectorAll('.action').forEach(b=>b.addEventListener('click',()=>{const id=b.dataset.id;doneTasks.has(id)?doneTasks.delete(id):doneTasks.add(id);store.set('dw.done',[...doneTasks]);renderActions();}));
  const open=A.filter(a=>!doneTasks.has(a.id)).length; const el=$('#navActions'); el.textContent=open||''; el.classList.toggle('zero',!open);
}
$('#markAllRead').addEventListener('click',()=>{if(!rk.last)return;buildAlerts(rk.last).forEach(a=>readAlerts.add(a.id));store.set('dw.read',[...readAlerts]);renderAlerts();toast('All alerts marked as read');});

function refreshInsights(){renderAlerts();renderActions();}
