"""CRMC paket ayrıştırma/sıralama/PDF testleri. Çalıştır: python3 -m unittest tests.test_crmc_packages -v"""

import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pypdf import PdfReader

from core import crmc_packages as cp
from tests.crmc_fixtures import item, page, slips_pdf, zip_bytes

PREFIXES = ("crm", "acry")
OID = ["111-0000001-0000001", "111-0000002-0000002", "111-0000003-0000003",
       "111-0000004-0000004", "111-0000005-0000005", "111-0000006-0000006"]


def parse(pages):
    return cp.parse_slips(slips_pdf(pages), "pkg", "pkg.zip")


class ParseTests(unittest.TestCase):
    def test_single_labeled_block(self):
        blocks, warns = parse([page(OID[0], item("crmc1246", 2, fields={"NAME": "Emily", "YEAR": "2024"}))])
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual(b.order_id, OID[0])
        self.assertEqual(b.pages, [0])
        self.assertEqual([(i.sku, i.qty) for i in b.items], [("crmc1246", 2)])
        self.assertEqual(b.items[0].fields["NAME"], "Emily")
        self.assertEqual(b.items[0].fields["YEAR"], "2024")
        self.assertTrue(b.gift_box)
        self.assertTrue(b.has_personalization)
        self.assertEqual(warns, [])

    def test_three_blocks(self):
        blocks, _ = parse([page(OID[i], item(f"crmc12{i}")) for i in range(3)])
        self.assertEqual([b.order_id for b in blocks], OID[:3])
        self.assertEqual([b.pages for b in blocks], [[0], [1], [2]])

    def test_overflow_block(self):
        blocks, warns = parse([
            page(OID[0], item("crmc1", fields={"NAME": "A"}) + item("crmc2", fields={"NAME": "B"})),
            page(OID[0], item("crmc3", fields={"NAME": "C"}), label=False),
            page(OID[1], item("crmc4")),
        ])
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].pages, [0, 1])
        self.assertEqual(blocks[0].skus, ["crmc1", "crmc2", "crmc3"])
        self.assertEqual(blocks[0].page_count, 2)
        self.assertEqual(warns, [])

    def test_two_items(self):
        blocks, _ = parse([page(OID[0], item("crmc1", 1, gift=False) + item("acry1050", 3, gift=True))])
        self.assertEqual([(i.sku, i.qty, i.gift_box) for i in blocks[0].items],
                         [("crmc1", 1, False), ("acry1050", 3, True)])

    def test_no_personalization(self):
        blocks, _ = parse([page(OID[0], item("crmc1", gift=False))])
        self.assertFalse(blocks[0].has_personalization)
        self.assertFalse(blocks[0].gift_box)

    def test_message_key(self):
        blocks, _ = parse([page(OID[0], item("crmc1", fields={"MESSAGE": "Merry Christmas"}))])
        self.assertEqual(blocks[0].items[0].personalization, {"MESSAGE": "Merry Christmas"})

    def test_wrapped_title_and_gift_box(self):
        lines = ["crmc77 - (QTY: 1) - Personalized Family Ornament With", "Five Names",
                 "1. NAME: Jo", "2. GIFT BOX: Yes, add gift", "box."]
        it = parse([page(OID[0], lines)])[0][0].items[0]
        self.assertEqual(it.title, "Personalized Family Ornament With Five Names")
        self.assertEqual(it.fields["GIFT BOX"], "Yes, add gift box.")
        self.assertTrue(it.gift_box)

    def test_multiple_fields_on_one_line(self):
        lines = ["crmc1828 - (QTY: 1) - Princess Unicorn", "1. NAME: QUIN RYAN 2. YEAR: 2026",
                 "3. GIFT BOX: Yes, add gift", "box."]
        it = parse([page(OID[0], lines)])[0][0].items[0]
        self.assertEqual(it.fields, {"NAME": "QUIN RYAN", "YEAR": "2026", "GIFT BOX": "Yes, add gift box."})

    def test_other_prefix_skus(self):
        blocks, _ = parse([page(OID[0], item("PO-1234") + item("GX55"))])
        self.assertEqual(blocks[0].skus, ["PO-1234", "GX55"])

    def test_ambiguous_first_page(self):
        blocks, warns = parse([page(OID[0], item("crmc1"), label=False), page(OID[1], item("crmc2"))])
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].ambiguous)
        self.assertEqual([w["tür"] for w in warns], ["Belirsiz sayfa"])

    def test_ambiguous_different_order_id(self):
        blocks, warns = parse([page(OID[0], item("crmc1")), page(OID[1], item("crmc2"), label=False)])
        self.assertEqual([b.pages for b in blocks], [[0], [1]])
        self.assertTrue(blocks[1].ambiguous)
        self.assertIn("Belirsiz sayfa", [w["tür"] for w in warns])

    def test_unreadable_and_multiple_order_ids(self):
        _, warns = parse([page(None, item("crmc1")),
                          page(OID[1], item("crmc2") + [f"Ref: {OID[2]}"])])
        kinds = [w["tür"] for w in warns]
        self.assertIn("Okunamayan order ID", kinds)
        self.assertIn("Birden fazla order ID", kinds)


