// Audit_Templates.jsx
// =========================================================================
// Template denetimi: her template'e örnek metinleri Render_Sheet.jsx ile AYNI
// fitText mantığıyla (data/FitText.jsxinc) yerleştirir, metin kutusu sınırlarını
// ince kırmızı çizgiyle gösterir ve data/audit/<SKU>_<font>.png olarak kaydeder.
// Template dosyaları KAYDEDİLMEDEN kapatılır — asla değişmez.
//
// Çalıştırma: File > Scripts > Other Script... > Audit_Templates.jsx
// Sonra kontak sayfası: python3 tools/contact_sheet.py
// =========================================================================

// --- AYARLAR ---
var TEMPLATE_FOLDER = "round_ceramic";          // round_ceramic / heart_ceramic / dog_round / snowglobe
var AUDIT_FONTS = ["MonotypeCorsiva", "Allstar-Regular", "PlayfairDisplay-Regular"];  // Illustrator PostScript adları; boşsa MonotypeCorsiva
var SAMPLE_TEXTS = {
    name: "Maximilian Alexander",
    year: "2026",
    message: "Merry Christmas Everyone"
};
var START_INDEX = 0;                            // alfabetik template listesinde başlangıç sırası
var BATCH_SIZE = 40;                            // bir çalıştırmada en fazla bu kadar template
// data/audit_skus.txt varsa (satır başına bir SKU) sadece o SKU'lar taranır; START_INDEX/BATCH_SIZE yok sayılır.

// Komut satırından (osascript) çalıştırırken ayarları ezmek için:
// AUDIT_OVERRIDES global'i tanımlıysa onun alanları kullanılır.
if (typeof AUDIT_OVERRIDES !== "undefined") {
    for (var k in AUDIT_OVERRIDES) {
        if (k === "TEMPLATE_FOLDER") TEMPLATE_FOLDER = AUDIT_OVERRIDES[k];
        if (k === "AUDIT_FONTS") AUDIT_FONTS = AUDIT_OVERRIDES[k];
        if (k === "START_INDEX") START_INDEX = AUDIT_OVERRIDES[k];
        if (k === "BATCH_SIZE") BATCH_SIZE = AUDIT_OVERRIDES[k];
        if (k === "QUIET") var AUDIT_QUIET = AUDIT_OVERRIDES[k];
    }
}

