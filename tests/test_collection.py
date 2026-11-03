import json
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scrape
from sources import contestkorea, thinkcontest, wevity
from sources.common import Collection


def soup(markup):
    return BeautifulSoup(markup, "html.parser")


def record(source="thinkcontest", title="2026 우리동네 아이디어 공모전", **changes):
    return {
        "id": f"{source}-1", "source": {"thinkcontest": "씽굿", "wevity": "위비티", "contestkorea": "콘테스트코리아"}[source],
        "title": title, "organization": "우리동네재단", "deadline": "2026-12-01",
        "category": "아이디어", "category_group": "ETC", "link": f"https://example.com/{source}/1",
        **changes,
    }


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.today = patch("sources.common.today_kst", return_value=date(2026, 11, 3))
        self.today.start()
        self.addCleanup(self.today.stop)

    def test_wevity_list_ignores_sidebar_and_extracts_stable_detail_link(self):
        page = soup('''<a href="?ix=999">광고</a><ul class="list"><li class="top">제목</li>
          <li><div class="tit"><a href="?c=find&amp;gbn=view&amp;ix=112063&amp;gp=3">공모전</a></div></li></ul>''')
        rows = wevity.parse_listing(page)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "112063")
        self.assertNotIn("gp=", rows[0][1])

    def test_wevity_actual_detail_fields_and_dates(self):
        page = soup('''<div class="contest-detail"><div class="tit-area"><h6 class="tit">AI 아이디어 &amp; 영상 공모전</h6></div>
          <ul class="cd-info-list"><li><span class="tit">분야</span>웹/모바일/IT</li>
          <li><span class="tit">주최/주관</span>우리동네재단</li><li><span class="tit">응모대상</span>제한없음</li>
          <li><span class="tit">접수기간</span>2026-10-19 ~ 2026-11-15 <span>D-13</span></li>
          <li><span class="tit">총 상금</span>500만원</li></ul></div>''')
        result = wevity.parse_detail(page, "112063", "https://www.wevity.com/?ix=112063")
        self.assertEqual(result["deadline"], "2026-11-15")
        self.assertEqual(result["category_group"], "IT")
        self.assertEqual(result["eligibility"], "제한없음")
        self.assertEqual(result["award"], "500만원")

    def test_contestkorea_detail_does_not_confuse_judging_and_application_dates(self):
        page = soup('''<h1>2026 청소년 영상 공모전</h1><table>
          <tr><th>주최 . 주관</th><td>우리동네재단</td></tr>
          <tr><th>대표분야</th><td>사진•영상•영화제</td></tr>
          <tr><th>참가대상</th><td>고등학생 (서울 거주)</td></tr>
          <tr><th>접수기간</th><td>2026.10.15 ~ 2026.11.20</td></tr>
          <tr><th>심사기간</th><td>2026.11.23 ~ 2026.12.09</td></tr>
          <tr><th>시상내역</th><td>총상금 : 610만원</td></tr></table>''')
        result = contestkorea.parse_detail(page, "202610260047", "https://www.contestkorea.com/sub/view.php")
        self.assertEqual(result["organization"], "우리동네재단")
        self.assertEqual(result["start_date"], "2026-10-15")
        self.assertEqual(result["deadline"], "2026-11-20")
        self.assertEqual(result["eligibility"], "고등학생 (서울 거주)")

    def test_changed_page_layout_is_failure_not_empty_success(self):
        with self.assertRaises(ValueError):
            wevity.parse_detail(soup("<html>잠시 후 다시 접속하세요</html>"), "1", "https://www.wevity.com/")
        with self.assertRaises(ValueError):
            contestkorea.parse_detail(soup("<h1>오류</h1>"), "1", "https://www.contestkorea.com/")

    def test_thinkcontest_extended_deadline_and_unknown_eligibility(self):
        item = {"contest_pk": 1, "program_nm": "공모전", "finish_dt": "2026-10-01 00:00:00",
                "extend_dt": "2026-12-01 23:59:00", "contest_field_nm": "디자인"}
        result = thinkcontest.parse_record(item)
        self.assertEqual(result["deadline"], "2026-12-01")
        self.assertEqual(result["eligibility"], "공고에서 확인")


