from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="user")
    created_at: Mapped[str] = mapped_column(String(32))
    __table_args__ = (CheckConstraint("role IN ('user', 'admin')", name="valid_user_role"),)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String(32), index=True)


class AuthAttempt(Base):
    __tablename__ = "auth_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[str] = mapped_column(String(32), index=True)


class Contest(Base):
    __tablename__ = "contests"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(String(800), index=True)
    organization: Mapped[str] = mapped_column(Text)
    normalized_organization: Mapped[str] = mapped_column(String(800))
    start_date: Mapped[str] = mapped_column(String(10), default="")
    deadline: Mapped[str] = mapped_column(String(10), index=True)
    category: Mapped[str] = mapped_column(Text)
    category_group: Mapped[str] = mapped_column(String(8))
    eligibility: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON)
    first_seen_at: Mapped[str] = mapped_column(String(32))
    last_seen_at: Mapped[str] = mapped_column(String(32))
    __table_args__ = (Index("ix_contest_title_host", "normalized_title", "normalized_organization"),)


class ContestAlias(Base):
    __tablename__ = "contest_aliases"
    alias: Mapped[str] = mapped_column(String(160), primary_key=True)
    contest_id: Mapped[str] = mapped_column(ForeignKey("contests.id"), index=True)


class SourceRecord(Base):
    __tablename__ = "source_records"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    contest_id: Mapped[str] = mapped_column(ForeignKey("contests.id"), index=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    last_seen_at: Mapped[str] = mapped_column(String(32))


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    trigger: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), index=True)
    requested_sources: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[str] = mapped_column(String(32))
    finished_at: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class ContestChange(Base):
    __tablename__ = "contest_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[str] = mapped_column(ForeignKey("contests.id"), index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(24))
    changes: Mapped[dict] = mapped_column(JSON)
    detected_at: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id"))


class TrackerEntry(Base):
    __tablename__ = "tracker_entries"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    contest_id: Mapped[str] = mapped_column(ForeignKey("contests.id"), primary_key=True)
    progress: Mapped[str] = mapped_column(String(20), default="saved")
    note: Mapped[str] = mapped_column(Text, default="")
    checklist: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    saved_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    __table_args__ = (CheckConstraint("progress IN ('saved','researching','preparing','submitted')", name="valid_progress"),)


class DataConflict(Base):
    __tablename__ = "data_conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    left_id: Mapped[str] = mapped_column(ForeignKey("contests.id"))
    right_id: Mapped[str] = mapped_column(ForeignKey("contests.id"))
    details: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="open")
    note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    detected_at: Mapped[str] = mapped_column(String(32))
    reviewed_at: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint("left_id", "right_id", name="uq_conflict_pair"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(200))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(32))


class OperationLock(Base):
    __tablename__ = "operation_locks"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[str] = mapped_column(String(32))