(function () {
    var ROOT = "/Users/melkarakas/Desktop/autoprint-enterprise";
    var TEMPLATES_ROOT = "/Users/melkarakas/Desktop/AutoPrint/templates";   // sadece okunur
    var OUT = Folder(ROOT + "/data/audit");
    var PNG_SCALE = 200;   // %200 → kontak sayfasında net görünsün

    $.evalFile(File(ROOT + "/data/FitText.jsxinc"));
    var S = AP_FIT.SIZES;

    var prevLevel = app.userInteractionLevel;
    try { app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS; } catch (e) {}

    if (!OUT.exists) OUT.create();
    var fonts = (AUDIT_FONTS && AUDIT_FONTS.length) ? AUDIT_FONTS : ["MonotypeCorsiva"];

    var folder = Folder(TEMPLATES_ROOT + "/" + TEMPLATE_FOLDER);
    if (!folder.exists) return finish("AUDIT_RESULT hata: klasör yok " + folder.fsName);

    var files = folder.getFiles(function (f) { return (f instanceof File) && /\.ai$/i.test(f.name); });
    files.sort(function (a, b) { var x = decodeURI(a.name).toLowerCase(), y = decodeURI(b.name).toLowerCase(); return x < y ? -1 : x > y ? 1 : 0; });
    var pngCount = 0, errors = [], problems = [], skipped = [], notFound = [];

    // Opsiyonel SKU listesi
    var skuFile = File(ROOT + "/data/audit_skus.txt"), skuMode = false;
    if (skuFile.exists) {
        skuFile.encoding = "UTF-8"; skuFile.open("r");
        var wanted = {}, wantedList = [], line;
        while (!skuFile.eof) {
            line = skuFile.readln().replace(/^\s+|\s+$/g, "");
            if (line && line.charAt(0) !== "#" && !wanted[line.toUpperCase()]) { wanted[line.toUpperCase()] = true; wantedList.push(line); }
        }
        skuFile.close();
        if (wantedList.length) {
            skuMode = true;
            var picked = [], found = {};
            for (var w = 0; w < files.length; w++) {
                var key = skuOf(files[w]).toUpperCase();
                if (wanted[key]) { picked.push(files[w]); found[key] = true; }
            }
            for (var w2 = 0; w2 < wantedList.length; w2++) if (!found[wantedList[w2].toUpperCase()]) notFound.push(wantedList[w2]);
            files = picked; START_INDEX = 0; BATCH_SIZE = files.length;
        }
    }
    var end = Math.min(START_INDEX + BATCH_SIZE, files.length);

    // Hiç metin alanı / kutusu olmayan template (örn. A-DENEME) → atlanır
    function hasTextFields(doc) {
        for (var i = 0; i < doc.textFrames.length; i++) if (/^TXT_(NAME|YEAR|MESSAGE)_/.test(doc.textFrames[i].name)) return true;
        return false;
    }
    function hasBounds(doc) {
        for (var i = 0; i < doc.pathItems.length; i++) if (/^(NAME|YEAR|MESSAGE)_BOUNDS_/.test(doc.pathItems[i].name)) return true;
        return false;
    }

    function csvRow(arr) {
        var out = [];
        for (var i = 0; i < arr.length; i++) { var v = String(arr[i] === undefined || arr[i] === null ? "" : arr[i]);
            out.push(/[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v); }
        return out.join(",");
    }
    function safe(s) { return String(s).replace(/[^A-Za-z0-9\-]+/g, ""); }
    function skuOf(f) { return decodeURI(f.name).replace(/\.ai$/i, "").replace(/_template\s*$/i, "").replace(/\s+$/, ""); }

    function drawBounds(doc) {
        var red = new RGBColor(); red.red = 230; red.green = 0; red.blue = 0;
        var layer = doc.layers.add(); layer.name = "AUDIT_BOUNDS";
        var names = ["YEAR_BOUNDS_1", "MESSAGE_BOUNDS_1"];
        for (var n = 1; n <= 10; n++) names.push("NAME_BOUNDS_" + n);
        var drawn = 0;
        for (var i = 0; i < names.length; i++) {
            var p; try { p = doc.pathItems.getByName(names[i]); } catch (e) { continue; }
            var g = p.geometricBounds; // [left, top, right, bottom]
            var r = layer.pathItems.rectangle(g[1], g[0], g[2] - g[0], g[1] - g[3]);
            r.filled = false; r.stroked = true; r.strokeColor = red; r.strokeWidth = 0.5;
            drawn++;
        }
        return drawn;
    }

    for (var i = START_INDEX; i < end; i++) {
        var f = files[i], sku = skuOf(f);
        for (var j = 0; j < fonts.length; j++) {
            var font = fonts[j], doc = null;
            try {
                doc = app.open(f);
                if (!hasTextFields(doc) || !hasBounds(doc)) {
                    skipped.push(sku);
                    doc.close(SaveOptions.DONOTSAVECHANGES); doc = null;
                    break;  // diğer fontları da deneme
                }
                var fits = [];
                for (var n = 1; n <= 10; n++)
                    fits.push(AP_FIT.fitText(doc, "TXT_NAME_" + n, "NAME_BOUNDS_" + n, SAMPLE_TEXTS.name, font, S.NAME.max, S.NAME.min, S.NAME.margin, "BLACK"));
                fits.push(AP_FIT.fitText(doc, "TXT_YEAR_1", "YEAR_BOUNDS_1", SAMPLE_TEXTS.year, font, S.YEAR.max, S.YEAR.min, S.YEAR.margin, "BLACK"));
                fits.push(AP_FIT.fitText(doc, "TXT_MESSAGE_1", "MESSAGE_BOUNDS_1", SAMPLE_TEXTS.message, font, S.MESSAGE.max, S.MESSAGE.min, S.MESSAGE.margin, "BLACK"));

                drawBounds(doc);
                for (var q = 0; q < fits.length; q++)
                    if (AP_FIT.isProblem(fits[q])) problems.push(csvRow([sku, font, fits[q].field, fits[q].font, fits[q].size, fits[q].max,
                        fits[q].hitMin ? "YES" : "", fits[q].overflow ? "YES" : "", fits[q].fallback ? "YES" : "", AP_FIT.problemReason(fits[q])]));

                var opt = new ExportOptionsPNG24();
                opt.artBoardClipping = true; opt.antiAliasing = true; opt.transparency = false;
                opt.horizontalScale = PNG_SCALE; opt.verticalScale = PNG_SCALE;
                doc.exportFile(File(OUT.fsName + "/" + safe(sku) + "_" + safe(font) + ".png"), ExportType.PNG24, opt);
                pngCount++;
            } catch (e) {
                errors.push(sku + " / " + font + ": " + e);
            }
            // Template asla kaydedilmez
            try { if (doc) doc.close(SaveOptions.DONOTSAVECHANGES); } catch (x) {}
        }
    }

    // Sorunlu yerleşimler (Render'daki fit raporuyla aynı kural)
    if (problems.length) {
        var rf = File(OUT.fsName + "/audit_report.csv"); var isNew = !rf.exists;
        rf.encoding = "UTF-8"; rf.lineFeed = "Unix";
        if (rf.open(isNew ? "w" : "a")) {
            if (isNew) rf.writeln("sku,audit_font,field,font,final_size,max_size,hit_min,still_overflows,outline_fallback,reason");
            for (var z = 0; z < problems.length; z++) rf.writeln(problems[z]);
            rf.close();
        }
    }

    var msg = "AUDIT_RESULT folder=" + TEMPLATE_FOLDER
        + (skuMode ? " sku_list=" + files.length + (notFound.length ? " bulunamadı=" + notFound.join("/") : "")
                   : " templates=" + START_INDEX + "-" + (end - 1) + " of " + files.length
                     + " next_start=" + (end < files.length ? end : "bitti"))
        + " png=" + pngCount + " problems=" + problems.length
        + " atlandı=" + (skipped.length ? skipped.join("/") : "0")
        + (errors.length ? " | " + errors.join(" ; ") : "");
    return finish(msg);

    function finish(m) {
        try { app.userInteractionLevel = prevLevel; } catch (e) {}
        if (typeof AUDIT_QUIET === "undefined" || !AUDIT_QUIET) alert(m.replace(/ \| /, "\n\nHatalar:\n").replace(/ ; /g, "\n"));
        return m;
    }
})();
