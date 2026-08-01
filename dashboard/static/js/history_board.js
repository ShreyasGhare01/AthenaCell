import { leaderboard } from './leaderboard.js';
import { wsClient } from './websocket_client.js';
import { athenaJournal } from './athena_journal.js';

class HistoryBoard {
    constructor() {
        this.currentRunId = null;
        this.currentGenId = null;
    }

    init() {
        this.loadRunsList();

        // Refresh runs list and warnings when updates come via WebSocket
        wsClient.addListener((data) => {
            if (data.status === "evolving" || data.status === "completed" || data.status === "failed") {
                this.loadRunsList(true); // preserve active selection
                if (this.currentRunId) {
                    this.loadDataQualityWarnings(this.currentRunId);
                }
            }
        });

        // Set up warning dropdown click toggle
        const badge = document.getElementById("dataQualityWarningBadge");
        const dropdown = document.getElementById("warningDropdown");
        if (badge && dropdown) {
            badge.addEventListener("click", (e) => {
                if (dropdown.style.display === "none" || !dropdown.style.display) {
                    dropdown.style.display = "block";
                } else {
                    dropdown.style.display = "none";
                }
                e.stopPropagation();
            });

            document.addEventListener("click", () => {
                dropdown.style.display = "none";
            });

            dropdown.addEventListener("click", (e) => {
                e.stopPropagation();
            });
        }
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
        this.loadDataQualityWarnings(runId);
    }

    loadDataQualityWarnings(runId) {
        const badge = document.getElementById("dataQualityWarningBadge");
        const countSpan = document.getElementById("warningCount");
        const contentDiv = document.getElementById("warningListContent");

        if (!badge || !countSpan || !contentDiv) return;

        fetch(`/api/runs/${runId}/data_quality_warnings`)
            .then(r => r.json())
            .then(warnings => {
                if (warnings && warnings.length > 0) {
                    badge.style.display = "flex";
                    countSpan.innerText = warnings.length;

                    contentDiv.innerHTML = warnings.map(w => {
                        const dateStr = w.date ? w.date.split("T")[0] : "N/A";
                        return `
                            <div style="border-bottom: 1px solid var(--border-color); padding-bottom: 0.4rem; margin-bottom: 0.4rem;">
                                <strong>Ticker:</strong> ${w.ticker}<br>
                                <strong>Date:</strong> ${dateStr}<br>
                                <strong>Divergence:</strong> ${(w.divergence_pct * 100).toFixed(2)}%<br>
                                <span style="font-size: 0.7rem; color: var(--text-muted);">${w.source_a} vs ${w.source_b}</span>
                            </div>
                        `;
                    }).join("");
                } else {
                    badge.style.display = "none";
                    countSpan.innerText = "0";
                    contentDiv.innerHTML = `<div style="color: var(--text-muted);">No warnings detected.</div>`;
                }
            })
            .catch(err => {
                console.error("Error loading data quality warnings:", err);
                badge.style.display = "none";
            });
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
        athenaJournal.loadJournal(genId);
    }
}

export const historyBoard = new HistoryBoard();
