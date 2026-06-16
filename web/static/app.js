/**
 * METEOR Station — Frontend Logic v2.0
 * Multi-satellite, date-grouped gallery, pass detail, bulk download
 */

// =============================================================================
// Configuration
// =============================================================================
const API = '';
const REFRESH_INTERVAL = 15000;
let currentFilter = 'all';
let passesData = [];

// =============================================================================
// Init
// =============================================================================
document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadUpcoming();
    loadPasses();

    setInterval(() => { loadStatus(); loadUpcoming(); }, REFRESH_INTERVAL);
    setInterval(loadPasses, 60000);

    // Lightbox close on click
    document.getElementById('lightbox').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeLightbox();
    });

    // Modal close on overlay click
    ['detail-modal', 'settings-modal'].forEach(id => {
        document.getElementById(id).addEventListener('click', (e) => {
            if (e.target === e.currentTarget) {
                e.target.classList.remove('active');
            }
        });
    });
});


// =============================================================================
// Status
// =============================================================================
async function loadStatus() {
    try {
        const res = await fetch(`${API}/api/status`);
        const data = await res.json();
        updateStatusUI(data);
        setConnectionStatus('online', 'Bağlı');
    } catch (e) {
        setConnectionStatus('offline', 'Bağlantı yok');
    }
}

