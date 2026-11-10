// Render_Sheet.jsx
// =========================================================================
// FINAL VERSION - ZERO MARGIN FIX
// 1. SAFEGUARD: Other templates are untouched.
// 2. SNOWGLOBE FIX: Side Margins set to 0. Spacing set to 0.
//    Allows fitting 28 items (4x7 grid) by using full board width.
// =========================================================================

(function () {
    try { 
        app.preferences.setBooleanPreference("isGPUPerformanceEnabled", false);
        app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
    } catch(e) {}

    // --- GENEL SAYFA AYARLARI ---
    var BOARD_WIDTH = 24 * 72; 
    var BOARD_HEIGHT = 16 * 72; 
    
    // --- VARSAYILAN BOSLUKLAR (Diger urunler icin - DOKUNMA) ---
    var DEFAULT_SPACING = 0.025 * 72;
    var DEFAULT_TOP_MARGIN = 0.1 * 72;
    var DEFAULT_BOTTOM_MARGIN = 0.1 * 72;
    var DEFAULT_SIDE_MARGIN = 0.5 * 72; // Snowglobe icin bunu 0 yapacagiz

    var BATCHES_FOLDER = Folder("/Users/melkarakas/Desktop/autoprint-enterprise/data/batches");
    var DEFAULT_JSON = File("/Users/melkarakas/Desktop/autoprint-enterprise/data/orders.json");
    var PROCESSED_FILE = File("/Users/melkarakas/Desktop/autoprint-enterprise/data/processed_orders.txt");
    // Python sadece "PDF olarak kaydet" seçilen gönderimde yazar, iş bitince siler
    var OPTIONS_FILE = File("/Users/melkarakas/Desktop/autoprint-enterprise/data/render_options.json");

    var TEMPLATE_FOLDERS = {
        "round_ceramic": Folder("/Users/melkarakas/Desktop/AutoPrint/templates/round_ceramic"),
        "heart_ceramic": Folder("/Users/melkarakas/Desktop/AutoPrint/templates/heart_ceramic"),
        "dog_round": Folder("/Users/melkarakas/Desktop/AutoPrint/templates/dog_round"),
        "snowglobe": Folder("/Users/melkarakas/Desktop/AutoPrint/templates/snowglobe")
    };

    var OUTLINE_NAME = "<outline>";

    var FONT_CONFIG = { 
        "SERIF": "MonotypeCorsiva", 
        "SANS": "MonotypeCorsiva", 
        "SCRIPT": "MonotypeCorsiva", 
        "WELCOME": "WelcomeChristmas" 
    };
    
    var SNOW_FONT = "josephsophia";
    var DOG_FONT = "WelcomeChristmas";

    // Metin yerleştirme (fitText), renkler ve font boyutları ortak dosyada:
    // Audit_Templates.jsx de aynı mantığı kullanır.
    $.evalFile(File("/Users/melkarakas/Desktop/autoprint-enterprise/data/FitText.jsxinc"));
    var fitText = AP_FIT.fitText;
    var NAME_MAX_SIZE = AP_FIT.SIZES.NAME.max; var NAME_MIN_SIZE = AP_FIT.SIZES.NAME.min; var NAME_MARGIN = AP_FIT.SIZES.NAME.margin;
    var YEAR_MAX_SIZE = AP_FIT.SIZES.YEAR.max; var YEAR_MIN_SIZE = AP_FIT.SIZES.YEAR.min; var YEAR_MARGIN = AP_FIT.SIZES.YEAR.margin;
    var MESSAGE_MAX_SIZE = AP_FIT.SIZES.MESSAGE.max; var MESSAGE_MIN_SIZE = AP_FIT.SIZES.MESSAGE.min; var MESSAGE_MARGIN = AP_FIT.SIZES.MESSAGE.margin;

    // --- HELPER FUNCTIONS ---
    function arrayContains(arr, v) { for(var i=0;i<arr.length;i++)if(arr[i]===v)return true;return false; }

    // --- SKU SIRALAMA: CRM/CRMC her zaman once, sonra numaraya gore yakinlik ---
    // CRM, CRMC ile ayni grup kabul edilir (orn. CRM1361 ve CRMC1361 ayni numarada yan yana gelir).
    // Her grup icinde harf-numara ayristirilip numara SAYISAL olarak karsilastirilir,
    // boylece CRMC2 / CRMC10 / CRMC100 string sirasina gore degil gercek yakinlik sirasina gore dizilir.
    function skuSortKey(skuRaw) {
        var sku = String(skuRaw).toUpperCase();
        var isCrm = /^CRMC/.test(sku) || /^CRM[0-9]/.test(sku);
        var prefix = sku, num = 0, suffix = "";
        var m = sku.match(/^([A-Z\-]+)(\d+)(.*)$/);
        if (m) { prefix = m[1]; num = parseInt(m[2], 10); suffix = m[3]; }
        if (isCrm) prefix = "CRMC";
        return { priority: isCrm ? 0 : 1, prefix: prefix, num: num, suffix: suffix };
    }
    function compareSku(aSku, bSku) {
        var A = skuSortKey(aSku), B = skuSortKey(bSku);
        if (A.priority !== B.priority) return A.priority - B.priority;
        if (A.prefix !== B.prefix) return (A.prefix < B.prefix) ? -1 : 1;
        if (A.num !== B.num) return A.num - B.num;
        if (A.suffix !== B.suffix) return (A.suffix < B.suffix) ? -1 : (A.suffix > B.suffix ? 1 : 0);
        return 0;
    }
    function ensureFolder(f) { if(!f.exists)f.create(); return f; }
    function pad(n) { return (n<10)?"00"+n:(n<100)?"0"+n:n; }
    function getTimestamp() { var d=new Date(); return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate())+"_"+pad(d.getHours())+pad(d.getMinutes())+pad(d.getSeconds()); }
    function readJSON(f) { f.encoding="UTF-8"; if(!f.open("r")) return null; var c=f.read(); f.close(); try{return eval("("+c+")");}catch(e){return null;} }
    
    function loadProcessedIds() {
        var ids = {}; if (!PROCESSED_FILE.exists) return ids;
        PROCESSED_FILE.encoding = "UTF-8";
        if (PROCESSED_FILE.open("r")) {
            while (!PROCESSED_FILE.eof) { var l = PROCESSED_FILE.readln(); if(l && l[0]!=="#") ids[l]=true; }
            PROCESSED_FILE.close();
        }
        return ids;
    }

    function appendProcessedIds(ids) {
        if(ids.length===0) return;
        PROCESSED_FILE.encoding="UTF-8"; 
        if(PROCESSED_FILE.open("a")) {
            for(var i=0; i<ids.length; i++) PROCESSED_FILE.writeln(ids[i]);
            PROCESSED_FILE.close();
        }
    }

    function findTemplate(sku) {
        if (sku.indexOf("ACRY2") === 0) {
            var dogFolder = TEMPLATE_FOLDERS["dog_round"];
            if (File(dogFolder.fsName + "/" + sku + ".ai").exists) return {f: File(dogFolder.fsName + "/" + sku + ".ai"), s: "dog_round"};
            if (File(dogFolder.fsName + "/_default_template.ai").exists) return {f: File(dogFolder.fsName + "/_default_template.ai"), s: "dog_round"};
        }

        for (var shapeName in TEMPLATE_FOLDERS) {
            var folder = TEMPLATE_FOLDERS[shapeName];
            if (!folder.exists) continue;
            
            if (File(folder.fsName + "/" + sku + ".ai").exists) return {f: File(folder.fsName + "/" + sku + ".ai"), s: shapeName};
            if (File(folder.fsName + "/" + sku + "_template.ai").exists) return {f: File(folder.fsName + "/" + sku + "_template.ai"), s: shapeName};
            
            if (shapeName === "snowglobe" && File(folder.fsName + "/_default_template.ai").exists) {
                 // Manual test fallback for snowglobe folder
                 // We don't auto-return here to avoid false positives for other shapes, 
                 // but if SKU starts with SNOW, we can trust it.
            }
        }
        return {f:null,s:null};
    }

    function getOutlineSize(f) {
        var d=app.open(f); var o=null;
        try { (function r(c){for(var i=0;i<c.pageItems.length;i++){if(c.pageItems[i].name===OUTLINE_NAME){o=c.pageItems[i];return;} if(c.pageItems[i].typename==="GroupItem")r(c.pageItems[i]);}})(d); } catch(e){}
        if(!o){d.close(SaveOptions.DONOTSAVECHANGES);return null;}
        var b=o.geometricBounds; var w=b[2]-b[0]; var h=b[1]-b[3]; d.close(SaveOptions.DONOTSAVECHANGES); return {w:w,h:h};
    }

    // --- GRID HESAPLAMA (DUZELTILDI) ---
    function calculateGrid(sw, sh, shapeName) {
        var gap = DEFAULT_SPACING;
        var tm = DEFAULT_TOP_MARGIN;
        var bm = DEFAULT_BOTTOM_MARGIN;
        var side_m = DEFAULT_SIDE_MARGIN; // Yan bosluk degiskeni

        // --- SNOWGLOBE ICIN SIFIR BOSLUK ---
        if (shapeName === "snowglobe") {
            gap = 0.005 * 72; // Cok minik bosluk (birbirine degmesin diye)
            tm = 0.05 * 72;   // Minik ust pay
            bm = 0.05 * 72;   // Minik alt pay
            side_m = 0.05 * 72; // *** DUZELTME BURADA: YAN BOSLUK MINIMUM ***
        }
        // -----------------------------------

        // Kullanilabilir alan hesabi
        var aw = BOARD_WIDTH - (2 * side_m); 
        var ah = BOARD_HEIGHT - tm - bm;
        
        var c = Math.floor((aw + gap) / (sw + gap)); 
        var r = Math.floor((ah + gap) / (sh + gap));
        
        return { 
            cols: c, rows: r, slots: c * r, 
            w: sw, h: sh, 
            lm: (BOARD_WIDTH - (c * sw + (c - 1) * gap)) / 2, // Ortala
            tm: tm,
            gap: gap 
        };
    }

    function duplicate(src, tgt, x, y) {
        app.activeDocument=src; for(var i=0;i<src.layers.length;i++)src.layers[i].locked=false;
        var o=null; (function r(c){for(var i=0;i<c.pageItems.length;i++){if(c.pageItems[i].name===OUTLINE_NAME){o=c.pageItems[i];return;} if(c.pageItems[i].typename==="GroupItem")r(c.pageItems[i]);}})(src);
        if(!o) return;
        
        src.selection=null; 
        for(var i=0;i<src.pageItems.length;i++) try{if(!src.pageItems[i].hidden && !src.pageItems[i].locked && !src.pageItems[i].guides)src.pageItems[i].selected=true;}catch(e){}
        
        app.copy(); app.activeDocument=tgt; app.paste();
        var p=tgt.selection; if(p.length===0) return;
        var g=(p.length===1 && p[0].typename==="GroupItem")?p[0]:(app.executeMenuCommand("group"),tgt.selection[0]);
        var po=null; (function r(c){for(var i=0;i<c.pageItems.length;i++){if(c.pageItems[i].name===OUTLINE_NAME){po=c.pageItems[i];return;} if(c.pageItems[i].typename==="GroupItem")r(c.pageItems[i]);}})(g);
        if(po){ var b=po.geometricBounds; g.translate(x-b[0], y-b[1]); }
        g.selected=true; app.executeMenuCommand("ungroup"); tgt.selection=null;
    }

    // --- FIT RAPORU: sorunlu metin yerleşimleri batch klasöründe fit_report.csv ---
    function csvRow(arr) {
        var out=[];
        for(var i=0;i<arr.length;i++){ var v=String(arr[i]===undefined||arr[i]===null?"":arr[i]);
            out.push(/[",\n]/.test(v) ? '"'+v.replace(/"/g,'""')+'"' : v); }
        return out.join(",");
    }
    function writeFitReport(folder, sheetName, rows) {
        var probs=[]; for(var i=0;i<rows.length;i++) if(AP_FIT.isProblem(rows[i].fit)) probs.push(rows[i]);
        if(!probs.length) return;  // sorun yoksa dosya oluşturma
        var f=File(folder.fsName+"/fit_report.csv"); var isNew=!f.exists;
        f.encoding="UTF-8"; f.lineFeed="Unix"; if(!f.open(isNew?"w":"a")) return;
        if(isNew) f.writeln("sheet,sku,order_item_id,field,font,final_size,max_size,ratio_pct,hit_min,still_overflows,fallback_measure,reason");
        for(var j=0;j<probs.length;j++){ var r=probs[j], x=r.fit;
            f.writeln(csvRow([sheetName, r.sku, r.oid, x.field, x.font, x.size, x.max, Math.round(x.ratio*100),
                x.hitMin?"YES":"", x.overflow?"YES":"", x.fallback?"YES":"", AP_FIT.problemReason(x)]));
        }
        f.close();
    }

    // ==================== MAIN LOOP ==================== //
    $.writeln("AutoPrint Started");
    // Python'a dönen özet: "AUTOPRINT_RESULT sheets=N skipped=N failed=id1,id2 | hata mesajları"
    var sheetCount=0, skippedIds=[], failedIds=[], errorMsgs=[];
    function summary(extra) {
        return "AUTOPRINT_RESULT sheets="+sheetCount+" skipped="+skippedIds.length
            +" failed="+failedIds.join(",")+" | "+(extra ? extra+" ; " : "")+errorMsgs.join(" ; ");
    }

    var ts=getTimestamp(); var bf=ensureFolder(new Folder(BATCHES_FOLDER.fsName+"/"+ts));
    var jf=DEFAULT_JSON; if(!jf.exists) return summary("orders.json bulunamadi");
    var orders=readJSON(jf); if(!orders) return summary("orders.json okunamadi");
    var proc=loadProcessedIds(); var obs={};
    var opts = OPTIONS_FILE.exists ? readJSON(OPTIONS_FILE) : null;
    var SAVE_PDF = !!(opts && opts.save_pdf === true);

    // Toplu baskı PDF'i (VersaWorks): renk dönüşümü yok (RGB kalır), saydamlık canlı,
    // spot renkler korunur, .ai gömülmez (dosya küçük kalır)
    // PDF modunda dosya adı = kategori + sheet sırası. Kategori, elle yazılan order_item_id'nin
    // sonundaki sayı atılınca kalan kısım (vehicles1, vehicles2 -> "vehicles"). Sheet'teki tüm
    // ürünler aynı kategorideyse vehicles1.pdf, vehicles2.pdf...; karışık ya da otomatik/Amazon
    // ID'si (sadece rakam, M-2026..., REPL-...) varsa null -> eski usul isim.
    var catCounters = {};
    function categoryOf(id) {
        var c = String(id).replace(/\d+$/, "").replace(/[\s_\-]+$/, "");
        if (c.length < 2 || !/^[A-Za-z][A-Za-z _\-]*$/.test(c) || /^repl/i.test(c)) return null;
        return c;
    }
    function categoryFileName(ids) {
        if (ids.length === 0) return null;
        var cat = null;
        for (var i = 0; i < ids.length; i++) {
            var c = categoryOf(ids[i]);
            if (!c) return null;
            if (cat === null) cat = c;
            else if (c.toLowerCase() !== cat.toLowerCase()) return null;
        }
        var key = cat.toLowerCase();
        catCounters[key] = (catCounters[key] || 0) + 1;
        return cat.replace(/[\/\\:*?"<>|]/g, "_") + catCounters[key];
    }

    function pdfOptions() {
        var po = new PDFSaveOptions();
        po.compatibility = PDFCompatibility.ACROBAT7;
        po.preserveEditability = false;
        po.generateThumbnails = false;
        po.viewAfterSaving = false;
        try { po.colorConversionID = ColorConversion.None; } catch(e) {}
        return po;
    }

    // Allstar-Regular VersaWorks'te sorun çıkarıyor: PDF'e kaydetmeden önce outline'a çevrilir.
    // (Eski elle çalıştırılan Outline_Allstar.jsx ile aynı iş.)
    function outlineAllstar(d) {
        var t=[];
        for(var i=0;i<d.textFrames.length;i++){ var tf=d.textFrames[i];
            try{ if(tf.contents && tf.textRange.characterAttributes.textFont.name==="Allstar-Regular") t.push(tf); }catch(e){} }
        for(var j=0;j<t.length;j++){ try{ t[j].createOutline(); }catch(e){} }
    }

    for(var i=0; i<orders.length; i++) {
        var o = orders[i];
        if(!o.is_manual && proc[o.order_item_id]) { if(!arrayContains(skippedIds, o.order_item_id)) skippedIds.push(o.order_item_id); continue; }

        var t=findTemplate(o.sku);
        if(!t.f) continue;

        if(!obs[t.s]) obs[t.s]={list:[], tpl:t.f};
        for(var q=0; q<(o.qty||1); q++) obs[t.s].list.push({ord:o, tpl:t.f});
    }

    for(var sh in obs) {
        var dat=obs[sh]; var lst=dat.list;
        lst.sort(function(a,b){ return compareSku(a.ord.sku, b.ord.sku); });
        
        var os=getOutlineSize(dat.tpl); if(!os) continue;
        var gc=calculateGrid(os.w, os.h, sh); 
        var sheets=Math.ceil(lst.length/gc.slots);

        for(var s=0; s<sheets; s++) {
            var preset = new DocumentPreset();
            preset.width = BOARD_WIDTH;
            preset.height = BOARD_HEIGHT;
            preset.units = RulerUnits.Inches;
            preset.colorMode = DocumentColorSpace.RGB;
            var doc = app.documents.addDocument("Print", preset);
            doc.artboards[0].artboardRect = [0, BOARD_HEIGHT, BOARD_WIDTH, 0];
            
            var start=s*gc.slots; var end=Math.min(start+gc.slots, lst.length);
            var sheetIds = []; 
            var allSheetIds = [];  // manuel dahil, dosya adı için
            var sheetFits = [];    // fit raporu kayıtları

            for(var k=start; k<end; k++) {
                var it=lst[k]; var o=it.ord;
                var td=null;
                // Tek bir siparişteki hata tüm batch'i durdurmasın: atla, raporla
                try {
                td=app.open(it.tpl);

                var isDog = (o.sku.indexOf("ACRY2") === 0);
                var isSnow = (sh === "snowglobe"); 
                
                var fName = FONT_CONFIG["SERIF"];
                if (isDog) fName = DOG_FONT;
                else if (isSnow) fName = SNOW_FONT; 
                else fName = FONT_CONFIG[o.font_option] || o.font_option || FONT_CONFIG["SERIF"];

                var itemFits = [];
                var rec = function(r) { if(r) itemFits.push({sku:o.sku, oid:String(o.order_item_id), fit:r}); };
                var cCode = isDog ? "IVORY" : (o.color_option || "BLACK");
                // Sheets'ten yıl sayı (2026) gelebilir — toUpperCase için String'e çevir
                var yt=String(o.year||""); var mt=String(o.message||"");
                if(isDog) { yt=yt.toUpperCase(); mt=mt.toUpperCase(); }

                for(var n=1; n<=10; n++) {
                    var nk = n===1 ? "name" : "name"+n;
                    var nt = String(o[nk]||"");
                    if(isDog) nt=nt.toUpperCase();
                    rec(fitText(td, "TXT_NAME_"+n, "NAME_BOUNDS_"+n, nt, fName, NAME_MAX_SIZE, NAME_MIN_SIZE, NAME_MARGIN, cCode));
                }
                rec(fitText(td, "TXT_YEAR_1", "YEAR_BOUNDS_1", yt, fName, YEAR_MAX_SIZE, YEAR_MIN_SIZE, YEAR_MARGIN, cCode));
                rec(fitText(td, "TXT_MESSAGE_1", "MESSAGE_BOUNDS_1", mt, fName, MESSAGE_MAX_SIZE, MESSAGE_MIN_SIZE, MESSAGE_MARGIN, cCode));

                var idx=k-start; var col=idx%gc.cols; var row=Math.floor(idx/gc.cols);
                
                duplicate(td, doc, gc.lm+col*(gc.w+gc.gap), BOARD_HEIGHT-gc.tm-row*(gc.h+gc.gap));
                td.close(SaveOptions.DONOTSAVECHANGES); td=null;
                for(var fi=0; fi<itemFits.length; fi++) sheetFits.push(itemFits[fi]);

                if(!o.is_manual && !arrayContains(sheetIds, o.order_item_id)) sheetIds.push(o.order_item_id);
                if(!arrayContains(allSheetIds, String(o.order_item_id))) allSheetIds.push(String(o.order_item_id));
                } catch(itemErr) {
                    try { if(td) td.close(SaveOptions.DONOTSAVECHANGES); } catch(x) {}
                    try { app.activeDocument = doc; } catch(x) {}
                    if(!arrayContains(failedIds, o.order_item_id)) failedIds.push(o.order_item_id);
                    errorMsgs.push(o.sku+" ("+o.order_item_id+"): "+itemErr);
                }
            }
            // Bir kopyası hata veren sipariş işlenmiş sayılmasın
            var okIds=[]; for(var z=0; z<sheetIds.length; z++) if(!arrayContains(failedIds, sheetIds[z])) okIds.push(sheetIds[z]);
            sheetIds=okIds;
            
            try{ (function r(c){for(var i=0;i<c.pageItems.length;i++){if(c.pageItems[i].name==="<template>"||c.pageItems[i].name==="<templates>")c.pageItems[i].hidden=true; if(c.pageItems[i].typename==="GroupItem")r(c.pageItems[i]);}})(doc); } catch(e){}

            var fNameSheet = "sheet_"+pad(s+1)+"_"+sh+(SAVE_PDF ? ".pdf" : ".ai");
            if (SAVE_PDF) { var catName = categoryFileName(allSheetIds); if (catName) fNameSheet = catName + ".pdf"; }
            if (SAVE_PDF) { outlineAllstar(doc); doc.saveAs(File(bf.fsName+"/"+fNameSheet), pdfOptions()); }
            else doc.saveAs(File(bf.fsName+"/"+fNameSheet));
            doc.close(SaveOptions.DONOTSAVECHANGES);
            try { writeFitReport(bf, fNameSheet, sheetFits); } catch(e) { errorMsgs.push("fit_report: "+e); }
            sheetCount++;

            appendProcessedIds(sheetIds);
            $.gc();
        }
    }
    jf.copy(bf.fsName+"/orders.json");

    var msg = sheetCount+" sheet oluşturuldu"+(SAVE_PDF ? " (PDF)." : ".");
    if (failedIds.length) {
        var ef=File(bf.fsName+"/HATALAR.txt"); ef.encoding="UTF-8";
        if(ef.open("w")) { ef.write(errorMsgs.join("\n")); ef.close(); }
        msg += "\n\nUYARI: "+failedIds.length+" sipariş oluşturulamadı (HATALAR.txt):\n"+errorMsgs.join("\n");
    }
    if (sheetCount===0 && skippedIds.length) {
        msg += "\n\n"+skippedIds.length+" sipariş daha önceki bir batch'te zaten oluşturulmuş — önceki batch klasörlerine bakın.";
    }
    var openFolder = confirm(msg+"\n\nKlasörü açmak ister misiniz?\n" + bf.fsName);
    if (openFolder) {
        bf.execute();
    }
    return summary("");
})();