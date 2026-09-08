import json
import math
import time
from datetime import date, datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://www.thinkcontest.com"
LIST_API_URL = f"{BASE_URL}/thinkgood/user/contest/subList.do"
PAGE_URL = f"{BASE_URL}/thinkgood/user/contest/index.do"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "contests.json"

ACTIVE_PROCESSES = ("ING", "INGEND", "YET")
PROCESS_LABELS = {
    "ING": "접수 중",
    "INGEND": "마감 임박",
    "YET": "접수 예정",
}

IT_KEYWORDS = {
    "AI", "SW", "소프트웨어", "웹", "앱", "개발", "프로그래밍", "데이터",
    "ICT", "IT", "코딩", "해커톤", "로봇", "시스템", "컴퓨터", "디지털",
    "플랫폼", "게임", "과학기술",
}


def clean(value) -> str:
    return " ".join(str(value or "").split())


def date_part(value) -> str:
    text = clean(value)
    if not text:
        return ""
    candidate = text[:10]
    try:
        return datetime.strptime(candidate, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def is_it_contest(title: str, field_name: str) -> bool:
    searchable = f"{title} {field_name}".lower()
    return any(keyword.lower() in searchable for keyword in IT_KEYWORDS)


def build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("POST",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(
        {
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": PAGE_URL,
            "User-Agent": "Contestly/1.0 (+daily public contest index)",
        }
    )
    return session


def request_page(session: requests.Session, process: str, page: int) -> dict:
    payload = {
        "recordsPerPage": 10,
        "currentPageNo": page,
        "contest_field": "",
        "host_organ": "",
        "enter_qualified": "",
        "award_size": "",
        "searchStatus": "Y",
        "searchProcess": process,
        "sidx": "",
        "sord": "",
    }
    response = session.post(LIST_API_URL, json=payload, timeout=25)
    response.raise_for_status()
    data = response.json()
    if str(data.get("status")) != "1":
        raise RuntimeError(data.get("msg") or f"목록 API 오류: {process} {page}페이지")
    return data


def normalize_contest(item: dict) -> dict | None:
    contest_id = clean(item.get("contest_pk"))
    title = clean(item.get("program_nm"))
    deadline = date_part(item.get("extend_dt")) or date_part(item.get("finish_dt"))

    if not contest_id or not title or not deadline:
        return None
    if date.fromisoformat(deadline) < date.today():
        return None

    field_name = clean(item.get("contest_field_nm")) or "기타"
    category_group = "IT" if is_it_contest(title, field_name) else "ETC"

    return {
        "id": f"thinkcontest-{contest_id}",
        "title": title,
        "organization": clean(item.get("host_company")),
        "start_date": date_part(item.get("accept_dt")),
        "deadline": deadline,
        "category": field_name,
        "category_group": category_group,
        "eligibility": clean(item.get("enter_qualified_nm")) or "제한 없음",
        "award": clean(item.get("award_size_nm")) or "시상 내역 확인 필요",
        "award_detail": clean(item.get("prize_money")),
        "apply_method": clean(item.get("apply_method_nm")),
        "status": PROCESS_LABELS.get(clean(item.get("process")), "접수 중"),
        "link": f"{BASE_URL}/thinkgood/user/contest/view.do?contest_pk={contest_id}",
        "source": "씽굿",
    }


def fetch_active_contests(session: requests.Session) -> list[dict]:
    contests_by_id: dict[str, dict] = {}

    for process in ACTIVE_PROCESSES:
        first = request_page(session, process, 1)
        total = int(first.get("totalcnt") or 0)
        rows = first.get("listJsonData") or []
        pages = max(1, math.ceil(total / max(1, len(rows)))) if total else 1

        for page in range(1, pages + 1):
            data = first if page == 1 else request_page(session, process, page)
            page_rows = data.get("listJsonData") or []
            if not page_rows:
                break

            for item in page_rows:
                contest = normalize_contest(item)
                if contest:
                    contests_by_id[contest["id"]] = contest

            if page < pages:
                time.sleep(0.12)

    return sorted(
        contests_by_id.values(),
        key=lambda contest: (contest["deadline"], contest["title"]),
    )


def write_json_safely(contests: list[dict]) -> None:
    if not contests:
        raise RuntimeError("수집 결과가 비어 있어 기존 데이터를 유지합니다.")

    temporary_path = OUTPUT_PATH.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(contests, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(OUTPUT_PATH)


def main() -> None:
    session = build_session()
    contests = fetch_active_contests(session)
    write_json_safely(contests)
    print(f"완료! 진행 중·마감 임박·접수 예정 공모전 {len(contests)}개 저장됨")


if __name__ == "__main__":
    main()
