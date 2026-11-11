// tools/workstation_crm_batch.user.js icin jsdom testleri (jsdom repoya eklenmez).
//   npm install --prefix /tmp/jsdom jsdom
//   NODE_PATH=/tmp/jsdom/node_modules node --test tests/workstation_userscript.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const SRC = fs.readFileSync(process.env.USERSCRIPT_PATH ||
  path.join(__dirname, '..', 'tools', 'workstation_crm_batch.user.js'), 'utf8');
const WS = 'https://holiday-treasures.sreforce.com/workstation';

function card(skus, pkg) {
  return `<div class="p-card"><div class="p-card-header"><button aria-label="${pkg || '26---11.11---03.05---1.0---' + skus[0]}"></button></div>` +
    `<div class="p-card-content">${skus.map((s) => `<button class="p-button-lg">${s}\nTitle</button>`).join('')}</div>` +
    `<button aria-label="Accept"></button><button aria-label="Reject"></button></div>`;
}

function setup({ cards = [], url = WS, cfg, stats } = {}) {
  const dom = new JSDOM(`<body><div id="list">${cards.join('')}</div></body>`,
    { url, runScripts: 'outside-only', virtualConsole: new VirtualConsole(), pretendToBeVisual: true });
  const w = dom.window;
  Object.defineProperty(w.HTMLElement.prototype, 'innerText', { get() { return this.textContent; }, configurable: true });
  if (cfg) w.localStorage.setItem('crmBatch.cfg', JSON.stringify(cfg));
  if (stats) w.sessionStorage.setItem('crmBatch.stats', JSON.stringify(stats));
  w.__CRM_BATCH_TEST__ = true;
  w.confirm = () => true;
  w.eval(SRC);
  open.push(w);
  return w;
}

// jsdom penceresindeki dizi/nesneler baska realm'den gelir; karsilastirmadan once duz JSON'a cevir
const plain = (x) => JSON.parse(JSON.stringify(x));
const open = [];
test.afterEach(() => { while (open.length) open.pop().close(); });
const btnByText = (w, t) => [...w.document.querySelectorAll('button')].find((b) => b.textContent === t);
const cards = (w) => [...w.document.querySelectorAll('#list .p-card')];
const savedCfg = (w) => JSON.parse(w.localStorage.getItem('crmBatch.cfg'));

// Paneli taklit eder: Accept -> Yes -> mavi kart (Download/Finish) -> ZIP -> Finish -> Yes -> kart kapanir.
// Tiklanan tum aria-label'lari kaydeder.
//   busyAfterFinishMs: Finish sonrasi panel bu sure listeyi yeniden cizer; bu arada Accept tiklamalari bosa gider
//   ignoreAccepts:     ilk N Accept tiklamasi onay penceresi acmaz ve listeyi yeniden cizer (eski referanslar duser)
//   vanishOnAccept:    bu SKU'lu kartin Accept'i karti listeden siler (baskasi aldi), pencere acilmaz
function simulatePanel(w, { swapSkusTo, busyAfterFinishMs = 0, ignoreAccepts = 0, vanishOnAccept } = {}) {
  const d = w.document;
  const clicks = [];
  let pending = null;
  let busyUntil = 0;
  let ignored = 0;
  const rerender = () => { const l = d.getElementById('list'); if (l) l.innerHTML = l.innerHTML; };
  const dialog = (onYes) => {
    const dlg = d.createElement('div');
    dlg.className = 'p-confirm-dialog';
    dlg.innerHTML = '<button aria-label="Yes"></button><button aria-label="No"></button>';
    d.body.appendChild(dlg);
    pending = () => { dlg.remove(); onYes(); };
  };
  d.addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('button');
    if (!b || !b.getAttribute('aria-label')) return;
    const label = b.getAttribute('aria-label');
    clicks.push(label);
    const c = b.closest('.p-card');
    if (label === 'Accept') {
      if (Date.now() < busyUntil) return;
      if (vanishOnAccept && c.textContent.includes(vanishOnAccept)) { c.remove(); return; }
      if (ignored < ignoreAccepts) { ignored++; setTimeout(rerender, 100); return; }
      dialog(() => {
        c.classList.add('bg-blue-50');
        c.querySelectorAll('[aria-label="Accept"],[aria-label="Reject"]').forEach((x) => x.remove());
        if (swapSkusTo) c.querySelector('.p-card-content').innerHTML = `<button class="p-button-lg">${swapSkusTo}</button>`;
        c.insertAdjacentHTML('beforeend', '<button aria-label="Download the package"></button>' +
          '<button aria-label="Send for Admin Review"></button><button aria-label="Reject"></button>' +
          '<button aria-label="Finish"></button>');
      });
    } else if (label === 'Yes') {
      setTimeout(pending, 50);
    } else if (label === 'Download the package') {
      const a = d.createElement('a');
      a.download = c.querySelector('.p-card-header button').getAttribute('aria-label') + '.zip';
      setTimeout(() => a.click(), 100);
    } else if (label === 'Finish') {
      dialog(() => {
        c.remove();
        if (busyAfterFinishMs) {
          busyUntil = Date.now() + busyAfterFinishMs;
          setTimeout(rerender, 500);
          setTimeout(rerender, busyAfterFinishMs);
        }
      });
    }
  }, true);
  return clicks;
}

