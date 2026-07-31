export class StrategyDrawer {
    constructor() {
        this.myChart = null;
    }

    init() {
        // Setup close button event listeners
        const closeBtn = document.querySelector("#strategyDrawer .close-btn");
        if (closeBtn) {
            closeBtn.addEventListener("click", () => this.closeDrawer());
        }
        const overlay = document.getElementById("drawerOverlay");
        if (overlay) {
            overlay.addEventListener("click", () => this.closeDrawer());
        }
    }

    showStrategyDetail(stratId) {
        fetch(`/api/strategies/${stratId}`)
            .then(r => r.json())
            .then(s => {
                document.getElementById("drawerStratName").innerText = s.name;
                document.getElementById("detailSharpe").innerText = s.agg_validation_sharpe.toFixed(2);
                document.getElementById("detailDrawdown").innerText = `${(s.agg_validation_drawdown * 100).toFixed(1)}%`;
                document.getElementById("detailWinRate").innerText = `${(s.agg_validation_win_rate * 100).toFixed(1)}%`;

                const detailRiskCap = document.getElementById("detailRiskCap");
                if (detailRiskCap) {
                    detailRiskCap.innerText = `${(s.risk_cap_applied_pct * 100).toFixed(0)}%`;
                }

                // Generate readable rule description
                const ruleSentences = this.renderRulesToSentences(s.config);
                document.getElementById("rulesSentencesContainer").innerHTML = ruleSentences;

                // Plot train vs val equity curve
                this.plotEquityCurves(s.folds);

                // Render trade logs
                const tradeLogBody = document.getElementById("tradeLogBody");
                if (tradeLogBody) {
                    tradeLogBody.innerHTML = "";
                    if (s.trades.length === 0) {
                        tradeLogBody.innerHTML = `<tr><td colspan="7" style="text-align:center;">No trades recorded for this strategy.</td></tr>`;
                    } else {
                        s.trades.forEach(t => {
                            const tr = document.createElement("tr");
                            const pColor = t.profit_pct >= 0 ? "green" : "red";
                            const profitText = t.profit_pct !== null ? `<span style="color:${pColor}; font-weight:600;">${(t.profit_pct * 100).toFixed(1)}%</span>` : "-";

                            tr.innerHTML = `
                                <td>${t.ticker}</td>
                                <td>${t.entry_date.split("T")[0]}</td>
                                <td>$${t.entry_price.toFixed(2)}</td>
                                <td>${t.exit_date ? t.exit_date.split("T")[0] : "-"}</td>
                                <td>${t.exit_price ? `$${t.exit_price.toFixed(2)}` : "-"}</td>
                                <td>${profitText}</td>
                                <td>${t.exit_reason || "-"}</td>
                            `;
                            tradeLogBody.appendChild(tr);
                        });
                    }
                }

                // Open Drawer
                document.getElementById("drawerOverlay").style.display = "block";
                document.getElementById("strategyDrawer").classList.add("open");
            })
            .catch(err => console.error("Error loading strategy details:", err));
    }

    closeDrawer() {
        const overlay = document.getElementById("drawerOverlay");
        const drawer = document.getElementById("strategyDrawer");
        if (overlay) overlay.style.display = "none";
        if (drawer) drawer.classList.remove("open");
    }

    renderRulesToSentences(config) {
        function recurseRule(rule) {
            if (rule.type === "and" || rule.type === "or") {
                const subParts = rule.rules.map(recurseRule);
                return `(${subParts.join(` <strong>${rule.type.toUpperCase()}</strong> `)})`;
            } else if (rule.type === "not") {
                return `<strong>NOT</strong> (${recurseRule(rule.rules[0])})`;
            } else {
                // simple condition
                const bVal = typeof rule.indicator_b === "object"
                    ? `${rule.indicator_b.name}(${rule.indicator_b.period || ''})`
                    : rule.indicator_b;
                return `${rule.indicator_a.name}(${rule.indicator_a.period || ''}) ${rule.operator} ${bVal}`;
            }
        }
        const entryText = recurseRule(config.entry_rules);
        const exitText = recurseRule(config.exit_rules);
        return `
            <p><strong>Entry Condition:</strong> Buy when ${entryText}</p>
            <p style="margin-top:0.5rem;"><strong>Exit Condition:</strong> Sell when ${exitText}</p>
        `;
    }

    plotEquityCurves(folds) {
        if (folds.length === 0) return;

        const firstFold = folds[0];
        const trainPoints = firstFold.train_equity_curve;
        const valPoints = firstFold.val_equity_curve;

        const labels = [];
        const data = [];

        trainPoints.forEach(pt => {
            labels.push(pt.date);
            data.push(pt.equity);
        });
        valPoints.forEach(pt => {
            labels.push(pt.date);
            data.push(pt.equity);
        });

        const ctx = document.getElementById("equityChartCanvas").getContext("2d");
        if (this.myChart) {
            this.myChart.destroy();
        }

        this.myChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Train Period Equity',
                    data: data.slice(0, trainPoints.length),
                    borderColor: '#C9A44C',
                    backgroundColor: 'rgba(201, 164, 76, 0.1)',
                    borderWidth: 2,
                    tension: 0.1
                }, {
                    label: 'Validation Period Equity',
                    data: Array(trainPoints.length).fill(null).concat(data.slice(trainPoints.length)),
                    borderColor: '#1A1A1A',
                    backgroundColor: 'rgba(26, 26, 26, 0.05)',
                    borderWidth: 2,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false
                    }
                }
            }
        });
    }
}

export const strategyDrawer = new StrategyDrawer();
