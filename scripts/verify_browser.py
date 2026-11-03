"""Browser smoke checks against an isolated database and a temporary Chrome profile.

Requires requirements-dev.txt and an installed Chrome/Chromium (or CHROME_BIN).
Produces screenshots/report in runtime/browser-qa; never uses personal browser data.
"""
import base64
from datetime import date, datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import make_engine, session_factory
from backend.domain import today_kst, utc_now
from backend.migrations import upgrade_schema
from backend.models import User
from backend.security import PASSWORDS


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Browser:
    def __init__(self, target):
        self.socket = websocket.create_connection(target, timeout=20, suppress_origin=True)
        self.command_id = 0
        self.exceptions = []

    def command(self, method, **params):
        self.command_id += 1
        self.socket.send(json.dumps({"id": self.command_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("method") == "Runtime.exceptionThrown":
                self.exceptions.append(message["params"]["exceptionDetails"].get("text", "JavaScript error"))
            if message.get("id") == self.command_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def evaluate(self, expression):
        result = self.command("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if result.get("exceptionDetails"):
            raise AssertionError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait(self, expression, label):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.evaluate(f"Boolean({expression})"):
                return
            time.sleep(0.05)
        raise AssertionError("Browser timeout: " + label)

    def screenshot(self, filename):
        image = self.command("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        filename.write_bytes(base64.b64decode(image["data"]))


def wait_http(client, url):
    for _ in range(100):
        try:
            result = client.get(url)
            if result.status_code == 200:
                return result.json()
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Service failed to start: " + url)


def login_form(browser, username, password):
    browser.evaluate("document.getElementById('accountButton').click()")
    browser.wait("document.getElementById('accountDialog').open", "login dialog")
    browser.evaluate(f"document.getElementById('username').value={json.dumps(username)};document.getElementById('password').value={json.dumps(password)};document.getElementById('accountForm').requestSubmit()")
    browser.wait("!document.getElementById('logoutButton').hidden", "login completed")


def prepare_snapshot(destination):
    """Keep fixture statuses stable as the checked-in snapshot ages; never edit data/."""
    shutil.copytree(ROOT / "data", destination)
    metadata = json.loads((destination / "collection-status.json").read_text(encoding="utf-8"))
    reference = datetime.fromisoformat(metadata["updated_at"]).date()
    shift = date.fromisoformat(today_kst()) - reference
    if shift.days:
        for path in destination.rglob("*.json"):
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                continue
            for record in records:
                for key in ("start_date", "deadline"):
                    if record.get(key):
                        record[key] = (date.fromisoformat(record[key]) + shift).isoformat()
            path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return shift.days


def main():
    chrome = os.getenv("CHROME_BIN") or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome and Path("C:/Program Files/Google/Chrome/Application/chrome.exe").is_file():
        chrome = "C:/Program Files/Google/Chrome/Application/chrome.exe"
    if not chrome:
        raise SystemExit("Chrome/Chromium이 필요합니다. CHROME_BIN으로 실행 파일을 지정할 수 있습니다.")
    evidence = ROOT / "runtime" / "browser-qa"
    evidence.mkdir(parents=True, exist_ok=True)
    checks = []
    server = chrome_process = browser = None
    with tempfile.TemporaryDirectory(prefix="contestly-browser-") as temporary:
        temporary = Path(temporary)
        snapshot = temporary / "catalogue"
        fixture_shift = prepare_snapshot(snapshot)
        database_url = "sqlite:///" + (temporary / "application.db").as_posix()
        password = secrets.token_urlsafe(24)
        engine = make_engine(database_url)
        upgrade_schema(engine)
        with session_factory(engine)() as db:
            db.add(User(username="qa-operator", display_name="검증 운영자", password_hash=PASSWORDS.hash(password),
                        role="admin", created_at=utc_now()))
            db.commit()
        engine.dispose()
        port, debug_port = free_port(), free_port()
        origin = f"http://127.0.0.1:{port}"
        environment = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "development", "AUTO_INIT_DB": "true",
                       "SEED_SNAPSHOT": "true", "CONTEST_DATA_DIR": str(snapshot), "PUBLIC_ORIGIN": origin,
                       "SECURE_COOKIES": "false", "PYTHONIOENCODING": "utf-8"}
        try:
            with (evidence / "server.log").open("w", encoding="utf-8") as log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
                                          cwd=ROOT, env=environment, stdout=log, stderr=log)
            with httpx.Client(trust_env=False, timeout=10) as client:
                wait_http(client, origin + "/api/health")
                expected = client.get(origin + "/api/contests").json()
                chrome_process = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--disable-dev-shm-usage", f"--remote-debugging-port={debug_port}",
                    f"--user-data-dir={temporary / 'chrome'}", "about:blank"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                debug_origin = f"http://127.0.0.1:{debug_port}"
                wait_http(client, debug_origin + "/json/version")
                target = client.put(debug_origin + "/json/new?about:blank").json()
                browser = Browser(target["webSocketDebuggerUrl"])
                browser.command("Page.enable")
                browser.command("Runtime.enable")
                browser.command("Emulation.setDeviceMetricsOverride", width=1440, height=1000, deviceScaleFactor=1, mobile=False)
                browser.command("Page.navigate", url=origin)
                browser.wait(f"document.getElementById('resultCount')?.textContent==={json.dumps(format(expected['total'], ','))}", "initial catalogue")
                assert browser.evaluate("document.querySelectorAll('.card:not(.skeleton-card)').length") == min(24, expected["total"])
                checks.append("database-backed catalogue renders 24 cards")

                browser.evaluate("document.querySelector('[data-action=bookmark]').click()")
                browser.wait("document.getElementById('savedCount').textContent==='1'", "guest bookmark")
                browser.evaluate("document.getElementById('accountButton').click();document.getElementById('accountSwitch').click();")
                browser.evaluate(f"document.getElementById('username').value='qa-member';document.getElementById('displayName').value='검증 사용자';document.getElementById('password').value={json.dumps(password)};document.getElementById('accountForm').requestSubmit()")
                browser.wait("!document.getElementById('logoutButton').hidden && document.getElementById('savedCount').textContent==='0'", "separate account storage")
                checks.append("registration separates guest storage from account storage")
                browser.evaluate("document.getElementById('importGuest').click()")
                browser.wait("document.getElementById('savedCount').textContent==='1' && !document.getElementById('importGuest').disabled", "explicit guest import")
                browser.evaluate("document.querySelector('.board-card [data-action=tracker]').click()")
                browser.wait("document.getElementById('trackerDialog').open", "tracker dialog")
                browser.evaluate("document.getElementById('trackerProgress').value='preparing';document.getElementById('trackerNote').value='기기 간 동기화 검증 메모';document.querySelector('.checklist-field input').checked=true;document.getElementById('trackerForm').requestSubmit()")
                browser.wait("!document.getElementById('trackerDialog').open", "tracker saved")
                stored = browser.evaluate("fetch('/api/tracker').then(r=>r.json()).then(r=>r.entries[0])")
                assert stored["note"] == "기기 간 동기화 검증 메모" and stored["progress"] == "preparing"
                checks.append("account tracker persists progress, notes and checklist")
                browser.evaluate("document.querySelector('.filter-panel').scrollIntoView({behavior:'instant'})")
                browser.screenshot(evidence / "catalogue-desktop.png")
                browser.command("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
                browser.evaluate("new Promise(r=>setTimeout(r,80))")
                assert browser.evaluate("document.documentElement.scrollWidth===document.documentElement.clientWidth"), "mobile horizontal overflow"
                browser.screenshot(evidence / "catalogue-mobile.png")
                checks.append("mobile layout has no horizontal overflow")
                browser.command("Emulation.setDeviceMetricsOverride", width=1440, height=1000, deviceScaleFactor=1, mobile=False)

                browser.evaluate("document.getElementById('logoutButton').click()")
                browser.wait("!document.getElementById('accountButton').hidden", "logout")
                browser.evaluate("document.getElementById('accountSwitch').click()")
                login_form(browser, "qa-member", password)
                browser.wait("document.querySelector('.board-card p')?.textContent.includes('메모 있음')", "login restores saved note")
                checks.append("logout and login restore account records")
                browser.evaluate("document.querySelector('[data-page=next]').click()")
                browser.wait("document.querySelector('[aria-current=page]')?.textContent==='2'", "server pagination")
                browser.evaluate("document.getElementById('statusFilter').value='upcoming';document.getElementById('statusFilter').dispatchEvent(new Event('change',{bubbles:true}))")
                browser.wait("document.querySelector('.status-badge')?.textContent==='접수 예정'", "upcoming status")
                assert browser.evaluate("[...document.querySelectorAll('.status-badge')].every(e=>e.textContent==='접수 예정')")
                checks.append("pagination and upcoming status filter use server results")
                browser.evaluate("document.querySelector('[data-action=history]').click()")
                browser.wait("document.getElementById('historyDialog').open && document.querySelector('.history-item')", "public history")
                browser.evaluate("document.getElementById('closeHistory').click()")
                checks.append("public contest history opens")

                browser.evaluate("document.getElementById('logoutButton').click()")
                browser.wait("!document.getElementById('accountButton').hidden", "member logout")
                login_form(browser, "qa-operator", password)
                browser.evaluate("document.getElementById('adminLink').click()")
                browser.wait("document.querySelectorAll('.admin-metrics article').length===4", "admin dashboard")
                conflict_count = browser.evaluate("document.querySelectorAll('[data-conflict]').length")
                if conflict_count:
                    browser.evaluate("document.querySelector('[data-conflict] input[name=note]').value='원문 비교를 통한 검토 완료';document.querySelector('[data-conflict]').requestSubmit()")
                    browser.wait("document.getElementById('auditList').textContent.includes('conflict.review')", "conflict audit")
                browser.screenshot(evidence / "admin-desktop.png")
                checks.append("authorized admin dashboard and conflict audit work")
                assert browser.evaluate("fetch('/api/admin/overview',{credentials:'omit'}).then(r=>r.status)") == 401
                checks.append("admin API rejects unauthenticated requests")
                assert not browser.exceptions, browser.exceptions
                report = {"verified_at": utc_now(), "checks": checks, "passed": len(checks),
                          "catalogue_count": expected["total"], "fixture_date_shift_days": fixture_shift,
                          "javascript_exceptions": browser.exceptions}
                (evidence / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if browser:
                browser.socket.close()
            if chrome_process and chrome_process.poll() is None:
                try:
                    with httpx.Client(trust_env=False, timeout=2) as client:
                        version = client.get(f"http://127.0.0.1:{debug_port}/json/version").json()
                        control = websocket.create_connection(version["webSocketDebuggerUrl"], suppress_origin=True, timeout=2)
                        control.send(json.dumps({"id": 1, "method": "Browser.close"}))
                        control.close()
                    chrome_process.wait(timeout=10)
                except Exception:
                    chrome_process.terminate()
                    chrome_process.wait(timeout=10)
            if server and server.poll() is None:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
