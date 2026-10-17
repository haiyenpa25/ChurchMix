import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

// Virtual DOM/canvas fixture: no browser, hardware, or network I/O.
function fixture(width = 900) {
  const ids = new Map(), callbacks = new Map(), intervals = [], drawings = new Map();
  let now = 1000, blob = null, download = null;
  class Element {
    constructor(name = '') { this.name=name;this.children=[];this.style={};this.value='';this.checked=false;this.events={};this.textContent='';this.classList={toggle(){}}; }
    append(...nodes) {this.children.push(...nodes);}
    replaceChildren(...nodes) {this.children=nodes;}
    setAttribute() {}
    addEventListener(name, callback) {this.events[name]=callback;}
    closest() {return this;}
    getBoundingClientRect() {return {width,height:245,left:0};}
    getContext() {
      if(!drawings.has(this.name))drawings.set(this.name,[]);
      const operations=drawings.get(this.name);
      return new Proxy({}, {get:(target,key)=>target[key] ?? ((...args)=>operations.push([key,...args])),set:(target,key,value)=>{target[key]=value;return true;}});
    }
    click() {download=this.download;}
  }
  const get=id=>{if(!ids.has(id))ids.set(id,new Element(id));return ids.get(id);};
  const document={getElementById:get,createElement:name=>new Element(name),activeElement:null,
    addEventListener:(name,callback)=>callbacks.set(name,callback)};
  const data={session:1,sampled_at:1700000000,source:{valid:true,simulated:true,label:'Demo • dữ liệu mô phỏng',reasons:[]},
    thresholds:{warning_dbfs:-12,critical_dbfs:-6,clip_dbfs:-0.5},events:[],history:[{seconds_ago:1,levels:[{channel:1,peak_dbfs:-3,rms_dbfs:-18}]}],
    channels:[{channel:1,name:'<img src=x onerror=alert(1)>',status:'CRITICAL',measured:true,peak_dbfs:-3,rms_dbfs:-18,headroom_db:3,peak_hold_dbfs:-2,over_seconds:4,streak_seconds:2,clip_events:0,advice:'Kiểm tra gain nguồn.'},
      {channel:2,name:'USB Input 02',status:'UNKNOWN',measured:false,peak_dbfs:null,rms_dbfs:null,headroom_db:null,peak_hold_dbfs:null,over_seconds:0,streak_seconds:0,clip_events:0,advice:'Chưa đo được.'}]};
  const context={document,Node:Element,performance:{now:()=>now},window:{devicePixelRatio:2},console,
    requestAnimationFrame:callback=>callback(),ResizeObserver:class{observe(){}},
    setInterval:callback=>intervals.push(callback),setTimeout:()=>1,clearTimeout(){},
    AbortController,Blob,URL:{createObjectURL:value=>{blob=value;return 'blob:fixture';},revokeObjectURL(){}},
    fetch:async()=>({ok:true,json:async()=>structuredClone(data)})};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(new URL('../apps/web/monitoring.js',import.meta.url),'utf8'),context);
  callbacks.get('DOMContentLoaded')();
  return {context,get,data,drawings,intervals,advance:value=>{now=value;},blob:()=>blob,download:()=>download,
    content:element=>[element.textContent,...element.children.map(child=>typeof child==='string'?child:[child.textContent,...child.children.map(c=>c.textContent)].join(' '))].join(' ')};
}

test('monitoring charts render on wide and narrow canvas with explicit demo source',async()=>{
  const html=fs.readFileSync(new URL('../apps/web/legacy.html',import.meta.url),'utf8');
  assert.match(html,/<summary>Công cụ & quy trình/);
  assert.match(html,/id="rtaSourceInfo"/);
  assert.doesNotMatch(html,/M\? PH\?NG|C\?ng c\?/);
  for(const width of [900,360]){
    const f=fixture(width);await new Promise(setImmediate);
    assert.match(f.get('cm-source-detail').textContent,/MÔ PHỎNG/);
    assert.equal(f.get('cm-warning').textContent,1);
    assert.equal(f.get('cm-critical').textContent,1);
    assert.equal(f.get('cm-unknown').textContent,1);
    assert.equal(f.get('cm-peak').textContent,'-3.0 dBFS');
    for(const id of ['cm-level-chart','cm-trend-chart','cm-duration-chart'])assert.ok(f.drawings.get(id).length>0,id);
    assert.equal(f.get('cm-level-chart').width,width*2);
    const td=f.get('cm-channel-table').children[0].children[0];
    assert.match(td.textContent,/<img src=x/);
    assert.equal(td.children.length,0,'source names must be literal text, never HTML');
  }
});

test('stale telemetry clears current values and marks source invalid',async()=>{
  const f=fixture();await new Promise(setImmediate);f.advance(4000);
  f.context.window.ChurchMixMonitor.disconnected();
  assert.equal(f.get('cm-measured').textContent,0);
  assert.equal(f.get('cm-critical').textContent,0);
  assert.equal(f.get('cm-peak').textContent,'—');
  assert.equal(f.get('cm-source-tag').textContent,'DỮ LIỆU CHƯA HỢP LỆ');
});

test('physical unmapped capture is explicit and CSV includes source provenance',async()=>{
  const f=fixture();await new Promise(setImmediate);f.advance(2000);
  f.data.source={valid:true,simulated:false,mapping_verified:false,label:'USB Audio',sample_rate:44100,tap_point:'UNKNOWN',reasons:['Chưa ánh xạ']};
  f.data.channels[0].name='=FORMULA';
  f.context.window.ChurchMixMonitor.update(f.data);
  assert.equal(f.context.window.cmPhysicalUnmapped,true);
  assert.match(f.get('cm-source-tag').textContent,/CHƯA ÁNH XẠ/);
  f.get('cm-export').events.click();
  const csv=await f.blob().text();
  assert.match(csv,/"Mô phỏng","Không"/);
  assert.match(csv,/"'=FORMULA"/,'CSV must neutralize formulas in source names');
  assert.match(f.download(),/^ChurchMix-signal-.*\.csv$/);
});

test('selecting a chart column updates the chosen input',async()=>{
  const f=fixture();await new Promise(setImmediate);
  f.get('cm-level-chart').events.click({currentTarget:f.get('cm-level-chart'),clientX:42+(900-54)/32*1.5});
  assert.equal(f.get('cm-channel-select').value,2);
});
