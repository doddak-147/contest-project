from contextlib import asynccontextmanager
from datetime import date, timedelta
import logging
import math
import secrets
import time
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from .config import ROOT, Settings
from .database import make_engine, session_factory
from .domain import PROGRESS, contest_payload, today_kst, utc_now
from .ingestion import import_directory
from .models import (AuditLog, Base, CollectionRun, Contest, ContestAlias, ContestChange,
                     DataConflict, LoginSession, SourceRecord, TrackerEntry, User)
from .schemas import (CollectRequest, Credentials, ImportEntries, Lookup, Register,
                      ReviewConflict, RoleChange, TrackerWrite)
from .security import (CSRF_COOKIE, DUMMY_HASH, PASSWORDS, SESSION_COOKIE, check_origin, digest,
                       get_user, issue_session, require_admin, require_csrf, throttle_auth, user_payload)

logger = logging.getLogger("uvicorn.error.contestly")


def get_db(request: Request):
    with request.app.state.db_factory() as db:
        yield db


def find_contest(db, contest_id):
    contest = db.get(Contest, contest_id)
    if not contest:
        alias = db.get(ContestAlias, contest_id)
        contest = db.get(Contest, alias.contest_id) if alias else None
    if not contest:
        raise HTTPException(404, "공모전을 찾을 수 없습니다.")
    return contest


def tracker_payload(entry, contest):
    return {"contest": contest_payload(contest), "progress": entry.progress, "note": entry.note,
            "checklist": entry.checklist, "version": entry.version, "savedAt": entry.saved_at,
            "updatedAt": entry.updated_at}


