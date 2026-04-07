"""
telegram_bot.py — Bot Telegram avec commandes interactives.
Écoute les messages entrants et répond aux commandes /stats, /bankroll, /bets.

Appelé via GitHub Actions (polling court, pas de serveur permanent).
"""

import requests
import time
import config
from modules.simulation import load_bankroll
from modules.stats_tracker import get_full_stats
from modules.db import get_client


BASE_URL = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def get_updates(offset: int = 0) -> list[dict]:
    try:
        resp = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 30},
            timeout=35,
        )
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except Exception as e:
        print(f"[Bot] Erreur getUpdates : {e}")
    return []


def reply(chat_id: int, text: str) -> None:
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[Bot] Erreur reply : {e}")


def cmd_bankroll(chat_id: int) -> None:
    b = load_bankroll()
    pl = b["current"] - b["initial"]
    roi = (pl / b["initial"] * 100) if b["initial"] else 0
    reply(chat_id, (
        f"💰 *BANKROLL*\n\n"
        f"Actuelle : *{b['current']:.2f}€*\n"
        f"Initiale : {b['initial']:.2f}€\n"
        f"P&L : *{pl:+.2f}€*  (ROI {roi:+.1f}%)\n"
        f"En attente : {b['pending']} pari(s)\n"
        f"Total joués : {b['total_bets']}  ({b['wins']}W / {b['losses']}L)"
    ))


def cmd_stats(chat_id: int) -> None:
    s = get_full_stats()
    if s.get("total_resolved", 0) == 0:
        reply(chat_id, "📊 Aucune stat disponible (aucun pari résolu encore).")
        return

    lines = [
        "📊 *STATISTIQUES*\n",
        f"Paris résolus : {s['total_resolved']}  ({s['wins']}W / {s['losses']}L)",
        f"Win rate : *{s['winrate']}%*",
        f"Yield global : *{s['yield_pct']:+.1f}%*",
        f"P&L total : *{s['total_pl']:+.2f}€*",
        f"Yield 30j : {s['recent_30d_yield']:+.1f}%  |  P&L 30j : {s['recent_30d_pl']:+.2f}€",
        "",
        "🏆 *Top compétitions :*",
    ]
    for comp, data in list(s.get("by_competition", {}).items())[:5]:
        lines.append(f"  {comp} — {data['yield_pct']:+.1f}%  ({data['wins']}W/{data['losses']}L)")

    lines += ["", "🎯 *Par marché :*"]
    for market, data in s.get("by_market", {}).items():
        lines.append(f"  {market} — {data['yield_pct']:+.1f}%  ({data['wins']}W/{data['losses']}L)")

    reply(chat_id, "\n".join(lines))


def cmd_bets(chat_id: int) -> None:
    db = get_client()
    resp = db.table("bets").select("*").eq("status", "PENDING").order("date", desc=True).execute()
    pending = resp.data or []

    if not pending:
        reply(chat_id, "⏳ Aucun pari en attente actuellement.")
        return

    lines = [f"⏳ *PARIS EN ATTENTE ({len(pending)})*\n"]
    for b in pending:
        lines.append(
            f"• *{b['match']}*\n"
            f"  Marché : `{b['market']}`  Cote : `{b['market_odds']}`\n"
            f"  Mise : `{float(b['sim_stake'] or 0):.2f}€`  Edge : {b['edge']}\n"
            f"  Date : {b['date']}\n"
        )
    reply(chat_id, "\n".join(lines))


def cmd_help(chat_id: int) -> None:
    reply(chat_id, (
        "⚽ *Value Bet Agent — Commandes*\n\n"
        "/bankroll — Solde et P&L actuel\n"
        "/stats — Statistiques de performance\n"
        "/bets — Paris en attente\n"
        "/help — Cette aide"
    ))


def handle_update(update: dict) -> None:
    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "").strip().lower()

    if not chat_id or not text:
        return

    # Sécurité : n'accepte que les messages de ton chat
    if str(chat_id) != str(config.TELEGRAM_CHAT_ID):
        reply(chat_id, "Accès non autorisé.")
        return

    if text.startswith("/bankroll"):
        cmd_bankroll(chat_id)
    elif text.startswith("/stats"):
        cmd_stats(chat_id)
    elif text.startswith("/bets"):
        cmd_bets(chat_id)
    elif text.startswith("/help") or text.startswith("/start"):
        cmd_help(chat_id)
    else:
        reply(chat_id, "Commande inconnue. Tape /help pour voir les commandes disponibles.")


def run_bot(duration_seconds: int = 55) -> None:
    """
    Polling pendant `duration_seconds` secondes.
    Conçu pour tourner dans un GitHub Actions (max 1 min).
    """
    print(f"[Bot] Démarrage du polling ({duration_seconds}s)...")
    offset = 0
    start = time.time()

    while time.time() - start < duration_seconds:
        updates = get_updates(offset)
        for update in updates:
            handle_update(update)
            offset = update["update_id"] + 1
        time.sleep(2)

    print("[Bot] Polling terminé.")


if __name__ == "__main__":
    run_bot()
