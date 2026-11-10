# AutoPrint Enterprise — Claude Code Bağlamı

## Proje Amacı
Amazon'dan gelen HTML/TXT packing slip dosyalarını parse edip Adobe Illustrator'da
print-ready baskı sayfaları (sheet) oluşturan hibrit bulut sistemi.
Mevcut masaüstü sistem (PyQt5) tamamen yedekte, bu proje sıfırdan inşa ediliyor.

## Mimari
- web/         : Streamlit web paneli (dosya yükleme, sipariş kuyruğu, dashboard)
- core/        : AmazonParser + JSX tetikleyici (mevcut mantık buraya taşınacak)
- agent/       : macOS'ta çalışan local watchdog (buluttan polling + Illustrator tetik)
- analytics/   : TACOS, ciro, SKU kârlılık hesabı
- fonts/       : Font validasyon ve fallback sistemi
- data/        : Runtime JSON dosyaları (gitignore'da)

## Donanım ve Ortam
- OS: macOS
- Yazıcı: Roland MO-240 (UV flatbed). Baskı VersaWorks üzerinden; sheet'ler PDF'e çevrilip VersaWorks'e atılır.
  (Eski Epson SureColor F570 sublimasyon yazıcısı artık kullanılmıyor.)
- Toplu baskı PDF modu: Kuyruk sekmesinde "PDF olarak kaydet" işaretlenirse Python
  data/render_options.json ({"save_pdf": true}) yazar, JSX sheet'leri .ai yerine PDF kaydeder
  (Acrobat 7 / PDF 1.6, renk dönüşümü yok, preserveEditability=false). Dosya iş bitince silinir;
  kutucuk her gönderimden sonra kapanır. Normal akış, watchdog ve Replacement hep .ai üretir.
  PDF adı: kullanıcı toplu baskıda order_item_id'yi elle kategori+sayı yazıyor (vehicles1,
  vehicles2... her SKU'ya). Kategori = sondaki sayı atılmış ID. Sheet'teki tüm ürünler aynı
  kategorideyse dosya <kategori><sheet sırası>.pdf (vehicles1.pdf, vehicles2.pdf; içindeki ID'lerden
  bağımsız). Karışık kategori ya da otomatik/Amazon/REPL ID'si varsa eski usul sheet_NN_<shape>.pdf.
- Allstar-Regular fontu VersaWorks'te sorun çıkarıyor, PDF'e girmeden outline'a çevrilmeli:
  PDF modunda Render_Sheet.jsx bunu otomatik yapar (outlineAllstar). Elle düzeltilen .ai için
  scripts/illustrator/Save_PDF_Roland.jsx: kaydet → Allstar outline → aynı adla PDF → .ai'yi
  outline'sız tekrar aç. Illustrator Scripts klasörüne (root sahipli) elle kopyalanmalı.
- Adobe Illustrator — osascript ile JSX tetikleme
- Illustrator JSX komutu: osascript -e 'tell application "Adobe Illustrator" ...'
- osascript timeout: 3600 saniye (büyük batch'ler için gerekli)

## Fit Raporu ve Template Denetimi
- fitText + renkler + font boyutları data/FitText.jsxinc'te (AP_FIT). Render_Sheet.jsx ve
  Audit_Templates.jsx bunu $.evalFile ile yükler — fit kuralını değiştirirken sadece orayı düzenle.
- Ölçüm FRAME ile (tf.width/height, 0.5pt adımlarla küçültme, yatayda ortalama). MAX isim 54,
  yıl 32, mesaj 36, MIN 8. Outline ölçümü + dikey ortalama denendi (2026-11-10), isimler çok büyük
  çıktığı için kullanıcı isteğiyle geri alındı — tekrar önerme.
- Render: batch klasöründe fit_report.csv — sadece MIN'e inen, hâlâ taşan veya fallback'e düşen
  alanlar (yedek ölçüm = frame okunamadı); sorun yoksa dosya oluşmaz.
- data/Audit_Templates.jsx: ayarlar dosyanın üstünde (TEMPLATE_FOLDER, AUDIT_FONTS, START_INDEX,
  BATCH_SIZE=40). data/audit_skus.txt varsa sadece o SKU'lar. Metin alanı/kutusu olmayan template
  "atlandı". Çıktı data/audit/<SKU>_<font>.png + audit_report.csv. Template'ler DONOTSAVECHANGES ile kapanır.
- tools/contact_sheet.py: data/audit PNG'lerini 5x6 kontak sayfası PDF'ine çevirir.
- Git: data/ ignore'da, sadece data/*.jsx ve data/*.jsxinc takip edilir (.bak, batches, audit, orders.json hariç).

## Ürün Tipleri ve SKU Mantığı
Ürün tipi SKU'dan değil template klasör yapısından belirlenir:
1. ACRY2 ile başlayan SKU → dog_round (kesin kural, klasöre bakılmaz)
2. templates/snowglobe/ klasöründe SKU.ai varsa → snowglobe
3. templates/heart_ceramic/ klasöründe SKU.ai varsa → heart_ceramic
4. Hiçbiri değilse → round_ceramic (varsayılan)

Bilinen SKU örnekleri: CRMC1246, CRMC1247 (round_ceramic), ACRY2001 (dog_round), ACRY1050

## Sipariş Veri Yapısı (orders.json)
{
  "order_id": "123-456-789",
  "order_item_id": "987654321",
  "sku": "CRMC1246",
  "qty": 2,
  "name": "Emily",
  "name2": "Jack",
  "year": "2024",
  "message": "Forever",
  "font_option": "SERIF",
  "color_option": "BLACK",
  "is_manual": false
}
name alanı name2...name10'a kadar uzayabilir.
font_option: SERIF / SANS / SCRIPT / WELCOME
color_option: BLACK / WHITE / GOLD / RED / SILVER / IVORY

## Font Sistemi
Mevcut FONT_MAPPING:
- "Monotype Corsiva" → SERIF
- "Abel" → SANS
- "elegant script" → SCRIPT

JSX font kodları:
- SERIF / SANS / SCRIPT → MonotypeCorsiva
- WELCOME → WelcomeChristmas
- dog_round → WelcomeChristmas (zorunlu)
- snowglobe → JosephSophia (zorunlu)

## Renk Sistemi (RGB)
BLACK: 0,0,0 | WHITE: 240,240,240 | IVORY: 255,255,240
RED: 180,30,40 | GOLD: 198,141,37 (#c68d25) | SILVER: 180,180,180
dog_round ürünlerinde color_option her zaman IVORY

## Grid ve Sayfa Ayarları
Board: 24x16 inç (pt cinsinden: 1728x1152)
Round/Heart/Dog: spacing=0.025*72pt, side_margin=0.5*72pt
Snowglobe: spacing=0.005*72pt, side_margin=0.05*72pt (4x7=28 adet sığar)

## Klasör Yapısı Referansı (Mevcut Sistem)
~/Desktop/AutoPrint/
├── input/parsed_orders/orders.json
├── batches/YYYY-MM-DD_HHMM/
├── templates/round_ceramic/ heart_ceramic/ dog_round/ snowglobe/
├── scripts/JSX/Render_Sheet.jsx
└── processed_orders.txt

## Geliştirme Sırası
Faz 1+2: Streamlit web panel + local watchdog agent
Faz 3: Google Sheets analytics (gspread, batch append)
Faz 4: Dinamik font desteği

## Kritik Kurallar
- orders.json formatı birebir korunmalı, JSX bu formatı bekliyor
- Manuel siparişler (is_manual: true) processed_orders.txt'e yazılmaz
- processed_orders.txt duplicate kontrolü için kritik
- Mevcut üretim sistemine dokunulmuyor

## Teknoloji
Streamlit, Render/Railway free tier, Google Sheets API (gspread), Python watchdog, python-dotenv
