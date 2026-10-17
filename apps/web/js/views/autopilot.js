// Lái tự động: bounded automation in LIMITED_AUTO.
// Turning it on is the operator's pre-approval for changes inside fixed limits
// (configs/safety-defaults.yaml → autopilot). Outside those limits the machine only warns.

import { api, getOperator } from '../api.js';
import { $, $$, esc, icon, pageHead, card, callout, confirmDialog, toast, withLoading, loadingRows, errorBox, fmt } from '../ui.js';

const FEATURE_INFO = {
  speech_rider: {
    title: 'Tự cân giọng nói', icon: 'mic',
    what: 'Giữ giọng Mục sư / MC đều tai khi người nói lúc to lúc nhỏ.',
    limits: (c) => `Tối đa ±${c.max_offset_db} dB quanh mức chuẩn, mỗi lần ${c.step_db} dB, cách nhau ≥ ${c.min_interval_s} giây. Đứng yên khi im lặng; không tăng khi có hú.`,
  },
  auto_notch: {
    title: 'Tự chống hú', icon: 'scissors',
    what: 'Cắt hẹp đúng tần số đang hú (−3.5 dB, Q 7) vào một dải EQ còn trống.',
    limits: (c) => `Tối đa ${c.budget_per_channel} lần cắt mỗi kênh; chỉ khi độ tin cậy ≥ ${Math.round(c.min_confidence * 100)}%. Không bao giờ ghi đè EQ đang dùng, không bao giờ tăng EQ.`,
  },
  livestream: {
    title: 'Tự cân độ to livestream', icon: 'broadcast',
    what: 'Giữ livestream gần mục tiêu độ to, không ảnh hưởng loa trong hội trường.',
    limits: (c, all) => `Chỉ bus ${all.livestream_bus}; mục tiêu ${c.target_lufs} LUFS, ±${c.max_offset_db} dB, mỗi lần ${c.step_db} dB / ${c.min_interval_s} giây. Cần nguồn đo của chính bus livestream.`,
  },
  clip_watch: {
    title: 'Cảnh báo vỡ tiếng', icon: 'alert',
    what: 'Báo kênh nào sát 0 dBFS liên tục để người giảm gain preamp.',
    limits: (c) => `Từ ${c.peak_dbfs} dBFS trong ${c.frames}/5 khung đo. Chỉ cảnh báo — máy không được chỉnh preamp.`,
  },
};
const STATUS_BADGE = { APPLIED: 'badge-ok', ALERT: 'badge-warn', FAILED: 'badge-bad', STOPPED: 'badge-bad', INFO: '' };

