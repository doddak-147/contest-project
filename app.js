let contests = [];
let currentKeyword = "";
let currentMode = "all";

fetch("data/contests.json")
  .then(res => res.json())
  .then(data => {
    contests = data;
    applyFilters();
  });

function getDDay(deadline) {
  const today = new Date();
  const end = new Date(deadline);
  return Math.ceil((end - today) / (1000 * 60 * 60 * 24));
}

function render(data) {
  const list = document.getElementById("list");
  list.innerHTML = "";

  if (data.length === 0) {
    list.innerHTML = "<p>조건에 맞는 공모전이 없습니다.</p>";
    return;
  }

  data.forEach(c => {
    const dDay = getDDay(c.deadline);

    list.innerHTML += `
      <div class="card ${dDay <= 3 ? 'urgent' : ''}">
        <h3>${c.title}</h3>
        <p>주최: ${c.organization}</p>
        <p>마감: ${c.deadline} ${dDay >= 0 ? `(D-${dDay})` : `(마감)`}</p>
        <p>분류: ${c.category}</p>
        <a href="${c.link}" target="_blank">바로가기</a>
      </div>
    `;
  });
}

function applyFilters() {
  let filtered = contests;

  if (currentMode === "it") {
    filtered = filtered.filter(c => c.category === "IT");
  }

  if (currentKeyword.trim() !== "") {
    const keyword = currentKeyword.toLowerCase();
    filtered = filtered.filter(c =>
      c.title.toLowerCase().includes(keyword) ||
      c.organization.toLowerCase().includes(keyword)
    );
  }

  render(filtered);
}

document.getElementById("search").addEventListener("input", e => {
  currentKeyword = e.target.value;
  applyFilters();
});

document.getElementById("showAll").addEventListener("click", () => {
  currentMode = "all";
  applyFilters();
});

document.getElementById("showIT").addEventListener("click", () => {
  currentMode = "it";
  applyFilters();
});