test('onek listesi ayristirma', () => {
  const w = setup();
  assert.deepStrictEqual(plain(w.__crmBatch.parsePrefixes(' CRM, acry ,, ')), ['crm', 'acry']);
  assert.strictEqual(w.__crmBatch.cfg.prefixes, 'crm,acry');   // varsayilan
  w.close();
});

test('en az bir SKU listede ise islenir; diger SKU ayrica isaretlenir', () => {
  const w = setup({ cards: [card(['crmc1246']), card(['crm1228', 'gx55']), card(['ro-1', 'po-2']), card(['acry2001'])] });
  const [a, mixed, none, acry] = cards(w);
  const t = w.__crmBatch;
  assert.deepStrictEqual([a, mixed, none, acry].map(t.isEligible), [true, true, false, true]);
  assert.deepStrictEqual([a, mixed, none, acry].map(t.hasOther), [false, true, true, false]);
  w.close();
});

test('onizleme cerceveler ve sayar, hicbir seye tiklamaz', () => {
  const w = setup({ cards: [card(['crmc1']), card(['crm2', 'GX1']), card(['ai-r02f-0r3l']), card(['acry3']), card(['DS9'])] });
  const clicks = simulatePanel(w);
  btnByText(w, 'Onizle').click();
  assert.deepStrictEqual(cards(w).map((c) => c.style.outline),
    ['4px solid orange', '4px dashed orange', '4px solid gray', '4px solid orange', '4px solid gray']);
  const status = w.document.body.textContent;
  assert.match(status, /Islenecek: 3/);
  assert.match(status, /Listede olmayan SKU iceren: 1/);
  assert.match(status, /Atlanacak: 2/);
  assert.deepStrictEqual(clicks, []);
  w.close();
});

test('onek kutusu localStorage a yazilir ve yenilemede kullanilir', () => {
  const w = setup();
  const input = [...w.document.querySelectorAll('input[type="text"]')][0];
  input.value = ' CRM ,  ';
  input.dispatchEvent(new w.Event('change'));
  assert.strictEqual(savedCfg(w).prefixes, 'crm');
  w.close();
  const w2 = setup({ cfg: { prefixes: 'crm' }, cards: [card(['acry1']), card(['crmc1'])] });
  assert.deepStrictEqual(cards(w2).map(w2.__crmBatch.isEligible), [false, true]);
  w2.close();
});

test('ardisik 3 hatali turda otomatik mod kapanir, DURDU basligi', () => {
  const w = setup({ cfg: { auto: false } });
  const t = w.__crmBatch;
  t.cfg.auto = true;
  t.recordRound(false, 'x');
  t.recordRound(true);                       // basari sayaci sifirlar
  t.recordRound(false, 'a');
  t.recordRound(false, 'b');
  assert.strictEqual(t.cfg.auto, true);
  assert.strictEqual(t.stats.errors, 2);
  t.recordRound(false, 'ZIP sinyali yok');
  assert.strictEqual(t.cfg.auto, false);
  assert.strictEqual(savedCfg(w).auto, false);
  assert.strictEqual(w.document.title, 'DURDU');
  assert.match(t.stats.lastError, /Ardisik 3 tur hata/);
  w.close();
});

test('login sayfasinda otomatik mod kapanir, arayuz kurulmaz', () => {
  const w = setup({ url: 'https://holiday-treasures.sreforce.com/login', cfg: { auto: true } });
  assert.strictEqual(savedCfg(w).auto, false);
  assert.strictEqual(w.document.title, 'DURDU');
  assert.strictEqual(btnByText(w, 'Onizle'), undefined);
  w.close();
});

test('otomatik tur: mavi kart varken baslamaz; onceki hatadan kalan mavi kart hata sayilir', async () => {
  const blue = card(['crmc1']).replace('class="p-card"', 'class="p-card bg-blue-50"');
  const w = setup({ cards: [blue, card(['crmc2'])], cfg: { auto: true }, stats: { errors: 0 } });
  const clicks = simulatePanel(w);
  const t = w.__crmBatch;
  await t.autoTick();
  assert.strictEqual(t.stats.errors, 0);      // kullanici calisiyor olabilir: sadece bekler
  t.stats.errors = 2;
  await t.autoTick();
  assert.strictEqual(t.cfg.auto, false);      // 3. ardisik hata
  assert.deepStrictEqual(clicks, []);
  w.close();
});

