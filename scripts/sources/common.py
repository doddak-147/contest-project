import html
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

KST = timezone(timedelta(hours=9))
REQUEST_DELAY = 0.3
IT_PATTERN = re.compile(
    r"\b(?:AI|SW|ICT|IT)\b|소프트웨어|웹|앱|개발|프로그래밍|데이터|코딩|해커톤|로봇|컴퓨터|디지털|게임|과학기술",
    re.IGNORECASE,
)


@dataclass
class Collection:
    records: list[dict]
    pages: int
    observed_ids: set[str] = field(default_factory=set)


def today_kst() -> date:
    return datetime.now(KST).date()


def clean(value) -> str:
    return " ".join(html.unescape(str(value or "")).split())


def text(element) -> str:
    return clean(element.get_text(" ", strip=True)) if element else ""


def parse_date(value) -> str:
    match = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", str(value or ""))
    if not match:
        return ""
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return ""


def parse_period(value) -> tuple[str, str]:
    dates = re.findall(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", str(value or ""))
    return (parse_date(dates[0]), parse_date(dates[-1])) if len(dates) >= 2 else ("", "")


def make_contest(*, source_id, source_name, title, organization, start_date, deadline,
                 category, eligibility="", award="", award_detail="", apply_method="", link):
    title, deadline = clean(title), parse_date(deadline)
    if not title or not deadline or date.fromisoformat(deadline) < today_kst():
        return None
    start_date = parse_date(start_date)
    category = clean(category) or "기타"
    days_left = (date.fromisoformat(deadline) - today_kst()).days
    status = "접수 예정" if start_date and start_date > today_kst().isoformat() else (
        "마감 임박" if days_left <= 7 else "접수 중"
    )
    return {
        "id": source_id,
        "title": title,
        "organization": clean(organization),
        "start_date": start_date,
        "deadline": deadline,
        "category": category,
        "category_group": "IT" if IT_PATTERN.search(f"{title} {category}") else "ETC",
        "eligibility": clean(eligibility) or "공고에서 확인",
        "award": clean(award) or "공고에서 확인",
        "award_detail": clean(award_detail),
        "apply_method": clean(apply_method),
        "status": status,
        "link": link,
        "source": source_name,
    }


def build_session(referer: str) -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "POST"), respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "Accept": "text/html,application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "User-Agent": "Contestly/1.0 (public contest index; daily update)",
        "Referer": referer,
    })
    return session


def get_soup(session: requests.Session, url: str, **kwargs) -> BeautifulSoup:
    time.sleep(REQUEST_DELAY)
    response = session.get(url, timeout=25, **kwargs)
    response.raise_for_status()
    return BeautifulSoup(response.content, "html.parser", from_encoding="utf-8")
