import { strategyDrawer } from './strategy_drawer.js';

class Leaderboard {
    constructor() {
        this.selectedStratId = null;
    }

    loadStrategies(genId) {
        fetch(`/api/generations/${genId}/strategies`)
            .then(r => r.json())
            .then(strats => {
                const tbody = document.getElementById("leaderboardBody");
                if (!tbody) return;
                tbody.innerHTML = "";
                if (strats.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color: var(--text-muted);">No strategies evaluated in this generation.</td></tr>`;
                    return;
                }
                strats.forEach((s, idx) => {
                    const tr = document.createElement("tr");
                    tr.className = `clickable-row ${this.selectedStratId === s.id ? 'selected' : ''}`;
                    tr.onclick = () => this.selectStrategy(s.id, tr);

                    // Check train vs validation gap indicator warning (gap > 1.0 is alarming)
                    const gapCell = s.agg_train_validation_gap > 1.0
                        ? `<span class="gap-warning">&#9888; Overfit (${s.agg_train_validation_gap.toFixed(2)})</span>`
                        : `<span>${s.agg_train_validation_gap.toFixed(2)}</span>`;

                    tr.innerHTML = `
                        <td>${idx + 1}</td>
                        <td><strong>${s.name}</strong><br><span style="font-size:0.75rem; color:var(--text-muted);">${s.id}</span></td>
                        <td>${s.agg_validation_sharpe.toFixed(2)}</td>
                        <td>${(s.agg_validation_drawdown * 100).toFixed(1)}%</td>
                        <td>${(s.agg_validation_win_rate * 100).toFixed(1)}%</td>
                        <td>${(s.risk_cap_applied_pct * 100).toFixed(0)}%</td>
                        <td>${gapCell}</td>
                        <td>${s.mutation_type ? `${s.mutation_type} (${s.parent_id})` : 'Seed'}</td>
                    `;
                    tbody.appendChild(tr);
                });
            })
            .catch(err => console.error("Error loading strategies:", err));
    }

    selectStrategy(stratId, rowEl) {
        this.selectedStratId = stratId;
        document.querySelectorAll(".clickable-row").forEach(el => el.classList.remove("selected"));
        if (rowEl) rowEl.classList.add("selected");

        strategyDrawer.showStrategyDetail(stratId);
    }
}

export const leaderboard = new Leaderboard();
