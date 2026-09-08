const STORAGE_KEY = "contestly-tracker-v1";
const DAY_IN_MS = 1000 * 60 * 60 * 24;
const PAGE_SIZE = 24;

const PROGRESS = {
  saved: { label: "관심 있음", shortLabel: "관심" },
  researching: { label: "자료 조사", shortLabel: "조사" },
  preparing: { label: "제작 중", shortLabel: "제작" },
  submitted: { label: "제출 완료", shortLabel: "제출" },
};

const state = {
  contests: [],
  keyword: "",
  mode: "all",
  sort: "deadline",
  category: "all",
  eligibility: "all",
  deadlineRange: "all",
  currentPage: 1,
  tracker: loadTracker(),
  editingId: null,
};

const elements = {
  list: document.getElementById("list"),
  search: document.getElementById("search"),
  sort: document.getElementById("sort"),
  categoryFilter: document.getElementById("categoryFilter"),
  eligibilityFilter: document.getElementById("eligibilityFilter"),
  deadlineFilter: document.getElementById("deadlineFilter"),
  resetFilters: document.getElementById("resetFilters"),
  resultCount: document.getElementById("resultCount"),
  pagination: document.getElementById("pagination"),
  openCount: document.getElementById("openCount"),
  itCount: document.getElementById("itCount"),
  urgentCount: document.getElementById("urgentCount"),
  savedCount: document.getElementById("savedCount"),
  todayLabel: document.getElementById("todayLabel"),
  filterButtons: [...document.querySelectorAll(".filter-button")],
  challengeBoard: document.getElementById("challengeBoard"),
  savedSummary: document.getElementById("savedSummary"),
  trackerDialog: document.getElementById("trackerDialog"),
  trackerForm: document.getElementById("trackerForm"),
  trackerContestTitle: document.getElementById("trackerContestTitle"),
  trackerProgress: document.getElementById("trackerProgress"),
  trackerNote: document.getElementById("trackerNote"),
  toast: document.getElementById("toast"),
};

function loadTracker() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function saveTracker() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.tracker));
}

function getContestId(contest) {
  if (contest.id) return String(contest.id);
  try {
    return `legacy-${new URL(contest.link).searchParams.get("contest_pk") || contest.link}`;
  } catch {
    return `legacy-${contest.title}-${contest.deadline}`;
  }
}

function normalizeContest(contest) {
  const legacyCategory = contest.category === "IT" || contest.category === "ETC";
  return {
    ...contest,
    id: getContestId(contest),
    category: legacyCategory ? (contest.category === "IT" ? "IT · 테크" : "기타") : contest.category || "기타",
    category_group: contest.category_group || (contest.category === "IT" ? "IT" : "ETC"),
    eligibility: contest.eligibility || "공고에서 확인",
    award: contest.award || "공고에서 확인",
    status: contest.status || (getDDay(contest.deadline) < 0 ? "접수 종료" : "접수 중"),
  };
}

function parseDate(dateString) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateString))) return new Date(NaN);
  const [year, month, day] = dateString.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function getDDay(deadline) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((parseDate(deadline) - today) / DAY_IN_MS);
}

function getDeadlineInfo(deadline) {
  const dDay = getDDay(deadline);
  if (!Number.isFinite(dDay)) return { label: "미정", status: "closed", statusText: "일정 확인" };
  if (dDay < 0) return { label: "마감", status: "closed", statusText: "접수 종료" };
  if (dDay === 0) return { label: "D-DAY", status: "urgent", statusText: "오늘 마감" };
  if (dDay <= 7) return { label: `D-${dDay}`, status: "urgent", statusText: "마감 임박" };
  return { label: `D-${dDay}`, status: "open", statusText: "접수 중" };
}

function formatDate(dateString) {
  const date = parseDate(dateString);
  if (Number.isNaN(date.getTime())) return "일정 미정";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeLink(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? escapeHtml(url.href) : "#";
  } catch {
    return "#";
  }
}

function isSaved(id) {
  return Boolean(state.tracker[id]);
}

