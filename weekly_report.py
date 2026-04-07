"""
weekly_report.py — Génère et envoie le rapport hebdomadaire via Telegram.
"""

from datetime import date, timedelta
from modules.telegram_reporter import send_message
from modules.simulation import load_bankroll
from modules.db import get_client


def get_week_range() -> tuple[str, str]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def load_week_bets(date_from: str, date_to: str) -> list[dict]:
    """Charge les paris de la semaine depuis Supabase."""
    db = get_client()
    resp = db.table("bets").select("*").gte("date", date_from).lte("date", date_to).execute()
    return resp.data or []


def compute_week_stats(bets: list[dict]) -> dict:
    total = len(bets)
    wins = sum(1 for b in bets if b["status"] == "WIN")
    losses = sum(1 for b in bets if b["status"] == "LOSS")
    pending = sum(1 for b in bets if b["status"] == "PENDING")

    total_staked = sum(float(b["sim_stake"] or 0) for b in bets)
    total_pl = sum(float(b["profit_loss"] or 0) for b in bets if b["profit_loss"] is not None)

    winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    yield_pct = (total_pl / total_staked * 100) if total_staked > 0 else 0

    best_bet = None
    best_pl = 0
    for b in bets:
        if b["profit_loss"] is not None and float(b["profit_loss"]) > best_pl:
            best_pl = float(b["profit_loss"])
            best_bet = b

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "total_staked": total_staked,
        "total_pl": total_pl,
        "winrate": winrate,
        "yield_pct": yield_pct,
        "best_bet": best_bet,
    }


def build_report_message(stats: dict, bets: list[dict], bankroll: dict, date_from: str, date_to: str) -> str:
    pl_emoji = "📈" if stats["total_pl"] >= 0 else "📉"
    pl_total = bankroll["current"] - bankroll["initial"]
    roi_total = (pl_total / bankroll["initial"] * 100) if bankroll["initial"] else 0

    lines = [
        f"*RAPPORT HEBDOMADAIRE*",
        f"_{date_from} → {date_to}_\n",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"*RÉSULTATS DE LA SEMAINE*\n",
        f"Paris joués : {stats['total']}",
        f"Victoires : {stats['wins']}",
        f"Défaites : {stats['losses']}",
        f"En attente : {stats['pending']}",
        f"Taux de réussite : {stats['winrate']:.1f}%\n",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"*PERFORMANCE FINANCIÈRE*\n",
        f"Total misé : {stats['total_staked']:.2f}€",
        f"{pl_emoji} P&L semaine : {stats['total_pl']:+.2f}€",
        f"Yield semaine : {stats['yield_pct']:+.1f}%\n",
    ]

    if stats["best_bet"]:
        b = stats["best_bet"]
        lines += [
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"*MEILLEUR PARI DE LA SEMAINE*\n",
            f"Match : {b['match']}",
            f"Marché : {b['market']}  |  Cote : {b['market_odds']}",
            f"Gain : +{float(b['profit_loss']):.2f}€\n",
        ]

    if bets:
        lines += [
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"*DÉTAIL DES PARIS*\n",
        ]
        for b in bets:
            status_emoji = {"WIN": "✅", "LOSS": "❌", "PENDING": "⏳"}.get(b["status"], "❓")
            pl = f"{float(b['profit_loss']):+.2f}€" if b["profit_loss"] is not None else "en attente"
            lines.append(f"{status_emoji} {b['match']} [{b['market']}] @ {b['market_odds']} → {pl}")

    lines += [
        f"\n━━━━━━━━━━━━━━━━━━━━━",
        f"*BANKROLL GLOBAL*\n",
        f"Départ : {bankroll['initial']:.2f}€",
        f"Actuel : {bankroll['current']:.2f}€",
        f"ROI global : {roi_total:+.1f}%",
        f"Paris total : {bankroll['total_bets']}  |  {bankroll['wins']}W  {bankroll['losses']}L",
        f"\n_Rapport généré automatiquement par Value Bet Agent_",
    ]

    return "\n".join(lines)


def run_weekly_report() -> None:
    print("\n Génération du rapport hebdomadaire...")

    date_from, date_to = get_week_range()
    bets = load_week_bets(date_from, date_to)
    bankroll = load_bankroll()
    stats = compute_week_stats(bets)

    if stats["total"] == 0:
        message = (
            f"*RAPPORT HEBDOMADAIRE*\n"
            f"_{date_from} → {date_to}_\n\n"
            f"Aucun pari enregistré cette semaine.\n"
            f"Bankroll : {bankroll['current']:.2f}€"
        )
    else:
        message = build_report_message(stats, bets, bankroll, date_from, date_to)

    send_message(message)
    print("Rapport hebdomadaire envoyé sur Telegram.")


if __name__ == "__main__":
    run_weekly_report()
