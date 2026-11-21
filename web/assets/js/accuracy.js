'use strict';
(function(){
  const $=s=>document.querySelector(s), pct=v=>(v*100).toFixed(1)+'%';
  let D=null;
  const cur=()=>{const h=$('#accH').value,t=+$('#accT').value;return{h,t,row:D.horizons[h].find(r=>r.t===t)};};
  function render(){
    if(!D) return; const {h,t,row}=cur(); $('#accTVal').textContent=t;
    $('#accKpi').innerHTML=[['PRECISION',row.precision,'Alarms that were real outbreaks'],['RECALL',row.recall,'Real outbreaks that were caught'],['F1 SCORE',row.f1,'Balance of precision and recall']]
      .map((k,i)=>`<article class="kpi"><div class="kpi-label">${k[0]}</div><div class="kpi-value ${i==2?'kpi-accent':''}">${pct(k[1])}</div><div class="kpi-sub">${k[2]}</div></article>`).join('')
      +`<article class="kpi"><div class="kpi-label">TEST SAMPLES</div><div class="kpi-value">${D.n_test.toLocaleString()}</div><div class="kpi-sub">${D.n_events} real outbreak ward-weeks</div></article>`;
    $('#accCm').innerHTML=`<span></span><span class="hd">PREDICTED<br>OUTBREAK</span><span class="hd">PREDICTED<br>NO OUTBREAK</span>
      <span class="hd">ACTUAL<br>OUTBREAK</span><div class="cell good"><b>${row.tp}</b><span>TRUE POSITIVE</span></div><div class="cell bad"><b>${row.fn}</b><span>MISSED (FN)</span></div>
      <span class="hd">ACTUAL<br>NO OUTBREAK</span><div class="cell bad"><b>${row.fp}</b><span>FALSE ALARM (FP)</span></div><div class="cell good"><b>${row.tn}</b><span>TRUE NEGATIVE</span></div>`;
    // chart
    const hs=Object.keys(D.horizons), w=760,H=250,p={l:40,r:14,t:14,b:34},iw=w-p.l-p.r,ih=H-p.t-p.b,gw=iw/hs.length,bw=gw/4;
    let g='';for(let i=0;i<=4;i++){const y=p.t+i*ih/4;g+=`<line class="chart-grid" x1="${p.l}" x2="${w-p.r}" y1="${y}" y2="${y}"/><text class="chart-label" x="${p.l-6}" y="${y+3}" text-anchor="end">${100-i*25}%</text>`;}
    const bars=hs.map((k,i)=>{const r=D.horizons[k].find(x=>x.t===t),x0=p.l+i*gw+gw*.12,sel=k===h?' sel':'';
      return [['p','precision'],['r','recall'],['f','f1']].map((m,j)=>{const v=r[m[1]],bh=v*ih;return `<rect class="acc-bar-${m[0]}${sel}" x="${x0+j*bw}" y="${p.t+ih-bh}" width="${bw-1}" height="${bh}" rx="2"><title>+${k}w ${m[1]}: ${pct(v)}</title></rect>`}).join('')+`<text class="chart-label" x="${x0+1.5*bw}" y="${H-10}" text-anchor="middle">${k}w</text>`;}).join('');
    $('#accChart').innerHTML=`<svg viewBox="0 0 ${w} ${H}" role="img" aria-label="Precision, recall and F1 by horizon">${g}${bars}</svg>`;
    $('#accRows').innerHTML=hs.map(k=>{const r=D.horizons[k].find(x=>x.t===t);return `<tr class="${k===h?'acc-sel':''}"><td class="ward-name">${k==='0'?'Nowcast':'+'+k+' wk'}</td><td class="estimate">${pct(r.precision)}</td><td class="estimate">${pct(r.recall)}</td><td class="estimate">${pct(r.f1)}</td><td>${r.tp}</td><td>${r.fp}</td><td>${r.fn}</td><td>${r.tn}</td></tr>`}).join('');
  }
  async function init(){
    try{
      D=window.ACC_DATA||await (await fetch('classification_metrics.json')).json();
      $('#accDef').textContent=`${D.event_definition}. Model: ${D.model}. Test period ${D.test_period}. An alarm is raised when predicted cases ≥ the threshold.`;
      $('#accH').innerHTML=Object.keys(D.horizons).map(k=>`<option value="${k}" ${k==='3'?'selected':''}>${k==='0'?'Latest-week nowcast':k+' week'+(k==='1'?'':'s')+' ahead'}</option>`).join('');
      $('#accT').value=D.default_threshold; $('#accH').addEventListener('change',render); $('#accT').addEventListener('input',render); render();
    }catch(e){ $('#accDef').textContent='Could not load classification_metrics.json: '+e.message; }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