function createCard(contest) {
  const deadline = getDeadlineInfo(contest.deadline);
  const saved = isSaved(contest.id);
  const categoryClass = contest.category_group === "IT" ? "it" : "etc";
  const progress = state.tracker[contest.id]?.progress || "saved";

  return `
    <article class="card" data-contest-id="${escapeHtml(contest.id)}">
      <div class="card-top">
        <span class="category-badge ${categoryClass}" title="${escapeHtml(contest.category)}">${escapeHtml(contest.category)}</span>
        <div class="card-top-actions">
          <span class="status-badge ${deadline.status}">${deadline.statusText}</span>
          <button class="bookmark-button${saved ? " active" : ""}" type="button" data-action="bookmark" aria-pressed="${saved}" aria-label="${escapeHtml(contest.title)} ${saved ? "찜 해제" : "찜하기"}">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 3.5h10v14l-5-3-5 3v-14Z"/></svg>
          </button>
        </div>
      </div>
      <h3>${escapeHtml(contest.title)}</h3>
      <p class="organization" title="${escapeHtml(contest.organization)}">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 17V6.5L10 3l6.5 3.5V17M7 17v-3h6v3M7 8h.01M10 8h.01M13 8h.01M7 11h.01M10 11h.01M13 11h.01"/></svg>
        ${escapeHtml(contest.organization || "주최 기관 미정")}
      </p>
      <div class="contest-details">
        <span title="${escapeHtml(contest.eligibility)}">대상 · ${escapeHtml(contest.eligibility)}</span>
        <span title="${escapeHtml(contest.award)}">시상 · ${escapeHtml(contest.award)}</span>
      </div>
      ${saved ? `
        <button class="progress-chip" type="button" data-action="tracker">
          ${escapeHtml(PROGRESS[progress]?.label || PROGRESS.saved.label)} · 기록 열기
        </button>` : ""}
      <div class="card-footer">
        <div>
          <span class="deadline-label">Deadline</span>
          <span class="deadline-date"><strong class="${deadline.status}">${deadline.label}</strong>${formatDate(contest.deadline)}</span>
        </div>
        <div class="card-links">
          <button class="calendar-button" type="button" data-action="calendar" aria-label="${escapeHtml(contest.title)} 캘린더에 추가">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 5.5h12v11H4zM4 8.5h12M7 3v4M13 3v4M7 12h6"/></svg>
          </button>
          <a class="card-link" href="${safeLink(contest.link)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(contest.title)} 상세 페이지 열기">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 15 15 5m0 0H8m7 0v7"/></svg>
          </a>
        </div>
      </div>
    </article>
  `;
}

function matchesEligibility(contest, filter) {
  if (filter === "all") return true;
  const value = contest.eligibility.replaceAll(" ", "");
  const matchers = {
    student: ["대학생", "대학원생"],
    youth: ["청소년", "초등학생", "중학생", "고등학생"],
    adult: ["일반인"],
    anyone: ["누구나", "제한없음", "전국민"],
  };
  return matchers[filter].some((keyword) => value.includes(keyword));
}

function getFilteredContests() {
  const normalizedKeyword = state.keyword.trim().toLocaleLowerCase("ko-KR");
  const range = state.deadlineRange === "all" ? Infinity : Number(state.deadlineRange);

  const filtered = state.contests.filter((contest) => {
    const dDay = getDDay(contest.deadline);
    const matchesMode =
      state.mode === "all" ||
      (state.mode === "it" && contest.category_group === "IT") ||
      (state.mode === "urgent" && dDay >= 0 && dDay <= 7) ||
      (state.mode === "saved" && isSaved(contest.id));
    const searchableText = `${contest.title} ${contest.organization} ${contest.category} ${contest.eligibility}`.toLocaleLowerCase("ko-KR");
    const matchesCategory = state.category === "all" || contest.category === state.category;
    const matchesDeadline = range === Infinity || (dDay >= 0 && dDay <= range);

    return matchesMode && matchesCategory && matchesEligibility(contest, state.eligibility) &&
      matchesDeadline && searchableText.includes(normalizedKeyword);
  });

  return filtered.sort((a, b) => {
    if (state.sort === "title") return a.title.localeCompare(b.title, "ko");
    const direction = state.sort === "latest" ? -1 : 1;
    return (parseDate(a.deadline) - parseDate(b.deadline)) * direction;
  });
}

