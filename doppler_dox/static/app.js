'use strict';
const $ = id => document.getElementById(id);
const S = { token: '', events: [], points: [], fit: null, view: null, result: null, config: {}, selected: 0, duration: 0, tracks: [], audioName: '', trackName: '', busy: false };
const palette = [[7,18,32],[22,42,67],[60,60,104],[126,73,113],[204,118,77],[247,218,139],[255,249,203]];
let pollTimer;
function color(v) { const x = Math.max(0,Math.min(1,v))*(palette.length-1), i = Math.min(palette.length-2,Math.floor(x)), f=x-i; return palette[i].map((a,j)=>Math.round(a+(palette[i+1][j]-a)*f)); }
function notice(text,error=false) { $('notice').textContent=text; $('notice').classList.toggle('error',error); }
async function api(path, data, binary=false) {
  const options = data === undefined ? {} : {method:'POST',headers:{'X-Workbench-Token':S.token,'Content-Type':binary?'application/octet-stream':'application/json'},body:binary?data:JSON.stringify(data)};
  const response=await fetch(path,options); let payload;
  try { payload=await response.json(); } catch { throw new Error(`Server returned ${response.status}. Is the workbench still running?`); }
  if(!response.ok) throw new Error(payload.error||`Request failed (${response.status})`);
  return payload;
}
function guarded(fn) { return async event => { try { await fn(event); } catch(e) { notice(e.message,true); } }; }
function el(tag,text,cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function busy(value) { S.busy=value; document.querySelectorAll('button,input,select').forEach(n=>{n.disabled=value;}); }
function viewBounds() { return Object.fromEntries(new FormData($('view-form')).entries().map(([k,v])=>[k,Number(v)])); }
async function loadView(bounds) {
  if(bounds) for(const [k,v] of Object.entries(bounds)) {const n=$(`view-${k}`);if(n)n.value=Number(v).toFixed(2);}
  const query=new URLSearchParams(viewBounds()); S.view=await api(`/api/view?${query}`);
  S.duration=S.view.duration; $('duration').textContent=`${S.duration.toFixed(1)} s · 0.5 Hz BINS`;
  $('plot-empty').hidden=true; drawSpectrogram();
}
function axes(ctx,w,h,view,box) {
  ctx.font='12px ui-monospace, monospace'; ctx.fillStyle='#8ba4b8'; ctx.strokeStyle='#6a809528'; ctx.lineWidth=1;
  for(let i=0;i<=5;i++) {const x=box.x+i/5*box.w;ctx.beginPath();ctx.moveTo(x,box.y);ctx.lineTo(x,box.y+box.h);ctx.stroke();ctx.fillText((view.start+i/5*(view.end-view.start)).toFixed(0),x-12,h-10);}
  for(let i=0;i<=4;i++) {const y=box.y+i/4*box.h;ctx.beginPath();ctx.moveTo(box.x,y);ctx.lineTo(box.x+box.w,y);ctx.stroke();ctx.fillText((view.high-i/4*(view.high-view.low)).toFixed(0),3,y+4);}
}
function drawLine(ctx,points,view,box,stroke,width=2) {
  ctx.save();ctx.beginPath();ctx.rect(box.x,box.y,box.w,box.h);ctx.clip();ctx.beginPath();let started=false;
  for(const [t,f] of points) { const x=box.x+(t-view.start)/(view.end-view.start)*box.w, y=box.y+(view.high-f)/(view.high-view.low)*box.h; if(!started){ctx.moveTo(x,y);started=true;} else ctx.lineTo(x,y); }
  ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();ctx.restore();
}
function drawSpectrogram() {
  const canvas=$('spectrogram'),ctx=canvas.getContext('2d'),v=S.view;if(!v)return;
  const box={x:48,y:12,w:canvas.width-60,h:canvas.height-44}; S.plotBox=box;
  ctx.fillStyle='#080f18';ctx.fillRect(0,0,canvas.width,canvas.height);
  const bytes=Uint8Array.from(atob(v.pixels),c=>c.charCodeAt(0));
  const off=document.createElement('canvas');off.width=v.width;off.height=v.height;
  const ox=off.getContext('2d'),img=ox.createImageData(v.width,v.height);
  for(let y=0;y<v.height;y++)for(let x=0;x<v.width;x++){const n=((v.height-1-y)*v.width+x)*4,rgb=color(bytes[y*v.width+x]/255);img.data[n]=rgb[0];img.data[n+1]=rgb[1];img.data[n+2]=rgb[2];img.data[n+3]=255;}
  ox.putImageData(img,0,0);ctx.imageSmoothingEnabled=false;ctx.drawImage(off,box.x,box.y,box.w,box.h); axes(ctx,canvas.width,canvas.height,v,box);
  if(S.fit)drawLine(ctx,S.fit.model,v,box,'#eac477',3);
  drawLine(ctx,[...S.points].sort((a,b)=>a[0]-b[0]),v,box,'#82e5c1',1.7);
  ctx.save();ctx.beginPath();ctx.rect(box.x,box.y,box.w,box.h);ctx.clip();ctx.fillStyle='#a9ffe0';
  for(const [t,f]of S.points){ctx.beginPath();ctx.arc(box.x+(t-v.start)/(v.end-v.start)*box.w,box.y+(v.high-f)/(v.high-v.low)*box.h,3,0,Math.PI*2);ctx.fill();}ctx.restore();
  $('point-count').textContent=`${S.points.length} points`;
}
function showFit() {
  const f=S.fit;$('fit-detail').hidden=!f;if(!f)return;
  const dl=$('fit-values');dl.replaceChildren();
  for(const [label,value]of [['Fundamental',`${f.f0.toFixed(2)} Hz`],['Speed',`${f.speed_mps.toFixed(1)} m/s`],['Slant distance',`${f.distance_m.toFixed(0)} m`],['Received CPA',`${f.cpa_s.toFixed(2)} s`],['Fit RMS',`${f.rms_hz.toFixed(3)} Hz`]]){dl.append(el('dt',label),el('dd',value));}
  $('fit-warning').textContent=f.warnings.join(' ');$('save-event').disabled=S.events.length>=2;
}
async function focusEvent(event) {
  S.points=event.points.map(p=>[...p]);S.fit=event;showFit();
  const times=event.points.map(p=>p[0]),fs=event.points.map(p=>p[1]);
  await loadView({start:Math.max(0,Math.min(...times)-4),end:Math.min(S.duration,Math.max(...times)+4),low:Math.max(20,Math.min(...fs)*.85),high:Math.min(800,Math.max(...fs)*1.15)});
}
function renderEvents() {
  const list=$('event-list');list.replaceChildren();$('event-count').textContent=`${S.events.length} / 2`;
  if(!S.events.length){const n=el('div','No events measured.','empty-events');n.append(el('p','Trace a ridge and fit its curve to reveal speed, slant range and received CPA.'));list.append(n);}
  S.events.forEach((e,i)=>{
    const card=el('div',undefined,'event'),head=el('div',undefined,'event-head'),name=el('strong',`EVENT ${String(i+1).padStart(2,'0')}`),remove=el('button','×');remove.type='button';remove.setAttribute('aria-label',`Remove event ${i+1}`);
    remove.onclick=guarded(async ev=>{ev.stopPropagation(); const next=S.events.filter((_,j)=>j!==i);await syncEvents(next);notice('Event removed.');});head.append(name,remove);card.append(head);
    const values=el('div',undefined,'event-data');for(const [a,b]of [['Speed',`${e.speed_mps.toFixed(1)} m/s`],['Slant range',`${(e.distance_m/1000).toFixed(2)} km`],['Received CPA',`${e.cpa_s.toFixed(1)} s`],['RMS',`${e.rms_hz.toFixed(3)} Hz`]]){const d=el('div');d.append(el('small',a),el('b',b));values.append(d);}card.append(values);
    card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label',`Inspect event ${i+1}`);card.onclick=guarded(()=>focusEvent(e));card.onkeydown=ev=>{if(ev.key==='Enter')card.click();};list.append(card);
  });
  if(S.events.length===2){const sorted=[...S.events].sort((a,b)=>a.cpa_s-b.cpa_s);list.append(el('div',`Δt = ${(sorted[1].cpa_s-sorted[0].cpa_s).toFixed(2)} s · shared clock`,'event-offset'));}
  showFit();
}
async function syncEvents(events) { const d=await api('/api/events',{events,sound_speed:Number($('search-form').elements.sound_speed.value)});S.events=d.events;invalidate();renderEvents(); }
function invalidate(){S.result=null;$('results').hidden=true;}
function setConfig(config){for(const [key,value]of Object.entries(config)){const n=$('search-form').elements.namedItem(key);if(!n)continue;if(n.type==='checkbox')n.checked=Boolean(value);else n.value=value;}S.config={...config};}
function getConfig(){const form=$('search-form'),data={};for(const n of form.elements){if(!n.name)continue;if(n.type==='checkbox')data[n.name]=n.checked;else if(n.value.trim()!=='')data[n.name]=n.type==='number'?Number(n.value):n.value.trim();}return data;}
async function getTracks(){const d=await api('/api/track-map');S.tracks=d.tracks;}
function download(name,data,type='application/json'){const blob=new Blob([typeof data==='string'?data:JSON.stringify(data,null,2)],{type});const url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}
function mapPoint(lat,lon,box){return [box.x+(lon-S.config.west)/(S.config.east-S.config.west)*box.w,box.y+(S.config.north-lat)/(S.config.north-S.config.south)*box.h];}
function drawMap(){
  const canvas=$('map'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,box={x:78,y:30,w:w-108,h:h-85};ctx.fillStyle='#0b1520';ctx.fillRect(0,0,w,h);ctx.font='12px ui-monospace,monospace';
  for(let i=0;i<=4;i++){const x=box.x+i*box.w/4,y=box.y+i*box.h/4;ctx.strokeStyle='#294052';ctx.beginPath();ctx.moveTo(x,box.y);ctx.lineTo(x,box.y+box.h);ctx.moveTo(box.x,y);ctx.lineTo(box.x+box.w,y);ctx.stroke();ctx.fillStyle='#8199ab';ctx.fillText((S.config.west+i*(S.config.east-S.config.west)/4).toFixed(3),x-27,h-20);ctx.fillText((S.config.north-i*(S.config.north-S.config.south)/4).toFixed(3),4,y+4);}
  ctx.save();ctx.beginPath();ctx.rect(box.x,box.y,box.w,box.h);ctx.clip();
  for(const track of S.tracks){ctx.strokeStyle='#49768c88';ctx.lineWidth=2;ctx.beginPath();track.points.forEach(([lat,lon],i)=>{const [x,y]=mapPoint(lat,lon,box);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();}
  const heat=S.result.heatmap,lo=Math.min(...heat.map(x=>x.score)),hi=Math.max(...heat.map(x=>x.score));
  for(const p of heat){const [x,y]=mapPoint(p.latitude,p.longitude,box),value=(p.score-lo)/Math.max(.001,hi-lo);ctx.fillStyle=`rgba(${color(value).join(',')},.65)`;ctx.beginPath();ctx.arc(x,y,9,0,Math.PI*2);ctx.fill();}
  S.result.candidates.forEach((p,i)=>{const [x,y]=mapPoint(p.latitude,p.longitude,box);ctx.fillStyle=i===S.selected?'#82e5c1':'#c8d6dd';ctx.strokeStyle='#0b1520';ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,y,i===S.selected?13:9,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.fillStyle='#09201c';ctx.font='bold 12px ui-monospace,monospace';ctx.fillText(String(i+1),x-4,y+4);});ctx.restore();
}
function comparison(){
  const r=S.result.candidates[S.selected],canvas=$('comparison'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;ctx.fillStyle='#0b1520';ctx.fillRect(0,0,w,h);if(!r)return;
  S.events.slice().sort((a,b)=>a.cpa_s-b.cpa_s).forEach((event,i)=>{const points=event.points,fs=points.map(p=>p[1]),ts=points.map(p=>p[0]),model=r.curves[i],all=fs.concat(model.map(p=>p[1]));const low=Math.min(...all)-5,high=Math.max(...all)+5,view={start:Math.min(...ts),end:Math.max(...ts),low,high},box={x:55+i*w/S.events.length,y:30,w:w/S.events.length-85,h:h-65};ctx.font='11px ui-monospace,monospace';ctx.fillStyle='#8ba4b8';ctx.fillText(`EVENT ${i+1} · observed / predicted`,box.x,18);ctx.fillText(`${low.toFixed(0)}–${high.toFixed(0)} Hz`,box.x,h-12);ctx.strokeStyle='#294052';ctx.strokeRect(box.x,box.y,box.w,box.h);drawLine(ctx,points,view,box,'#82e5c1',2);drawLine(ctx,model,view,box,'#eac477',2);});
}
function chooseRank(index){S.selected=index;document.querySelectorAll('.rank-row').forEach((n,i)=>n.classList.toggle('active',i===index));const r=S.result.candidates[index];$('selected-rank').textContent=`RANK ${index+1}`;$('candidate-detail').textContent=`${r.tracks.join(' + ')} · ${r.latitude.toFixed(6)}, ${r.longitude.toFixed(6)} · shared clock shift ${r.clock_shift_s.toFixed(2)} s · recording start ${new Date(r.recording_start_epoch*1000).toISOString()} · event scores ${r.event_scores.map(s=>s.toFixed(3)).join(' / ')}`;drawMap();comparison();}
function renderResults(){
  const r=S.result;$('results').hidden=false;$('resolution').textContent=`${r.resolution_m||'—'} m LOCAL REFINEMENT`;
  const ranks=$('rank-list');ranks.replaceChildren();
  r.candidates.forEach((p,i)=>{const row=el('button',undefined,'rank-row'),copy=el('span');copy.append(el('strong',p.tracks.join(' + ')),el('small',`${p.latitude.toFixed(5)}, ${p.longitude.toFixed(5)}`));row.append(el('span',String(i+1).padStart(2,'0'),'rank-number'),copy,el('span',p.score.toFixed(2),'rank-score'));row.onclick=()=>chooseRank(i);ranks.append(row);});
  if(!r.candidates.length)ranks.append(el('p','No consistent candidate found. Broaden the bounds or check your input data.','help'));
  const c=r.counts;$('counts').textContent=`${c.grid_cells.toLocaleString()} cells · ${c.geometry_matches.toLocaleString()} geometry matches · ${c.timing_matches.toLocaleString()} timing matches · ${c.silence_rejected} silence rejections · ${c.shortlisted||0} scored coarse candidates. ${c.timing_candidates_not_scored||0} timing candidates omitted by the CPU shortlist.`;
  $('result-warnings').replaceChildren(...r.warnings.map(w=>el('li',w)));
  $('export-report').disabled=false;$('export-geojson').disabled=false;
  if(r.candidates.length)chooseRank(0);else{$('candidate-detail').textContent='';drawMap();$('comparison').getContext('2d').clearRect(0,0,1200,250);}
}
async function poll(){
  const d=await api('/api/state'),job=d.job;$('progress-label').textContent=job.phase;$('progress-value').textContent=`${Math.round(job.progress*100)}%`;$('progress').value=job.progress;
  if(job.status==='running'){pollTimer=setTimeout(()=>poll().catch(e=>{busy(false);notice(e.message,true);}),800);return;}
  busy(false);if(job.status==='error'){notice(job.phase,true);return;}
  if(d.result){S.result=d.result;renderResults();notice(d.result.candidates.length?`Search complete. ${d.result.candidates.length} flight assignment(s) ranked. Inspect the curve overlays and export your report.`:'Search complete: no consistent candidate found. Check bounds, coverage and measurement tolerances.');}
}
$('view-form').onsubmit=guarded(async e=>{e.preventDefault();await loadView();});
$('spectrogram').onclick=e=>{if(!S.view||S.busy)return;const canvas=$('spectrogram'),rect=canvas.getBoundingClientRect(),x=(e.clientX-rect.left)*canvas.width/rect.width,y=(e.clientY-rect.top)*canvas.height/rect.height,b=S.plotBox,v=S.view;if(x<b.x||x>b.x+b.w||y<b.y||y>b.y+b.h)return;S.points.push([v.start+(x-b.x)/b.w*(v.end-v.start),v.high-(y-b.y)/b.h*(v.high-v.low)]);S.fit=null;showFit();drawSpectrogram();};
$('undo').onclick=()=>{S.points.pop();S.fit=null;showFit();drawSpectrogram();};
$('clear-trace').onclick=()=>{S.points=[];S.fit=null;showFit();drawSpectrogram();};
$('auto-trace').onclick=guarded(async()=>{if(!S.view)throw new Error('Load audio first.');notice('Tracing the strongest continuous ridge in the current window…');const r=await api('/api/trace',viewBounds());S.points=r.points;S.fit=null;showFit();drawSpectrogram();notice('Ridge traced. Inspect the line, then fit the Doppler curve.');});
$('fit').onclick=guarded(async()=>{S.fit=await api('/api/fit',{points:S.points,sound_speed:Number($('search-form').elements.sound_speed.value)});showFit();drawSpectrogram();notice(`Curve fitted. RMS ${S.fit.rms_hz.toFixed(3)} Hz. ${S.fit.warnings.join(' ')}`);});
$('save-event').onclick=guarded(async()=>{if(!S.fit)throw new Error('Fit a trace first.');if(S.events.length>=2)throw new Error('Remove an event before adding another.');await syncEvents([...S.events,S.fit]);notice('Event saved. Trace another pass, or search one event with a known UTC recording start.');});
$('demo').onclick=guarded(async()=>{busy(true);notice('Rendering the fictional two-pass recording…');try{const d=await api('/api/demo',{});S.events=d.events;S.duration=d.duration;S.audioName='synthetic-demo.wav';S.trackName='demo-tracks.csv';setConfig(d.config);invalidate();renderEvents();await getTracks();await focusEvent(S.events[0]);$('audio-label').textContent=`Synthetic two-pass recording · ${d.duration} s`;$('tracks-label').textContent=`${d.tracks.tracks} synthetic propeller flights · ${d.tracks.positions} positions`;$('elevation-label').textContent='Demo uses flat elevation: 0 m.';$('download-tracks').hidden=false;notice(`Demo ready. Known fictional observer: ${d.truth.latitude.toFixed(5)}, ${d.truth.longitude.toFixed(5)}. Two events are already measured; run the search to test recovery.`);}finally{busy(false);showFit();}});
$('audio-file').onchange=guarded(async e=>{const file=e.target.files[0];if(!file)return;busy(true);notice('Decoding locally and calculating the spectrogram…');try{const d=await api('/api/audio',file,true);S.audioName=file.name;S.duration=d.duration;S.events=[];S.points=[];S.fit=null;invalidate();renderEvents();await loadView({start:0,end:Math.min(60,d.duration),low:40,high:600});$('audio-label').textContent=`${file.name} · ${d.duration.toFixed(1)} s`;notice('Recording loaded. Find a flyover and narrow the time/frequency window.');}finally{busy(false);}});
$('track-file').onchange=guarded(async e=>{const file=e.target.files[0];if(!file)return;const d=await api('/api/tracks',file,true);S.trackName=file.name;invalidate();await getTracks();$('tracks-label').textContent=`${file.name} · ${d.tracks} segments · ${d.excluded_jets} jet types excluded`;notice('Flight tracks loaded. Altitudes must use the same datum as the terrain.');});
$('elevation-file').onchange=guarded(async e=>{const file=e.target.files[0];if(!file)return;await api('/api/elevations',file,true);invalidate();$('elevation-label').textContent=`Terrain loaded: ${file.name}`;notice('Terrain samples loaded. Each candidate must have a sample within 2 km.');});
$('flat-elevation').onclick=guarded(async()=>{await api('/api/reset-elevations',{});invalidate();$('elevation-label').textContent='Using the flat elevation specified above.';$('elevation-file').value='';notice('Using flat observer elevation.');});
$('search-form').onsubmit=guarded(async e=>{e.preventDefault();S.config=getConfig();await api('/api/search',S.config);busy(true);invalidate();$('progress-wrap').hidden=false;notice('Searching local flight geometry and scoring with a shared clock…');await poll();});
$('export-report').onclick=guarded(async()=>{download('doppler-dox-report.json',await api('/api/export'));});
$('export-geojson').onclick=guarded(async()=>{download('doppler-dox-candidates.geojson',(await api('/api/export')).geojson);});
$('export-case').onclick=()=>download('doppler-dox-case.json',{audio:S.audioName||'recording.wav',tracks:S.trackName||'tracks.csv',events:S.events,config:S.config,output:'result.json'});
$('download-tracks').onclick=guarded(async()=>{const response=await fetch('/api/demo-tracks');if(!response.ok)throw new Error('Load the demo first.');download('demo-tracks.csv',await response.text(),'text/csv');});
(async()=>{try{const d=await api('/api/state');S.token=d.token;S.events=d.events;renderEvents();if(d.has_audio){await loadView();$('audio-label').textContent='Recording retained in this server session';}if(d.tracks){await getTracks();$('tracks-label').textContent=`${d.tracks} flight segments retained in this server session`;}if(d.job.status==='running'){busy(true);$('progress-wrap').hidden=false;await poll();}else if(d.result){notice('Prior results remain on the server. Export them, or run a new search with your bounds.');}}catch(e){notice(e.message,true);}})();