class MergeTests(unittest.TestCase):
    def test_duplicate_sources_merge_and_all_bookmark_aliases_remain(self):
        result = scrape.merge_contests([record(), record("wevity", title="[기간연장] 2026 우리동네 아이디어 공모전")], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "thinkcontest-1")
        self.assertEqual(set(result[0]["aliases"]), {"thinkcontest-1", "wevity-1"})
        self.assertEqual(len(result[0]["sources"]), 2)

    def test_existing_canonical_id_is_stable_after_new_source_added(self):
        previous = [record("wevity")]
        result = scrape.merge_contests([record(), record("wevity")], previous)
        self.assertEqual(result[0]["id"], "wevity-1")
        self.assertEqual(result[0]["source"], "위비티")

    def test_round_deadline_or_host_difference_does_not_merge(self):
        rows = [record(), record("wevity", organization="다른재단"),
                record("contestkorea", deadline="2026-12-02"),
                record("wevity", title="2027 우리동네 아이디어 공모전", id="wevity-2")]
        self.assertEqual(len(scrape.merge_contests(rows, [])), 4)

    def test_removed_source_alias_survives_for_existing_bookmarks(self):
        previous = scrape.merge_contests([record(), record("wevity")], [])
        result = scrape.merge_contests([record()], previous)
        self.assertIn("wevity-1", result[0]["aliases"])

    def test_split_duplicates_keep_unique_ids_and_separate_aliases(self):
        previous = scrape.merge_contests([record(), record("wevity")], [])
        result = scrape.merge_contests([record(), record("wevity", deadline="2026-12-02")], previous)
        self.assertEqual({row["id"] for row in result}, {"thinkcontest-1", "wevity-1"})
        self.assertEqual(result[0]["aliases"], ["thinkcontest-1"])

    def test_duplicate_rows_on_same_site_have_one_source_link(self):
        result = scrape.merge_contests([record(), record(id="thinkcontest-2")], [])
        self.assertEqual(len(result[0]["sources"]), 1)
        self.assertEqual(len(result[0]["aliases"]), 2)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in {
            "OUTPUT_PATH": self.root / "contests.json",
            "METADATA_PATH": self.root / "collection-status.json",
            "CACHE_DIR": self.root / "sources",
        }.items():
            patcher = patch.object(scrape, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("scrape.today_kst", return_value=date(2026, 11, 3))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failed_source_retains_only_unexpired_cached_records(self):
        cache = scrape.CACHE_DIR / "wevity.json"
        scrape.write_json_safely(cache, [record("wevity"), record("wevity", id="wevity-old", deadline="2026-10-01")])
        before = cache.read_bytes()
        with patch.object(wevity, "collect", side_effect=TimeoutError("upstream timeout")):
            rows, status = scrape.refresh_source("wevity", 5, [], {})
        self.assertEqual([row["id"] for row in rows], ["wevity-1"])
        self.assertEqual(status["status"], "cached")
        self.assertEqual(cache.read_bytes(), before)

    def test_recent_scan_removes_observed_closed_records_and_retains_unseen_records(self):
        cache = scrape.CACHE_DIR / "wevity.json"
        scrape.write_json_safely(cache, [record("wevity"), record("wevity", id="wevity-2")])
        fresh = Collection([record("wevity", id="wevity-3")], 1, {"wevity-1", "wevity-3"})
        with patch.object(wevity, "collect", return_value=fresh):
            rows, status = scrape.refresh_source("wevity", 5, [], {})
        self.assertEqual({row["id"] for row in rows}, {"wevity-2", "wevity-3"})
        self.assertEqual(status["status"], "success")

    def test_all_sources_fail_without_overwriting_published_data(self):
        scrape.write_json_safely(scrape.OUTPUT_PATH, [record()])
        before = scrape.OUTPUT_PATH.read_bytes()
        with patch.object(thinkcontest, "collect", side_effect=TimeoutError("timeout")), \
             patch.object(wevity, "collect", side_effect=TimeoutError("timeout")), \
             patch.object(contestkorea, "collect", side_effect=TimeoutError("timeout")):
            with self.assertRaises(RuntimeError):
                scrape.run()
        self.assertEqual(scrape.OUTPUT_PATH.read_bytes(), before)

    def test_partial_failure_publishes_success_and_preserves_failed_source(self):
        scrape.write_json_safely(scrape.CACHE_DIR / "thinkcontest.json", [record()])
        scrape.write_json_safely(scrape.CACHE_DIR / "contestkorea.json", [record("contestkorea", title="별도 문학 공모전")])
        with patch.object(thinkcontest, "collect", side_effect=TimeoutError("timeout")), \
             patch.object(wevity, "collect", return_value=Collection([record("wevity", title="새로운 영상 공모전")], 1)), \
             patch.object(contestkorea, "collect", side_effect=TimeoutError("timeout")):
            metadata = scrape.run()
        rows = json.loads(scrape.OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(metadata["sources"]["thinkcontest"]["status"], "cached")
        self.assertEqual(metadata["sources"]["wevity"]["status"], "success")

    def test_targeted_refresh_preserves_other_source_snapshot(self):
        scrape.write_json_safely(scrape.CACHE_DIR / "thinkcontest.json", [record()])
        fresh = Collection([record("wevity", title="다른 공모전")], 1)
        with patch.object(wevity, "collect", return_value=fresh):
            metadata = scrape.run(selected_sources=["wevity"])
        rows = json.loads(scrape.OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(metadata["sources"]["thinkcontest"]["status"], "not_refreshed")


if __name__ == "__main__":
    unittest.main()
