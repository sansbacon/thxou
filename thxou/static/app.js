(function () {
  "use strict";

  const copyButton = document.querySelector("[data-copy-share]");
  if (copyButton) {
    copyButton.addEventListener("click", async function () {
      const input = document.querySelector("[data-share-url]");
      const status = document.querySelector("[data-copy-status]");
      try {
        await navigator.clipboard.writeText(input.value);
        status.textContent = "Link copied.";
      } catch (_) {
        input.focus();
        input.select();
        status.textContent = "Copy the selected link.";
      }
    });
  }

  const questionRows = Array.from(document.querySelectorAll("[data-question-row]"));
  const addQuestion = document.querySelector("[data-add-question]");
  if (addQuestion && questionRows.length) {
    function visibleRows() { return questionRows.filter(row => !row.hidden); }
    function renumber() {
      visibleRows().forEach((row, index) => {
        row.querySelector("[data-question-number]").textContent = String(index + 1);
        row.querySelector("input").required = index === 0;
      });
      addQuestion.disabled = visibleRows().length >= 30;
    }
    questionRows.forEach((row, index) => {
      const input = row.querySelector("input");
      if (index > 0 && !input.value) row.hidden = true;
      row.querySelector("[data-remove-question]").addEventListener("click", function () {
        if (visibleRows().length === 1) return;
        input.value = "";
        row.hidden = true;
        renumber();
      });
    });
    addQuestion.addEventListener("click", function () {
      const row = questionRows.find(candidate => candidate.hidden);
      if (!row) return;
      row.hidden = false;
      renumber();
      row.querySelector("input").focus();
    });
    renumber();
  }

  const table = document.querySelector("[data-contest-id]");
  const body = document.querySelector("#standings");
  if (!table || !body) return;
  const id = table.dataset.contestId;
  const status = document.querySelector("#status");
  let timer;
  async function refresh() {
    try {
      const response = await fetch(`/api/contests/${id}/leaderboard`, { credentials: "same-origin" });
      if (!response.ok) throw new Error();
      const data = await response.json();
      const rows = (data.standings || []).map(player => {
        const row = document.createElement("tr");
        for (const value of [player.rank, player.username, player.score]) {
          const cell = document.createElement("td");
          cell.textContent = String(value);
          row.appendChild(cell);
        }
        return row;
      });
      if (rows.length) body.replaceChildren(...rows);
      status.textContent = `Updated ${new Date().toLocaleTimeString()} · ${data.phase}`;
      if (data.phase === "completed") clearInterval(timer);
    } catch (_) {
      status.textContent = "Updates paused—retry by refreshing this page.";
    }
  }
  timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
})();
