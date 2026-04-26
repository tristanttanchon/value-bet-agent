"""
dashboard.py — Génère un dashboard HTML local (mode pronostiqueur).

Pas de bankroll, pas de €. Juste un récap winrate + détail des pronos
récents lus depuis Supabase.

Usage :
  python dashboard.py
"""

import json
import webbrowser
from datetime import date, timedelta
import config
from modules.db import get_client
from modules.winrate_tracker import get_winrate_stats


DASHBOARD_FILE = config.DATA_DIR / "dashboard.html"


def load_recent_bets(limit: int = 50) -> list[dict]:
    """Charge les N derniers pronos depuis Supabase."""
    db = get_client()
    try:
        resp = (
            db.table("bets")
            .select("*")
            .order("date", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Dashboard] Erreur lecture Supabase : {e}")
        return []


def load_winrate_history(days: int = 30) -> list[dict]:
    """Reconstruit un historique du winrate cumulé jour par jour."""
    db = get_client()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        resp = (
            db.table("bets")
            .select("date,status")
            .gte("date", cutoff)
            .order("date")
            .execute()
        )
        rows = resp.data or []
    except Exception as e:
        print(f"[Dashboard] Erreur historique : {e}")
        return []

    # Cumulé par date
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r.get("date") or "?"
        slot = by_date.setdefault(d, {"W": 0, "L": 0})
        if r.get("status") == "WIN":
            slot["W"] += 1
        elif r.get("status") == "LOSS":
            slot["L"] += 1

    cum_w = cum_l = 0
    out = []
    for d in sorted(by_date.keys()):
        cum_w += by_date[d]["W"]
        cum_l += by_date[d]["L"]
        decisive = cum_w + cum_l
        wr = (cum_w / decisive * 100) if decisive else 0
        out.append({"date": d, "winrate": round(wr, 1)})
    return out


def stats_by_market(bets: list[dict]) -> dict[str, dict]:
    by: dict[str, dict] = {}
    for b in bets:
        m = b.get("market") or "—"
        slot = by.setdefault(m, {"total": 0, "W": 0, "L": 0, "P": 0, "Pend": 0})
        slot["total"] += 1
        st = b.get("status")
        if st == "WIN":
            slot["W"] += 1
        elif st == "LOSS":
            slot["L"] += 1
        elif st == "PUSH":
            slot["P"] += 1
        elif st == "PENDING":
            slot["Pend"] += 1
    for slot in by.values():
        decisive = slot["W"] + slot["L"]
        slot["winrate"] = round((slot["W"] / decisive * 100) if decisive else 0, 1)
    return by


def stats_by_competition(bets: list[dict]) -> dict[str, dict]:
    by: dict[str, dict] = {}
    for b in bets:
        c = b.get("competition") or "—"
        slot = by.setdefault(c, {"total": 0, "W": 0, "L": 0, "P": 0, "Pend": 0})
        slot["total"] += 1
        st = b.get("status")
        if st == "WIN":
            slot["W"] += 1
        elif st == "LOSS":
            slot["L"] += 1
        elif st == "PUSH":
            slot["P"] += 1
        elif st == "PENDING":
            slot["Pend"] += 1
    for slot in by.values():
        decisive = slot["W"] + slot["L"]
        slot["winrate"] = round((slot["W"] / decisive * 100) if decisive else 0, 1)
    return by


def generate_dashboard() -> str:
    """Génère le fichier HTML du dashboard et retourne son chemin."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    stats_7 = get_winrate_stats(days=7)
    stats_30 = get_winrate_stats(days=30)
    stats_all = get_winrate_stats()
    history = load_winrate_history(days=30)
    recent = load_recent_bets(limit=50)
    by_market = stats_by_market(recent)
    by_comp = stats_by_competition(recent)

    chart_labels = json.dumps([h["date"] for h in history])
    chart_data = json.dumps([h["winrate"] for h in history])

    def market_rows_html() -> str:
        if not by_market:
            return '<tr><td colspan="5" style="color:#888;text-align:center">Aucune donnée</td></tr>'
        out = ""
        for m, s in sorted(by_market.items(), key=lambda kv: -kv[1]["total"]):
            color = "#2ecc71" if s["winrate"] >= 60 else ("#f39c12" if s["winrate"] >= 50 else "#e74c3c")
            out += f"""
            <tr>
                <td><code>{m}</code></td>
                <td>{s['total']}</td>
                <td>{s['W']}W / {s['L']}L</td>
                <td>{s['Pend']}</td>
                <td style="color:{color};font-weight:bold">{s['winrate']:.0f}%</td>
            </tr>"""
        return out

    def comp_rows_html() -> str:
        if not by_comp:
            return '<tr><td colspan="5" style="color:#888;text-align:center">Aucune donnée</td></tr>'
        out = ""
        for c, s in sorted(by_comp.items(), key=lambda kv: -kv[1]["total"])[:10]:
            color = "#2ecc71" if s["winrate"] >= 60 else ("#f39c12" if s["winrate"] >= 50 else "#e74c3c")
            out += f"""
            <tr>
                <td>{c}</td>
                <td>{s['total']}</td>
                <td>{s['W']}W / {s['L']}L</td>
                <td>{s['Pend']}</td>
                <td style="color:{color};font-weight:bold">{s['winrate']:.0f}%</td>
            </tr>"""
        return out

    def recent_rows_html() -> str:
        if not recent:
            return '<tr><td colspan="6" style="color:#888;text-align:center">Aucun prono</td></tr>'
        out = ""
        for b in recent[:30]:
            colors = {"WIN": "#2ecc71", "LOSS": "#e74c3c", "PUSH": "#888", "PENDING": "#f39c12"}
            color = colors.get(b.get("status"), "#aaa")
            conf = int(b.get("confidence") or 0)
            stars = "⭐" * conf if conf else "—"
            res = b.get("result") or "—"
            out += f"""
            <tr>
                <td>{b.get('date', '')}</td>
                <td>{b.get('match', '')}</td>
                <td><code>{b.get('market', '')}</code></td>
                <td>{b.get('market_odds', '')}</td>
                <td>{stars}</td>
                <td style="color:{color};font-weight:bold">{b.get('status', '')} <span style="color:#888;font-weight:normal">({res})</span></td>
            </tr>"""
        return out

    wr_color = "#2ecc71" if stats_30["winrate_pct"] >= 60 else ("#f39c12" if stats_30["winrate_pct"] >= 50 else "#e74c3c")

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pronostiqueur — Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; }}
        .header {{ background: linear-gradient(135deg, #1a1d2e, #16213e); padding: 24px 32px; border-bottom: 1px solid #2a2d3e; }}
        .header h1 {{ font-size: 1.8rem; color: #fff; }}
        .header p {{ color: #888; margin-top: 4px; font-size: 0.9rem; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 24px 32px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #1a1d2e; border-radius: 12px; padding: 20px; border: 1px solid #2a2d3e; }}
        .card h3 {{ font-size: 0.8rem; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
        .card .value {{ font-size: 2rem; font-weight: bold; }}
        .card .sub {{ font-size: 0.85rem; color: #888; margin-top: 4px; }}
        .chart-container {{ background: #1a1d2e; border-radius: 12px; padding: 24px; border: 1px solid #2a2d3e; margin-bottom: 24px; }}
        .chart-container h2 {{ margin-bottom: 16px; font-size: 1rem; color: #ccc; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 10px 12px; font-size: 0.8rem; color: #888; text-transform: uppercase; border-bottom: 1px solid #2a2d3e; }}
        td {{ padding: 10px 12px; font-size: 0.9rem; border-bottom: 1px solid #1a1d2e; }}
        tr:hover td {{ background: #1f2235; }}
        .section {{ background: #1a1d2e; border-radius: 12px; padding: 24px; border: 1px solid #2a2d3e; margin-bottom: 24px; }}
        .section h2 {{ margin-bottom: 16px; font-size: 1rem; color: #ccc; }}
        .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
        @media (max-width: 900px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
        code {{ background: #0f1117; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; color: #74b9ff; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 Pronostiqueur — Dashboard</h1>
        <p>Mis à jour le {date.today().isoformat()}</p>
    </div>

    <div class="container">

        <div class="grid">
            <div class="card">
                <h3>Winrate 7 jours</h3>
                <div class="value">{stats_7['winrate_pct']:.0f}%</div>
                <div class="sub">{stats_7['wins']}W / {stats_7['losses']}L</div>
            </div>
            <div class="card">
                <h3>Winrate 30 jours</h3>
                <div class="value" style="color:{wr_color}">{stats_30['winrate_pct']:.0f}%</div>
                <div class="sub">{stats_30['wins']}W / {stats_30['losses']}L</div>
            </div>
            <div class="card">
                <h3>Winrate global</h3>
                <div class="value">{stats_all['winrate_pct']:.0f}%</div>
                <div class="sub">{stats_all['wins']}W / {stats_all['losses']}L  |  {stats_all['pushes']} PUSH</div>
            </div>
            <div class="card">
                <h3>Pronos en attente</h3>
                <div class="value" style="color:#f39c12">{stats_all['pending']}</div>
                <div class="sub">Total résolus : {stats_all['total']}</div>
            </div>
        </div>

        <div class="chart-container">
            <h2>📈 Évolution du winrate cumulé (30 derniers jours)</h2>
            <canvas id="winrateChart" height="80"></canvas>
        </div>

        <div class="two-col">
            <div class="section">
                <h2>🎯 Performance par marché</h2>
                <table>
                    <thead><tr><th>Marché</th><th>Total</th><th>W/L</th><th>⏳</th><th>Winrate</th></tr></thead>
                    <tbody>{market_rows_html()}</tbody>
                </table>
            </div>
            <div class="section">
                <h2>🏆 Performance par compétition</h2>
                <table>
                    <thead><tr><th>Compétition</th><th>Total</th><th>W/L</th><th>⏳</th><th>Winrate</th></tr></thead>
                    <tbody>{comp_rows_html()}</tbody>
                </table>
            </div>
        </div>

        <div class="section">
            <h2>📋 30 derniers pronos</h2>
            <table>
                <thead><tr><th>Date</th><th>Match</th><th>Marché</th><th>Cote</th><th>Confiance</th><th>Statut</th></tr></thead>
                <tbody>{recent_rows_html()}</tbody>
            </table>
        </div>

    </div>

    <script>
        const ctx = document.getElementById('winrateChart').getContext('2d');
        const labels = {chart_labels};
        const data = {chart_data};

        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: labels.length ? labels : ['—'],
                datasets: [
                    {{
                        label: 'Winrate cumulé (%)',
                        data: data.length ? data : [0],
                        borderColor: '#2ecc71',
                        backgroundColor: 'rgba(46,204,113,0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 3,
                    }},
                    {{
                        label: 'Seuil 60%',
                        data: labels.map(_ => 60),
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
                    y: {{ min: 0, max: 100, ticks: {{ color: '#888', callback: v => v + '%' }}, grid: {{ color: '#2a2d3e' }} }}
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
