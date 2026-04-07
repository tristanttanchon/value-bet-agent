"""
Stats Tracker — Statistiques de performance par compétition, marché et période.
"""

from collections import defaultdict
from datetime import date, timedelta
from modules.db import get_client


def load_all_bets(status_filter: list[str] | None = None) -> list[dict]:
    """Charge tous les paris depuis Supabase avec filtre optionnel sur le statut."""
    db = get_client()
    query = db.table("bets").select("*")
    if status_filter:
        query = query.in_("status", status_filter)
    resp = query.execute()
    return resp.data or []


def compute_stats_by(bets: list[dict], key: str) -> dict:
    """Calcule W/L/ROI/yield groupés par une clé donnée."""
    groups = defaultdict(lambda: {
        "total": 0, "wins": 0, "losses": 0,
        "staked": 0.0, "returned": 0.0, "pl": 0.0,
    })

    for bet in bets:
        if bet["status"] not in ("WIN", "LOSS"):
            continue
        g = groups[bet.get(key) or "Inconnu"]
        g["total"] += 1
        stake = float(bet["sim_stake"] or 0)
        g["staked"] = round(g["staked"] + stake, 2)

        if bet["status"] == "WIN":
            g["wins"] += 1
            returned = stake * float(bet["market_odds"] or 0)
            g["returned"] = round(g["returned"] + returned, 2)
            g["pl"] = round(g["pl"] + returned - stake, 2)
        else:
            g["losses"] += 1

    result = {}
    for name, g in groups.items():
        resolved = g["wins"] + g["losses"]
        winrate = (g["wins"] / resolved * 100) if resolved > 0 else 0
        yield_pct = (g["pl"] / g["staked"] * 100) if g["staked"] > 0 else 0
        result[name] = {
            **g,
            "winrate": round(winrate, 1),
            "yield_pct": round(yield_pct, 1),
        }

    return dict(sorted(result.items(), key=lambda x: x[1]["yield_pct"], reverse=True))


def get_full_stats() -> dict:
    """Retourne toutes les stats : global, par compétition, par marché, par période."""
    resolved_bets = load_all_bets(status_filter=["WIN", "LOSS"])

    if not resolved_bets:
        return {"total_resolved": 0}

    total = len(resolved_bets)
    wins = sum(1 for b in resolved_bets if b["status"] == "WIN")
    losses = total - wins
    staked = sum(float(b["sim_stake"] or 0) for b in resolved_bets)
    pl = sum(float(b["profit_loss"] or 0) for b in resolved_bets)
    winrate = (wins / total * 100) if total > 0 else 0
    yield_pct = (pl / staked * 100) if staked > 0 else 0

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    recent_bets = [b for b in resolved_bets if str(b["date"]) >= cutoff]
    recent_pl = sum(float(b["profit_loss"] or 0) for b in recent_bets)
    recent_staked = sum(float(b["sim_stake"] or 0) for b in recent_bets)
    recent_yield = (recent_pl / recent_staked * 100) if recent_staked > 0 else 0

    return {
        "total_resolved": total,
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 1),
        "total_staked": round(staked, 2),
        "total_pl": round(pl, 2),
        "yield_pct": round(yield_pct, 1),
        "recent_30d_yield": round(recent_yield, 1),
        "recent_30d_pl": round(recent_pl, 2),
        "by_competition": compute_stats_by(resolved_bets, "competition"),
        "by_market": compute_stats_by(resolved_bets, "market"),
    }


def format_stats_for_report(stats: dict) -> str:
    """Formate les stats pour inclusion dans le rapport texte."""
    if stats.get("total_resolved", 0) == 0:
        return "Aucune stat disponible (aucun pari résolu).\n"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "  STATISTIQUES DE PERFORMANCE",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"  Global : {stats['wins']}W / {stats['losses']}L  "
        f"| WR {stats['winrate']}%  "
        f"| Yield {stats['yield_pct']:+.1f}%  "
        f"| P&L {stats['total_pl']:+.2f}€",
        f"  30 derniers jours : Yield {stats['recent_30d_yield']:+.1f}%  "
        f"| P&L {stats['recent_30d_pl']:+.2f}€",
        "",
        "  PAR COMPÉTITION :",
    ]

    for comp, s in list(stats["by_competition"].items())[:8]:
        lines.append(
            f"    {comp:<30} {s['wins']}W/{s['losses']}L  "
            f"Yield {s['yield_pct']:+.1f}%  P&L {s['pl']:+.2f}€"
        )

    lines += ["", "  PAR MARCHÉ :"]
    for market, s in stats["by_market"].items():
        lines.append(
            f"    {market:<15} {s['wins']}W/{s['losses']}L  "
            f"Yield {s['yield_pct']:+.1f}%  P&L {s['pl']:+.2f}€"
        )

    lines.append("")
    return "\n".join(lines)