class HelperTests(unittest.TestCase):
    def test_natural_sort_and_prefix(self):
        self.assertLess(cp.natural_key("crmc2"), cp.natural_key("CRMC10"))
        self.assertTrue(cp.is_listed_sku("CRM1001", PREFIXES))
        self.assertTrue(cp.is_listed_sku("acry2001", PREFIXES))
        self.assertFalse(cp.is_listed_sku("RO-12", PREFIXES))

    def test_package_id_and_date(self):
        name = "26---11.11---03.05---batch7 (1).zip"
        self.assertEqual(cp.package_id_from_name(name), "26---11.11---03.05---batch7")
        self.assertEqual(cp.zip_datetime(name).strftime("%Y-%m-%d %H:%M"), "2026-11-11 03:05")


def make_inbox(zips: dict[str, bytes], age: float = 120) -> tempfile.TemporaryDirectory:
    d = tempfile.TemporaryDirectory()
    t = time.time() - age
    for name, data in zips.items():
        p = Path(d.name) / name
        p.write_bytes(data)
        os.utime(p, (t, t))
    return d


class ScanTests(unittest.TestCase):
    def test_unreachable(self):
        res = cp.scan_inbox("/nonexistent/CRMC_Inbox", PREFIXES)
        self.assertFalse(res.reachable)

    def test_sort_other_section_and_mixed(self):
        z = zip_bytes([
            page(OID[0], item("crmc10")),
            page(OID[1], item("PO-77")),                        # sadece diğer SKU
            page(OID[2], item("crm5") + item("RO-1")),          # crm + diğer karışık
            page(OID[3], item("acry2001")),
            page(OID[4], item("crmc2")),
        ])
        with make_inbox({"26---11.11---03.05---a.zip": z}) as d:
            res = cp.scan_inbox(d, PREFIXES)
        order = [(b.first_sku, b.is_other) for b in cp.sort_blocks(res.blocks)]
        self.assertEqual(order, [("acry2001", False), ("crmc2", False), ("crmc10", False),
                                 ("crm5", True), ("PO-77", True)])

    def test_skip_rules_and_retry(self):
        good = zip_bytes([page(OID[0], item("crmc1"))])
        with make_inbox({
            "a.zip": good,
            "a (1).zip": good,                                  # Chrome kopyası
            "b.zip.crdownload": good,
            "c.zip": b"not a zip",
            "d.zip": zip_bytes([page(OID[1], item("GX1"))]),    # listede SKU yok
        }) as d:
            fresh = Path(d) / "e.zip"
            fresh.write_bytes(zip_bytes([page(OID[2], item("crmc3"))]))
            before = {p.name: p.stat().st_mtime for p in Path(d).iterdir()}
            res = cp.scan_inbox(d, PREFIXES)
            after = {p.name: p.stat().st_mtime for p in Path(d).iterdir()}
        self.assertEqual(before, after)                         # inbox'a dokunulmadı
        self.assertEqual([p.package_id for p in res.packages], ["a"])
        self.assertEqual({r["zip"] for r in res.retry}, {"c.zip", "e.zip"})
        self.assertEqual({s["zip"] for s in res.skipped}, {"a (1).zip", "d.zip"})

    def test_duplicate_order_across_zips(self):
        with make_inbox({"a.zip": zip_bytes([page(OID[0], item("crmc1"))]),
                         "b.zip": zip_bytes([page(OID[0], item("crmc1")), page(OID[1], item("crmc2"))])}) as d:
            res = cp.scan_inbox(d, PREFIXES)
        self.assertEqual([(b.order_id, b.package_id) for b in res.blocks], [(OID[0], "a"), (OID[1], "b")])
        self.assertEqual([w["tür"] for w in res.warnings], ["Kopya order ID"])

    def test_stale_inbox(self):
        with make_inbox({"a.zip": zip_bytes([page(OID[0], item("crmc1"))])}, age=45 * 60) as d:
            res = cp.scan_inbox(d, PREFIXES)
        self.assertIn("İndirme duruyor olabilir", [w["tür"] for w in res.warnings])

    def test_queue_warnings(self):
        blocks, _ = parse([page(OID[0], item("crmc1", fields={"NAME": "A"})),
                           page(OID[1], item("crmc2")),
                           page(OID[2], item("crmc3", fields={"NAME": "C"}))])
        queue = [{"order_id": OID[2], "sku": "crmc3"},
                 {"order_id": OID[4], "sku": "CRMC9"},
                 {"order_id": OID[5], "sku": "GX1"}]          # listede olmayan SKU uyarı vermez
        warns = cp.queue_warnings(blocks, blocks, queue, PREFIXES)
        self.assertEqual(sorted((w["tür"], w["order_id"]) for w in warns),
                         [("Kuyrukta var, ZIP yok", OID[4]), ("ZIP'te var, kuyrukta yok", OID[0])])


