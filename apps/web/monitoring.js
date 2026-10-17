/* Read-only monitoring UI. All charts use local Canvas; no chart CDN needed. */
(() => {
  'use strict';
  const labels = { NORMAL:'Dưới ngưỡng', WARNING:'Cảnh báo', CRITICAL:'Nguy hiểm', CLIP_RISK:'Sát clipping', SILENT:'Ít tín hiệu / nghỉ', UNKNOWN:'Chưa đo được' };
  const colors = { NORMAL:'#38bdf8', WARNING:'#fbbf24', CRITICAL:'#fb7185', CLIP_RISK:'#f43f5e', SILENT:'#64748b', UNKNOWN:'#475569' };
  const priority = { CLIP_RISK:0, CRITICAL:1, WARNING:2, UNKNOWN:3, NORMAL:4, SILENT:5 };
  let latest = null, history = [], selected = 1, session = null, lastReceived = 0, lastRender = 0;
  let pending = false, channelSignature = '', historyRequest = null, historyChannel = null;
  const $ = id => document.getElementById(id);
  const text = (id, value) => { if ($(id)) $(id).textContent = value; };
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const db = value => finite(value) ? `${value.toFixed(1)} dBFS` : '—';
  const seconds = value => finite(value) ? `${value.toFixed(1)} s` : '—';
  const tag = status => {
    const el = document.createElement('span'); el.className = 'cm-tag';
    el.textContent = labels[status] || status; el.style.color = colors[status] || colors.UNKNOWN; return el;
  };
  function update(data) {
    if (!data || !Array.isArray(data.channels)) return;
    if (session !== data.session) { history = []; session = data.session; }
    latest = data; lastReceived = performance.now();
    window.cmPhysicalUnmapped = !data.source?.simulated && !data.source?.mapping_verified;
    if (performance.now() - lastRender > 250) schedule();
  }
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; lastRender = performance.now(); render(); });
  }
  function current() {
    if (!latest) return null;
    if (performance.now() - lastReceived <= 1500 && !latest.stale) return latest;
    return { ...latest, stale:true, source:{...latest.source,valid:false,reasons:['Không nhận được dữ liệu mới; kiểm tra kết nối.']},
      channels:latest.channels.map(r => ({...r,status:'UNKNOWN',measured:false,peak_dbfs:null,rms_dbfs:null,headroom_db:null})) };
  }
  function render() {
    const data = current(); if (!data) return;
    const source = data.source || {}, rows = data.channels;
    const measured = rows.filter(r => r.measured), over = rows.filter(r => ['WARNING','CRITICAL','CLIP_RISK'].includes(r.status));
    const severe = rows.filter(r => ['CRITICAL','CLIP_RISK'].includes(r.status));
    const worst = measured.reduce((a,b) => !a || b.peak_dbfs > a.peak_dbfs ? b : a, null);
    $('cm-source').classList.toggle('invalid', !source.valid);
    text('cm-source-title', source.label || 'Chưa có nguồn đo');
    const context = source.simulated ? 'MÔ PHỎNG — không phải mức đo trên thiết bị thật.' : `Đo đầu vào USB • ${source.sample_rate || '—'} Hz • tap: ${source.tap_point || 'chưa xác nhận'}`;
    text('cm-source-detail', [context, ...(source.reasons || [])].join(' • '));
    text('cm-source-tag', !source.valid ? 'DỮ LIỆU CHƯA HỢP LỆ' : source.simulated ? 'MÔ PHỎNG' : 'USB • CHƯA ÁNH XẠ');
    text('cm-measured', measured.length); text('cm-warning', over.length); text('cm-critical', severe.length);
    text('cm-unknown', rows.filter(r => !r.measured).length); text('cm-peak', db(worst?.peak_dbfs));
    text('cm-worst-name', worst?.name || 'chưa có dữ liệu');
    text('cm-updated', source.valid ? `Cập nhật ${new Date(data.sampled_at * 1000).toLocaleTimeString('vi-VN')}` : 'Đang chờ khung đo hợp lệ');
    const signature = JSON.stringify(rows.map(r => [r.channel,r.name]));
    if (signature !== channelSignature) {
      channelSignature = signature;
      $('cm-channel-select').replaceChildren(...rows.map(r => {
        const option = document.createElement('option'); option.value = r.channel; option.textContent = `${String(r.channel).padStart(2,'0')} • ${r.name}`; return option;
      }));
      if (!rows.some(r => r.channel === selected)) selected = rows[0]?.channel || 1;
      $('cm-channel-select').value = selected;
    }
    const chosen = rows.find(r => r.channel === selected);
    text('cm-headroom', chosen?.measured ? `${chosen.headroom_db.toFixed(1)} dB` : '—');
    text('cm-hold', db(chosen?.peak_hold_dbfs)); text('cm-duration', seconds(chosen?.over_seconds));
    text('cm-clip-count', chosen?.clip_events ?? '—');
    text('cm-advice', data.stale ? 'Dữ liệu đã cũ. Các giá trị thống kê là lịch sử của phiên trước khung đo cuối.' : chosen?.advice || 'Đang chờ dữ liệu.');
    renderTable(rows); renderEvents(data.events || []);
    drawLevels(data); drawTrend(data); drawDurations(data);
    const inputValues = [['cm-warning-input','warning_dbfs'],['cm-critical-input','critical_dbfs'],['cm-clip-input','clip_dbfs']];
    if (!document.activeElement?.closest('#cm-threshold-form')) inputValues.forEach(([id,key]) => { if (finite(data.thresholds?.[key])) $(id).value = data.thresholds[key]; });
  }
  function renderTable(rows) {
    const filtered = rows.filter(r => !$('cm-only-alerts').checked || ['WARNING','CRITICAL','CLIP_RISK','UNKNOWN'].includes(r.status));
    filtered.sort((a,b) => priority[a.status]-priority[b.status] || (b.peak_dbfs ?? -200)-(a.peak_dbfs ?? -200));
    const elements = filtered.map(r => {
      const tr = document.createElement('tr'); tr.tabIndex = 0; tr.setAttribute('aria-label', `Xem ${r.name}`);
      if (r.channel === selected) tr.style.background = '#172b43';
      const values = [`${String(r.channel).padStart(2,'0')} • ${r.name}`,tag(r.status),`${db(r.peak_dbfs)} / ${db(r.rms_dbfs)}`,
        r.measured ? `${r.headroom_db.toFixed(1)} dB` : '—',seconds(r.streak_seconds),r.advice];
      values.forEach(value => { const td = document.createElement('td'); if (value instanceof Node) td.append(value); else td.textContent = value; tr.append(td); });
      tr.onclick = () => choose(r.channel); tr.onkeydown = e => { if (e.key === 'Enter') choose(r.channel); };
      return tr;
    });
    if (!elements.length) { const tr=document.createElement('tr'),td=document.createElement('td'); td.colSpan=6; td.textContent='Không có đầu vào phù hợp bộ lọc.';tr.append(td);elements.push(tr); }
    $('cm-channel-table').replaceChildren(...elements);
  }
  function renderEvents(events) {
    const nodes = events.slice(0,30).map(e => {
      const el=document.createElement('div');el.className='cm-alert';
      const info=document.createElement('span');info.textContent=`${new Date(e.timestamp*1000).toLocaleTimeString('vi-VN')} • ${e.name} • ${db(e.peak_dbfs)}`;
      el.append(tag(e.status),info);return el;
    });
    if (!nodes.length) {const el=document.createElement('p');el.className='cm-empty';el.textContent='Chưa ghi nhận đợt vượt ngưỡng trong phiên này.';nodes.push(el);}
    $('cm-event-list').replaceChildren(...nodes);
  }
  function canvas(id) {
    const el=$(id), rect=el.getBoundingClientRect(), ratio=window.devicePixelRatio || 1;
    const w=Math.max(1,rect.width),h=Math.max(1,rect.height);el.width=Math.round(w*ratio);el.height=Math.round(h*ratio);
    const ctx=el.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);ctx.font='11px Arial';return {ctx,w,h};
  }
  function grid(c, thresholds) {
    const {ctx,w,h}=c, left=42,right=w-12,top=12,bottom=h-30;
    const y=value=>bottom-Math.max(0,Math.min(60,value+60))/60*(bottom-top);
    for(let level=-60;level<=0;level+=12){ctx.strokeStyle='#20304a';ctx.beginPath();ctx.moveTo(left,y(level));ctx.lineTo(right,y(level));ctx.stroke();ctx.fillStyle='#8ca2bf';ctx.fillText(String(level),5,y(level)+4);}
    for(const [key,color] of [['warning_dbfs','#fbbf24'],['critical_dbfs','#fb7185'],['clip_dbfs','#f43f5e']]){
      const value=thresholds?.[key];if(!finite(value))continue;ctx.setLineDash([5,4]);ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(left,y(value));ctx.lineTo(right,y(value));ctx.stroke();ctx.setLineDash([]);
      ctx.fillStyle=color;ctx.fillText(`${value} dBFS`,right-62,y(value)+12);
    }
    return {left,right,top,bottom,y};
  }
  function drawLevels(data) {
    const c=canvas('cm-level-chart'),g=grid(c,data.thresholds),step=(g.right-g.left)/32;
    data.channels.forEach(r=>{
      const x=g.left+(r.channel-1)*step+2,width=Math.max(2,step-4);
      c.ctx.fillStyle=colors[r.status];
      if(r.measured){const y=g.y(r.peak_dbfs);c.ctx.fillRect(x,y,width,Math.max(2,g.bottom-y));}
      else {c.ctx.fillRect(x,g.bottom-5,width,5);}
      if(finite(r.peak_hold_dbfs)){c.ctx.strokeStyle='#dae8fa';c.ctx.beginPath();c.ctx.moveTo(x,g.y(r.peak_hold_dbfs));c.ctx.lineTo(x+width,g.y(r.peak_hold_dbfs));c.ctx.stroke();}
      if(r.channel===selected){c.ctx.strokeStyle='#f8fafc';c.ctx.strokeRect(x-1,g.top,width+2,g.bottom-g.top);}
      if(c.w>650 || r.channel%2===1){c.ctx.fillStyle=r.channel===selected?'#fff':'#9bb0cb';c.ctx.textAlign='center';c.ctx.fillText(String(r.channel).padStart(2,'0'),x+width/2,g.bottom+18);c.ctx.textAlign='left';}
    });
  }
  function drawTrend(data) {
    const c=canvas('cm-trend-chart'),g=grid(c,data.thresholds);
    for(const age of [120,90,60,30,0]){const x=g.left+(1-age/120)*(g.right-g.left);c.ctx.fillStyle='#8ca2bf';c.ctx.textAlign=age===0?'right':'left';c.ctx.fillText(age===0?'hiện tại':`−${age}s`,x,g.bottom+20);}
    c.ctx.textAlign='left';
    for(const [key,color] of [['peak_dbfs','#38bdf8'],['rms_dbfs','#a78bfa']]){
      c.ctx.strokeStyle=color;c.ctx.lineWidth=1.8;c.ctx.beginPath();let drawing=false;
      history.forEach(point=>{const row=point.levels.find(r=>r.channel===selected),value=row?.[key];
        if(!finite(value)){drawing=false;return;}const x=g.left+(1-point.seconds_ago/120)*(g.right-g.left);
        if(drawing)c.ctx.lineTo(x,g.y(value));else c.ctx.moveTo(x,g.y(value));drawing=true;
      });c.ctx.stroke();c.ctx.lineWidth=1;
    }
    if(!history.some(p=>p.levels.some(r=>r.channel===selected&&finite(r.peak_dbfs)))){c.ctx.fillStyle='#9baac1';c.ctx.fillText('Chưa có lịch sử hợp lệ cho đầu vào này',g.left+10,(g.top+g.bottom)/2);}
  }
  function drawDurations(data) {
    const c=canvas('cm-duration-chart');
    const rows=[...data.channels].filter(r=>r.over_seconds>0).sort((a,b)=>b.over_seconds-a.over_seconds).slice(0,6);
    if(!rows.length){c.ctx.fillStyle='#9baac1';c.ctx.fillText('Chưa ghi nhận thời gian vượt ngưỡng',12,c.h/2);return;}
    const max=Math.max(1,...rows.map(r=>r.over_seconds));
    rows.forEach((r,i)=>{const y=10+i*36;c.ctx.fillStyle='#cad8ed';c.ctx.fillText(`${r.channel.toString().padStart(2,'0')} • ${r.name.slice(0,23)}`,10,y+12);
      const width=(c.w-100)*r.over_seconds/max;c.ctx.fillStyle='#fbbf24';c.ctx.fillRect(10,y+19,width,7);c.ctx.fillStyle='#dbe9f8';c.ctx.fillText(seconds(r.over_seconds),width+20,y+26);
    });
  }
  function choose(channel) { selected=channel;$('cm-channel-select').value=channel;history=[];schedule();poll(); }
  async function poll() {
    if(historyRequest && historyChannel===selected)return;
    historyRequest?.abort();const controller=new AbortController();historyRequest=controller;historyChannel=selected;
    const timeout=setTimeout(()=>controller.abort(),4000);
    const requestChannel=selected;
    try {
      const response=await fetch(`/api/v1/monitoring/analysis?channel=${requestChannel}`,{signal:controller.signal,cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const data=await response.json();if(requestChannel!==selected)return;
      update(data);history=data.history || [];schedule();
    } catch(error) {if(error.name!=='AbortError'&&performance.now()-lastReceived>1500)schedule();}
    finally {clearTimeout(timeout);if(historyRequest===controller)historyRequest=null;}
  }
  function exportCSV() {
    const data=current();if(!data)return;
    const safe=value=>{let s=String(value??'');if(typeof value==='string'&&/^[=+\-@\t\r]/.test(s))s="'"+s;return `"${s.replaceAll('"','""')}"`;};
    const rows=[['ChurchMix — báo cáo mức tín hiệu'],['Nguồn',data.source.label],['Mô phỏng',data.source.simulated?'Có':'Không'],
      ['Dữ liệu hợp lệ',data.source.valid?'Có':'Không'],['Cảnh báo dBFS',data.thresholds.warning_dbfs],['Nguy hiểm dBFS',data.thresholds.critical_dbfs],['Sát clipping dBFS',data.thresholds.clip_dbfs],
      ['Input','Tên nguồn','Trạng thái','Peak dBFS','RMS dBFS','Headroom dB','Peak lớn nhất phiên','Thời gian vượt s','Đợt sát clipping','Phân tích']];
    data.channels.forEach(r=>rows.push([r.channel,r.name,labels[r.status],r.peak_dbfs,r.rms_dbfs,r.headroom_db,r.peak_hold_dbfs,r.over_seconds,r.clip_events,r.advice]));
    rows.push([],['Lịch sử đầu vào',selected],['Giây trước hiện tại','Peak dBFS','RMS dBFS']);
    history.forEach(p=>{const r=p.levels.find(r=>r.channel===selected);rows.push([p.seconds_ago,r?.peak_dbfs,r?.rms_dbfs]);});
    const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(row=>row.map(safe).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'}));
    const a=document.createElement('a');a.href=url;a.download=`ChurchMix-signal-${new Date().toISOString().replaceAll(':','-').slice(0,19)}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  window.ChurchMixMonitor={update,disconnected:()=>{lastReceived=0;schedule();}};
  document.addEventListener('DOMContentLoaded',()=>{
    $('cm-channel-select').addEventListener('change',e=>choose(Number(e.target.value)));
    $('cm-only-alerts').addEventListener('change',schedule);$('cm-export').addEventListener('click',exportCSV);
    $('cm-level-chart').addEventListener('click',event=>{const rect=event.currentTarget.getBoundingClientRect();const ch=Math.floor((event.clientX-rect.left-42)/(rect.width-54)*32)+1;if(ch>=1&&ch<=32)choose(ch);});
    $('cm-threshold-form').addEventListener('submit',async event=>{
      event.preventDefault();const button=event.submitter;button.disabled=true;
      try {const response=await fetch('/api/v1/monitoring/thresholds',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({warning_dbfs:Number($('cm-warning-input').value),critical_dbfs:Number($('cm-critical-input').value),clip_dbfs:Number($('cm-clip-input').value)})});
        const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Ngưỡng không hợp lệ.');history=[];text('cm-settings-message',result.message);await poll();
      } catch(error){text('cm-settings-message',error.message);}finally{button.disabled=false;}
    });
    new ResizeObserver(schedule).observe($('cm-title').closest('section'));
    poll();setInterval(poll,1000);setInterval(()=>{if(latest&&performance.now()-lastReceived>1500)schedule();},500);
  });
})();
