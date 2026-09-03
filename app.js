const state = {
  contests: [],
  keyword: "",
  mode: "all",
  sort: "deadline",
};

const elements = {
  list: document.getElementById("list"),
  search: document.getElementById("search"),
  sort: document.getElementById("sort"),
  resultCount: document.getElementById("resultCount"),
  openCount: document.getElementById("openCount"),
  itCount: document.getElementById("itCount"),
  urgentCount: document.getElementById("urgentCount"),
  todayLabel: document.getElementById("todayLabel"),
  filterButtons: [...document.querySelectorAll(".filter-button")],
};

const DAY_IN_MS = 1000 * 60 * 60 * 24;

function parseDate(dateString) {
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

  if (dDay < 0) return { label: "마감", status: "closed", statusText: "접수 종료" };
  if (dDay === 0) return { label: "D-DAY", status: "urgent", statusText: "오늘 마감" };
  if (dDay <= 7) return { label: `D-${dDay}`, status: "urgent", statusText: "마감 임박" };
  return { label: `D-${dDay}`, status: "open", statusText: "접수 중" };
}

function formatDate(dateString) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    weekday: "short",
  }).format(parseDate(dateString));
}

function escapeHtml(value) {
  return String(value)
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

function createCard(contest) {
  const deadline = getDeadlineInfo(contest.deadline);
  const category = contest.category === "IT" ? "IT · 테크" : "일반";
  const categoryClass = contest.category === "IT" ? "it" : "etc";

  return `
    <article class="card">
      <div class="card-top">
        <span class="category-badge ${categoryClass}">${category}</span>
        <span class="status-badge ${deadline.status}">${deadline.statusText}</span>
      </div>
      <h3>${escapeHtml(contest.title)}</h3>
      <p class="organization" title="${escapeHtml(contest.organization)}">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 17V6.5L10 3l6.5 3.5V17M7 17v-3h6v3M7 8h.01M10 8h.01M13 8h.01M7 11h.01M10 11h.01M13 11h.01"/></svg>
        ${escapeHtml(contest.organization || "주최 기관 미정")}
      </p>
      <div class="card-footer">
        <div>
          <span class="deadline-label">Deadline</span>
          <span class="deadline-date"><strong class="${deadline.status}">${deadline.label}</strong>${formatDate(contest.deadline)}</span>
        </div>
        <a class="card-link" href="${safeLink(contest.link)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(contest.title)} 상세 페이지 열기">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 15 15 5m0 0H8m7 0v7"/></svg>
        </a>
      </div>
    </article>
  `;
}

function getFilteredContests() {
  const normalizedKeyword = state.keyword.trim().toLocaleLowerCase("ko-KR");

  const filtered = state.contests.filter((contest) => {
    const dDay = getDDay(contest.deadline);
    const matchesMode =
      state.mode === "all" ||
      (state.mode === "it" && contest.category === "IT") ||
      (state.mode === "urgent" && dDay >= 0 && dDay <= 7);
    const searchableText = `${contest.title} ${contest.organization}`.toLocaleLowerCase("ko-KR");
    return matchesMode && searchableText.includes(normalizedKeyword);
  });

  return filtered.sort((a, b) => {
    if (state.sort === "title") return a.title.localeCompare(b.title, "ko");
    const direction = state.sort === "latest" ? -1 : 1;
    return (parseDate(a.deadline) - parseDate(b.deadline)) * direction;
  });
}

function render() {
  const filtered = getFilteredContests();
  elements.list.setAttribute("aria-busy", "false");
  elements.resultCount.textContent = filtered.length.toLocaleString("ko-KR");

  if (filtered.length === 0) {
    elements.list.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="18" cy="18" r="11"/><path d="m27 27 7 7M13.5 18h9"/></svg>
        <strong>조건에 맞는 공모전이 없어요</strong>
        <p>검색어를 바꾸거나 다른 카테고리를 선택해 보세요.</p>
      </div>`;
    return;
  }

  elements.list.innerHTML = filtered.map(createCard).join("");
}

function updateStats() {
  const open = state.contests.filter((contest) => getDDay(contest.deadline) >= 0).length;
  const it = state.contests.filter(
    (contest) => contest.category === "IT" && getDDay(contest.deadline) >= 0
  ).length;
  const urgent = state.contests.filter((contest) => {
    const dDay = getDDay(contest.deadline);
    return dDay >= 0 && dDay <= 7;
  }).length;

  elements.openCount.textContent = open.toLocaleString("ko-KR");
  elements.itCount.textContent = it.toLocaleString("ko-KR");
  elements.urgentCount.textContent = urgent.toLocaleString("ko-KR");
}

function showError() {
  elements.list.setAttribute("aria-busy", "false");
  elements.list.innerHTML = `
    <div class="error-state">
      <svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="15"/><path d="M20 12v10m0 6h.01"/></svg>
      <strong>공모전 정보를 불러오지 못했어요</strong>
      <p>잠시 후 페이지를 새로고침해 주세요.</p>
    </div>`;
}

async function loadContests() {
  try {
    const response = await fetch("data/contests.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.contests = Array.isArray(data) ? data : [];
    updateStats();
    render();
  } catch (error) {
    console.error("공모전 데이터를 불러오지 못했습니다.", error);
    showError();
  }
}

elements.search.addEventListener("input", (event) => {
  state.keyword = event.target.value;
  render();
});

elements.sort.addEventListener("change", (event) => {
  state.sort = event.target.value;
  render();
});

elements.filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    elements.filterButtons.forEach((item) => {
      const isActive = item === button;
      item.classList.toggle("active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });
    render();
  });
});

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.search.focus();
  }
});

elements.todayLabel.textContent =
  new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date()) + " 기준";

loadContests();