class PrintedTests(unittest.TestCase):
    def test_mark_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "printed.json"
            self.assertEqual(cp.load_printed(p), {})
            cp.mark_printed(["x|pkg"], "run1", p)
            self.assertEqual(cp.load_printed(p)["x|pkg"]["run_id"], "run1")


class BuildPdfTests(unittest.TestCase):
    def _blocks(self, n_normal, n_other=0):
        pages = [page(f"222-{i:07d}-0000000", item(f"crmc{i}")) for i in range(n_normal)]
        pages += [page(f"333-{i:07d}-0000000", item(f"GX{i}")) for i in range(n_other)]
        blocks, _ = cp.parse_slips(slips_pdf(pages), "pkg", "pkg.zip")
        for b in blocks:
            b.is_other = not all(cp.is_listed_sku(s, PREFIXES) for s in b.skus)
        return blocks, {"pkg": slips_pdf(pages)}

    def _texts(self, data):
        return [pg.extract_text() or "" for pg in PdfReader(io.BytesIO(data)).pages]

    def test_summary_divider_and_stamps(self):
        pages = [page(OID[0], item("crmc5")),
                 page(OID[1], item("GX1")),
                 page(OID[2], item("crmc1") + item("crmc2")),
                 page(OID[2], item("crmc3"), label=False)]
        slips = slips_pdf(pages)
        blocks, _ = cp.parse_slips(slips, "pkg", "pkg.zip")
        for b in blocks:
            b.is_other = not all(cp.is_listed_sku(s, PREFIXES) for s in b.skus)
        files = cp.build_pdfs(blocks, {"pkg": slips}, "R1", {"Belirsiz sayfa": 1})
        self.assertEqual([f[0] for f in files], ["CRMC_R1_001.pdf"])
        t = self._texts(files[0][1])
        self.assertEqual(len(t), 1 + 3 + 1 + 1)               # özet + crmc1(2) + crmc5 + ayraç + GX1
        self.assertIn("Toplam blok: 3", t[0])
        self.assertIn("R1 · #001 · 1/2", t[1])
        self.assertIn(OID[2], t[1])
        self.assertIn("R1 · #001 · 2/2", t[2])
        self.assertIn("R1 · #002 · 1/1", t[3])
        self.assertIn("DİĞER SKU'LAR", t[4])
        self.assertIn("R1 · #003 · 1/1 · DİĞER", t[5])
        self.assertIn(OID[1], t[5])
        self.assertEqual(PdfReader(io.BytesIO(files[0][1])).pages[1].mediabox.width, 792)

    def test_split_every_100_blocks(self):
        blocks, slips = self._blocks(150, 60)
        files = cp.build_pdfs(blocks, slips, "R2")
        self.assertEqual([f[0] for f in files], ["CRMC_R2_001.pdf", "CRMC_R2_002.pdf", "CRMC_R2_003.pdf"])
        texts = [self._texts(d) for _, d in files]
        stamped = [sum(1 for x in t if "R2 · #" in x) for t in texts]
        self.assertEqual(stamped, [100, 100, 10])
        self.assertEqual(len(texts[1]), 100 + 1)              # 50 normal + ayraç + 50 diğer
        self.assertIn("CRMC Paket", texts[0][0])              # özet sadece ilk dosyada
        self.assertNotIn("CRMC Paket", texts[1][0])
        t2 = self._texts(files[1][1])
        self.assertIn("#101 · 1/1", t2[0])
        self.assertIn("DİĞER SKU'LAR", t2[50])
        self.assertIn("#151 · 1/1 · DİĞER", t2[51])
        self.assertIn("#210 · 1/1 · DİĞER", self._texts(files[2][1])[-1])


