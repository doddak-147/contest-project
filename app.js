let contests = [];

fetch("../data/contests.json")
  .then(res => res.json())
  .then(data => {
    contests = data;
    render(contests);
  });

function render(data) {
  const list = document.getElementById("list");
  list.innerHTML = "";

  data.forEach(c => {
    const dDay = getDDay(c.deadline);

    list.innerHTML += `
      <div class="card ${dDay <= 3 ? 'urgent' : ''}">
        <h3>${c.title}</h3>
        <p>${c.organization}</p>
        <p>마감: ${c.deadline} (D-${dDay})</p>
        <a href="${c.link}" target="_blank">바로가기</a>
      </div>
    `;
  });
}

function getDDay(deadline) {
  const today = new Date();
  const end = new Date(deadline);
  return Math.ceil((end - today) / (1000 * 60 * 60 * 24));
}

// 검색 기능
document.getElementById("search").addEventListener("input", e => {
  const keyword = e.target.value.toLowerCase();

  const filtered = contests.filter(c =>
    c.title.toLowerCase().includes(keyword)
  );

  render(filtered);
});