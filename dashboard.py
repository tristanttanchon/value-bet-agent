"""
dashboard.py — Génère un dashboard HTML local.
Ouvre automatiquement dans le navigateur.

Usage :
  python dashboard.py
"""

import csv
import json
import webbrowser
from datetime import date
from pathlib import Path
import config
from modules.simulation import load_bankroll
from modules.stats_tracker import get_full_stats
from modules.clv_tracker import get_clv_summary
from modules.bankroll_guard import get_drawdown, get_kelly_fraction, get_status_line


DASHBOARD_FILE = config.DATA_DIR / "dashboard.html"


def load_bankroll_history() -> list[dict]:
    """Reconstruit l'historique du bankroll depuis le CSV des paris."""
    if not config.BETS_LOG_FILE.exists():
        return []

    history = []
    bankroll = load_bankroll()
    current = bankroll["initial"]

    with open(config.BETS_LOG_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r["status"] in ("WIN", "LOSS") and r["profit_loss"]]

    rows.sort(key=lambda r: r["date"])

    for row in rows:
        current = round(current + float(row["profit_loss"]), 2)
        history.append({"date": row["date"], "bankroll": current})

    return history


def generate_dashboard() -> str:
    """Génère le fichier HTML du dashboard et retourne son chemin."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    bankroll = load_bankroll()
    stats = get_full_stats()
    clv = get_clv_summary()
    history = load_bankroll_history()
    guard_status = get_status_line(bankroll)
    dd = get_drawdown(bankroll)
    pl = bankroll["current"] - bankroll["initial"]
    roi = (pl / bankroll["initial"] * 100) if bankroll["initial"] else 0

    # Données pour le graphique
    chart_labels = json.dumps([h["date"] for h in history])
    chart_data = json.dumps([h["bankroll"] for h in history])
    initial_line = json.dumps([bankroll["initial"]] * len(history))

    # Stats par compétition
    comp_rows = ""
    if stats.get("by_competition"):
        for comp, s in list(stats["by_competition"].items())[:10]:
            color = "#2ecc71" if s["yield_pct"] > 0 else "#e74c3c"
            comp_rows += f"""
            <tr>
                <td>{comp}</td>
                <td>{s['total']}</td>
                <td>{s['wins']}W / {s['losses']}L</td>
                <td>{s['winrate']}%</td>
                <td style="color:{color};font-weight:bold">{s['yield_pct']:+.1f}%</td>
                <td style="color:{color};font-weight:bold">{s['pl']:+.2f}€</td>
            </tr>"""

    # Stats par marché
    market_rows = ""
    if stats.get("by_market"):
        for market, s in stats["by_market"].items():
            color = "#2ecc71" if s["yield_pct"] > 0 else "#e74c3c"
            market_rows += f"""
            <tr>
                <td>{market}</td>
                <td>{s['total']}</td>
                <td>{s['wins']}W / {s['losses']}L</td>
                <td>{s['winrate']}%</td>
                <td style="color:{color};font-weight:bold">{s['yield_pct']:+.1f}%</td>
                <td style="color:{color};font-weight:bold">{s['pl']:+.2f}€</td>
            </tr>"""

    # Derniers paris
    recent_bets_rows = ""
    all_bets = []
    if config.BETS_LOG_FILE.exists():
        with open(config.BETS_LOG_FILE, encoding="utf-8") as f:
            all_bets = list(csv.DictReader(f))
    for bet in reversed(all_bets[-20:]):
        status_color = {"WIN": "#2ecc71", "LOSS": "#e74c3c", "PENDING": "#f39c12"}.get(bet["status"], "#aaa")
        pl_str = f"{float(bet['profit_loss']):+.2f}€" if bet.get("profit_loss") else "—"
        recent_bets_rows += f"""
        <tr>
            <td>{bet['date']}</td>
            <td>{bet['match']}</td>
            <td>{bet['market']}</td>
            <td>{bet['market_odds']}</td>
            <td>{bet['edge']}</td>
            <td>{bet['sim_stake']}€</td>
            <td style="color:{status_color};font-weight:bold">{bet['status']}</td>
            <td style="color:{status_color}">{pl_str}</td>
        </tr>"""

    pl_color = "#2ecc71" if pl >= 0 else "#e74c3c"
    clv_quality = clv.get("model_quality", "N/A")
    clv_avg = f"{clv.get('avg_clv', 0):+.1f}%" if clv.get("total", 0) > 0 else "N/A"

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Value Bet Agent — Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; }}
        .header {{ background: linear-gradient(135deg, #1a1d2e, #16213e); padding: 24px 32px; border-bottom: 1px solid #2a2d3e; }}
        .header h1 {{ font-size: 1.8rem; color: #fff; }}
        .header p {{ color: #888; margin-top: 4px; font-size: 0.9rem; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 24px 32px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #1a1d2e; border-radius: 12px; padding: 20px; border: 1px solid #2a2d3e; }}
        .card.wide {{ grid-column: span 2; }}
        .card h3 {{ font-size: 0.8rem; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
        .card .value {{ font-size: 2rem; font-weight: bold; }}
        .card .sub {{ font-size: 0.85rem; color: #888; margin-top: 4px; }}
        .positive {{ color: #2ecc71; }}
        .negative {{ color: #e74c3c; }}
        .neutral {{ color: #f39c12; }}
        .chart-container {{ background: #1a1d2e; border-radius: 12px; padding: 24px; border: 1px solid #2a2d3e; margin-bottom: 24px; }}
        .chart-container h2 {{ margin-bottom: 16px; font-size: 1rem; color: #ccc; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 10px 12px; font-size: 0.8rem; color: #888; text-transform: uppercase; border-bottom: 1px solid #2a2d3e; }}
        td {{ padding: 10px 12px; font-size: 0.9rem; border-bottom: 1px solid #1a1d2e; }}
        tr:hover td {{ background: #1f2235; }}
        .section {{ background: #1a1d2e; border-radius: 12px; padding: 24px; border: 1px solid #2a2d3e; margin-bottom: 24px; }}
        .section h2 {{ margin-bottom: 16px; font-size: 1rem; color: #ccc; }}
        .guard-bar {{ background: #0f1117; border-radius: 8px; padding: 12px 16px; font-size: 0.85rem; color: #aaa; margin-bottom: 24px; border: 1px solid #2a2d3e; }}
        .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
        @media (max-width: 900px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <div class="header">
        <h1>⚽ Value Bet Agent — Dashboard</h1>
        <p>Mis à jour le {date.today().isoformat()}</p>
    </div>

    <div class="container">

        <!-- Statut bankroll guard -->
        <div class="guard-bar">{guard_status}</div>

        <!-- KPIs -->
        <div class="grid">
            <div class="card">
                <h3>Bankroll actuelle</h3>
                <div class="value">{bankroll['current']:.2f}€</div>
                <div class="sub">Initial : {bankroll['initial']:.2f}€</div>
            </div>
            <div class="card">
                <h3>P&L total</h3>
                <div class="value {'positive' if pl >= 0 else 'negative'}">{pl:+.2f}€</div>
                <div class="sub">ROI : {roi:+.1f}%</div>
            </div>
            <div class="card">
                <h3>Yield global</h3>
                <div class="value {'positive' if stats.get('yield_pct', 0) >= 0 else 'negative'}">{stats.get('yield_pct', 0):+.1f}%</div>
                <div class="sub">30 derniers jours : {stats.get('recent_30d_yield', 0):+.1f}%</div>
            </div>
            <div class="card">
                <h3>Taux de réussite</h3>
                <div class="value">{stats.get('winrate', 0):.1f}%</div>
                <div class="sub">{stats.get('wins', 0)}W / {stats.get('losses', 0)}L</div>
            </div>
            <div class="card">
                <h3>Drawdown</h3>
                <div class="value {'negative' if dd > 0.1 else 'positive'}">{dd*100:.1f}%</div>
                <div class="sub">Stop loss à 20%</div>
            </div>
            <div class="card">
                <h3>CLV moyen</h3>
                <div class="value {'positive' if clv.get('avg_clv', 0) > 0 else 'negative'}">{clv_avg}</div>
                <div class="sub">Qualité modèle : {clv_quality}</div>
            </div>
            <div class="card">
                <h3>Paris en attente</h3>
                <div class="value neutral">{bankroll.get('pending', 0)}</div>
                <div class="sub">Total joués : {bankroll.get('total_bets', 0)}</div>
            </div>
        </div>

        <!-- Graphique bankroll -->
        <div class="chart-container">
            <h2>📈 Évolution du bankroll</h2>
            <canvas id="bankrollChart" height="80"></canvas>
        </div>

        <!-- Stats par compétition et par marché -->
        <div class="two-col">
            <div class="section">
                <h2>🏆 Performance par compétition</h2>
                <table>
                    <thead><tr><th>Compétition</th><th>Paris</th><th>W/L</th><th>WR</th><th>Yield</th><th>P&L</th></tr></thead>
                    <tbody>{comp_rows if comp_rows else '<tr><td colspan="6" style="color:#888;text-align:center">Aucune donnée</td></tr>'}</tbody>
                </table>
            </div>
            <div class="section">
                <h2>🎯 Performance par marché</h2>
                <table>
                    <thead><tr><th>Marché</th><th>Paris</th><th>W/L</th><th>WR</th><th>Yield</th><th>P&L</th></tr></thead>
                    <tbody>{market_rows if market_rows else '<tr><td colspan="6" style="color:#888;text-align:center">Aucune donnée</td></tr>'}</tbody>
                </table>
            </div>
        </div>

        <!-- Derniers paris -->
        <div class="section">
            <h2>📋 20 derniers paris</h2>
            <table>
                <thead><tr><th>Date</th><th>Match</th><th>Marché</th><th>Cote</th><th>Edge</th><th>Mise</th><th>Statut</th><th>P&L</th></tr></thead>
                <tbody>{recent_bets_rows if recent_bets_rows else '<tr><td colspan="8" style="color:#888;text-align:center">Aucun pari enregistré</td></tr>'}</tbody>
            </table>
        </div>

    </div>

    <script>
        const ctx = document.getElementById('bankrollChart').getContext('2d');
        const labels = {chart_labels};
        const data = {chart_data};
        const initialLine = {initial_line};

        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: labels.length ? labels : ['Début'],
                datasets: [
                    {{
                        label: 'Bankroll',
                        data: data.length ? data : [{bankroll['current']}],
                        borderColor: '#3498db',
                        backgroundColor: 'rgba(52,152,219,0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 3,
                    }},
                    {{
                        label: 'Bankroll initiale',
                        data: initialLine.length ? initialLine : [{bankroll['initial']}],
                        borderColor: '#888',
                        borderDash: [5, 5],
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: false,
                    }}
                ]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ labels: {{ color: '#aaa' }} }},
                    tooltip: {{ mode: 'index' }}
                }},
                scales: {{
                    x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#2a2d3e' }} }},
                    y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#2a2d3e' }} }}
                }}
            }}
        }});
    </script>
</body>
</html>"""

    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    return str(DASHBOARD_FILE)


def open_dashboard() -> None:
    path = generate_dashboard()
    webbrowser.open(f"file:///{path.replace(chr(92), '/')}")
    print(f"✅ Dashboard ouvert dans le navigateur : {path}")


if __name__ == "__main__":
    open_dashboard()
