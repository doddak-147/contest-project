from urllib.parse import parse_qs, urlencode, urlparse

from .common import Collection, build_session, get_soup, make_contest, parse_period, text

NAME = "콘테스트코리아"
URL = "https://www.contestkorea.com/sub/list.php?int_gbn=1"
KEEP_UNSEEN = True


def parse_listing(soup) -> list[tuple[str, str]]:
    items = []
    for anchor in soup.select(".list_style_2 > ul > li .title a[href]"):
        query = parse_qs(urlparse(anchor["href"]).query)
        contest_id = query.get("str_no", [""])[0]
        if contest_id.isdigit() and query.get("int_gbn") == ["1"]:
            params = {"int_gbn": 1, "Txt_bcode": query.get("Txt_bcode", [""])[0], "str_no": contest_id}
            items.append((contest_id, f"https://www.contestkorea.com/sub/view.php?{urlencode(params)}"))
    return items


def parse_detail(soup, contest_id: str, link: str) -> dict | None:
    fields = {}
    for row in soup.select("table tr"):
        label, value = row.find("th"), row.find("td")
        if label and value:
            fields[text(label).replace(" ", "")] = text(value)
    if "접수기간" not in fields or not soup.select_one("h1"):
        raise ValueError("콘테스트코리아 상세 정보 영역을 찾을 수 없습니다.")
    start_date, deadline = parse_period(fields["접수기간"])
    return make_contest(
        source_id=f"contestkorea-{contest_id}", source_name=NAME,
        title=text(soup.select_one("h1")), organization=fields.get("주최.주관"),
        start_date=start_date, deadline=deadline, category=fields.get("대표분야"),
        eligibility=fields.get("참가대상"), award=fields.get("시상내역"),
        apply_method=fields.get("접수방법"), link=link,
    )


def collect(max_pages: int = 5) -> Collection:
    links, pages, seen = {}, 0, set()
    with build_session(URL) as session:
        for page in range(1, max_pages + 1):
            soup = get_soup(session, "https://www.contestkorea.com/sub/list.php", params={
                "int_gbn": 1, "page": page, "displayrow": 12,
            })
            if not soup.select_one(".list_style_2"):
                raise ValueError("콘테스트코리아 목록 영역을 찾을 수 없습니다.")
            items = parse_listing(soup)
            if not items:
                break
            ids = {item[0] for item in items}
            if ids <= seen:
                raise ValueError("콘테스트코리아에서 같은 목록 페이지가 반복됩니다.")
            seen.update(ids)
            links.update(items)
            pages += 1
            if len(items) < 12:
                break

        records = []
        for index, (contest_id, link) in enumerate(links.items(), 1):
            record = parse_detail(get_soup(session, link), contest_id, link)
            if record:
                records.append(record)
            if index % 25 == 0:
                print(f"[{NAME}] 상세 {index}/{len(links)}개 확인", flush=True)
    return Collection(records, pages, {f"contestkorea-{item}" for item in links})
