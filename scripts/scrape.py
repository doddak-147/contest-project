"""Collect contest summaries, retaining per-source snapshots on upstream failures."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import re
import unicodedata
from pathlib import Path

if __package__:
    from .sources import COLLECTORS
    from .sources.common import KST, clean, parse_date, today_kst
else:
    from sources import COLLECTORS
    from sources.common import KST, clean, parse_date, today_kst

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_PATH = DATA_DIR / "contests.json"
METADATA_PATH = DATA_DIR / "collection-status.json"
CACHE_DIR = DATA_DIR / "sources"


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json_safely(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(path)


def active_records(records: list[dict]) -> list[dict]:
    today = today_kst().isoformat()
    return [record for record in records if parse_date(record.get("deadline")) >= today]


def normalize_identity(value: str) -> str:
    value = unicodedata.normalize("NFKC", clean(value)).casefold()
    # Remove only administrative extension tags, keeping years/rounds/regions intact.
    value = re.sub(r"[\[(]\s*(?:접수\s*)?기간\s*연장\s*[\])]", "", value)
    return re.sub(r"[^\w가-힣]", "", value)


def same_organization(first: dict, second: dict) -> bool:
    left, right = normalize_identity(first.get("organization", "")), normalize_identity(second.get("organization", ""))
    return bool(left and right) and (left == right or (min(len(left), len(right)) >= 6 and (left in right or right in left)))


def merge_contests(records: list[dict], previous: list[dict]) -> list[dict]:
    """Conservative title/deadline/host match with stable IDs and source aliases."""
    previous_ids = {}
    for record in previous:
        for member_id in [record["id"], *record.get("aliases", [])]:
            previous_ids[member_id] = record["id"]

    current_ids = {record["id"] for record in records}
    groups = {}
    for record in sorted(records, key=lambda item: (not item["id"].startswith("thinkcontest-"), item["id"])):
        key = (normalize_identity(record["title"]), record["deadline"])
        matches = groups.setdefault(key, [])
        group = next((group for group in matches if any(same_organization(record, member) for member in group)), None)
        if group is None:
            matches.append([record])
        elif all(member["id"] != record["id"] for member in group):
            group.append(record)

    combined = []
    used_ids = set()
    for matches in groups.values():
        for group in matches:
            aliases = sorted({record["id"] for record in group})
            candidates = [previous_ids[alias] for alias in aliases if alias in previous_ids
                          and (previous_ids[alias] in aliases or previous_ids[alias] not in current_ids)]
            canonical_id = next((candidate for candidate in candidates if candidate not in used_ids), group[0]["id"])
            if canonical_id in used_ids:
                canonical_id = next(alias for alias in aliases if alias not in used_ids)
            primary = next((record for record in group if record["id"] == canonical_id), group[0])
            record = {**primary, "id": canonical_id}
            inherited = [alias for old in previous if old["id"] == canonical_id
                         for alias in old.get("aliases", []) if alias in aliases or alias not in current_ids]
            record["aliases"] = sorted(set([canonical_id, *aliases, *inherited]))
            source_links = {}
            for member in [primary, *group]:
                source_links.setdefault(member["source"], {"id": member["id"], "name": member["source"], "url": member["link"]})
            record["sources"] = list(source_links.values())
            record["category_group"] = "IT" if any(member["category_group"] == "IT" for member in group) else "ETC"
            combined.append(record)
            used_ids.add(canonical_id)
    return sorted(combined, key=lambda record: (record["deadline"], record["title"], record["id"]))


def refresh_source(key: str, max_pages: int, previous: list[dict], old_status: dict) -> tuple[list[dict], dict]:
    collector = COLLECTORS[key]
    cache_path = CACHE_DIR / f"{key}.json"
    cached = read_json(cache_path, [record for record in previous if record.get("source") == collector.NAME])
    status = {
        "name": collector.NAME,
        "url": collector.URL,
        "last_success_at": old_status.get("last_success_at"),
        "scope": "active" if not collector.KEEP_UNSEEN else "recent",
        "max_pages": None if not collector.KEEP_UNSEEN else max_pages,
    }
    try:
        result = collector.collect(max_pages=max_pages)
        fresh = active_records(result.records)
        if not fresh:
            raise RuntimeError("활성 공모전이 0건으로 반환되어 기존 데이터를 유지합니다.")
        records = {
            record["id"]: record for record in active_records(cached)
            if record["id"] not in result.observed_ids
        } if collector.KEEP_UNSEEN else {}
        # Remove newly observed closed records as well as updating active records.
        records.update({record["id"]: record for record in fresh})
        rows = sorted(records.values(), key=lambda record: record["id"])
        write_json_safely(cache_path, rows)
        status.update(status="success", count=len(rows), fetched_count=len(fresh), pages=result.pages,
                      last_success_at=datetime.now(KST).isoformat(timespec="seconds"))
        print(f"[{collector.NAME}] {len(fresh)}개 수집, {len(rows)}개 보관", flush=True)
        return rows, status
    except Exception as error:
        rows = active_records(cached)
        status.update(status="cached" if rows else "unavailable", count=len(rows), error=str(error))
        print(f"::warning::[{collector.NAME}] 수집 실패, 캐시 {len(rows)}개 사용: {error}", flush=True)
        return rows, status


def run(max_pages: int = 5, selected_sources: list[str] | None = None) -> dict:
    previous = read_json(OUTPUT_PATH, [])
    old_metadata = read_json(METADATA_PATH, {})
    old_sources = old_metadata.get("sources", {})
    chosen = selected_sources or list(COLLECTORS)
    records, statuses = [], {}
    with ThreadPoolExecutor(max_workers=len(chosen)) as executor:
        futures = {
            executor.submit(refresh_source, key, max_pages, previous, old_sources.get(key, {})): key
            for key in chosen
        }
        for future in as_completed(futures):
            rows, status = future.result()
            key = futures[future]
            records.extend(rows)
            statuses[key] = status

    # A targeted refresh must not discard the other sources.
    for key, collector in COLLECTORS.items():
        if key not in chosen:
            cached = read_json(CACHE_DIR / f"{key}.json", [record for record in previous if record.get("source") == collector.NAME])
            rows = active_records(cached)
            records.extend(rows)
            statuses[key] = {**old_sources.get(key, {}), "name": collector.NAME, "url": collector.URL,
                             "status": "not_refreshed", "count": len(rows)}

    if not any(statuses[key]["status"] == "success" for key in chosen):
        raise RuntimeError("모든 수집 요청이 실패해 기존 통합 데이터 파일을 유지합니다.")
    contests = merge_contests(records, previous)
    if not contests:
        raise RuntimeError("통합 결과가 비어 있어 기존 데이터를 유지합니다.")
    metadata = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "count": len(contests),
        "raw_count": len(records),
        "duplicate_count": len(records) - len(contests),
        "sources": {key: statuses[key] for key in COLLECTORS},
    }
    write_json_safely(OUTPUT_PATH, contests)
    write_json_safely(METADATA_PATH, metadata)
    print(f"완료! {len(records)}개 원본 → {len(contests)}개 공모전 (중복 {metadata['duplicate_count']}개 통합)", flush=True)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="공모전 사이트 통합 수집")
    parser.add_argument("--max-pages", type=int, default=5, help="추가 사이트의 목록별 수집 페이지 수 (기본 5)")
    parser.add_argument("--sources", nargs="+", choices=list(COLLECTORS), help="특정 사이트만 갱신")
    parser.add_argument("--data-dir", type=Path, help="수집 결과를 저장할 디렉터리")
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 100:
        parser.error("--max-pages는 1~100 사이여야 합니다.")
    if args.data_dir:
        global OUTPUT_PATH, METADATA_PATH, CACHE_DIR
        OUTPUT_PATH = args.data_dir / "contests.json"
        METADATA_PATH = args.data_dir / "collection-status.json"
        CACHE_DIR = args.data_dir / "sources"
    run(args.max_pages, args.sources)


if __name__ == "__main__":
    main()
