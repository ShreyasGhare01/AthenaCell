import { wsClient } from './websocket_client.js';

export function initHeader() {
    const statusDot = document.getElementById("statusDot");
    const statusLabel = document.getElementById("statusLabel");

    wsClient.addListener((data) => {
        if (!statusDot || !statusLabel) return;

        if (data.status === "evolving") {
            statusDot.className = "status-dot evolving";
            statusLabel.innerText = `Evolving Gen ${data.generation}/${data.total_generations} - Best Sharpe: ${data.best_sharpe.toFixed(2)}`;
        } else if (data.status === "completed") {
            statusDot.className = "status-dot";
            statusLabel.innerText = "Complete";
        } else if (data.status === "failed") {
            statusDot.className = "status-dot idle";
            statusLabel.innerText = "Failed";
            alert("Evolution run encountered an error: " + data.error);
        }
    });
}