def make_templates(spec: dict[str, list[str]]) -> tempfile.TemporaryDirectory:
    """{"round_ceramic": ["CRMC1_template.ai", ...], ...} şeklinde geçici template kökü."""
    d = tempfile.TemporaryDirectory()
    for folder, files in spec.items():
        (Path(d.name) / folder).mkdir()
        for f in files:
            (Path(d.name) / folder / f).write_bytes(b"")
    return d


TEMPLATES = {
    "round_ceramic": ["CRMC1_template.ai", "CRMC1714 _template.ai", "crmc20.ai", "CRMC77_template.ai"],
    "heart_ceramic": ["CRM1228_template.ai", "CRMC1222_template.ai", "CRMC77_template.ai"],
    "snowglobe": ["ACRY1414_template.ai"],
}


def shaped_blocks(pages, manual=None, prefixes=PREFIXES):
    slips = slips_pdf(pages)
    blocks, _ = cp.parse_slips(slips, "pkg", "pkg.zip")
    for b in blocks:
        b.is_other = not all(cp.is_listed_sku(s, prefixes) for s in b.skus)
    with make_templates(TEMPLATES) as d:
        index = cp.build_template_index(d)
    shapes = cp.assign_shapes(blocks, prefixes, index, manual or {})
    return blocks, shapes, slips


