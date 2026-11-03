const adminState = { csrf: "", user: null, refreshing: false };
const html = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const when = (value) => value ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "—";
const runLabels = { running: "실행 중", completed: "완료", failed: "실패", success: "정상", cached: "이전 데이터 사용", unavailable: "수집 불가", not_refreshed: "이번 실행 제외" };
let notificationTimer;
function notify(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message; toast.classList.add("show"); clearTimeout(notificationTimer);
  notificationTimer = setTimeout(() => toast.classList.remove("show"), 3500);
}
async function request(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options, headers: {
    "Content-Type": "application/json", "X-CSRF-Token": adminState.csrf, ...options.headers,
  }, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "입력값을 확인해 주세요.");
  return result;
}
function sourceLink(source) {
  try { if (!["https:", "http:"].includes(new URL(source.url).protocol)) return ""; } catch { return ""; }
  return `<a href="${html(source.url)}" target="_blank" rel="noopener noreferrer">${html(source.name)} ↗</a>`;
}
async function refreshAdmin() {
  if (adminState.refreshing) return;
  adminState.refreshing = true;
  try {
    const session = await request("/api/auth/me");
    if (session.user.role !== "admin") throw new Error("관리자 계정으로 로그인해 주세요.");
    adminState.csrf = session.csrf_token; adminState.user = session.user;
    const [overview, conflicts, users, audit] = await Promise.all([
      request("/api/admin/overview"), request("/api/admin/conflicts"), request("/api/admin/users"), request("/api/admin/audit"),
    ]);
    document.getElementById("adminContent").hidden = false;
    document.getElementById("adminError").textContent = "";
    document.getElementById("adminMetrics").innerHTML = [["보관 중인 공모전", overview.contests], ["접수 종료", overview.archived], ["사용자", overview.users], ["확인할 충돌", overview.open_conflicts]].map(([label, value]) => `<article><span>${label}</span><strong>${value.toLocaleString("ko-KR")}</strong></article>`).join("");
    const completed = overview.runs.find((run) => run.status === "completed");
    document.getElementById("adminSources").innerHTML = Object.values(completed?.summary.sources || {}).map((source) => `<article><strong>${html(source.name)}</strong><span class="operation-status">${html(runLabels[source.status] || source.status)}</span><p>${html(source.count)}개 · 마지막 성공 ${when(source.last_success_at)}</p>${source.error ? `<p class="form-error">${html(source.error)}</p>` : ""}</article>`).join("") || "아직 수집 기록이 없습니다.";
    document.getElementById("runList").innerHTML = overview.runs.map((run) => `<tr><td>${when(run.started_at)}</td><td>${html(run.trigger)}</td><td>${html(runLabels[run.status] || run.status)}</td><td>${run.error ? html(run.error) : `${run.summary.created || 0}개 추가 / ${run.summary.updated || 0}개 변경`}</td></tr>`).join("");
    document.getElementById("collectButton").disabled = overview.runs.some((run) => run.status === "running");
    document.getElementById("conflictList").innerHTML = conflicts.items.map((item) => `<article class="conflict-card"><h3>${html(item.details.title)}</h3><p>${html(item.details.left_deadline)} · ${item.details.left_sources.map(sourceLink).join(" ")}</p><p>${html(item.details.right_deadline)} · ${item.details.right_sources.map(sourceLink).join(" ")}</p><p>검토 상태: ${html({ open: "확인 필요", resolved: "확인 완료", ignored: "별도 공고로 판단" }[item.status])}</p>${item.note ? `<p>검토 기록: ${html(item.note)}</p>` : ""}<form data-conflict="${item.id}"><select name="status" aria-label="검토 결과"><option value="resolved">확인 완료</option><option value="ignored">별도 공고로 판단</option></select><input name="note" placeholder="원문 확인 결과와 판단 근거 (5자 이상)" minlength="5" maxlength="1000" required><button class="secondary-button" type="submit">검토 저장</button></form></article>`).join("") || '<p class="panel-description">검토할 정보 충돌이 없습니다.</p>';
    document.getElementById("userList").innerHTML = users.items.map((user) => `<tr><td>${html(user.username)}</td><td>${html(user.display_name)}</td><td>${html(user.role)}</td><td>${user.id === session.user.id ? "현재 계정" : `<button class="secondary-button" type="button" data-user="${user.id}" data-role="${user.role === "admin" ? "user" : "admin"}">${user.role === "admin" ? "일반 사용자로" : "관리자로"}</button>`}</td></tr>`).join("");
    document.getElementById("auditList").innerHTML = audit.items.map((item) => `<tr><td>${when(item.created_at)}</td><td>${html(item.actor_id)}</td><td>${html(item.action)}</td><td>${html(item.target)}<br>${html(JSON.stringify(item.details))}</td></tr>`).join("") || '<tr><td colspan="4">아직 관리 작업 기록이 없습니다.</td></tr>';
  } catch (error) {
    document.getElementById("adminError").textContent = `${error.message} 공모전 목록의 로그인 버튼에서 계정을 확인하세요.`;
    document.getElementById("adminContent").hidden = true;
  } finally { adminState.refreshing = false; }
}
document.getElementById("refreshAdmin").addEventListener("click", refreshAdmin);
document.getElementById("collectForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const sources = [...event.currentTarget.querySelectorAll('input[name="source"]:checked')].map((input) => input.value);
  if (!sources.length) return notify("수집할 사이트를 하나 이상 선택하세요.");
  document.getElementById("collectButton").disabled = true;
  try {
    await request("/api/admin/collect", { method: "POST", body: { sources, max_pages: Number(document.getElementById("maxPages").value) } });
    notify("수집 작업을 시작했습니다. 실행 결과가 자동으로 갱신됩니다.");
    await refreshAdmin();
  } catch (error) { notify(error.message); document.getElementById("collectButton").disabled = false; }
});
document.getElementById("conflictList").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target.closest("[data-conflict]");
  if (!form) return;
  try {
    await request(`/api/admin/conflicts/${form.dataset.conflict}`, { method: "PATCH", body: {
      status: form.elements.status.value, note: form.elements.note.value.trim(),
    } });
    notify("검토 결과를 저장했습니다."); await refreshAdmin();
  } catch (error) { notify(error.message); }
});
document.getElementById("userList").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-user]"); if (!button) return;
  try {
    await request(`/api/admin/users/${button.dataset.user}/role`, { method: "PATCH", body: { role: button.dataset.role } });
    notify("권한을 변경했습니다."); await refreshAdmin();
  } catch (error) { notify(error.message); }
});
setInterval(() => { if (!document.hidden && document.getElementById("collectButton").disabled) refreshAdmin(); }, 5000);
refreshAdmin();
