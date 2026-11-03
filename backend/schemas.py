from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import CHECKLIST


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)


class Register(Credentials):
    display_name: str = Field(min_length=1, max_length=40)


class TrackerWrite(StrictModel):
    progress: Literal["saved", "researching", "preparing", "submitted"] = "saved"
    note: str = Field(default="", max_length=5000)
    checklist: list[str] = Field(default_factory=list, max_length=5)
    version: int | None = Field(default=None, ge=1)

    @field_validator("checklist")
    @classmethod
    def valid_checklist(cls, value):
        if not set(value) <= CHECKLIST or len(value) != len(set(value)):
            raise ValueError("잘못된 체크리스트 항목입니다.")
        return value


class TrackerImport(TrackerWrite):
    contest_id: str = Field(max_length=160)


class ImportEntries(StrictModel):
    entries: list[TrackerImport] = Field(max_length=200)


class Lookup(StrictModel):
    ids: list[str] = Field(max_length=200)


class CollectRequest(StrictModel):
    sources: list[Literal["thinkcontest", "wevity", "contestkorea"]] = Field(default_factory=lambda: ["thinkcontest", "wevity", "contestkorea"], min_length=1, max_length=3)
    max_pages: int = Field(default=5, ge=1, le=20)


class ReviewConflict(StrictModel):
    status: Literal["resolved", "ignored"]
    note: str = Field(min_length=5, max_length=1000)


class RoleChange(StrictModel):
    role: Literal["user", "admin"]
