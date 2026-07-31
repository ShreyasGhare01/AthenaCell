import { historyBoard } from './history_board.js';

export function initControlBoard() {
    const launchBtn = document.querySelector(".sidebar-panel .btn-gold");
    if (launchBtn) {
        launchBtn.addEventListener("click", () => {
            fetch("/api/runs/start", { method: "POST" })
                .then(r => r.json())
                .then(res => {
                    alert(res.message);
                    historyBoard.loadRunsList();
                })
                .catch(err => {
                    console.error("Failed to start run:", err);
                    alert("Error starting evolution run.");
                });
        });
    }
}
