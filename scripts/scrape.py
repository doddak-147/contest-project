import requests
import json
import time
from pathlib import Path

BASE_URL = "https://www.thinkcontest.com"
API_URL = "https://www.thinkcontest.com/thinkgood/user/bannerinfo/jsonList.do"
PAGE_URL = "https://www.thinkcontest.com/thinkgood/user/contest/index.do"

def is_it_contest(title: str) -> bool:
    keywords = [
        "AI", "SW", "소프트웨어", "웹", "앱", "개발",
        "프로그래밍", "데이터", "ICT", "IT", "코딩",
        "해커톤", "로봇", "시스템", "컴퓨터",
        "디지털", "플랫폼", "기술", "온라인", "엔지니어"
    ]
    title_lower = title.lower()
    return any(k.lower() in title_lower for k in keywords)

def main():
    session = requests.Session()

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Referer": PAGE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }

    params = {
        "pagesite": "contest",
        "division": "pcmainb",
        "special": "CHARGE",
        "contest_field": "",
        "host_organ": "",
        "enter_qualified": "",
        "award_size": "",
        "_": str(int(time.time() * 1000))
    }

    res = session.get(API_URL, params=params, headers=headers, timeout=15)
    res.raise_for_status()

    data = res.json()
    raw_list = data.get("listJsonData", [])

    contests = []

    for item in raw_list:
        title = str(item.get("contest_nm", "")).strip()
        org = str(item.get("host_company", "")).strip()
        period = str(item.get("receive_period", "")).strip()
        inner_link = str(item.get("inner_link", "")).strip()

        if not title or not period or not inner_link:
            continue

        end_date = period.split("~")[-1].strip()
        link = BASE_URL + inner_link
        category = "IT" if is_it_contest(title) else "ETC"

        contests.append({
            "title": title,
            "organization": org,
            "deadline": end_date,
            "link": link,
            "category": category
        })

    output_path = Path(__file__).resolve().parent.parent / "data" / "contests.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(contests, f, ensure_ascii=False, indent=2)

    print(f"완료! 총 {len(contests)}개 저장됨")

if __name__ == "__main__":
    main()