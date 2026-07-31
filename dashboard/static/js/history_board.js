import { leaderboard } from './leaderboard.js';
import { wsClient } from './websocket_client.js';

class HistoryBoard {
    constructor() {
        this.currentRunId = null;
        this.currentGenId = null;
    }

    init() {
        this.loadRunsList();

        // Refresh runs list when updates come via WebSocket
        wsClient.addListener((data) => {
            if (data.status === "evolving" || data.status === "completed" || data.status === "failed") {
                this.loadRunsList(true); // preserve active selection
            }
        });
    }

    loadRunsList(preserveSelection = false) {
        fetch("/api/runs")
            .then(r => r.json())
            .then(runs => {
                const container = document.getElementById("runListContainer");
                if (!container) return;
                container.innerHTML = "";
                runs.forEach((r, idx) => {
                    const li = document.createElement("li");
                    li.className = `run-item ${this.currentRunId === r.id ? 'active' : ''}`;
                    li.innerHTML = `
                        <strong>${r.name}</strong>
                        <span style="font-size:0.75rem; color:var(--text-muted);">${r.status}</span>
                    `;
                    li.onclick = () => this.selectRun(r.id);
                    container.appendChild(li);

                    // Select latest automatically if none selected and not preserving selection
                    if (idx === 0 && !this.currentRunId && !preserveSelection) {
                        this.selectRun(r.id);
                    }
                });
            })
            .catch(err => console.error("Error loading runs:", err));
    }

    selectRun(runId) {
        this.currentRunId = runId;
        document.querySelectorAll(".run-item").forEach(el => el.classList.remove("active"));
        this.loadGenerations(runId);
    }

    loadGenerations(runId) {
        fetch(`/api/runs/${runId}/generations`)
            .then(r => r.json())
            .then(gens => {
                const container = document.getElementById("generationListContainer");
                if (!container) return;
                container.innerHTML = "";
                gens.forEach((g, idx) => {
                    const btn = document.createElement("button");
                    btn.className = `generation-tab ${this.currentGenId === g.id ? 'active' : ''}`;
                    btn.innerText = `Gen ${g.generation_number}`;
                    btn.onclick = () => this.selectGeneration(g.id, btn);
                    container.appendChild(btn);

                    if (idx === gens.length - 1 && !this.currentGenId) {
                        btn.click();
                    }
                });
            })
            .catch(err => console.error("Error loading generations:", err));
    }

    selectGeneration(genId, btnEl) {
        this.currentGenId = genId;
        document.querySelectorAll(".generation-tab").forEach(el => el.classList.remove("active"));
        if (btnEl) btnEl.classList.add("active");

        leaderboard.loadStrategies(genId);
    }
}

export const historyBoard = new HistoryBoard();