export default {
  mount(root) {
    let alive = true;
    let data = null;
    let busy = false;

    root.innerHTML = `
      ${pageHead('Lái tự động', 'Máy tự làm các việc lặp lại trong giờ lễ, trong giới hạn bạn đã duyệt trước. Âm sắc và cân bằng nghệ thuật vẫn do người quyết định.')}
      <div data-hero>${loadingRows(2)}</div>
      <div class="grid-2 mt-16" data-features></div>
      <div class="grid-2 mt-16">
        ${card({ title: 'Giọng nói đang được giữ đều', sub: 'Kênh Mục sư / MC. Mức chuẩn lấy từ tiết mục (Lưu từ mixer) hoặc vị trí fader lúc bật.', body: '<div data-riders></div>' })}
        ${card({ title: 'Cần người xử lý', sub: 'Những việc nằm ngoài giới hạn — máy chỉ báo, không tự làm.', body: '<div data-alerts></div>' })}
        ${card({ title: 'Các lần cắt hú tự động', sub: 'Sau lễ, xem lại: giữ nếu hội trường hay hú ở tần số đó, bỏ nếu chỉ là sự cố.', body: '<div data-notches></div>' })}
        ${card({ title: 'Livestream', sub: 'Độ to bus livestream', body: '<div data-livestream></div>' })}
      </div>
      <div class="mt-16">${card({ title: 'Nhật ký lái tự động', sub: 'Mọi thay đổi đều đi qua Safety Gate và được ghi vào nhật ký hệ thống.',
        actions: `<button class="btn btn-sm" data-revert>${icon('history', 'icon-sm')}Hoàn tác mọi thay đổi của máy</button>`, body: '<div data-log></div>' })}</div>`;

    const els = {
      hero: $('[data-hero]', root), features: $('[data-features]', root), riders: $('[data-riders]', root),
      alerts: $('[data-alerts]', root), notches: $('[data-notches]', root), livestream: $('[data-livestream]', root), log: $('[data-log]', root),
    };

    async function load() {
      if (!alive || document.hidden || busy) return;
      try {
        data = await api.get('/api/v1/autopilot');
        if (alive && !busy) render();
      } catch (e) {
        if (alive) els.hero.innerHTML = errorBox(e);
      }
    }

    function render() {
      const on = data.enabled;
      const src = data.source || {};
      els.hero.innerHTML = `
        <div class="hero ${on ? (data.inactive_reason ? 'warn' : 'ok') : ''}">
          <div class="hero-icon">${icon(on ? 'zap' : 'hand', 'icon-lg')}</div>
          <div class="grow">
            <h2>${on ? (data.inactive_reason ? 'Lái tự động đang chờ' : 'Lái tự động đang chạy') : 'Lái tự động đang tắt'}</h2>
            <p>${on
              ? esc(data.inactive_reason || `Bật bởi ${data.enabled_by || '—'}. Chế độ: Tự động có giới hạn. Kéo fader tay bất cứ lúc nào — máy sẽ theo mức của bạn.`)
              : esc(data.inactive_reason || 'Bật để máy tự cân giọng nói, chống hú và cân livestream trong giới hạn an toàn.')}</p>
            <p class="small muted mt-8">Nguồn đo: ${esc(src.label || '—')}${src.simulated ? ' · <strong>MÔ PHỎNG</strong>' : ''}${src.mapping_verified === false ? ' · chưa xác minh đúng kênh X32 → máy không chỉnh' : ''}</p>
          </div>
          ${on
            ? `<button class="btn btn-lg btn-danger" data-toggle>${icon('stop')}Tắt lái tự động</button>`
            : `<button class="btn btn-lg btn-primary" data-toggle>${icon('zap')}Bật lái tự động</button>`}
        </div>`;
      $('[data-toggle]', els.hero).addEventListener('click', (e) => toggle(e.currentTarget));

      els.features.innerHTML = Object.entries(FEATURE_INFO).map(([key, f]) => {
        const enabled = data.features[key];
        return `
          <section class="card ${enabled && on ? 'ok' : ''}">
            <header class="card-head">${icon(f.icon)}<h3>${f.title}<span class="card-sub">${esc(f.what)}</span></h3>
              <div class="segmented" data-feature="${key}">
                <button type="button" data-v="1" class="${enabled ? 'active' : ''}">Bật</button>
                <button type="button" data-v="0" class="${enabled ? '' : 'active'}">Tắt</button>
              </div></header>
            <div class="card-body small text-2">${esc(f.limits(data.config[key] || {}, data.config))}</div>
          </section>`;
      }).join('');
      $$('[data-feature] button', els.features).forEach(b => b.addEventListener('click', async () => {
        const name = b.closest('[data-feature]').dataset.feature;
        const res = await withLoading(b, () => api.put(`/api/v1/autopilot/features/${name}`, { enabled: b.dataset.v === '1', operator_id: getOperator() }));
        if (res) { data = res; render(); }
      }));

      const maxOff = data.config.speech_rider.max_offset_db || 3;
      els.riders.innerHTML = data.riders.length ? `<div class="stack-sm">${data.riders.map(r => {
        const pct = Math.min(50, Math.abs(r.offset_db) / maxOff * 50);
        return `
          <div class="row" style="flex-wrap:nowrap">
            <div style="width:160px;min-width:0"><div class="strong">${esc(r.name)}</div>
              <div class="tiny muted">Kênh ${r.channel} · ${r.on ? (r.speaking ? '<span class="ok-text">đang nói</span>' : 'im lặng (giữ nguyên)') : 'đang tắt'}</div></div>
            <div class="grow">
              <div style="position:relative;height:10px;background:var(--bg);border:1px solid var(--border);border-radius:999px">
                <span style="position:absolute;top:-3px;bottom:-3px;left:50%;width:2px;background:var(--border-strong)"></span>
                <span style="position:absolute;top:1px;bottom:1px;border-radius:999px;background:${r.offset_db >= 0 ? 'var(--ok)' : 'var(--warn)'};
                  ${r.offset_db >= 0 ? `left:50%;width:${pct}%` : `right:50%;width:${pct}%`}"></span>
              </div>
              <div class="tiny muted mt-8">Máy đang bù <strong>${r.offset_db >= 0 ? '+' : ''}${fmt.num(r.offset_db)} dB</strong> (giới hạn ±${maxOff}) · mức vào ${r.level_dbfs === null ? '—' : fmt.num(r.level_dbfs) + ' dBFS'} · chuẩn ${r.reference_db === null ? '—' : fmt.num(r.reference_db) + ' dB'}</div>
            </div>
          </div>`;
      }).join('')}</div>` : '<p class="muted small">Chưa có kênh vai trò "Mục sư/MC" trong Sơ đồ kênh, hoặc chưa bật lái tự động.</p>';

      els.alerts.innerHTML = data.alerts.length
        ? `<div class="stack-sm">${data.alerts.map(a => callout('warn', `<strong>${a.channel ? `Kênh ${a.channel}` : esc(FEATURE_INFO[a.feature]?.title || '')}</strong> — ${esc(a.message)}`)).join('')}</div>`
        : callout('ok', 'Không có việc nào cần người xử lý.');

      els.notches.innerHTML = data.notches.length ? `<table class="table"><thead><tr><th>Kênh</th><th>Tần số</th><th>Dải EQ</th><th>Lúc</th></tr></thead><tbody>
        ${data.notches.map(n => `<tr><td>${n.channel}</td><td class="mono">${fmt.hz(n.freq_hz)}</td><td>${n.band}</td><td class="small">${fmt.time(n.applied_at)}</td></tr>`).join('')}
        </tbody></table><p class="tiny muted mt-8">Ngân sách: ${data.notch_budget} lần / kênh / buổi lễ.</p>` : '<p class="muted small">Chưa cắt lần nào.</p>';

      const ls = data.livestream;
      els.livestream.innerHTML = `<dl class="kv"><dt>Bus</dt><dd>${ls.bus}</dd><dt>Mục tiêu</dt><dd>${ls.target_lufs} LUFS</dd>
        <dt>Đang đo</dt><dd>${ls.lufs === null || ls.lufs === undefined ? '—' : fmt.num(ls.lufs) + ' LUFS'}</dd>
        <dt>Máy đã bù</dt><dd>${ls.offset_db >= 0 ? '+' : ''}${fmt.num(ls.offset_db)} dB</dd></dl><p class="small text-2 mt-8">${esc(ls.status || '')}</p>`;

      els.log.innerHTML = data.log.length ? `<div class="table-wrap" style="max-height:340px;overflow:auto"><table class="table"><tbody>
        ${data.log.map(l => `<tr><td class="nowrap small mono">${new Date(l.at * 1000).toLocaleTimeString('vi-VN')}</td>
          <td><span class="badge ${STATUS_BADGE[l.status] || ''}">${esc(l.status)}</span></td>
          <td class="small">${esc(l.message)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted small">Chưa có hoạt động.</p>';
    }

    async function toggle(btn) {
      if (data.enabled) {
        const res = await withLoading(btn, () => api.post('/api/v1/autopilot/disable', { operator_id: getOperator() }));
        if (res) { data = res; render(); toast('Đã tắt lái tự động. Hệ thống về chế độ Chỉ quan sát.', 'info'); }
        return;
      }
      busy = true;
      const ok = await confirmDialog({
        title: 'Bật lái tự động?',
        message: `Bật = bạn <strong>duyệt trước</strong> cho máy tự chỉnh trong các giới hạn trên trang này (±${esc(data.config.speech_rider.max_offset_db)} dB giọng nói, cắt hú hẹp có ngân sách, chỉ bus livestream ${esc(data.config.livestream_bus)}).<br><br>
          Máy <strong>không</strong> chỉnh preamp, routing, Main LR, Talkback; <strong>không</strong> tăng EQ; <strong>không</strong> tăng âm lượng khi im lặng.<br>
          Bấm <strong>STOP</strong> hoặc đổi chế độ bất cứ lúc nào để dừng ngay. Người vận hành: <strong>${esc(getOperator())}</strong>.`,
        confirmText: 'Bật lái tự động',
      });
      busy = false;
      if (!ok) return;
      const res = await withLoading(btn, () => api.post('/api/v1/autopilot/enable', { operator_id: getOperator() }), { errorPrefix: 'Không bật được: ' });
      if (res) { data = res; render(); toast('Lái tự động đang chạy.', 'ok'); }
    }

    $('[data-revert]', root).addEventListener('click', async (e) => {
      busy = true;
      const ok = await confirmDialog({
        title: 'Hoàn tác mọi thay đổi của máy?',
        message: 'Đưa fader giọng nói và bus livestream về mức chuẩn, gỡ các lần cắt hú tự động (trả dải EQ về như trước). Cần chế độ Hỗ trợ hoặc Lái tự động.',
        confirmText: 'Hoàn tác', danger: true,
      });
      busy = false;
      if (!ok) return;
      const res = await withLoading(e.currentTarget, () => api.post('/api/v1/autopilot/revert', { operator_id: getOperator() }), { errorPrefix: 'Không hoàn tác được: ' });
      if (res) { data = res; render(); toast('Đã hoàn tác các thay đổi của lái tự động.', 'ok'); }
    });

    load();
    const timer = setInterval(load, 1000);
    return () => { alive = false; clearInterval(timer); };
  },
};
