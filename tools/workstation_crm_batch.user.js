// ==UserScript==
// @name         Workstation CRM Toplu Isleme
// @namespace    autoprint
// @version      1.2
// @description  Listedeki SKU oneklerinden en az birini iceren paketleri sirayla Accept, Download, Finish yapar
// @match        https://*.sreforce.com/workstation*
// @match        https://*.sreforce.com/login*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  var MAX_DEFAULT = 25;          // tek turda en fazla paket
  var PREFIXES_DEFAULT = 'crm,acry';
  var INTERVAL_DEFAULT = 5;      // otomatik mod kontrol araligi (dk)
  var REFRESH_DEFAULT = 15;      // otomatik modda sayfa yenileme araligi (dk)
  var MAX_ERRORS = 3;            // ardisik bu kadar hatali turda otomatik mod kapanir
  var ACCEPT_TRIES = 3;          // Accept onay penceresi icin deneme sayisi
  var NEXT_DELAY = 5000;         // Finish sonrasi bir sonraki Accept'ten once bekleme
  var LS = 'crmBatch.';
  var state = { running: false, stop: false, zips: [] };

  // ---- Ayarlar (localStorage) ve oturum istatistikleri (sessionStorage, yenilemede kalir) ----
  function load(store, key, def) {
    try { var v = store.getItem(LS + key); return v === null ? def : JSON.parse(v); } catch (x) { return def; }
  }
  function save(store, key, v) {
    try { store.setItem(LS + key, JSON.stringify(v)); } catch (x) {}
  }
  var cfg = Object.assign({ prefixes: PREFIXES_DEFAULT, max: MAX_DEFAULT, interval: INTERVAL_DEFAULT,
                            refresh: REFRESH_DEFAULT, auto: false }, load(localStorage, 'cfg', {}));
  var stats = Object.assign({ lastOkAt: null, total: 0, lastError: '', errors: 0 }, load(sessionStorage, 'stats', {}));
  function saveCfg() { save(localStorage, 'cfg', cfg); }
  function saveStats() { save(sessionStorage, 'stats', stats); }

  var timer = null, nextCheckAt = null, blinkTimer = null, pageLoadedAt = Date.now();
  var autoCb = null, statusEl = null, infoEl = null;

  // ---- Oturum dustu mu: login sayfasi / login formu ----
  function sessionLost() {
    return /\/login/i.test(location.pathname) || !!document.querySelector('input[type="password"]');
  }

  // Login sayfasinda arayuz kurulmaz; otomatik mod aciksa kapatilir ve uyari verilir
  if (sessionLost()) {
    if (cfg.auto) haltAuto('Oturum dustu (login sayfasi).');
    return;
  }

  // ---- Indirme sinyali: panel ZIP'i <paket-kimligi>.zip adli bir link tiklamasiyla indiriyor ----
  var _de = EventTarget.prototype.dispatchEvent;
  EventTarget.prototype.dispatchEvent = function (e) {
    try {
      if (this instanceof HTMLAnchorElement && e && e.type === 'click' && /\.zip$/i.test(this.download || '')) {
        state.zips.push(this.download);
      }
    } catch (x) {}
    return _de.apply(this, arguments);
  };
  var _ac = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    try {
      if (/\.zip$/i.test(this.download || '')) state.zips.push(this.download);
    } catch (x) {}
    return _ac.apply(this, arguments);
  };

  // ---- Yardimcilar ----
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function waitFor(fn, ms) {
    var t = Date.now();
    while (Date.now() - t < (ms || 15000)) {
      var v = fn();
      if (v) return v;
      await sleep(250);
    }
    return null;
  }

  // Butonlar SADECE tam aria-label eslesmesiyle secilir (Reject ve "Send for Admin Review" asla secilmez)
  function btn(root, label) {
    return Array.prototype.find.call(root.querySelectorAll('button'), function (b) {
      return b.getAttribute('aria-label') === label;
    });
  }

  function skusOf(card) {
    var out = [];
    card.querySelectorAll('.p-card-content .p-button-lg').forEach(function (b) {
      var s = b.innerText.trim().split('\n')[0].trim().toLowerCase();
      if (s && out.indexOf(s) === -1) out.push(s);
    });
    return out;
  }

  function parsePrefixes(text) {
    return String(text || '').split(',').map(function (p) { return p.trim().toLowerCase(); })
      .filter(function (p) { return p; });
  }

  function listed(sku) {
    return parsePrefixes(cfg.prefixes).some(function (p) { return sku.indexOf(p) === 0; });
  }

  // En az bir SKU listedeki bir onekle basliyorsa paket islenir
  function isEligible(card) { return skusOf(card).some(listed); }

  // Islenecek pakette listede olmayan SKU da var mi
  function hasOther(card) { return skusOf(card).some(function (s) { return !listed(s); }); }

  function pendingCards() {
    return Array.prototype.map.call(
      document.querySelectorAll('button[aria-label="Accept"]'),
      function (b) { return b.closest('.p-card'); }
    );
  }

  function currentCard() { return document.querySelector('.p-card.bg-blue-50'); }

  function yesButton() {
    return Array.prototype.find.call(
      document.querySelectorAll('.p-confirm-dialog button, .p-dialog button'),
      function (b) { return b.getAttribute('aria-label') === 'Yes'; }
    );
  }

  function pkgIdOf(card) {
    var ids = Array.prototype.map.call(card.querySelectorAll('.p-card-header button'), function (b) {
      return b.getAttribute('aria-label') || '';
    });
    return ids.find(function (a) { return /---/.test(a); }) || '';
  }

  // Bekleyen kart, indeks yerine paket kimligiyle (yoksa SKU listesiyle) taze olarak bulunur
  function findPending(id, want) {
    return pendingCards().find(function (c) {
      return c && (id ? pkgIdOf(c) === id : skusOf(c).join(',') === want);
    }) || null;
  }

  // Finish sonrasi panel listeyi yeniden cizer: kart sayisi ve Accept referanslari 1.5 sn
  // degismeyene kadar bekle (en fazla 15 sn)
  async function waitListSettled() {
    function snap() { return Array.prototype.slice.call(document.querySelectorAll('button[aria-label="Accept"]')); }
    var t0 = Date.now(), last = snap(), stableSince = Date.now();
    while (Date.now() - t0 < 15000) {
      await sleep(250);
      var now = snap();
      var same = now.length === last.length && now.every(function (b, i) { return b === last[i]; });
      if (!same) { last = now; stableSince = Date.now(); }
      else if (Date.now() - stableSince >= 1500) return true;
    }
    return false;
  }

  function labelsOf(nodes) {
    return Array.prototype.map.call(nodes, function (b) { return b.getAttribute('aria-label') || b.textContent.trim().replace(/\s+/g, ' '); });
  }

  // Tani: Accept sonrasi sayfadaki dialog/mask sayisi ve bulunan dugmeler
  function acceptDiag(card, id, want, attempt) {
    var fresh = findPending(id, want);
    var dlgs = document.querySelectorAll('.p-dialog, .p-confirm-dialog, .p-dialog-mask, .p-component-overlay, [role="dialog"], [role="alertdialog"]');
    var dlgBtns = [];
    Array.prototype.forEach.call(dlgs, function (d) { dlgBtns = dlgBtns.concat(labelsOf(d.querySelectorAll('button'))); });
    return 'deneme ' + attempt + '/' + ACCEPT_TRIES + ', dialog/mask: ' + dlgs.length +
      ', dialog dugmeleri: [' + dlgBtns.join(', ') + ']' +
      ', tiklanan kart DOM da: ' + (card && card.isConnected ? 'evet' : 'hayir (liste yeniden cizilmis)') +
      ', kart dugmeleri: [' + (fresh ? labelsOf(fresh.querySelectorAll('button')).join(', ') : 'kart bulunamadi') + ']';
  }

  // Accept + onay penceresi, en fazla ACCEPT_TRIES deneme. Hedef her denemede taze bulunur.
  async function acceptWithRetry(id, want) {
    var diag = '';
    for (var attempt = 1; attempt <= ACCEPT_TRIES; attempt++) {
      if (currentCard()) {
        return { fail: true, msg: 'Accept oncesi beklenmeyen acik paket (mavi kart) var. Dokunulmadi, elle kontrol et.' };
      }
      var card = findPending(id, want);
      var a = card && btn(card, 'Accept');
      if (!a) return { gone: true };
      a.click();
      var y = await waitFor(yesButton, 6000);
      if (y) return { yes: y };
      diag = acceptDiag(card, id, want, attempt);
      say('Accept onay penceresi cikmadi (' + diag + ')');
      if (attempt < ACCEPT_TRIES) await sleep(2000);
    }
    return { fail: true, msg: 'Accept onay penceresi cikmadi, ' + ACCEPT_TRIES + ' deneme basarisiz. Tani: ' + diag };
  }

  function hhmm(t) {
    if (!t) return '-';
    var d = new Date(t);
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }

  // ---- Durdu uyarisi: baslik yanip soner + kisa ses ----
  function beep() {
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      var ctx = new AC();
      if (ctx.state === 'suspended') { ctx.close(); return; }   // kullanici etkilesimi yok, sessizce atla
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; g.gain.value = 0.2;
      o.connect(g); g.connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + 0.6);
      setTimeout(function () { ctx.close(); }, 1000);
    } catch (x) {}
  }

  function stopBlink() {
    if (blinkTimer) { clearInterval(blinkTimer); blinkTimer = null; document.title = 'CRM Toplu Isleme'; }
  }

  function haltAuto(reason) {
    cfg.auto = false; saveCfg();
    if (autoCb) autoCb.checked = false;
    clearTimeout(timer); timer = null; nextCheckAt = null;
    stats.lastError = hhmm(Date.now()) + ' ' + reason; saveStats();
    stopBlink();
    var on = true;
    document.title = 'DURDU';
    blinkTimer = setInterval(function () { on = !on; document.title = on ? 'DURDU' : '!!! DURDU !!!'; }, 1000);
    beep();
    if (statusEl) say('DURDU: ' + reason + ' Otomatik mod kapatildi.');
  }

  // ---- Arayuz ----
  var box = document.createElement('div');
  box.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:99999;background:#fff;border:2px solid #333;border-radius:8px;padding:10px;font:13px/1.4 sans-serif;width:280px;box-shadow:0 2px 10px rgba(0,0,0,.3);color:#111';
  var title = document.createElement('div');
  title.textContent = 'CRM Toplu Isleme';
  title.style.cssText = 'font-weight:bold;margin-bottom:6px';

  function row(label, input) {
    var r = document.createElement('div');
    r.textContent = label;
    r.style.cssText = 'margin-top:3px';
    input.style.cssText = 'margin-left:4px;width:' + (input.type === 'text' ? '120px' : '60px');
    r.appendChild(input);
    return r;
  }
  function numInput(min, max, value) {
    var i = document.createElement('input');
    i.type = 'number'; i.min = String(min); i.max = String(max); i.value = String(value);
    return i;
  }

  var prefixInput = document.createElement('input');
  prefixInput.type = 'text'; prefixInput.value = cfg.prefixes;
  prefixInput.onchange = function () {
    cfg.prefixes = parsePrefixes(prefixInput.value).join(',') || PREFIXES_DEFAULT;
    prefixInput.value = cfg.prefixes; saveCfg();
    say('SKU onekleri: ' + cfg.prefixes);
  };
  var maxInput = numInput(1, 100, cfg.max);
  maxInput.onchange = function () { cfg.max = readMax(); maxInput.value = String(cfg.max); saveCfg(); };
  var intervalInput = numInput(1, 120, cfg.interval);
  intervalInput.onchange = function () {
    cfg.interval = Math.max(1, parseInt(intervalInput.value, 10) || INTERVAL_DEFAULT); saveCfg();
    if (cfg.auto && !state.running) schedule(cfg.interval * 60000);
  };
  var refreshInput = numInput(1, 240, cfg.refresh);
  refreshInput.onchange = function () { cfg.refresh = Math.max(1, parseInt(refreshInput.value, 10) || REFRESH_DEFAULT); saveCfg(); };

  autoCb = document.createElement('input');
  autoCb.type = 'checkbox'; autoCb.checked = !!cfg.auto;
  var autoRow = document.createElement('label');
  autoRow.style.cssText = 'display:block;margin-top:6px;font-weight:bold;cursor:pointer';
  autoRow.appendChild(autoCb);
  autoRow.appendChild(document.createTextNode(' Otomatik mod'));

  var bPreview = document.createElement('button'); bPreview.textContent = 'Onizle';
  var bStart = document.createElement('button'); bStart.textContent = 'Baslat';
  var bStop = document.createElement('button'); bStop.textContent = 'Durdur';
  [bPreview, bStart, bStop].forEach(function (b) { b.style.cssText = 'margin:6px 6px 0 0;padding:4px 10px;cursor:pointer'; });
  infoEl = document.createElement('div');
  infoEl.style.cssText = 'margin-top:8px;padding:4px;background:#f3f3f3;white-space:pre-wrap;font-size:12px';
  statusEl = document.createElement('div');
  statusEl.style.cssText = 'margin-top:8px;max-height:180px;overflow:auto;white-space:pre-wrap;font-size:12px';
  [title,
   row('SKU onekleri:', prefixInput),
   row('Tur basina en fazla paket:', maxInput),
   autoRow,
   row('Kontrol araligi (dk):', intervalInput),
   row('Sayfa yenileme (dk):', refreshInput),
   bPreview, bStart, bStop, infoEl, statusEl].forEach(function (e) { box.appendChild(e); });
  document.body.appendChild(box);

  var lines = [];
  function say(msg) {
    lines.push(msg);
    if (lines.length > 40) lines.shift();
    statusEl.textContent = lines.join('\n');
    statusEl.scrollTop = statusEl.scrollHeight;
    console.log('[CRM]', msg);
    renderInfo();
  }

  function renderInfo() {
    infoEl.textContent =
      'Son basarili indirme: ' + hhmm(stats.lastOkAt) + '\n' +
      'Bu oturumda islenen: ' + stats.total + ' paket\n' +
      'Son hata: ' + (stats.lastError || '-') + '\n' +
      'Sonraki kontrol: ' + (cfg.auto ? hhmm(nextCheckAt) : 'otomatik mod kapali');
  }

  function readMax() {
    return Math.max(1, Math.min(100, parseInt(maxInput.value, 10) || MAX_DEFAULT));
  }

  // ---- Onizleme: hicbir seye tiklamaz, sadece isaretler ----
  bPreview.onclick = function () {
    var cards = pendingCards();
    var n = 0, other = 0, skip = 0;
    cards.forEach(function (c) {
      if (!isEligible(c)) { c.style.outline = '4px solid gray'; skip++; return; }
      n++;
      if (hasOther(c)) { c.style.outline = '4px dashed orange'; other++; }
      else c.style.outline = '4px solid orange';
    });
    say('Onizleme (' + cfg.prefixes + '): ' + cards.length + ' paket. Islenecek: ' + n +
        ' (turuncu), Listede olmayan SKU iceren: ' + other + ' (kesikli), Atlanacak: ' + skip + ' (gri).');
  };

  bStop.onclick = function () { state.stop = true; say('Durdurma istendi, mevcut paket bitince duracak.'); };

  // ---- Tek paket: Accept (+onay) -> Download (ZIP sinyali) -> Finish (+onay) ----
  async function processOne(skipIds) {
    var cards = pendingCards().filter(function (c) { return isEligible(c) && skipIds.indexOf(pkgIdOf(c) || skusOf(c).join(',')) === -1; });
    if (!cards.length) return { done: true, msg: 'Islenecek paket kalmadi.' };
    var target = cards[0];
    var id = pkgIdOf(target);
    var want = skusOf(target).join(',');
    var other = hasOther(target);

    var acc = await acceptWithRetry(id, want);
    if (acc.gone) return { skip: id || want, msg: 'Paket bulunamadi (baskasi almis veya kaybolmus olabilir), sonrakine geciliyor: ' + (id || want) };
    if (acc.fail) return acc;
    var y1 = acc.yes;
    y1.click();

    var cur = await waitFor(currentCard, 15000);
    if (!cur) return { fail: true, msg: 'Accept sonrasi paket sola gecmedi.' };
    if (skusOf(cur).join(',') !== want) {
      return { fail: true, msg: 'Beklenmeyen paket acildi (' + skusOf(cur).join(',') + '). Dokunulmadi, elle kontrol et.' };
    }
    var pkg = pkgIdOf(cur);

    var dl = await waitFor(function () { return btn(cur, 'Download the package'); }, 15000);
    if (!dl) return { fail: true, msg: 'Download butonu cikmadi. Paket sende acik kaldi: ' + pkg };
    var before = state.zips.length;
    dl.click();
    var zip = await waitFor(function () {
      return state.zips.slice(before).find(function (z) { return !pkg || z.indexOf(pkg) !== -1; });
    }, 30000);
    if (!zip) return { fail: true, msg: 'ZIP indirme sinyali gelmedi, Finish a BASILMADI. Paket acik: ' + pkg };

    await sleep(1500);
    btn(cur, 'Finish').click();
    var y2 = await waitFor(yesButton, 10000);
    if (!y2) return { fail: true, msg: 'Finish onay penceresi cikmadi. Paket acik: ' + pkg };
    y2.click();
    var gone = await waitFor(function () { return !currentCard(); }, 15000);
    if (!gone) return { fail: true, msg: 'Finish sonrasi paket kapanmadi: ' + pkg };

    return { ok: true, msg: want + '  ->  ' + zip, other: other };
  }

  // ---- Tur: hata veren paket acik kalir, tur durur, sonraki paketlere gecilmez ----
  async function runRound(auto) {
    if (state.running) { say('Zaten calisiyor.'); return null; }
    if (currentCard()) {
      say('DURDU: Zaten uzerinde calisilan bir paket var (mavi kart). Once onu elle bitir.');
      return null;
    }
    var max = readMax();
    var n = pendingCards().filter(isEligible).length;
    if (!n) { say('Islenecek paket yok (' + cfg.prefixes + ').'); return { ok: true, count: 0 }; }
    var toDo = Math.min(max, n);
    if (!auto && !window.confirm(toDo + ' paket islenecek (Accept, Download, Finish).\nDevam edilsin mi?')) return null;

    state.running = true; state.stop = false;
    var okCount = 0, failed = '';
    say('Basladi: en fazla ' + toDo + ' paket.');
    try {
      var skipIds = [];
      while (okCount < toDo && !state.stop) {
        var r = await processOne(skipIds);
        if (r.done) { say(r.msg); break; }
        if (r.fail) { failed = r.msg; say('HATA: ' + r.msg); break; }
        if (r.skip) { skipIds.push(r.skip); say(r.msg); continue; }
        okCount++;
        stats.total++; stats.lastOkAt = Date.now(); saveStats();
        say(okCount + '/' + toDo + '  ' + r.msg + (r.other ? '  (dikkat: diger SKU iceriyor)' : ''));
        if (okCount < toDo && !state.stop) {
          await sleep(NEXT_DELAY);
          if (!(await waitListSettled())) say('Kart listesi 15 sn icinde yerlesmedi, yine de devam ediliyor.');
        }
      }
    } catch (err) {
      failed = 'Beklenmeyen hata: ' + err;
      say(failed);
    }
    state.running = false;
    if (failed) { stats.lastError = hhmm(Date.now()) + ' ' + failed; saveStats(); }
    say('Bitti. Islenen: ' + okCount + ' paket. Downloads klasorundeki ZIP sayisiyla karsilastir.');
    return { ok: !failed, count: okCount, error: failed };
  }

  bStart.onclick = function () { runRound(false); };

  // ---- Otomatik mod ----
  function recordRound(ok, err) {
    if (ok) { stats.errors = 0; saveStats(); return; }
    stats.errors = (stats.errors || 0) + 1; saveStats();
    if (stats.errors >= MAX_ERRORS) haltAuto('Ardisik ' + stats.errors + ' tur hata. Son: ' + err);
  }

  function schedule(ms) {
    clearTimeout(timer);
    nextCheckAt = Date.now() + ms;
    timer = setTimeout(autoTick, ms);
    renderInfo();
  }

  function refreshDue() { return Date.now() - pageLoadedAt >= cfg.refresh * 60000; }

  // Uzerinde calisilan paket veya devam eden tur varken asla yenilenmez
  function maybeReload() {
    if (cfg.auto && !state.running && !currentCard() && refreshDue()) {
      say('Sayfa yenileniyor (' + cfg.refresh + ' dk doldu).');
      location.reload();
      return true;
    }
    return false;
  }

  async function autoTick() {
    timer = null; nextCheckAt = null;
    if (!cfg.auto) return;
    if (sessionLost()) { haltAuto('Oturum dustu (login).'); return; }
    if (state.running) { schedule(cfg.interval * 60000); return; }
    var r;
    if (currentCard()) {
      // Onceki turun hatasindan kalan acik paket hata sayilir; kullanici elle calisiyorsa sadece beklenir
      if (stats.errors > 0) {
        r = { ok: false, error: 'Onceki hatadan kalan acik paket (mavi kart) duruyor.' };
        say('Otomatik: ' + r.error);
      } else {
        say('Otomatik: mavi kart var, bekleniyor.');
        schedule(cfg.interval * 60000);
        return;
      }
    } else {
      r = await runRound(true);
    }
    if (r) recordRound(r.ok, r.error);
    if (!cfg.auto) return;
    if (maybeReload()) return;
    schedule(cfg.interval * 60000);
  }

  autoCb.onchange = function () {
    if (autoCb.checked) {
      if (!window.confirm('Otomatik mod: her ' + cfg.interval + ' dk bekleyen uygun paketler (' + cfg.prefixes +
          ') sirayla Accept, Download, Finish yapilacak, sayfa ' + cfg.refresh + ' dk da bir yenilenecek.\n' +
          'Reject ve Send for Admin Review e dokunulmaz.\nAcilsin mi?')) {
        autoCb.checked = false;
        return;
      }
      cfg.auto = true; saveCfg();
      stats.errors = 0; saveStats();
      stopBlink();
      say('Otomatik mod acildi.');
      schedule(2000);
    } else {
      cfg.auto = false; saveCfg();
      clearTimeout(timer); timer = null; nextCheckAt = null;
      say('Otomatik mod kapatildi.');
    }
  };

  // Bosta periyodik yenileme + SPA icinde login'e dusme kontrolu
  setInterval(function () {
    if (!cfg.auto) return;
    if (sessionLost()) { haltAuto('Oturum dustu (login).'); return; }
    maybeReload();
  }, 30000);

  renderInfo();
  if (cfg.auto) {
    say('Otomatik mod devam ediyor (sayfa yenilendi).');
    schedule(5000);
  }

  if (window.__CRM_BATCH_TEST__) {
    window.__crmBatch = { parsePrefixes: parsePrefixes, isEligible: isEligible, hasOther: hasOther,
                          recordRound: recordRound, autoTick: autoTick, runRound: runRound,
                          cfg: cfg, stats: stats, state: state };
  }
})();
