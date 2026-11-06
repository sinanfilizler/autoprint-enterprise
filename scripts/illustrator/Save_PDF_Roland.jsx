// Save_PDF_Roland.jsx
// =========================================================================
// Tek tıkla: açık sheet'i kaydeder, Allstar-Regular metinleri outline'a çevirir,
// aynı klasöre aynı isimle PDF kaydeder (VersaWorks için), sonra .ai dosyasını
// outline'sız haliyle tekrar açar. Yani .ai hep düzenlenebilir kalır.
//
// Kullanım: File > Scripts > Save_PDF_Roland
// (Eski iki adım — Outline_Allstar + Save As PDF — yerine.)
// =========================================================================

(function () {
    if (app.documents.length === 0) { alert("Açık doküman yok."); return; }
    var doc = app.activeDocument;
    var TARGET_FONT = "Allstar-Regular";

    var src = null;
    try { src = doc.fullName; } catch (e) {}
    if (!src || !doc.path || String(doc.path) === "") {
        alert("Önce dosyayı .ai olarak kaydet, sonra scripti çalıştır.");
        return;
    }
    var isPdf = /\.pdf$/i.test(src.name);

    // Elle yapılan düzeltmeler kaybolmasın
    if (!doc.saved && !isPdf) doc.save();

    // Allstar metinlerini outline'a çevir
    var targets = [];
    for (var i = 0; i < doc.textFrames.length; i++) {
        var tf = doc.textFrames[i];
        try {
            if (tf.contents && tf.textRange.characterAttributes.textFont.name === TARGET_FONT) targets.push(tf);
        } catch (e) {}
    }
    var count = 0;
    for (var j = 0; j < targets.length; j++) {
        try { targets[j].createOutline(); count++; } catch (e) {}
    }

    // PDF ayarları: render script'iyle aynı
    var po = new PDFSaveOptions();
    po.compatibility = PDFCompatibility.ACROBAT7;
    po.preserveEditability = false;
    po.generateThumbnails = false;
    po.viewAfterSaving = false;
    try { po.colorConversionID = ColorConversion.None; } catch (e) {}

    var pdfFile = File(src.parent.fsName + "/" + src.name.replace(/\.[^.]+$/, "") + ".pdf");
    doc.saveAs(pdfFile, po);

    if (!isPdf) {
        // Outline'lı hali .ai'ye yazılmasın: kapat ve orijinal .ai'yi aç
        doc.close(SaveOptions.DONOTSAVECHANGES);
        app.open(src);
    }

    alert(count + " Allstar metni outline'a çevrildi.\nPDF kaydedildi: " + decodeURI(pdfFile.name));
})();
