from urllib.parse import parse_qs, urlparse

from .common import Collection, build_session, clean, get_soup, make_contest, parse_period, text

NAME = "위비티"
URL = "https://www.wevity.com/?c=find&s=1&gub=1"
KEEP_UNSEEN = True


def parse_listing(soup) -> list[tuple[str, str]]:
    items = []
    for anchor in soup.select("ul.list > li .tit a[href]"):
        contest_id = parse_qs(urlparse(anchor["href"]).query).get("ix", [""])[0]
        if contest_id.isdigit():
            items.append((contest_id, f"https://www.wevity.com/?c=find&s=1&gub=1&gbn=view&ix={contest_id}"))
    return items


def parse_detail(soup, contest_id: str, link: str) -> dict | None:
    detail = soup.select_one(".contest-detail")
    if not detail:
        raise ValueError("위비티 상세 정보 영역을 찾을 수 없습니다.")
    fields = {}
    for item in detail.select(".cd-info-list > li"):
        label = item.select_one(".tit")
        if label:
            key = text(label)
            fields[key] = clean(text(item).removeprefix(key))
    start_date, deadline = parse_period(fields.get("접수기간"))
    return make_contest(
        source_id=f"wevity-{contest_id}", source_name=NAME,
        title=text(detail.select_one(".tit-area .tit")), organization=fields.get("주최/주관"),
        start_date=start_date, deadline=deadline, category=fields.get("분야"),
        eligibility=fields.get("응모대상"), award=fields.get("총 상금"),
        award_detail=fields.get("1등 상금"), link=link,
    )


def collect(max_pages: int = 5) -> Collection:
    links, pages = {}, 0
    with build_session(URL) as session:
        for mode in ("ing", "future"):
            seen = set()
            for page in range(1, max_pages + 1):
                soup = get_soup(session, "https://www.wevity.com/", params={
                    "c": "find", "s": 1, "gub": 1, "mode": mode, "gp": page,
                })
                if not soup.select_one("ul.list"):
                    raise ValueError("위비티 목록 영역을 찾을 수 없습니다.")
                items = parse_listing(soup)
                if not items:
                    break
                ids = {item[0] for item in items}
                if ids <= seen:
                    raise ValueError("위비티에서 같은 목록 페이지가 반복됩니다.")
                seen.update(ids)
                links.update(items)
                pages += 1
                has_next = any(
                    int(parse_qs(urlparse(a["href"]).query).get("gp", ["0"])[0]) > page
                    for a in soup.select(".list-navi a[href]")
                )
                if not has_next:
                    break

        records = []
        for index, (contest_id, link) in enumerate(links.items(), 1):
            record = parse_detail(get_soup(session, link), contest_id, link)
            if record:
                records.append(record)
            if index % 25 == 0:
                print(f"[{NAME}] 상세 {index}/{len(links)}개 확인", flush=True)
    return Collection(records, pages, {f"wevity-{item}" for item in links})
