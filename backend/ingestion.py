from collections import defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from .domain import identity, today_kst, utc_now
from .models import CollectionRun, Contest, ContestAlias, ContestChange, DataConflict, SourceRecord

WATCHED = ("title", "organization", "start_date", "deadline", "category", "category_group",
           "eligibility", "award", "award_detail", "apply_method", "sources")


def read_snapshot(directory: Path):
    with (directory / "contests.json").open(encoding="utf-8") as file:
        contests = json.load(file)
    metadata_path = directory / "collection-status.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    raw = []
    for path in sorted((directory / "sources").glob("*.json")):
        raw.extend(json.loads(path.read_text(encoding="utf-8")))
    return contests, raw, metadata


def differences(before, after):
    return {field: {"before": before.get(field), "after": after.get(field)}
            for field in WATCHED if before.get(field) != after.get(field)}


def validate_snapshot(contests):
    if not isinstance(contests, list) or not contests:
        raise ValueError("통합 공모전 목록이 비어 있습니다.")
    seen = set()
    for item in contests:
        if not isinstance(item, dict) or not all(item.get(key) for key in ("id", "title", "deadline", "link")):
            raise ValueError("필수 공모전 정보가 누락되었습니다.")
        if item["id"] in seen or len(item["id"]) > 160:
            raise ValueError("중복되거나 잘못된 공모전 ID입니다.")
        seen.add(item["id"])
        date.fromisoformat(item["deadline"])
        if item.get("start_date"):
            date.fromisoformat(item["start_date"])


def ingest_snapshot(db, contests, raw=None, metadata=None, run_id=None):
    """One transaction; missing/closed contests remain available to saved trackers."""
    validate_snapshot(contests)
    raw, metadata = raw or [], metadata or {}
    fingerprint = hashlib.sha256(json.dumps(
        {"contests": contests, "raw": raw, "metadata": metadata}, sort_keys=True, ensure_ascii=False
    ).encode()).hexdigest()
    existing = db.scalar(select(CollectionRun).where(CollectionRun.fingerprint == fingerprint))
    if existing:
        if run_id and run_id != existing.id:
            duplicate_run = db.get(CollectionRun, run_id)
            if duplicate_run:
                duplicate_run.status, duplicate_run.finished_at = "completed", utc_now()
                duplicate_run.summary = {**existing.summary, "unchanged": True}
                db.commit()
        return {"run_id": existing.id, "unchanged": True, **existing.summary}
    now = utc_now()
    run = db.get(CollectionRun, run_id) if run_id else None
    if not run:
        run = CollectionRun(id=run_id or str(uuid4()), trigger="snapshot", status="running", started_at=now,
                            requested_sources=[], summary={})
        db.add(run)
        db.flush()
    run.fingerprint = fingerprint
    created, updated = 0, 0
    for data in contests:
        data = dict(data)
        data.setdefault("sources", [{"id": data["id"], "name": data.get("source", "출처"), "url": data["link"]}])
        data.setdefault("aliases", [data["id"]])
        contest = db.get(Contest, data["id"])
        if contest is None:
            contest = Contest(id=data["id"], first_seen_at=now)
            db.add(contest)
            created += 1
            change = {"title": {"before": None, "after": data["title"]}}
            kind = "created"
        else:
            change = differences(contest.data, data)
            kind = "updated"
            updated += bool(change)
        for field in ("title", "organization", "start_date", "deadline", "category", "category_group", "eligibility"):
            setattr(contest, field, data.get(field) or ("ETC" if field == "category_group" else ""))
        contest.normalized_title = identity(data["title"])
        contest.normalized_organization = identity(data.get("organization"))
        contest.data, contest.last_seen_at = data, now
        db.flush()
        if change:
            db.add(ContestChange(contest_id=contest.id, kind=kind, changes=change, detected_at=now, run_id=run.id))
        for alias in {contest.id, *data["aliases"]}:
            mapping = db.get(ContestAlias, alias)
            if mapping:
                mapping.contest_id = contest.id
            else:
                db.add(ContestAlias(alias=alias, contest_id=contest.id))
    db.flush()
    if not raw:
        raw = [{**item, "id": source["id"], "source": source["name"], "link": source["url"]}
               for item in contests for source in item.get("sources", [{"id": item["id"], "name": item.get("source", "출처"), "url": item["link"]}])]
    for data in raw:
        mapping = db.get(ContestAlias, data["id"])
        if not mapping:
            continue
        source = db.get(SourceRecord, data["id"])
        if source:
            change = differences(source.data, data)
            if change:
                db.add(ContestChange(contest_id=mapping.contest_id, source_record_id=source.id,
                                    kind="source_updated", changes=change, detected_at=now, run_id=run.id))
            source.contest_id, source.data, source.last_seen_at = mapping.contest_id, data, now
        else:
            db.add(SourceRecord(id=data["id"], contest_id=mapping.contest_id, source=data.get("source", ""),
                                data=data, last_seen_at=now))
    db.flush()
    conflicts = detect_conflicts(db, now)
    summary = {"count": len(contests), "created": created, "updated": updated, "open_conflicts": conflicts,
               "sources": metadata.get("sources", {}), "snapshot_updated_at": metadata.get("updated_at")}
    run.status, run.finished_at, run.summary = "completed", now, summary
    db.commit()
    return {"run_id": run.id, "unchanged": False, **summary}


def detect_conflicts(db, now):
    groups = defaultdict(list)
    for contest in db.scalars(select(Contest).where(Contest.deadline >= today_kst())):
        if contest.normalized_organization:
            groups[(contest.normalized_title, contest.normalized_organization)].append(contest)
    current = set()
    for group in groups.values():
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                if left.deadline == right.deadline:
                    continue
                first, second = sorted((left, right), key=lambda item: item.id)
                pair = (first.id, second.id)
                current.add(pair)
                details = {"title": first.title, "left_deadline": first.deadline, "right_deadline": second.deadline,
                           "left_sources": first.data.get("sources", []), "right_sources": second.data.get("sources", [])}
                conflict = db.scalar(select(DataConflict).where(DataConflict.left_id == first.id, DataConflict.right_id == second.id))
                if conflict:
                    if conflict.details != details:
                        conflict.status, conflict.note, conflict.reviewed_by, conflict.reviewed_at = "open", "", None, None
                    conflict.details = details
                else:
                    db.add(DataConflict(left_id=first.id, right_id=second.id, details=details, detected_at=now, status="open", note=""))
    for conflict in db.scalars(select(DataConflict).where(DataConflict.status == "open")):
        if (conflict.left_id, conflict.right_id) not in current:
            conflict.status, conflict.note, conflict.reviewed_at = "resolved", "출처 정보가 일치하거나 접수가 종료되어 자동 해소", now
    db.flush()
    return len(list(db.scalars(select(DataConflict.id).where(DataConflict.status == "open"))))


def import_directory(factory, directory):
    contests, raw, metadata = read_snapshot(directory)
    with factory() as db:
        return ingest_snapshot(db, contests, raw, metadata)
