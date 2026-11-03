from datetime import datetime, timedelta, timezone
import re
import unicodedata

KST = timezone(timedelta(hours=9))
PROGRESS = ("saved", "researching", "preparing", "submitted")
CHECKLIST = {"eligibility", "guideline", "document", "submission", "final"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def today_kst():
    return datetime.now(KST).date().isoformat()


def identity(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\[(]\s*(?:접수\s*)?기간\s*연장\s*[\])]", "", text)
    return re.sub(r"[^\w가-힣]", "", text)


def status_for(start_date, deadline, today=None):
    today = today or today_kst()
    if deadline < today:
        return "closed"
    if start_date and start_date > today:
        return "upcoming"
    return "open"


def contest_payload(contest):
    return {**contest.data, "id": contest.id, "status_code": status_for(contest.start_date, contest.deadline),
            "last_seen_at": contest.last_seen_at}
