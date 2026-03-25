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
- Yazıcı: Epson SureColor F570 Pro (dye-sublimation)
- Adobe Illustrator — osascript ile JSX tetikleme
- Illustrator JSX komutu: osascript -e 'tell application "Adobe Illustrator" ...'
- osascript timeout: 3600 saniye (büyük batch'ler için gerekli)

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
RED: 180,30,40 | GOLD: 200,160,60 | SILVER: 180,180,180
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
