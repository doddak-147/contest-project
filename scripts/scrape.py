import requests
import json
import time
from pathlib import Path

print("=== 새 scrape.py 실행됨 ===")

BASE_URL = "https://www.thinkcontest.com"
API_URL = "https://www.thinkcontest.com/thinkgood/user/bannerinfo/jsonList.do"
PAGE_URL = "https://www.thinkcontest.com/thinkgood/user/contest/index.do"

def is_it_contest(title: str) -> bool:
    keywords = [
        "AI", "SW", "소프트웨어", "웹", "앱", "개발",
        "프로그래밍", "데이터", "ICT", "IT", "코딩",
        "해커톤", "로봇", "시스템", "컴퓨터"
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

    print("status code:", res.status_code)
    print("content-type:", res.headers.get("Content-Type"))
    print("response preview:")
    print(res.text[:300])

    res.raise_for_status()

    data = res.json()
    raw_list = data.get("listJsonData", [])

    print("raw_list 개수:", len(raw_list))

    contests = []

    for i, item in enumerate(raw_list):
        title = str(item.get("contest_nm", "")).strip()
        org = str(item.get("host_company", "")).strip()
        period = str(item.get("receive_period", "")).strip()
        inner_link = str(item.get("inner_link", "")).strip()

        print(f"[{i}] title={title}")
        print(f"[{i}] period={period}")
        print(f"[{i}] inner_link={inner_link}")
        print("-" * 40)

        if not title or not period or not inner_link:
            print(f"[{i}] 저장 제외됨")
            continue

        end_date = period.split("~")[-1].strip()
        link = BASE_URL + inner_link

        contests.append({
            "title": title,
            "organization": org,
            "deadline": end_date,
            "link": link,
            "category": "ETC"
        })

    output_path = Path(__file__).resolve().parent.parent / "data" / "contests.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(contests, f, ensure_ascii=False, indent=2)

    print("저장 위치:", output_path)
    print("완료! 총", len(contests), "개 저장됨")

if __name__ == "__main__":
    main()