def create_app(settings=None):
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)

    @asynccontextmanager
    async def lifespan(app):
        if settings.auto_init:
            from .migrations import upgrade_schema
            upgrade_schema(engine)
        if settings.seed_snapshot and (settings.data_dir / "contests.json").exists():
            import_directory(factory, settings.data_dir)
        yield
        engine.dispose()

    app = FastAPI(title="Contestly API", version="1.0.0", lifespan=lifespan,
                  description="공모전 통합 검색·지원 기록·운영 관리 API")
    app.state.settings, app.state.engine, app.state.db_factory = settings, engine, factory

    @app.middleware("http")
    async def request_metadata(request, call_next):
        started, request_id = time.perf_counter(), secrets.token_hex(8)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(("/api/auth", "/api/tracker", "/api/admin")):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path in ("/", "/index.html", "/admin"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' https://cdn.jsdelivr.net; "
                "font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; connect-src 'self'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
        logger.info("request_id=%s method=%s path=%s status=%s duration_ms=%.1f", request_id, request.method,
                    request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
        return response

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        return JSONResponse(status_code=409, content={"detail": "다른 요청으로 데이터가 변경되었습니다. 다시 확인해 주세요."})

    @app.get("/api/health", tags=["operations"])
    def health(db=Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "데이터베이스 연결을 확인해 주세요.")
        return {"status": "ok", "database": "ok", "version": "1.0.0"}

    @app.get("/api/contests", tags=["contests"])
    def list_contests(request: Request, q: str = Query("", max_length=100), source: str = Query("all", max_length=40),
                      category: str = Query("all", max_length=300), eligibility: Literal["all", "student", "youth", "adult", "anyone"] = "all",
                      status: Literal["active", "open", "upcoming", "closed", "all"] = "active",
                      mode: Literal["all", "it", "urgent", "saved"] = "all",
                      days: int | None = Query(None, ge=0, le=3650),
                      sort: Literal["deadline", "latest", "title"] = "deadline", page: int = Query(1, ge=1, le=100000),
                      page_size: int = Query(24, ge=1, le=100), db=Depends(get_db)):
        today = today_kst()
        open_condition = and_(Contest.deadline >= today, or_(Contest.start_date == "", Contest.start_date <= today))
        stmt = select(Contest)
        if status == "active":
            stmt = stmt.where(Contest.deadline >= today)
        elif status == "open":
            stmt = stmt.where(open_condition)
        elif status == "upcoming":
            stmt = stmt.where(Contest.deadline >= today, Contest.start_date > today)
        elif status == "closed":
            stmt = stmt.where(Contest.deadline < today)
        if q.strip():
            pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(or_(*(column.ilike(pattern, escape="\\") for column in
                                   (Contest.title, Contest.organization, Contest.category, Contest.eligibility))))
        if source != "all":
            stmt = stmt.where(Contest.id.in_(select(SourceRecord.contest_id).where(SourceRecord.source == source)))
        if category != "all":
            stmt = stmt.where(Contest.category == category)
        targets = {"student": ("대학생", "대학원생"), "youth": ("청소년", "초등학생", "중학생", "고등학생"),
                   "adult": ("일반인",), "anyone": ("누구나", "제한없음", "제한 없음", "전국민")}
        if eligibility != "all":
            stmt = stmt.where(or_(*(Contest.eligibility.contains(word) for word in targets[eligibility])))
        if days is not None:
            stmt = stmt.where(Contest.deadline >= today, Contest.deadline <= (date.fromisoformat(today) + timedelta(days=days)).isoformat())
        if mode == "it":
            stmt = stmt.where(Contest.category_group == "IT")
        elif mode == "urgent":
            stmt = stmt.where(open_condition, Contest.deadline <= (date.fromisoformat(today) + timedelta(days=7)).isoformat())
        elif mode == "saved":
            user = get_user(request, db)
            stmt = stmt.where(Contest.id.in_(select(TrackerEntry.contest_id).where(TrackerEntry.user_id == user.id)))
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        pages = max(1, math.ceil(total / page_size))
        page = min(page, pages)
        order = Contest.title if sort == "title" else Contest.deadline.desc() if sort == "latest" else Contest.deadline
        rows = db.scalars(stmt.order_by(order, Contest.id).offset((page - 1) * page_size).limit(page_size)).all()
        stats = {
            "open": db.scalar(select(func.count()).select_from(Contest).where(open_condition)),
            "it": db.scalar(select(func.count()).select_from(Contest).where(open_condition, Contest.category_group == "IT")),
            "urgent": db.scalar(select(func.count()).select_from(Contest).where(open_condition, Contest.deadline <= (date.fromisoformat(today) + timedelta(days=7)).isoformat())),
            "upcoming": db.scalar(select(func.count()).select_from(Contest).where(Contest.deadline >= today, Contest.start_date > today)),
        }
        return {"items": [contest_payload(row) for row in rows], "total": total, "page": page,
                "page_size": page_size, "pages": pages, "stats": stats}

    @app.get("/api/facets", tags=["contests"])
    def facets(db=Depends(get_db)):
        return {"categories": list(db.scalars(select(Contest.category).distinct().order_by(Contest.category))),
                "sources": list(db.scalars(select(SourceRecord.source).distinct().order_by(SourceRecord.source)))}

    @app.post("/api/contests/lookup", tags=["contests"])
    def lookup(body: Lookup, db=Depends(get_db)):
        ids = set(body.ids)
        ids.update(db.scalars(select(ContestAlias.contest_id).where(ContestAlias.alias.in_(body.ids))))
        return {"items": [contest_payload(contest) for contest in db.scalars(select(Contest).where(Contest.id.in_(ids)))]}

    @app.get("/api/contests/{contest_id}", tags=["contests"])
    def contest_detail(contest_id: str, db=Depends(get_db)):
        return contest_payload(find_contest(db, contest_id))

    @app.get("/api/contests/{contest_id}/history", tags=["contests"])
    def contest_history(contest_id: str, db=Depends(get_db)):
        contest = find_contest(db, contest_id)
        changes = db.scalars(select(ContestChange).where(ContestChange.contest_id == contest.id).order_by(ContestChange.id.desc()).limit(100))
        return {"title": contest.title, "items": [{"kind": row.kind, "changes": row.changes,
                "source_record_id": row.source_record_id, "detected_at": row.detected_at} for row in changes]}

    @app.get("/api/collection-status", tags=["operations"])
    def collection_status(db=Depends(get_db)):
        run = db.scalar(select(CollectionRun).where(CollectionRun.status == "completed").order_by(CollectionRun.finished_at.desc()))
        sources = run.summary.get("sources", {}) if run else {}
        updated_at = (run.summary.get("snapshot_updated_at") or run.finished_at) if run else None
        return {"updated_at": updated_at, "sources": {
            key: {field: value for field, value in source.items() if field in ("name", "count", "status", "last_success_at", "scope")}
            for key, source in sources.items()}}

    @app.post("/api/auth/register", status_code=201, tags=["auth"])
    def register(body: Register, request: Request, response: Response, db=Depends(get_db)):
        check_origin(request)
        throttle_auth(request, db)
        username = body.username.lower()
        if db.scalar(select(User.id).where(User.username == username)):
            raise HTTPException(409, "이미 사용 중인 아이디입니다.")
        user = User(username=username, display_name=body.display_name.strip() or username,
                    password_hash=PASSWORDS.hash(body.password), role="user", created_at=utc_now())
        db.add(user)
        db.commit()
        return issue_session(request, response, db, user)

    @app.post("/api/auth/login", tags=["auth"])
    def login(body: Credentials, request: Request, response: Response, db=Depends(get_db)):
        check_origin(request)
        throttle_auth(request, db)
        user = db.scalar(select(User).where(User.username == body.username.lower()))
        valid = PASSWORDS.verify(body.password, user.password_hash if user else DUMMY_HASH)
        if not user or not valid:
            raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")
        return issue_session(request, response, db, user)

    @app.get("/api/auth/me", tags=["auth"])
    def me(request: Request, db=Depends(get_db)):
        user = get_user(request, db)
        return {"user": user_payload(user), "csrf_token": request.cookies.get(CSRF_COOKIE, "")}

    @app.post("/api/auth/logout", tags=["auth"])
    def logout(request: Request, response: Response, db=Depends(get_db)):
        require_csrf(request, db)
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(request.cookies[SESSION_COOKIE])))
        db.commit()
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/tracker", tags=["tracker"])
    def tracker(request: Request, db=Depends(get_db)):
        user = get_user(request, db)
        rows = db.execute(select(TrackerEntry, Contest).join(Contest).where(TrackerEntry.user_id == user.id).order_by(TrackerEntry.saved_at.desc()))
        return {"entries": [tracker_payload(entry, contest) for entry, contest in rows]}

    @app.put("/api/tracker/{contest_id}", tags=["tracker"])
    def save_entry(contest_id: str, body: TrackerWrite, request: Request, db=Depends(get_db)):
        user = require_csrf(request, db)
        contest = find_contest(db, contest_id)
        entry = db.get(TrackerEntry, (user.id, contest.id))
        now = utc_now()
        values = {"progress": body.progress, "note": body.note, "checklist": body.checklist, "updated_at": now}
        if entry:
            if body.version is None:
                raise HTTPException(409, "다른 기기의 변경사항을 불러온 후 다시 저장해 주세요.")
            changed = db.execute(update(TrackerEntry).where(TrackerEntry.user_id == user.id,
                TrackerEntry.contest_id == contest.id, TrackerEntry.version == body.version).values(**values, version=body.version + 1))
            if not changed.rowcount:
                raise HTTPException(409, "다른 기기에서 기록이 변경되었습니다. 최신 기록을 확인해 주세요.")
        else:
            if body.version is not None:
                raise HTTPException(409, "기록이 삭제되었습니다. 최신 상태를 확인해 주세요.")
            db.add(TrackerEntry(user_id=user.id, contest_id=contest.id, **values, version=1, saved_at=now))
        db.commit()
        db.expire_all()
        return tracker_payload(db.get(TrackerEntry, (user.id, contest.id)), contest)

    @app.delete("/api/tracker/{contest_id}", tags=["tracker"])
    def delete_entry(contest_id: str, request: Request, version: int = Query(ge=1), db=Depends(get_db)):
        user = require_csrf(request, db)
        contest = find_contest(db, contest_id)
        deleted = db.execute(delete(TrackerEntry).where(TrackerEntry.user_id == user.id,
                            TrackerEntry.contest_id == contest.id, TrackerEntry.version == version))
        if not deleted.rowcount:
            raise HTTPException(409, "기록이 변경되었거나 이미 삭제되었습니다.")
        db.commit()
        return {"ok": True}

    @app.post("/api/tracker/import", tags=["tracker"])
    def import_entries(body: ImportEntries, request: Request, db=Depends(get_db)):
        user = require_csrf(request, db)
        imported, skipped = 0, 0
        for item in body.entries:
            try:
                contest = find_contest(db, item.contest_id)
            except HTTPException:
                skipped += 1
                continue
            entry = db.get(TrackerEntry, (user.id, contest.id))
            now = utc_now()
            if entry:
                notes = list(dict.fromkeys(filter(None, [*entry.note.split("\n\n"), *item.note.split("\n\n")])))
                values = {"note": "\n\n".join(notes)[:5000], "checklist": sorted(set(entry.checklist) | set(item.checklist)),
                          "progress": PROGRESS[max(PROGRESS.index(entry.progress), PROGRESS.index(item.progress))]}
                if any(getattr(entry, key) != value for key, value in values.items()):
                    previous_version = entry.version
                    changed = db.execute(update(TrackerEntry).where(TrackerEntry.user_id == user.id,
                        TrackerEntry.contest_id == contest.id, TrackerEntry.version == previous_version)
                        .values(**values, version=previous_version + 1, updated_at=now))
                    if not changed.rowcount:
                        raise HTTPException(409, "다른 기기에서 기록이 변경되었습니다. 가져오기를 다시 시도하세요.")
            else:
                db.add(TrackerEntry(user_id=user.id, contest_id=contest.id, progress=item.progress, note=item.note,
                                    checklist=item.checklist, version=1, saved_at=now, updated_at=now))
            db.flush()
            imported += 1
        db.commit()
        return {"imported": imported, "skipped": skipped}

    @app.get("/api/admin/overview", tags=["admin"])
    def admin_overview(request: Request, db=Depends(get_db)):
        require_admin(request, db)
        runs = list(db.scalars(select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(30)))
        return {"contests": db.scalar(select(func.count()).select_from(Contest)),
                "archived": db.scalar(select(func.count()).select_from(Contest).where(Contest.deadline < today_kst())),
                "users": db.scalar(select(func.count()).select_from(User)),
                "open_conflicts": db.scalar(select(func.count()).select_from(DataConflict).where(DataConflict.status == "open")),
                "runs": [{"id": run.id, "trigger": run.trigger, "status": run.status, "started_at": run.started_at,
                          "finished_at": run.finished_at, "summary": run.summary, "error": run.error} for run in runs]}

    @app.post("/api/admin/collect", status_code=202, tags=["admin"])
    def admin_collect(body: CollectRequest, request: Request, tasks: BackgroundTasks, db=Depends(get_db)):
        user = require_admin(request, db, write=True)
        from .operations import execute_collection, reserve_collection
        run = reserve_collection(factory, body.sources, body.max_pages, trigger="manual")
        if not run:
            raise HTTPException(409, "이미 수집 작업이 실행 중입니다.")
        db.add(AuditLog(actor_id=user.id, action="collection.request", target=run,
                        details=body.model_dump(), created_at=utc_now()))
        db.commit()
        tasks.add_task(execute_collection, factory, settings.data_dir, run, body.sources, body.max_pages)
        return {"run_id": run, "status": "running"}

    @app.get("/api/admin/conflicts", tags=["admin"])
    def conflicts(request: Request, db=Depends(get_db)):
        require_admin(request, db)
        return {"items": [{"id": row.id, "left_id": row.left_id, "right_id": row.right_id, "details": row.details,
                           "status": row.status, "note": row.note, "reviewed_at": row.reviewed_at}
                          for row in db.scalars(select(DataConflict).order_by(DataConflict.id.desc()).limit(200))]}

    @app.patch("/api/admin/conflicts/{conflict_id}", tags=["admin"])
    def review_conflict(conflict_id: int, body: ReviewConflict, request: Request, db=Depends(get_db)):
        user = require_admin(request, db, write=True)
        conflict = db.get(DataConflict, conflict_id)
        if not conflict:
            raise HTTPException(404, "검토 항목을 찾을 수 없습니다.")
        previous = {"status": conflict.status, "note": conflict.note}
        conflict.status, conflict.note, conflict.reviewed_by, conflict.reviewed_at = body.status, body.note, user.id, utc_now()
        db.add(AuditLog(actor_id=user.id, action="conflict.review", target=str(conflict.id),
                        details={"before": previous, "after": body.model_dump()}, created_at=utc_now()))
        db.commit()
        return {"ok": True}

    @app.get("/api/admin/users", tags=["admin"])
    def users(request: Request, db=Depends(get_db)):
        require_admin(request, db)
        return {"items": [user_payload(user) for user in db.scalars(select(User).order_by(User.id).limit(200))]}

    @app.patch("/api/admin/users/{user_id}/role", tags=["admin"])
    def change_role(user_id: int, body: RoleChange, request: Request, db=Depends(get_db)):
        admin = require_admin(request, db, write=True)
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "사용자를 찾을 수 없습니다.")
        if user.id == admin.id:
            raise HTTPException(400, "자신의 관리자 권한은 변경할 수 없습니다.")
        previous, user.role = user.role, body.role
        db.add(AuditLog(actor_id=admin.id, action="user.role", target=str(user.id),
                        details={"before": previous, "after": body.role}, created_at=utc_now()))
        db.commit()
        return user_payload(user)

    @app.get("/api/admin/audit", tags=["admin"])
    def audit(request: Request, db=Depends(get_db)):
        require_admin(request, db)
        return {"items": [{"id": row.id, "actor_id": row.actor_id, "action": row.action, "target": row.target,
                           "details": row.details, "created_at": row.created_at}
                          for row in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100))]}

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "index.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(ROOT / "admin.html")

    @app.get("/{asset}", include_in_schema=False)
    def static_asset(asset: str):
        if asset not in {"app.js", "api.js", "admin.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(ROOT / asset)

    return app


app = create_app()
