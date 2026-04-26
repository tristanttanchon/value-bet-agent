"""
weekly_report.py — Rapport hebdomadaire (mode pronostiqueur).

Pas de bankroll, pas de ROI, pas d'€. Juste des compteurs WIN/LOSS et
un winrate, plus le détail des pronos de la semaine.
"""

from datetime import date, timedelta
from modules.telegram_reporter import send_message
from modules.db import get_client


def get_week_range() -> tuple[str, str]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def load_week_bets(date_from: str, date_to: str) -> list[dict]:
    """Charge les pronos de la semaine depuis Supabase."""
    db = get_client()
    resp = db.table("bets").select("*").gte("date", date_from).lte("date", date_to).execute()
    return resp.data or []


def compute_week_stats(bets: list[dict]) -> dict:
    total = len(bets)
    wins = sum(1 for b in bets if b.get("status") == "WIN")
    losses = sum(1 for b in bets if b.get("status") == "LOSS")
    pushes = sum(1 for b in bets if b.get("status") == "PUSH")
    pending = sum(1 for b in bets if b.get("status") == "PENDING")

    decisive = wins + losses  # PUSH exclu
    winrate = (wins / decisive * 100) if decisive > 0 else 0.0

    # Compteurs par marché (1, X, 2, Over 2.5, etc.)
    by_market: dict[str, dict] = {}
    for b in bets:
        m = b.get("market") or "—"
        slot = by_market.setdefault(m, {"W": 0, "L": 0, "P": 0, "Pend": 0})
        st = b.get("status")
        if st == "WIN":
            slot["W"] += 1
        elif st == "LOSS":
            slot["L"] += 1
        elif st == "PUSH":
            slot["P"] += 1
        elif st == "PENDING":
            slot["Pend"] += 1

    # Confiance moyenne sur les résolus
    resolved_with_conf = [int(b["confidence"]) for b in bets
                          if b.get("confidence") and b.get("status") in ("WIN", "LOSS", "PUSH")]
    avg_conf = (sum(resolved_with_conf) / len(resolved_with_conf)) if resolved_with_conf else 0.0

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "winrate": winrate,
        "by_market": by_market,
        "avg_conf": avg_conf,
    }


def build_report_message(stats: dict, bets: list[dict], date_from: str, date_to: str) -> str:
    lines = [
        f"📊 *RAPPORT HEBDOMADAIRE*",
        f"_{date_from} → {date_to}_",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "*BILAN DE LA SEMAINE*",
        "",
        f"Pronos joués : *{stats['total']}*",
        f"✅ Victoires : *{stats['wins']}*",
        f"❌ Défaites  : *{stats['losses']}*",
    ]
    if stats["pushes"]:
        lines.append(f"↩️ Push       : *{stats['pushes']}*")
    if stats["pending"]:
        lines.append(f"⏳ En attente : *{stats['pending']}*")

    lines.append("")
    lines.append(f"🎯 Winrate : *{stats['winrate']:.1f}%*")
    if stats["avg_conf"]:
        lines.append(f"⭐ Confiance moyenne : *{stats['avg_conf']:.1f}/5*")

    if stats["by_market"]:
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "*PAR MARCHÉ*",
            "",
        ]
        for market, c in sorted(stats["by_market"].items()):
            decisive = c["W"] + c["L"]
            wr = (c["W"] / decisive * 100) if decisive > 0 else 0
            extras = []
            if c["P"]:
                extras.append(f"{c['P']}P")
            if c["Pend"]:
                extras.append(f"{c['Pend']}⏳")
            extras_s = f"  ({', '.join(extras)})" if extras else ""
            lines.append(f"`{market:<10}` {c['W']}W / {c['L']}L → *{wr:.0f}%*{extras_s}")

    if bets:
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "*DÉTAIL DES PRONOS*",
            "",
        ]
        emoji_map = {"WIN": "✅", "LOSS": "❌", "PUSH": "↩️", "PENDING": "⏳"}
        for b in bets:
            e = emoji_map.get(b.get("status"), "❓")
            res = b.get("result") or ""
            res_s = f" ({res})" if res else ""
            lines.append(
                f"{e} {b.get('match', '')} — `{b.get('market', '')}` @ {b.get('market_odds', '')}{res_s}"
            )

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "_Rapport généré automatiquement par Pronostiqueur_",
    ]

    return "\n".join(lines)


def run_weekly_report() -> None:
    print("\n📊 Génération du rapport hebdomadaire...")

    date_from, date_to = get_week_range()
    bets = load_week_bets(date_from, date_to)
    stats = compute_week_stats(bets)

    if stats["total"] == 0:
        message = (
            f"📊 *RAPPORT HEBDOMADAIRE*\n"
            f"_{date_from} → {date_to}_\n\n"
            f"😴 Aucun prono enregistré cette semaine."
        )
    else:
        message = build_report_message(stats, bets, date_from, date_to)

    send_message(message)
    print("Rapport hebdomadaire envoyé sur Telegram.")


if __name__ == "__main__":
    run_weekly_report()
