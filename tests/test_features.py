import importlib.util
import datetime
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


indic = load_module("indic_transliterate", ROOT / "IndicTransliterator" / "indic_transliterate.py")
find_replace = load_module("find_replace_app", ROOT / "FindReplaceApp" / "find_replace_app.py")
sys.path.insert(0, str(ROOT / "Youtube Transcript"))
youtube = load_module("youtube_transcript", ROOT / "Youtube Transcript" / "youtube_transcript.py")
cleaner = load_module("remove_timestamps", ROOT / "Youtube Transcript" / "remove_timestamps.py")


class IndicTests(unittest.TestCase):
    def test_iast_round_trip(self):
        self.assertEqual(indic.transliterate("कृष्ण", "devanagari", "english"), "kṛṣṇa")
        self.assertEqual(indic.transliterate("bhārata", "english", "devanagari"), "भारत")

    def test_large_input_is_not_sliced(self):
        source = "नमस्ते " * 50000
        result = indic.transliterate(source, "devanagari", "kannada")
        self.assertEqual(len(result), len(source))
        self.assertTrue(result.endswith(" "))


class PlaylistTests(unittest.TestCase):
    def test_start_video_wins_and_index_is_fallback(self):
        info = {"video_ids": ["a", "b", "c", "d"]}
        self.assertEqual(youtube.take_from(info, "c", 2, 1), (["c", "d"], 2))
        self.assertEqual(youtube.take_from(info, "missing", 2, 3), (["c", "d"], 2))

    def test_index_and_combined_section(self):
        url = "https://youtube.com/watch?v=abcdefghijk&list=PL123&index=17"
        self.assertEqual(youtube.extract_playlist_index(url), 17)
        section = cleaner.playlist_section(17, "Lesson", "abcdefghijk", "Transcript")
        self.assertIn("#17 - Lesson [abcdefghijk]", section)
        self.assertIn("Transcript", section)


class XlsTests(unittest.TestCase):
    def test_first_sheet_values_and_types(self):
        import xlrd
        import xlwt

        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            source = folder / "input.xls"
            reference = folder / "pairs.csv"
            output = folder / "output.xls"

            book = xlwt.Workbook()
            sheet = book.add_sheet("Data")
            sheet.write(0, 0, "colour and colour")
            sheet.write(0, 1, 42)
            sheet.write(1, 0, True)
            sheet.write(1, 1, datetime.datetime(2026, 9, 15),
                        xlwt.easyxf(num_format_str="YYYY-MM-DD"))
            book.add_sheet("Ignored").write(0, 0, "colour")
            book.save(str(source))
            reference.write_text("Find,Replace\ncolour,color\n", encoding="utf-8")

            result = find_replace.run_job(str(source), str(reference), str(output))
            saved = xlrd.open_workbook(str(output))
            self.assertEqual(saved.sheet_names(), ["Data"])
            out = saved.sheet_by_index(0)
            self.assertEqual(out.cell_value(0, 0), "color and color")
            self.assertEqual(out.cell_value(0, 1), 42)
            self.assertEqual(out.cell_type(1, 0), xlrd.XL_CELL_BOOLEAN)
            self.assertEqual(out.cell_type(1, 1), xlrd.XL_CELL_DATE)
            self.assertEqual(result["total"], 2)


if __name__ == "__main__":
    unittest.main()