test('tur: uygun paketleri isler, atlananlara ve Reject/Admin Review a dokunmaz', async () => {
  const w = setup({ cards: [card(['gx1']), card(['crmc5', 'po-9']), card(['acry7'])] });
  const clicks = simulatePanel(w);
  const r = await w.__crmBatch.runRound(true);
  assert.deepStrictEqual(plain(r), { ok: true, count: 2, error: '' });
  assert.strictEqual(w.__crmBatch.stats.total, 2);
  assert.ok(w.__crmBatch.stats.lastOkAt);
  assert.deepStrictEqual(cards(w).length, 1);  // sadece gx1 kaldi
  assert.ok(!clicks.includes('Reject') && !clicks.includes('Send for Admin Review'));
  assert.deepStrictEqual(clicks.filter((c) => c === 'Finish').length, 2);
  assert.match(w.document.body.textContent, /crmc5,po-9 .*dikkat: diger SKU iceriyor/);
  w.close();
});

test('Accept sonrasi farkli paket acilirsa tur durur, paket acik kalir, Finish e basilmaz', async () => {
  const w = setup({ cards: [card(['crmc1']), card(['crmc2'])] });
  const clicks = simulatePanel(w, { swapSkusTo: 'crmc999' });
  const r = await w.__crmBatch.runRound(true);
  assert.strictEqual(r.ok, false);
  assert.match(r.error, /Beklenmeyen paket/);
  assert.ok(w.document.querySelector('.p-card.bg-blue-50'));
  assert.deepStrictEqual(clicks, ['Accept', 'Yes']);   // ikinci pakete gecilmedi
  w.close();
});

const acceptCount = (clicks) => clicks.filter((c) => c === 'Accept').length;

test('iki paket arka arkaya: Finish sonrasi panel yeniden cizerken ikinci Accept bosa gitmez', async () => {
  const w = setup({ cards: [card(['crmc1']), card(['crmc2'])] });
  const clicks = simulatePanel(w, { busyAfterFinishMs: 3500 });
  const r = await w.__crmBatch.runRound(true);
  assert.deepStrictEqual(plain(r), { ok: true, count: 2, error: '' });
  assert.strictEqual(acceptCount(clicks), 2);
  assert.strictEqual(cards(w).length, 0);
});

test('Accept 1. denemede pencere acmaz (liste yeniden cizilir), 2. denemede taze kartla basarili', async () => {
  const w = setup({ cards: [card(['crmc1'])] });
  const clicks = simulatePanel(w, { ignoreAccepts: 1 });
  const r = await w.__crmBatch.runRound(true);
  assert.deepStrictEqual(plain(r), { ok: true, count: 1, error: '' });
  assert.strictEqual(acceptCount(clicks), 2);
  assert.match(w.document.body.textContent, /deneme 1\/3/);
});

test('Accept 3 denemede de pencere acmazsa tani bilgisiyle hata, tur durur, sonraki pakete gecilmez', async () => {
  const w = setup({ cards: [card(['crmc1']), card(['crmc2'])] });
  const clicks = simulatePanel(w, { ignoreAccepts: 99 });
  const logs = [];
  w.console.log = (...a) => logs.push(a.join(' '));
  const r = await w.__crmBatch.runRound(true);
  assert.strictEqual(r.ok, false);
  assert.match(r.error, /3 deneme basarisiz/);
  assert.match(r.error, /deneme 3\/3, dialog\/mask: 0, dialog dugmeleri: \[\], tiklanan kart DOM da: hayir.*kart dugmeleri: \[26---.*crmc1, crmc1 Title, Accept, Reject\]/);
  assert.strictEqual(acceptCount(clicks), 3);
  assert.deepStrictEqual(plain(clicks), ['Accept', 'Accept', 'Accept']);
  assert.ok(logs.some((l) => /deneme 3\/3/.test(l)));
  assert.match(w.__crmBatch.stats.lastError, /3 deneme basarisiz/);
});

test('hedef paket kaybolursa hata sayilmaz, sonraki uygun pakete gecilir', async () => {
  const w = setup({ cards: [card(['crmc1']), card(['crmc2'])] });
  const clicks = simulatePanel(w, { vanishOnAccept: 'crmc1' });
  const r = await w.__crmBatch.runRound(true);
  assert.deepStrictEqual(plain(r), { ok: true, count: 1, error: '' });
  assert.deepStrictEqual(plain(clicks).filter((c) => c !== 'Download the package'), ['Accept', 'Accept', 'Yes', 'Finish', 'Yes']);
  assert.match(w.document.body.textContent, /Paket bulunamadi/);
});

test('Accept hatasi otomatik mod hata sayacini artirir', async () => {
  const w = setup({ cards: [card(['crmc1'])], cfg: { auto: true }, stats: { errors: 2 } });
  simulatePanel(w, { ignoreAccepts: 99 });
  await w.__crmBatch.autoTick();
  assert.strictEqual(w.__crmBatch.stats.errors, 3);
  assert.strictEqual(w.__crmBatch.cfg.auto, false);
});
