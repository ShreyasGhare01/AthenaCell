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
            container.innerText = text;
            if (card) {
                card.style.display = "block";
            }
        } else {
            container.innerText = "No Athena Selection log available for this generation.";
            // If there's no log, we can still show the card but with a placeholder
            if (card) {
                // If it's the standard tournament selection, hide the card or keep it showing a message
                card.style.display = "none";
            }
        }
    }
}

export const athenaJournal = new AthenaJournal();
