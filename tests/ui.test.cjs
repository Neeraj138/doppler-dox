const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'../doppler_dox/static');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const source=fs.readFileSync(path.join(root,'app.js'),'utf8');
const leaflet=fs.readFileSync(path.join(root,'vendor/leaflet.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const idle={token:'test-session',status:'idle',has_example:true};
// Replay the public result from the actual original-recording validation.
const matched={status:'match',location:{latitude:40.873237513474734,longitude:-73.52247905065951},area:'Oyster Bay, New York',flyovers:2,note:'An experimental estimate, not a verified location.'};
async function app(responder=()=>idle){
 const dom=new JSDOM(html,{url:'http://127.0.0.1:8765/',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window;w.scrollTo=()=>{};const calls=[];
 w.fetch=async(url,options={})=>{calls.push({url,options});const payload=await responder(url,options,calls);return {ok:true,status:200,json:async()=>payload};};
 w.eval(leaflet);w.eval(source);await tick();await tick();
 return {dom,w,d:w.document,calls,close:()=>dom.window.close()};
}
function submit(w,form){form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));}

test('home exposes one upload and keeps analysis controls out of the main UI',async()=>{
 const a=await app();try{assert.equal(a.d.querySelectorAll('input[type=file]').length,1);assert.equal(a.d.querySelector('#analyze').disabled,true);assert.equal(a.d.querySelector('#upload-screen').hidden,false);assert.equal(a.d.querySelector('#context-screen').hidden,true);assert.equal(a.d.querySelector('#result-screen').hidden,true);assert.equal(a.d.querySelector('#example-wrap').hidden,false);assert.equal(a.d.querySelector('#view-form'),null);assert.equal(a.d.querySelector('#search-form'),null);}finally{a.close();}
});

test('real-result response produces an OSM pin, coordinates and a map link',async()=>{
 const a=await app(()=>({...idle,...matched}));try{assert.equal(a.d.querySelector('#result-screen').hidden,false);assert.match(a.d.querySelector('#coordinates').textContent,/40\.873238/);assert.match(a.d.querySelector('#open-map').href,/openstreetmap\.org\/\?mlat=40\.873237/);assert.ok(a.d.querySelector('#result-map .pin-icon'));assert.match(a.d.querySelector('#result-map').textContent,/OpenStreetMap/);}finally{a.close();}
});

test('file selection and submit invoke the automatic upload endpoint',async()=>{
 let analyzing=false;
 const a=await app((url,options)=>{if(url==='/api/simple/upload'){analyzing=true;return {status:'analyzing'};}return analyzing?{...idle,...matched}:idle;});
 try{const drop=new a.w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(drop,'dataTransfer',{value:{files:[{name:'friend.webm',size:1024,type:'video/webm'}]}});a.d.querySelector('#dropzone').dispatchEvent(drop);assert.equal(a.d.querySelector('#analyze').disabled,false);assert.equal(a.d.querySelector('#drop-title').textContent,'friend.webm');submit(a.w,a.d.querySelector('#upload-form'));await tick();await tick();assert.ok(a.calls.some(c=>c.url==='/api/simple/upload'));assert.equal(a.d.querySelector('#result-screen').hidden,false);assert.equal(a.calls.find(c=>c.url==='/api/simple/upload').options.headers['X-File-Name'],'friend.webm');}finally{a.close();}
});

test('missing time/area requests only the small context form',async()=>{
 const a=await app(()=>({...idle,status:'needs_context',recorded_at:null}));try{assert.equal(a.d.querySelector('#context-screen').hidden,false);assert.equal(a.d.querySelector('#upload-screen').hidden,true);assert.ok(a.d.querySelector('#area-map').classList.contains('leaflet-container'));submit(a.w,a.d.querySelector('#context-form'));await tick();assert.equal(a.d.querySelector('#context-error').hidden,false);assert.ok(!a.calls.some(c=>c.url==='/api/simple/continue'));}finally{a.close();}
});

test('recording time and rough map area continue the same investigation',async()=>{
 let continued=false;
 const a=await app(url=>{if(url==='/api/simple/continue'){continued=true;return {status:'analyzing'};}return continued?{...idle,...matched}:{...idle,status:'needs_context',recorded_at:null};});
 try{a.d.querySelector('#recorded-at').value='2026-09-08T20:52:15';a.d.querySelector('#area-lat').value='40.875';a.d.querySelector('#area-lon').value='-73.525';submit(a.w,a.d.querySelector('#context-form'));await tick();await tick();const request=a.calls.find(c=>c.url==='/api/simple/continue');assert.ok(request);const body=JSON.parse(request.options.body);assert.equal(body.latitude,40.875);assert.match(body.recorded_at,/Z$/);assert.equal(a.d.querySelector('#result-screen').hidden,false);}finally{a.close();}
});

test('no aircraft or weak evidence produces a friendly empty state with no pin',async()=>{
 const a=await app(()=>({...idle,status:'inconclusive',message:'No clear aircraft flyover found.'}));
 try{a.d.querySelector('#example').click();await tick();await tick();assert.equal(a.d.querySelector('#empty-screen').hidden,false);assert.equal(a.d.querySelector('#result-screen').hidden,true);assert.match(a.d.querySelector('#empty-message').textContent,/No clear aircraft/);assert.equal(a.d.querySelector('#result-map .pin-icon'),null);}finally{a.close();}
});

test('unavailable flight history is not presented as a location',async()=>{
 const a=await app(()=>({...idle,status:'unavailable',message:'Flight history is unavailable for that time.'}));
 try{a.d.querySelector('#example').click();await tick();await tick();assert.equal(a.d.querySelector('#empty-screen').hidden,false);assert.match(a.d.querySelector('#empty-title').textContent,/missing a piece/);assert.equal(a.d.querySelector('#result-screen').hidden,true);}finally{a.close();}
});
