(function () {
  const id = window.THXOU_CONTEST_ID, body = document.querySelector("#standings");
  if (!id || !body) return;
  const status = document.querySelector("#status");
  let timer;
  async function refresh() {
    try {
      const response = await fetch(`/api/contests/${id}/leaderboard`, { credentials: "same-origin" });
      if (!response.ok) throw new Error();
      const data = await response.json();
      body.replaceChildren(...(data.standings || []).map(x => {
        const row = document.createElement("tr");
        for (const value of [x.rank, x.username, x.score]) {
          const cell = document.createElement("td");
          cell.textContent = String(value);
          row.appendChild(cell);
        }
        return row;
      }));
      status.textContent = `Updated ${new Date().toLocaleTimeString()}`;
      if (data.phase === "completed") clearInterval(timer);
    } catch (_) { status.textContent = "Updates paused—retry"; }
  }
  refresh();
  timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
})();