function render() {
  const filtered = getFilteredContests();
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  state.currentPage = Math.min(state.currentPage, totalPages);
  const startIndex = (state.currentPage - 1) * PAGE_SIZE;
  const visible = filtered.slice(startIndex, startIndex + PAGE_SIZE);
  elements.list.setAttribute("aria-busy", "false");
  elements.resultCount.textContent = filtered.length.toLocaleString("ko-KR");

  if (filtered.length === 0) {
    elements.list.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="18" cy="18" r="11"/><path d="m27 27 7 7M13.5 18h9"/></svg>
        <strong>조건에 맞는 공모전이 없어요</strong>
        <p>${state.mode === "saved" ? "마음에 드는 공모전을 먼저 찜해 보세요." : "검색어나 상세 필터를 바꿔보세요."}</p>
      </div>`;
  } else {
    elements.list.innerHTML = visible.map(createCard).join("");
  }

  renderPagination(filtered.length, totalPages);
  renderBoard();
  updateSavedCount();
}

function getPaginationItems(totalPages) {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);

  const pages = new Set([1, totalPages, state.currentPage - 1, state.currentPage, state.currentPage + 1]);
  if (state.currentPage <= 4) [2, 3, 4, 5].forEach((page) => pages.add(page));
  if (state.currentPage >= totalPages - 3) {
    [totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1].forEach((page) => pages.add(page));
  }

  const sorted = [...pages].filter((page) => page > 0 && page <= totalPages).sort((a, b) => a - b);
  const items = [];
  sorted.forEach((page, index) => {
    if (index && page - sorted[index - 1] > 1) items.push("ellipsis");
    items.push(page);
  });
  return items;
}

function renderPagination(resultCount, totalPages) {
  elements.pagination.hidden = resultCount <= PAGE_SIZE;
  if (elements.pagination.hidden) {
    elements.pagination.innerHTML = "";
    return;
  }

  const pageButtons = getPaginationItems(totalPages).map((item) => {
    if (item === "ellipsis") return '<span class="pagination-ellipsis" aria-hidden="true">…</span>';
    const isCurrent = item === state.currentPage;
    return `<button type="button" data-page="${item}"${isCurrent ? ' class="active" aria-current="page"' : ""} aria-label="${item}페이지">${item}</button>`;
  }).join("");

  elements.pagination.innerHTML = `
    <button class="pagination-arrow" type="button" data-page="prev" aria-label="이전 페이지"${state.currentPage === 1 ? " disabled" : ""}>←</button>
    ${pageButtons}
    <button class="pagination-arrow" type="button" data-page="next" aria-label="다음 페이지"${state.currentPage === totalPages ? " disabled" : ""}>→</button>
  `;
}

function goToPage(page) {
  const totalPages = Math.max(1, Math.ceil(getFilteredContests().length / PAGE_SIZE));
  state.currentPage = Math.min(Math.max(page, 1), totalPages);
  render();
  document.getElementById("browse-title").scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    block: "start",
  });
}

function createBoardItem(contest) {
  const tracker = state.tracker[contest.id];
  const completed = tracker.checklist?.length || 0;
  return `
    <article class="board-card" data-contest-id="${escapeHtml(contest.id)}">
      <span class="board-dday">${getDeadlineInfo(contest.deadline).label}</span>
      <h4>${escapeHtml(contest.title)}</h4>
      <p>${completed}/5 체크 · ${tracker.note ? "메모 있음" : "메모 없음"}</p>
      <div class="board-card-actions">
        <select data-action="progress" aria-label="${escapeHtml(contest.title)} 진행 상태">
          ${Object.entries(PROGRESS).map(([value, item]) => `<option value="${value}"${tracker.progress === value ? " selected" : ""}>${item.label}</option>`).join("")}
        </select>
        <button type="button" data-action="tracker">기록</button>
      </div>
    </article>
  `;
}

function renderBoard() {
  const savedContests = state.contests.filter((contest) => isSaved(contest.id));
  elements.savedSummary.textContent = savedContests.length
    ? `${savedContests.length}개의 도전을 준비하고 있어요.`
    : "찜한 공모전의 준비 과정을 한곳에서 관리하세요.";

  if (!savedContests.length) {
    elements.challengeBoard.innerHTML = `
      <div class="board-empty">
        <strong>아직 시작한 도전이 없어요</strong>
        <p>위 목록에서 북마크 아이콘을 누르면 이곳에 준비 보드가 만들어집니다.</p>
        <a href="#browse-title">공모전 둘러보기</a>
      </div>`;
    return;
  }

  elements.challengeBoard.innerHTML = Object.entries(PROGRESS).map(([key, progress]) => {
    const items = savedContests.filter((contest) => state.tracker[contest.id].progress === key);
    return `
      <section class="board-column">
        <header><h3>${progress.label}</h3><span>${items.length}</span></header>
        <div class="board-column-list">
          ${items.length ? items.map(createBoardItem).join("") : '<p class="column-empty">아직 항목이 없어요</p>'}
        </div>
      </section>`;
  }).join("");
}

function updateStats() {
  const open = state.contests.filter((contest) => getDDay(contest.deadline) >= 0).length;
  const it = state.contests.filter((contest) => contest.category_group === "IT" && getDDay(contest.deadline) >= 0).length;
  const urgent = state.contests.filter((contest) => {
    const dDay = getDDay(contest.deadline);
    return dDay >= 0 && dDay <= 7;
  }).length;

  elements.openCount.textContent = open.toLocaleString("ko-KR");
  elements.itCount.textContent = it.toLocaleString("ko-KR");
  elements.urgentCount.textContent = urgent.toLocaleString("ko-KR");
}

function updateSavedCount() {
  const validIds = new Set(state.contests.map((contest) => contest.id));
  const count = Object.keys(state.tracker).filter((id) => validIds.has(id)).length;
  elements.savedCount.textContent = count.toLocaleString("ko-KR");
}

function populateCategoryFilter() {
  const categories = [...new Set(state.contests.map((contest) => contest.category))]
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b, "ko"));
  elements.categoryFilter.insertAdjacentHTML(
    "beforeend",
    categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("")
  );
}

function toggleBookmark(contest) {
  if (isSaved(contest.id)) {
    delete state.tracker[contest.id];
    showToast("찜한 공모전에서 삭제했어요.");
  } else {
    state.tracker[contest.id] = {
      progress: "saved",
      note: "",
      checklist: [],
      savedAt: new Date().toISOString(),
    };
    showToast("내 도전 보드에 추가했어요.");
  }
  saveTracker();
  render();
}

function escapeIcs(value) {
  return String(value).replaceAll("\\", "\\\\").replaceAll(";", "\\;").replaceAll(",", "\\,").replaceAll(/\r?\n/g, "\\n");
}

function addOneDay(dateString) {
  const date = parseDate(dateString);
  date.setDate(date.getDate() + 1);
  return `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}`;
}

function downloadCalendar(contest) {
  const date = contest.deadline.replaceAll("-", "");
  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Contestly//Contest Deadline//KO",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${escapeIcs(contest.id)}@contestly`,
    `DTSTAMP:${new Date().toISOString().replaceAll(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`,
    `DTSTART;VALUE=DATE:${date}`,
    `DTEND;VALUE=DATE:${addOneDay(contest.deadline)}`,
    `SUMMARY:${escapeIcs(`[마감] ${contest.title}`)}`,
    `DESCRIPTION:${escapeIcs(`${contest.organization}\n${contest.link}`)}`,
    `URL:${escapeIcs(contest.link)}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `contestly-${contest.deadline}.ics`;
  anchor.click();
  URL.revokeObjectURL(url);
  showToast("캘린더 파일을 만들었어요.");
}

function showTracker(contest) {
  if (!isSaved(contest.id)) toggleBookmark(contest);
  const tracker = state.tracker[contest.id];
  state.editingId = contest.id;
  elements.trackerContestTitle.textContent = contest.title;
  elements.trackerProgress.value = tracker.progress;
  elements.trackerNote.value = tracker.note;
  elements.trackerForm.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    checkbox.checked = tracker.checklist.includes(checkbox.value);
  });
  elements.trackerDialog.showModal();
}

function closeTracker() {
  elements.trackerDialog.close();
  state.editingId = null;
}

function saveTrackerForm(event) {
  event.preventDefault();
  const tracker = state.tracker[state.editingId];
  if (!tracker) return closeTracker();
  tracker.progress = elements.trackerProgress.value;
  tracker.note = elements.trackerNote.value.trim();
  tracker.checklist = [...elements.trackerForm.querySelectorAll('input[type="checkbox"]:checked')]
    .map((checkbox) => checkbox.value);
  saveTracker();
  closeTracker();
  render();
  showToast("도전 기록을 저장했어요.");
}

let toastTimer;
function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  toastTimer = setTimeout(() => elements.toast.classList.remove("show"), 2400);
}

function findContest(element) {
  const card = element.closest("[data-contest-id]");
  return state.contests.find((contest) => contest.id === card?.dataset.contestId);
}

function handleContestAction(event) {
  const control = event.target.closest("[data-action]");
  if (!control) return;
  const contest = findContest(control);
  if (!contest) return;

  if (control.dataset.action === "bookmark" && event.type === "click") toggleBookmark(contest);
  if (control.dataset.action === "calendar" && event.type === "click") downloadCalendar(contest);
  if (control.dataset.action === "tracker" && event.type === "click") showTracker(contest);
  if (control.dataset.action === "progress" && event.type === "change") {
    state.tracker[contest.id].progress = control.value;
    saveTracker();
    render();
  }
}

function resetFilters() {
  state.keyword = "";
  state.mode = "all";
  state.sort = "deadline";
  state.category = "all";
  state.eligibility = "all";
  state.deadlineRange = "all";
  state.currentPage = 1;
  elements.search.value = "";
  elements.sort.value = "deadline";
  elements.categoryFilter.value = "all";
  elements.eligibilityFilter.value = "all";
  elements.deadlineFilter.value = "all";
  elements.filterButtons.forEach((button) => {
    const isActive = button.dataset.mode === "all";
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
  render();
}

function showError() {
  elements.list.setAttribute("aria-busy", "false");
  elements.list.innerHTML = `
    <div class="error-state">
      <svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="15"/><path d="M20 12v10m0 6h.01"/></svg>
      <strong>공모전 정보를 불러오지 못했어요</strong>
      <p>로컬에서는 웹 서버를 실행한 뒤 접속해 주세요.</p>
    </div>`;
}

async function loadContests() {
  try {
    const response = await fetch("data/contests.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.contests = Array.isArray(data) ? data.map(normalizeContest) : [];
    populateCategoryFilter();
    updateStats();
    render();
  } catch (error) {
    console.error("공모전 데이터를 불러오지 못했습니다.", error);
    showError();
    renderBoard();
  }
}

elements.search.addEventListener("input", (event) => {
  state.keyword = event.target.value;
  state.currentPage = 1;
  render();
});

elements.sort.addEventListener("change", (event) => {
  state.sort = event.target.value;
  state.currentPage = 1;
  render();
});

elements.categoryFilter.addEventListener("change", (event) => {
  state.category = event.target.value;
  state.currentPage = 1;
  render();
});

elements.eligibilityFilter.addEventListener("change", (event) => {
  state.eligibility = event.target.value;
  state.currentPage = 1;
  render();
});

elements.deadlineFilter.addEventListener("change", (event) => {
  state.deadlineRange = event.target.value;
  state.currentPage = 1;
  render();
});

elements.filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    state.currentPage = 1;
    elements.filterButtons.forEach((item) => {
      const isActive = item === button;
      item.classList.toggle("active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });
    render();
  });
});

elements.resetFilters.addEventListener("click", resetFilters);
elements.pagination.addEventListener("click", (event) => {
  const button = event.target.closest("[data-page]");
  if (!button || button.disabled) return;
  const target = button.dataset.page;
  if (target === "prev") return goToPage(state.currentPage - 1);
  if (target === "next") return goToPage(state.currentPage + 1);
  goToPage(Number(target));
});
elements.list.addEventListener("click", handleContestAction);
elements.challengeBoard.addEventListener("click", handleContestAction);
elements.challengeBoard.addEventListener("change", handleContestAction);
elements.trackerForm.addEventListener("submit", saveTrackerForm);
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", closeTracker));
elements.trackerDialog.addEventListener("click", (event) => {
  if (event.target === elements.trackerDialog) closeTracker();
});

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.search.focus();
  }
});

elements.todayLabel.textContent = `${new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "long",
  day: "numeric",
}).format(new Date())} 기준`;

renderBoard();
loadContests();