function updateStatusUI(data) {
    // Station
    const st = data.station || {};
    setText('image-count', st.image_count || 0);

    // Recording badge
    const badge = document.getElementById('recording-badge');
    if (st.status === 'recording') {
        badge.style.display = 'flex';
    } else {
        badge.style.display = 'none';
    }

    // Disk
    const disk = data.disk || {};
    setText('disk-usage', `${disk.free_gb || '?'} GB boş`);
    setProgress('disk-progress', disk.percent_used || 0);

    // System
    const sys = data.system || {};
    setText('cpu-percent', `${sys.cpu_percent || 0}%`);
    setText('ram-percent', `${sys.memory_percent || 0}%`);
    setText('cpu-temp', sys.cpu_temp ? `${sys.cpu_temp.toFixed(1)}°C` : '—');
    setText('uptime', sys.uptime || '—');
    setText('station-status', st.message || st.status || '—');

    // Sun info
    const sun = data.sun || {};
    if (sun.sunrise || sun.sunset) {
        const icon = sun.is_daylight ? '☀️' : '🌙';
        const rise = sun.sunrise ? new Date(sun.sunrise).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '?';
        const set = sun.sunset ? new Date(sun.sunset).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '?';
        setText('sun-info', `${icon} Doğuş ${rise} | Batış ${set}`);
    } else {
        setText('sun-info', '—');
    }

    // Next pass info & countdown
    if (st.next_pass) {
        const np = st.next_pass;
        const aosDate = new Date(np.aos);
        const losDate = new Date(np.los);
        setText('next-pass-time', formatDateTime(aosDate));
        setText('next-pass-sat', np.satellite || '—');

        if (st.status === 'recording') {
            // Kayıt sırasında LOS'a geri sayım
            startCountdown(losDate, true);
        } else {
            startCountdown(aosDate, false);
        }
    }

    // Last decode telemetry
    const ld = data.last_decode;
    const ldSection = document.getElementById('last-decode-section');
    if (ld && ldSection) {
        ldSection.style.display = 'block';
        const satName = ld.satellite || '?';
        const satClass = satName.includes('M2-4') ? 'm24' : 'm23';
        const satLabel = satName.includes('M2-4') ? 'M2-4' : 'M2-3';
        setText('ld-satellite', `${satLabel}`);
        const ldSatEl = document.getElementById('ld-satellite');
        if (ldSatEl) ldSatEl.className = `ld-value sat-color-${satClass}`;
        // Time: ISO date → local, fallback → pass_id'den çıkar
        let ldTime = '?';
        if (ld.time) {
            try {
                const d = new Date(ld.time);
                if (!isNaN(d.getTime())) {
                    ldTime = d.toLocaleString('tr-TR', {day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'});
                } else {
                    ldTime = ld.pass_id || ld.time;
                }
            } catch(e) {
                ldTime = ld.pass_id || ld.time;
            }
        }
        setText('ld-time', ldTime);
        setText('ld-elevation', ld.max_elevation ? `${ld.max_elevation}°` : '?');
        setText('ld-frequency', ld.frequency_mhz ? `${ld.frequency_mhz} MHz` : '?');
        setText('ld-channels', ld.channel_count ? `${ld.channel_count} kanal` : '?');
        setText('ld-norad', ld.norad || '?');
    } else if (ldSection) {
        ldSection.style.display = 'none';
    }

    // Telemetry panel
    const tlm = data.last_decode?.telemetry_summary;
    const tlmPanel = document.getElementById('telemetry-panel');
    if (tlm && tlm.has_analog && tlmPanel) {
        tlmPanel.style.display = 'block';
        renderTelemetry(tlm, data.last_decode);
    } else if (tlmPanel) {
        tlmPanel.style.display = 'none';
    }
}

// ── Telemetry Render ──
function adcToApproxC(adc) {
    // Yaklaşık ADC→°C dönüşümü (MSU-MR detektörleri için)
    // Lineer interpolasyon: ADC 142 ≈ -131°C, ADC 206 ≈ -67°C
    if (adc == null) return null;
    return Math.round(-273 + adc);
}

function detectorLedInfo(adc) {
    const tempC = adcToApproxC(adc);
    if (tempC == null) return { cls: '', label: '?', icon: '⚪' };
    if (tempC <= -120) return { cls: 'led-green', label: 'Mükemmel', icon: '🟢' };
    if (tempC <= -100) return { cls: 'led-yellow', label: 'Gürültülü', icon: '🟡' };
    return { cls: 'led-red', label: 'Bozuk', icon: '🔴' };
}

function renderTelemetry(tlm, ld) {
    // Header
    const satName = ld.satellite || tlm.msu_mr_id ? `METEOR-M2-${tlm.msu_mr_id}` : '?';
    setText('tlm-sat-name', satName);
    setText('tlm-mode', (tlm.msu_mr_set || '?').toUpperCase());
    setText('tlm-msu-id', tlm.msu_mr_id || '?');

    // LED for Ch6
    const ch6Led = detectorLedInfo(tlm.detector_ch6);
    const ledEl = document.getElementById('tlm-led');
    if (ledEl) {
        ledEl.className = `led ${ch6Led.cls}`;
    }
    setText('tlm-led-label', ch6Led.label);

    // Thermal Management
    const ch6C = adcToApproxC(tlm.detector_ch6);
    const ch5C = adcToApproxC(tlm.detector_ch5);
    const ch3C = adcToApproxC(tlm.detector_ch3);
    const bpC = adcToApproxC(tlm.baseplate_temp);

    setText('tlm-det-ch6', ch6C != null ? `${ch6C}°C (ADC: ${tlm.detector_ch6})` : '—');
    setText('tlm-det-ch5', ch5C != null ? `${ch5C}°C (ADC: ${tlm.detector_ch5})` : '—');
    setText('tlm-det-ch3', ch3C != null ? `${ch3C}°C (ADC: ${tlm.detector_ch3})` : '—');
    setText('tlm-baseplate', bpC != null ? `${bpC}°C (ADC: ${tlm.baseplate_temp})` : '—');

    // Status for detectors
    const ch6Info = detectorLedInfo(tlm.detector_ch6);
    const ch5Info = detectorLedInfo(tlm.detector_ch5);
    const ch3Info = detectorLedInfo(tlm.detector_ch3);
    setText('tlm-det-ch6-status', `${ch6Info.icon} ${ch6Info.label}`);
    setText('tlm-det-ch5-status', `${ch5Info.icon} ${ch5Info.label}`);
    setText('tlm-det-ch3-status', `${ch3Info.icon} ${ch3Info.label}`);

    // Calibration
    setText('tlm-hot1', tlm.hot_body_1_c != null ? `+${tlm.hot_body_1_c}°C` : '—');
    setText('tlm-hot2', tlm.hot_body_2_c != null ? `+${tlm.hot_body_2_c}°C` : '—');
    setText('tlm-cold', tlm.cold_body_1_c != null ? `${tlm.cold_body_1_c}°C` : '—');

    // Cal status — check within expected ranges
    const hot1ok = tlm.hot_body_1_c != null && tlm.hot_body_1_c > 30 && tlm.hot_body_1_c < 60;
    const hot2ok = tlm.hot_body_2_c != null && tlm.hot_body_2_c > 30 && tlm.hot_body_2_c < 60;
    const coldok = tlm.cold_body_1_c != null && tlm.cold_body_1_c > -20 && tlm.cold_body_1_c < 5;
    setText('tlm-hot1-status', hot1ok ? '✅ Normal' : '⚠️ Kontrol');
    setText('tlm-hot2-status', hot2ok ? '✅ Normal' : '⚠️ Kontrol');
    setText('tlm-cold-status', coldok ? '✅ Normal' : '⚠️ Kontrol');

    // Power & Optical
    setText('tlm-hv', `VK1: ${tlm.hv_vk1 || '?'} / VK2: ${tlm.hv_vk2 || '?'}`);
    const hvOk = tlm.hv_vk1 > 50 && tlm.hv_vk2 > 50;
    setText('tlm-hv-status', hvOk ? '✅ Stabil' : '🔴 Düşük!');

    setText('tlm-lamps', `${tlm.lamp_ch1 || '?'} / ${tlm.lamp_ch2 || '?'} / ${tlm.lamp_ch3 || '?'}`);
    const lampsOk = tlm.lamp_ch1 > 0 && tlm.lamp_ch2 > 0 && tlm.lamp_ch3 > 0;
    setText('tlm-lamps-status', lampsOk ? '✅ Aktif' : '🔴 Kapalı!');

    setText('tlm-ir-lens', `ADC: ${tlm.ir_lens_temp || '?'}`);
}

function setConnectionStatus(status, message) {
    const el = document.getElementById('connection-status');
    el.textContent = message;
    el.style.color = status === 'online' ? 'var(--success)' : 'var(--danger)';
}


// =============================================================================
// Upcoming Passes
// =============================================================================
async function loadUpcoming() {
    try {
        const res = await fetch(`${API}/api/upcoming`);
        const data = await res.json();
        updateUpcomingUI(data);
    } catch (e) { /* silent */ }
}

function updateUpcomingUI(data) {
    const tbody = document.getElementById('upcoming-body');
    const passes = data.upcoming_passes || [];

    if (!passes.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Yaklaşan geçiş yok</td></tr>';
        return;
    }

    tbody.innerHTML = passes.map(p => {
        const aos = new Date(p.aos);
        const los = new Date(p.los);
        const satClass = p.satellite?.includes('M2-4') ? 'm24' : 'm23';
        const satLabel = p.satellite?.includes('M2-4') ? 'M2-4' : 'M2-3';
        const aosLocal = formatDateTime(aos);
        const aosUTC = aos.toISOString().slice(5,16).replace('T',' ');
        const losLocal = formatTime(los);
        const losUTC = los.toISOString().slice(11,16);
        return `<tr>
            <td><span class="sat-badge ${satClass}">${satLabel}</span></td>
            <td>${aosLocal}</td>
            <td>${losLocal}</td>
            <td>${formatDuration(p.duration_sec)}</td>
            <td>${p.max_elevation}°</td>
            <td>${p.frequency_mhz || '—'} MHz</td>
            <td>${p.priority || '—'}</td>
        </tr>`;
    }).join('');
}


// =============================================================================
// Countdown
// =============================================================================
let countdownInterval = null;
let countdownIsRecording = false;
function startCountdown(targetDate, isRecording = false) {
    if (countdownInterval) clearInterval(countdownInterval);
    countdownIsRecording = isRecording;

    function update() {
        const now = new Date();
        const diff = targetDate - now;
        if (diff <= 0) {
            if (countdownIsRecording) {
                setText('countdown', '⏳ Decode bekleniyor...');
            } else {
                setText('countdown', '🔴 ŞİMDİ!');
            }
            clearInterval(countdownInterval);
            return;
        }
        const h = Math.floor(diff / 3600000);
        const m = Math.floor((diff % 3600000) / 60000);
        const s = Math.floor((diff % 60000) / 1000);
        const timeStr = `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        if (countdownIsRecording) {
            setText('countdown', `🔴 REC ${timeStr}`);
        } else {
            setText('countdown', timeStr);
        }
    }

    update();
    countdownInterval = setInterval(update, 1000);
}


// =============================================================================
// Gallery — Date Grouped
// =============================================================================
async function loadPasses() {
    try {
        const satParam = currentFilter !== 'all' ? `?satellite=${currentFilter}` : '';
        const res = await fetch(`${API}/api/passes${satParam}`);
        passesData = await res.json();
        renderGallery(passesData);
    } catch (e) { /* silent */ }
}

function renderGallery(dateGroups) {
    const container = document.getElementById('gallery-container');

    if (!dateGroups.length) {
        container.innerHTML = '<div class="empty-state">📡 Henüz kayıtlı geçiş yok</div>';
        return;
    }

    container.innerHTML = dateGroups.map((group, gi) => {
        const dateFormatted = formatDateHeader(group.date);
        const isOpen = gi === 0 ? 'open' : '';

        const passCards = group.passes.map(p => {
            const meta = p.metadata || {};
            // Bug #4 fix: önce metadata.satellite, sonra folder adı
            const satName = meta.satellite || p.id || 'Manuel Test';
            const satClass = satName.includes('M2-4') ? 'm24' : satName.includes('M2-3') ? 'm23' : 'm23';
            const satLabel = satName.includes('M2-4') ? 'M2-4' : satName.includes('M2-3') ? 'M2-3' : '?';
            const statusClass = meta.success === true ? 'pass-status-ok' : meta.success === false ? 'pass-status-fail' : 'pass-status-unknown';
            const statusIcon = meta.success === true ? '✅' : meta.success === false ? '❌' : '⚪';
            // Zaman: klasör adından çıkar ve TR saatine çevir
            let timeStr = '--:--';
            const idStr = p.id || '';
            // Standart format: YYYY-MM-DD_HHMMSS
            const timeMatch = idStr.match(/(\d{4})-(\d{2})-(\d{2})[_T](\d{2})[\-_]?(\d{2})[\-_]?(\d{2})?/);
            if (timeMatch) {
                // Folder adı UTC — Date objesi oluştur ve TR'ye çevir
                const utcDate = new Date(`${timeMatch[1]}-${timeMatch[2]}-${timeMatch[3]}T${timeMatch[4]}:${timeMatch[5]}:${timeMatch[6]||'00'}Z`);
                timeStr = utcDate.toLocaleTimeString('tr-TR', {hour:'2-digit', minute:'2-digit'});
            }
            // metadata'dan AOS zamanı fallback
            if (timeStr === '--:--' && meta.aos) {
                try {
                    const d = new Date(meta.aos);
                    timeStr = d.toLocaleTimeString('tr-TR', {hour:'2-digit', minute:'2-digit'});
                } catch (e) { }
            }
            // Max elevation: metadata'dan al
            const maxElev = meta.max_elevation || 0;
            // Thumbnail: MSU-MR alt klasöründen de ara
            let thumbSrc = '';
            if (p.images.length > 0) {
                // Önce MSU-MR Filled'dan, sonra MSU-MR'den, sonra herhangi birinden
                const filled = p.images.find(i => i.path && i.path.includes('Filled'));
                const msuImg = p.images.find(i => i.path && i.path.includes('MSU-MR'));
                const best = filled || msuImg || p.images[0];
                thumbSrc = `${API}/api/passes/${p.id}/files/${best.path}`;
            }

            return `<div class="pass-card" onclick="openDetail('${p.id}')">
                ${thumbSrc
                    ? `<img class="pass-thumb" src="${thumbSrc}" alt="thumb" loading="lazy">`
                    : `<div class="pass-thumb no-image">📡</div>`}
                <div class="pass-info">
                    <div class="pass-info-row">
                        <span class="pass-time">${timeStr}</span>
                        <span class="sat-badge ${satClass}">${satLabel}</span>
                        <span class="${statusClass}">${statusIcon}</span>
                    </div>
                    <div class="pass-meta">
                        <span>🔺 ${maxElev}°</span>
                        <span>📻 ${meta.frequency_mhz || '?'} MHz</span>
                        <span>🖼️ ${p.images.length}</span>
                        <span>💾 ${p.total_size_mb} MB</span>
                        ${meta.snr_avg ? `<span class="pass-snr-badge">📊 ${meta.snr_avg} dB</span>` : ''}
                        ${meta.has_baseband ? '<span>📦 IQ</span>' : ''}
                    </div>
                </div>
                <div class="pass-actions" onclick="event.stopPropagation()">
                    <button class="btn btn-sm" onclick="downloadPassZip('${p.id}')" title="ZIP İndir">⬇️</button>
                    <button class="btn btn-sm btn-danger" onclick="deletePass('${p.id}')" title="Sil">🗑️</button>
                </div>
            </div>`;
        }).join('');

        return `<div class="date-group ${isOpen}">
            <div class="date-header" onclick="toggleDateGroup(this)">
                <div class="date-header-left">
                    <span class="date-arrow">▼</span>
                    <h3>📅 ${dateFormatted}</h3>
                </div>
                <div class="date-stats">
                    <span class="date-stat">📡 ${group.passes.length} geçiş</span>
                    <span class="date-stat">🖼️ ${group.total_images} görüntü</span>
                    <span class="date-stat">💾 ${group.total_size_mb} MB</span>
                    <button class="btn btn-sm" onclick="event.stopPropagation(); downloadDaily('${group.date}')" title="Günü indir">📦</button>
                </div>
            </div>
            <div class="date-passes">${passCards}</div>
        </div>`;
    }).join('');
}

function toggleDateGroup(header) {
    header.parentElement.classList.toggle('open');
}

function filterSatellite(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filter);
    });
    loadPasses();
}


// =============================================================================
// Pass Detail Modal
// =============================================================================
async function openDetail(passId) {
    try {
        const res = await fetch(`${API}/api/passes/${passId}/detail`);
        const data = await res.json();
        renderDetail(data);
        document.getElementById('detail-modal').classList.add('active');
    } catch (e) {
        showToast('Detay yüklenemedi');
    }
}

function renderDetail(data) {
    const meta = data.metadata || {};
    const satLabel = meta.satellite?.includes('M2-4') ? 'METEOR-M2-4' : 'METEOR-M2-3';

    // Title
    document.getElementById('detail-title').textContent = `${satLabel} — ${data.id}`;

    // Metadata table
    const metaTable = document.getElementById('detail-metadata');
    const metaRows = [
        ['Uydu', meta.satellite],
        ['AOS', meta.aos ? `${new Date(meta.aos).toLocaleString('tr-TR')} <small class="utc-hint">(UTC ${new Date(meta.aos).toISOString().slice(11,16)})</small>` : '—'],
        ['LOS', meta.los ? `${new Date(meta.los).toLocaleString('tr-TR')} <small class="utc-hint">(UTC ${new Date(meta.los).toISOString().slice(11,16)})</small>` : '—'],
        ['Süre', meta.duration_sec ? `${meta.duration_sec}s (${Math.round(meta.duration_sec / 60)}dk)` : '—'],
        ['Max Elevasyon', `${meta.max_elevation || 0}°`],
        ['Başarı', meta.success ? '✅ Başarılı' : '❌ Başarısız'],
        ['Baseband', meta.has_baseband ? `📦 ${meta.baseband_file || 'baseband.raw'} (${meta.baseband_size_mb || 0} MB)` : '❌ Yok'],
        ['İndirildi', meta.downloaded ? '✅' : '❌'],
        ['Konum', meta.observer ? `${meta.observer.lat}°N, ${meta.observer.lon}°E` : '—'],
        ['Kayıt Tarihi', meta.recorded_at ? new Date(meta.recorded_at).toLocaleString('tr-TR') : '—'],
    ];

    // SNR & Frame stats
    if (meta.snr_avg != null) {
        metaRows.push(['📊 SNR Ortalama', `${meta.snr_avg} dB`]);
        metaRows.push(['📊 SNR Peak', `${meta.snr_peak} dB`]);
    }
    if (meta.viterbi_avg != null) {
        metaRows.push(['🔢 Viterbi BER', meta.viterbi_avg.toFixed(4)]);
    }
    if (meta.deframer_synced > 0 || meta.deframer_nosync > 0) {
        const total = meta.deframer_synced + meta.deframer_nosync;
        const pct = total > 0 ? Math.round((meta.deframer_synced / total) * 100) : 0;
        metaRows.push(['🔗 Frame Sync', `${meta.deframer_synced}/${total} (${pct}%)`]);
    }

    metaTable.innerHTML = metaRows
        .map(([k, v]) => `<tr><td>${k}</td><td>${v || '—'}</td></tr>`).join('');

    // Decode settings
    const ds = data.decode_settings || {};
    const decodeTable = document.getElementById('detail-decode');
    decodeTable.innerHTML = [
        ['Frekans', ds.frequency_mhz ? `${ds.frequency_mhz} MHz` : '—'],
        ['Pipeline', ds.pipeline || '—'],
        ['Sample Rate', ds.sample_rate_khz ? `${ds.sample_rate_khz} kHz` : '—'],
        ['Gain', ds.gain_db ? `${ds.gain_db} dB` : '—'],
        ['Threads', ds.threads || '—'],
        ['Exit Code', ds.exit_code !== null ? ds.exit_code : '—'],
    ].map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');

    // Files
    const filesDiv = document.getElementById('detail-files');
    const files = data.files || [];
    const icons = { image: '🖼️', baseband: '📦', metadata: '📋', log: '📃', other: '📄' };
    filesDiv.innerHTML = files.map(f => `
        <div class="detail-file">
            <div class="detail-file-info">
                <span class="detail-file-icon">${icons[f.type] || '📄'}</span>
                <span class="detail-file-name">${f.name}</span>
                <span class="detail-file-size">${f.size_mb > 1 ? f.size_mb + ' MB' : f.size_kb + ' KB'}</span>
            </div>
            <a class="btn btn-sm" href="${API}/api/passes/${data.id}/download/${f.path}" download>⬇️</a>
        </div>
    `).join('');

    // Images with channel mixer info
    const imagesDiv = document.getElementById('detail-images');
    const imageFiles = files.filter(f => f.type === 'image');
    if (imageFiles.length) {
        imagesDiv.innerHTML = imageFiles.map(f => {
            const chInfo = getChannelInfo(f.name);
            return `<div class="detail-img-wrap">
                <img src="${API}/api/passes/${data.id}/images/${f.name}"
                      alt="${f.name}"
                      onclick="openLightbox('${data.id}', '${f.name}')"
                      loading="lazy">
                ${chInfo ? `<span class="channel-info" title="${chInfo}">${chInfo}</span>` : ''}
            </div>`;
        }).join('');
    } else {
        imagesDiv.innerHTML = '<div class="empty-state">Görüntü yok</div>';
    }

    // Decode log
    document.getElementById('detail-log').textContent = data.decode_log || 'Log mevcut değil';

    // SNR Chart
    const snrHistory = meta.snr_history || [];
    const snrSection = document.getElementById('snr-chart-section');
    if (snrHistory.length > 2 && snrSection) {
        snrSection.style.display = 'block';
        setTimeout(() => drawSnrChart(snrHistory, meta), 100);
        setText('snr-chart-info', `${snrHistory.length} ölçüm | Ort: ${meta.snr_avg} dB | Peak: ${meta.snr_peak} dB`);
    } else if (snrSection) {
        snrSection.style.display = 'none';
    }

    // Footer buttons
    document.getElementById('detail-download-btn').onclick = () => downloadPassZip(data.id);
    document.getElementById('detail-delete-btn').onclick = () => {
        deletePass(data.id);
        closeDetail();
    };
}

function closeDetail() {
    document.getElementById('detail-modal').classList.remove('active');
}

function drawSnrChart(snrData, meta) {
    const canvas = document.getElementById('snr-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // Hi-DPI support
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const pad = { top: 10, right: 15, bottom: 25, left: 40 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    const minSnr = Math.max(0, Math.min(...snrData) - 1);
    const maxSnr = Math.max(...snrData) + 1;
    const range = maxSnr - minSnr || 1;

    // Clear
    ctx.clearRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = 'rgba(100, 116, 139, 0.15)';
    ctx.lineWidth = 1;
    const gridSteps = 4;
    for (let i = 0; i <= gridSteps; i++) {
        const y = pad.top + (ch / gridSteps) * i;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(w - pad.right, y);
        ctx.stroke();

        // Y axis labels
        const val = maxSnr - (range / gridSteps) * i;
        ctx.fillStyle = 'rgba(148, 163, 184, 0.7)';
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${val.toFixed(0)}`, pad.left - 6, y + 3);
    }

    // X axis label
    ctx.fillStyle = 'rgba(148, 163, 184, 0.5)';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Zaman →', w / 2, h - 2);

    // Data points → pixel coords
    const points = snrData.map((v, i) => ({
        x: pad.left + (i / (snrData.length - 1)) * cw,
        y: pad.top + ch - ((v - minSnr) / range) * ch
    }));

    // Gradient fill
    const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + ch);
    grad.addColorStop(0, 'rgba(56, 189, 248, 0.25)');
    grad.addColorStop(1, 'rgba(56, 189, 248, 0.02)');
    ctx.beginPath();
    ctx.moveTo(points[0].x, pad.top + ch);
    points.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(points[points.length - 1].x, pad.top + ch);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    points.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
    ctx.stroke();

    // Peak dot
    const peakIdx = snrData.indexOf(Math.max(...snrData));
    if (peakIdx >= 0) {
        const pp = points[peakIdx];
        ctx.beginPath();
        ctx.arc(pp.x, pp.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#22c55e';
        ctx.fill();
        ctx.strokeStyle = 'rgba(34, 197, 94, 0.4)';
        ctx.lineWidth = 6;
        ctx.stroke();
    }
}


// ── Channel Mixer Info ──
const CHANNEL_MAP = {
    'MCIR': 'Ch4 (IR) + Harita Overlay',
    'MSA': 'Ch1 (Kırmızı) + Güneş Açısı Düzeltme',
    'AVHRR_221': 'Ch2-Ch2-Ch1 (Görünür False Color)',
    'MSU-MR_124': 'Ch1-Ch2-Ch4 (Görünür+IR False Color)',
    '3.75um_IR_(CIRA)': 'Ch4 3.75µm (Isıl IR — CIRA)',
    '3.75um_IR_(Enhanced_Rainbow)': 'Ch4 3.75µm (Geliştirilmiş Gökkuşağı)',
    '3.75um_IR_(Rainbow)': 'Ch4 3.75µm (IR Gökkuşağı)',
    '3.9_um_Shortwave_IR_(Calibrated)': 'Ch4 3.9µm (Kalibre Kısa Dalga IR)',
    '3.9_um_Shortwave_IR_(Uncalibrated)': 'Ch4 3.9µm (Ham Kısa Dalga IR)',
    '3.9_um_Cloud_Tops': 'Ch4 3.9µm (Bulut Üstü)',
    'MSU-MR-1': 'Kanal 1 — 0.5-0.7µm (Görünür Işık)',
    'MSU-MR-2': 'Kanal 2 — 0.7-1.1µm (Yakın IR)',
    'MSU-MR-3': 'Kanal 3 — 1.6-1.8µm (Kısa Dalga IR)',
    'MSU-MR-4': 'Kanal 4 — 3.5-4.1µm (Isıl IR)',
    'MSU-MR-5': 'Kanal 5 — 10.5-11.5µm (Termal IR)',
    'MSU-MR-6': 'Kanal 6 — 11.5-12.5µm (Termal IR-2)',
};

function getChannelInfo(filename) {
    for (const [key, desc] of Object.entries(CHANNEL_MAP)) {
        if (filename.includes(key)) return desc;
    }
    return null;
}


// =============================================================================
// Downloads
// =============================================================================
function downloadPassZip(passId) {
    window.location.href = `${API}/api/download/pass/${passId}`;
    showToast('ZIP indiriliyor...');
}

function downloadDaily(date) {
    const satParam = currentFilter !== 'all' ? `&satellite=${currentFilter}` : '';
    window.location.href = `${API}/api/download/daily/${date}?${satParam}`;
    showToast(`${date} indiriliyor...`);
}

function downloadBulk(type) {
    const now = new Date();
    const satParam = currentFilter !== 'all' ? `satellite=${currentFilter}` : '';

    if (type === 'daily') {
        const date = now.toISOString().slice(0, 10);
        window.location.href = `${API}/api/download/daily/${date}?${satParam}`;
    } else if (type === 'weekly') {
        const week = getISOWeek(now);
        window.location.href = `${API}/api/download/weekly/${now.getFullYear()}/${week}?${satParam}`;
    } else if (type === 'monthly') {
        window.location.href = `${API}/api/download/monthly/${now.getFullYear()}/${now.getMonth() + 1}?${satParam}`;
    }
    showToast(`${type} ZIP indiriliyor...`);
}

function getISOWeek(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7);
    const week1 = new Date(d.getFullYear(), 0, 4);
    return 1 + Math.round(((d - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
}


// =============================================================================
// Delete
// =============================================================================
async function deletePass(passId) {
    if (!confirm(`"${passId}" silinsin mi?`)) return;
    try {
        await fetch(`${API}/api/passes/${passId}`, { method: 'DELETE' });
        showToast('Geçiş silindi');
        loadPasses();
    } catch (e) {
        showToast('Silme hatası');
    }
}


// =============================================================================
// Lightbox
// =============================================================================
function openLightbox(passId, filename) {
    const lb = document.getElementById('lightbox');
    const img = document.getElementById('lightbox-img');
    const name = document.getElementById('lightbox-name');
    const dl = document.getElementById('lightbox-download');

    img.src = `${API}/api/passes/${passId}/images/${filename}`;
    name.textContent = filename;
    dl.href = `${API}/api/passes/${passId}/download/${filename}`;
    lb.classList.add('active');
}

function closeLightbox() {
    document.getElementById('lightbox').classList.remove('active');
}


// =============================================================================
// Settings
// =============================================================================
async function openSettings() {
    try {
        const res = await fetch(`${API}/api/config`);
        const cfg = await res.json();

        document.getElementById('cfg-lat').value = cfg.observer_lat;
        document.getElementById('cfg-lon').value = cfg.observer_lon;
        document.getElementById('cfg-alt').value = cfg.observer_alt;
        document.getElementById('cfg-elev').value = cfg.min_elevation;
        document.getElementById('cfg-gain').value = cfg.gain;
        document.getElementById('cfg-bias').checked = cfg.bias_tee;
        document.getElementById('cfg-delete-days').value = cfg.auto_delete_days;

        // Bias-T kilit durumu
        const biasCheckbox = document.getElementById('cfg-bias');
        const biasWarning = document.getElementById('bias-lock-warning');
        if (cfg.bias_tee_locked) {
            biasCheckbox.disabled = true;
            biasCheckbox.checked = false;
            biasWarning.style.display = 'inline';
        } else {
            biasCheckbox.disabled = false;
            biasWarning.style.display = 'none';
        }

        // Satellite toggles
        const toggles = document.getElementById('satellite-toggles');
        if (cfg.satellites) {
            toggles.innerHTML = Object.entries(cfg.satellites).map(([name, s]) => `
                <div class="sat-toggle">
                    <div class="sat-toggle-info">
                        <span class="sat-toggle-name">${name}</span>
                        <span class="sat-toggle-freq">${s.frequency_mhz} MHz | NORAD ${s.norad_id} | Öncelik: ${s.priority}</span>
                    </div>
                    <input type="checkbox" id="sat-${name}" ${s.enabled ? 'checked' : ''}>
                </div>
            `).join('');
        }

        document.getElementById('settings-modal').classList.add('active');
    } catch (e) {
        showToast('Ayarlar yüklenemedi');
    }
}

function closeSettings() {
    document.getElementById('settings-modal').classList.remove('active');
}

async function saveSettings() {
    const sats = {};
    document.querySelectorAll('[id^="sat-METEOR"]').forEach(el => {
        const name = el.id.replace('sat-', '');
        sats[name] = { enabled: el.checked };
    });

    const biasChecked = document.getElementById('cfg-bias').checked;
    let biasConfirm = false;

    // Bias-T açılmak isteniyorsa çift onay iste
    if (biasChecked) {
        biasConfirm = confirm(
            '⚠️ UYARI: Bias-T\'yi açmak donanıma zarar verebilir!\n\n'
            + 'Bias-T sadece harici LNA kullanıyorsanız açılmalıdır.\n'
            + 'Emin misiniz?'
        );
        if (!biasConfirm) {
            document.getElementById('cfg-bias').checked = false;
            return;
        }
    }

    const body = {
        observer_lat: parseFloat(document.getElementById('cfg-lat').value),
        observer_lon: parseFloat(document.getElementById('cfg-lon').value),
        observer_alt: parseFloat(document.getElementById('cfg-alt').value),
        min_elevation: parseInt(document.getElementById('cfg-elev').value),
        gain: parseInt(document.getElementById('cfg-gain').value),
        bias_tee: biasChecked,
        bias_tee_confirm: biasConfirm,
        auto_delete_days: parseInt(document.getElementById('cfg-delete-days').value),
        satellites: sats,
    };

    try {
        const res = await fetch(`${API}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const result = await res.json();

        if (result.bias_tee_locked && biasChecked) {
            showToast('🔒 Bias-T güvenlik kilidi aktif — değiştirilemez');
        } else {
            showToast('Ayarlar kaydedildi ✅');
        }
        closeSettings();
    } catch (e) {
        showToast('Kaydetme hatası');
    }
}


// =============================================================================
// Helpers
// =============================================================================
function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setProgress(id, percent) {
    const el = document.getElementById(id);
    if (el) {
        el.style.width = `${Math.min(100, percent)}%`;
        if (percent > 80) el.style.background = 'linear-gradient(90deg, var(--warning), var(--danger))';
    }
}

function formatTime(date) {
    return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
}

function formatDateTime(date) {
    return date.toLocaleString('tr-TR', {
        day: '2-digit', month: '2-digit',
        hour: '2-digit', minute: '2-digit'
    });
}

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}dk ${s}s`;
}

function formatDateHeader(dateStr) {
    try {
        // Non-date strings (e.g. "Manuel Kayıtlar")
        if (!dateStr || !/^\d{4}-\d{2}-\d{2}/.test(dateStr)) return dateStr || 'Bilinmeyen';
        const [y, m, d] = dateStr.split('-');
        const date = new Date(y, m - 1, d);
        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        if (dateStr === today.toISOString().slice(0, 10)) return `Bugün — ${d}.${m}.${y}`;
        if (dateStr === yesterday.toISOString().slice(0, 10)) return `Dün — ${d}.${m}.${y}`;
        return `${d}.${m}.${y}`;
    } catch {
        return dateStr;
    }
}

function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('active');
    setTimeout(() => toast.classList.remove('active'), 3000);
}
