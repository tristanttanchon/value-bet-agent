"""
prematch_alert.py — Alerte Telegram 1h avant chaque match avec un pari en attente.
Appelé toutes les heures par GitHub Actions.
"""

from datetime import datetime, timezone, timedelta
import config
from modules.db import get_client
from modules.telegram_reporter import send_message


def run_prematch_alert() -> None:
    db = get_client()
    resp = db.table("bets").select("*").eq("status", "PENDING").execute()
    pending = resp.data or []

    if not pending:
        print("[PreMatch] Aucun pari en attente.")
        return

    now = datetime.now(timezone.utc)
    alerts = []

    for bet in pending:
        kickoff_str = bet.get("kickoff", "")
        if not kickoff_str:
            continue
        try:
            # Format HH:MM → on assume aujourd'hui
            if len(kickoff_str) == 5 and ":" in kickoff_str:
                today = now.date()
                kickoff = datetime.combine(
                    today,
                    datetime.strptime(kickoff_str, "%H:%M").time(),
                    tzinfo=timezone.utc
                )
            else:
                # Format ISO complet
                kickoff = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))

            diff = (kickoff - now).total_seconds() / 60  # en minutes

            # Alerte si entre 50 et 70 minutes avant le match
            if 50 <= diff <= 70:
                alerts.append((bet, kickoff))

        except Exception:
            continue

    if not alerts:
        print(f"[PreMatch] Aucun match dans 1h.")
        return

    for bet, kickoff in alerts:
        send_message(
            f"⏰ *MATCH DANS 1H*\n\n"
            f"⚽ *{bet['match']}*\n"
            f"Coup d'envoi : *{kickoff.strftime('%H:%M')} UTC*\n\n"
            f"🎯 Ton pari : `{bet['market']}` @ `{bet['market_odds']}`\n"
            f"💶 Mise simulée : `{float(bet['sim_stake'] or 0):.2f}€`\n"
            f"📈 Edge : {bet['edge']}"
        )
        print(f"[PreMatch] Alerte envoyée pour {bet['match']}")


if __name__ == "__main__":
    run_prematch_alert()
