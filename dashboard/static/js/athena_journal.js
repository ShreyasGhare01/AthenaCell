import { wsClient } from './websocket_client.js';

class AthenaJournal {
    constructor() {
        this.currentGenId = null;
    }

    init() {
        // Wire up live updates via WebSocket
        wsClient.addListener((data) => {
            if (data.status === "athena_journal") {
                this.displayJournalText(data.entry_text);
            }
        });
    }

    loadJournal(genId) {
        this.currentGenId = genId;
        const container = document.getElementById("athenaJournalContent");
        const card = document.getElementById("athenaJournalCard");

        if (container) {
            container.innerText = "Loading Athena decision journal...";
        }

        fetch(`/api/generations/${genId}/athena_log`)
            .then(r => r.json())
            .then(data => {
                if (data && data.entry_text) {
                    this.displayJournalText(data.entry_text);
                } else {
                    this.displayJournalText("");
                }
            })
            .catch(err => {
                console.error("Error loading Athena Selection journal:", err);
                this.displayJournalText("Error loading Athena Selection journal rationale.");
            });
    }

    displayJournalText(text) {
        const container = document.getElementById("athenaJournalContent");
        const card = document.getElementById("athenaJournalCard");

        if (!container) return;

        if (text && text.trim()) {
            if (card) {
                card.style.display = "block";
            }

            let entryText = text;
            let warningsHtml = "";

            if (entryText.startsWith("!!!WARNINGS: ")) {
                const parts = entryText.split("!!!\n\n");
                if (parts.length > 1) {
                    const warnStr = parts[0].replace("!!!WARNINGS: ", "");
                    const warnings = warnStr.split(" | ");

                    warningsHtml = `
                        <div style="background-color: #F8D7DA; color: #721C24; border: 1px solid #F5C6CB; padding: 0.8rem; border-radius: 6px; margin-bottom: 1rem; font-weight: bold; font-size: 0.85rem;">
                            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem;">
                                <span>⚠ Warning: Athena.md parsing issues detected — using defaults:</span>
                            </div>
                            <ul style="margin-left: 1.5rem; font-weight: normal; list-style-type: disc;">
                                ${warnings.map(w => `<li>${w}</li>`).join("")}
                            </ul>
                        </div>
                    `;
                    entryText = parts.slice(1).join("!!!\n\n");
                }
            }

            const escapedText = entryText
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");

            container.innerHTML = warningsHtml + escapedText;
        } else {
            container.innerHTML = "No Athena Selection log available for this generation.";
            if (card) {
                card.style.display = "none";
            }
        }
    }
}

export const athenaJournal = new AthenaJournal();
