import math
import time

from .common import Collection, REQUEST_DELAY, build_session, clean, make_contest, parse_date

NAME = "씽굿"
URL = "https://www.thinkcontest.com/thinkgood/user/contest/index.do"
API_URL = "https://www.thinkcontest.com/thinkgood/user/contest/subList.do"
KEEP_UNSEEN = False


def parse_record(item: dict) -> dict | None:
    contest_id = clean(item.get("contest_pk"))
    if not contest_id:
        return None
    return make_contest(
        source_id=f"thinkcontest-{contest_id}", source_name=NAME,
        title=item.get("program_nm"), organization=item.get("host_company"),
        start_date=item.get("accept_dt"),
        deadline=parse_date(item.get("extend_dt")) or parse_date(item.get("finish_dt")),
        category=item.get("contest_field_nm"), eligibility=item.get("enter_qualified_nm"),
        award=item.get("award_size_nm"), award_detail=item.get("prize_money"),
        apply_method=item.get("apply_method_nm"),
        link=f"https://www.thinkcontest.com/thinkgood/user/contest/view.do?contest_pk={contest_id}",
    )


def collect(max_pages: int = 5) -> Collection:
    records, pages = {}, 0
    with build_session(URL) as session:
        for process in ("ING", "INGEND", "YET"):
            page, total_pages, seen = 1, 1, set()
            while page <= total_pages:
                time.sleep(REQUEST_DELAY)
                response = session.post(API_URL, json={
                    "recordsPerPage": 10, "currentPageNo": page,
                    "contest_field": "", "host_organ": "", "enter_qualified": "",
                    "award_size": "", "searchStatus": "Y", "searchProcess": process,
                    "sidx": "", "sord": "",
                }, timeout=25)
                response.raise_for_status()
                data = response.json()
                if str(data.get("status")) != "1":
                    raise RuntimeError(f"씽굿 목록 오류: {process}/{page}")
                rows = data.get("listJsonData") or []
                if page == 1:
                    total = int(data.get("totalcnt") or 0)
                    total_pages = math.ceil(total / len(rows)) if rows else 0
                    if total and not rows:
                        raise RuntimeError("씽굿 목록의 건수와 응답이 일치하지 않습니다.")
                    if total_pages > 500:
                        raise RuntimeError("씽굿 페이지 수가 예상 범위를 벗어났습니다.")
                ids = {str(item.get("contest_pk")) for item in rows}
                if page > 1 and (not rows or ids <= seen):
                    raise RuntimeError("씽굿 페이지 순회가 중단되어 기존 데이터를 유지합니다.")
                seen.update(ids)
                for item in rows:
                    record = parse_record(item)
                    if record:
                        records[record["id"]] = record
                pages += 1
                page += 1
    return Collection(list(records.values()), pages)