class ShapeTests(unittest.TestCase):
    def test_template_index_names(self):
        with make_templates(TEMPLATES) as d:
            idx = cp.build_template_index(d)
        self.assertEqual(idx["crmc1714"], {"round_ceramic"})        # "CRMC1714 _template.ai"
        self.assertEqual(idx["crmc20"], {"round_ceramic"})          # uzantısız eşleşme
        self.assertEqual(idx["crmc77"], {"round_ceramic", "heart_ceramic"})
        self.assertIsNone(cp.build_template_index("/nonexistent/templates"))

    def test_resolve_sources(self):
        with make_templates(TEMPLATES) as d:
            idx = cp.build_template_index(d)
        r = lambda sku, title="Ornament", manual=None: cp.resolve_sku_shape(sku, title, idx, manual or {})
        self.assertEqual((r("CRMC1").shape, r("CRMC1").source), ("ROUND", "klasör"))
        self.assertEqual((r("crm1228").shape, r("crm1228").source), ("HEART", "klasör"))
        self.assertEqual((r("crmc77").shape, r("crmc77").source), ("UNKNOWN", "çakışma"))
        self.assertEqual((r("crmc9", "Big Heart Ornament").shape, r("crmc9", "Big Heart Ornament").source),
                         ("HEART", "başlık"))
        self.assertEqual(r("crmc9", "Round Heart").shape, "UNKNOWN")          # ikisi birden: tahmin yok
        self.assertEqual((r("acry1414").shape, r("acry1414").detail), ("UNKNOWN", "snowglobe klasöründe"))
        self.assertEqual(r("crmc77", manual={"crmc77": "HEART"}).source, "elle")   # elle çakışmayı ezer
        self.assertEqual(r("CRMC1", manual={"crmc1": "HEART"}).shape, "HEART")     # elle klasörü ezer

    def test_block_classes(self):
        blocks, _, _ = shaped_blocks([
            page(OID[0], item("crmc1") + item("crmc20")),            # round + round
            page(OID[1], item("crm1228") + item("crmc1222")),        # heart + heart
            page(OID[2], item("crmc1") + item("crm1228")),           # round + heart
            page(OID[3], item("crmc1") + item("crmc999")),           # round + belirsiz
            page(OID[4], item("crmc77")),                            # çakışma
            page(OID[5], item("crmc1") + item("GX55")),              # yabancı SKU sınıfı etkilemez
        ])
        self.assertEqual([b.shape for b in blocks], ["ROUND", "HEART", "MIXED", "UNKNOWN", "UNKNOWN", "ROUND"])
        self.assertEqual(blocks[2].shape_skus, {"ROUND": ["crmc1"], "HEART": ["crm1228"]})
        self.assertTrue(blocks[5].is_other)
        only_foreign, _, _ = shaped_blocks([page(OID[0], item("PO-1"))])
        self.assertIsNone(only_foreign[0].shape)

    def test_sort_sections(self):
        blocks, _, _ = shaped_blocks([
            page(OID[0], item("PO-1")),                              # sadece yabancı
            page(OID[1], item("crmc999")),                           # UNKNOWN
            page(OID[2], item("crmc1") + item("crm1228")),           # MIXED
            page(OID[3], item("crmc1222")),                          # HEART
            page(OID[4], item("crmc20")),                            # ROUND
            page(OID[5], item("crmc1")),                             # ROUND
            page("111-0000007-0000007", item("crm1228")),            # HEART
            page("111-0000008-0000008", item("crmc1") + item("RO-2")),  # ROUND + yabancı → DİĞER
        ])
        order = [(b.shape, b.first_sku, b.is_other) for b in cp.sort_blocks(blocks)]
        self.assertEqual(order, [
            ("ROUND", "crmc1", False), ("ROUND", "crmc20", False),
            ("HEART", "crm1228", False), ("HEART", "crmc1222", False),
            ("MIXED", "crmc1", False), ("UNKNOWN", "crmc999", False),
            ("ROUND", "crmc1", True), (None, "PO-1", True),
        ])

    def test_stamp_text(self):
        blocks, _, _ = shaped_blocks([
            page(OID[0], item("crmc1")), page(OID[1], item("crm1228")),
            page(OID[2], item("crmc1") + item("crmc20") + item("crm1228")),
            page(OID[3], item("crmc999")), page(OID[4], item("crmc1") + item("GX1")), page(OID[5], item("GX2")),
        ])
        texts = [cp.stamp_text("R1", 7, 1, b) for b in blocks]
        self.assertEqual(texts, [
            "R1 · #007 · 1/1 · R",
            "R1 · #007 · 1/1 · H",
            "R1 · #007 · 1/1 · MIX R: crmc1, crmc20 | H: crm1228",
            "R1 · #007 · 1/1 · ?",
            "R1 · #007 · 1/1 · R · DİĞER",
            "R1 · #007 · 1/1 · DİĞER",
        ])

    def test_partial_pdf_and_printed(self):
        blocks, _, slips = shaped_blocks([
            page(OID[0], item("crmc1")),                    # ROUND
            page(OID[1], item("crm1228")),                  # HEART
            page(OID[2], item("crmc1") + item("crm1228")),  # MIXED
            page(OID[3], item("crmc999")),                  # UNKNOWN
            page(OID[4], item("GX9")),                      # sadece yabancı
            page(OID[5], item("crmc1222") + item("GX1")),   # HEART + yabancı
        ])
        sel = cp.select_blocks(blocks, "ROUND")
        self.assertEqual(sorted(b.order_id for b in sel), sorted([OID[0], OID[2], OID[3], OID[4]]))
        self.assertEqual(len(cp.select_blocks(blocks, "all")), 6)
        heart = cp.select_blocks(blocks, "HEART")
        self.assertEqual(sorted(b.order_id for b in heart), sorted([OID[1], OID[2], OID[3], OID[4], OID[5]]))

        files = cp.build_pdfs(sel, {"pkg": slips}, "R9", scope_label="Sadece ROUND")
        texts = [pg.extract_text() or "" for pg in PdfReader(io.BytesIO(files[0][1])).pages]
        self.assertIn("Kapsam: Sadece ROUND", texts[0])
        self.assertIn("ROUND: 1 blok (#001-#001)", texts[0])
        self.assertIn("MIXED: 1 blok (#002-#002)", texts[0])
        stamps = [t for t in texts[1:] if "R9 · #" in t]
        self.assertEqual(len(stamps), 4)
        self.assertIn("#001 · 1/1 · R", stamps[0])
        self.assertIn("#002 · 1/1 · MIX R: crmc1 | H: crm1228", stamps[1])
        self.assertIn("#003 · 1/1 · ?", stamps[2])
        self.assertIn("#004 · 1/1 · DİĞER", stamps[3])
        self.assertFalse(any(OID[1] in t for t in texts))           # HEART bloğu PDF'te yok

        with tempfile.TemporaryDirectory() as d:
            pf = Path(d) / "printed.json"
            cp.mark_printed([b.key for b in sel], "R9", pf)
            printed = cp.load_printed(pf)
        left = [b.order_id for b in blocks if b.key not in printed]
        self.assertEqual(sorted(left), sorted([OID[1], OID[5]]))   # HEART'lar basılmamış kaldı

    def test_manual_shapes_file(self):
        with tempfile.TemporaryDirectory() as d:
            pf = Path(d) / "shapes.json"
            self.assertEqual(cp.load_manual_shapes(pf), {})
            cp.save_manual_shapes({"ACRY1414": "ROUND", "x": "BAD"}, pf)
            self.assertEqual(cp.load_manual_shapes(pf), {"acry1414": "ROUND"})


if __name__ == "__main__":
    unittest.main()
