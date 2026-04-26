"""
telegram_bot.py — Bot Telegram avec commandes interactives.

Mode pronostiqueur : pas de bankroll, pas de €.
Commandes : /stats, /bets, /help.

Appelé via GitHub Actions (polling court, pas de serveur permanent).
"""

import requests
import time
import config
from modules.db import get_client
from modules.winrate_tracker import get_winrate_stats


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


def cmd_stats(chat_id: int) -> None:
    s7 = get_winrate_stats(days=7)
    s30 = get_winrate_stats(days=30)
    s_all = get_winrate_stats()

    if s_all.get("total", 0) == 0 and s_all.get("pending", 0) == 0:
        reply(chat_id, "📊 Aucun prono enregistré pour le moment.")
        return

    lines = [
        "📊 *STATISTIQUES PRONOSTIQUEUR*",
        "",
        f"*7 derniers jours*  : {s7['wins']}W / {s7['losses']}L  →  *{s7['winrate_pct']:.0f}%*",
        f"*30 derniers jours* : {s30['wins']}W / {s30['losses']}L  →  *{s30['winrate_pct']:.0f}%*",
        f"*Toutes périodes*   : {s_all['wins']}W / {s_all['losses']}L  →  *{s_all['winrate_pct']:.0f}%*",
    ]
    if s_all.get("pushes"):
        lines.append(f"_PUSH : {s_all['pushes']}_")
    lines.append("")
    lines.append(f"⏳ En attente : *{s_all['pending']}* prono(s)")

    reply(chat_id, "\n".join(lines))


def cmd_bets(chat_id: int) -> None:
    db = get_client()
    try:
        resp = (
            db.table("bets")
            .select("*")
            .eq("status", "PENDING")
            .order("date", desc=True)
            .execute()
        )
        pending = resp.data or []
    except Exception as e:
        reply(chat_id, f"❌ Erreur Supabase : {e}")
        return

    if not pending:
        reply(chat_id, "⏳ Aucun prono en attente actuellement.")
        return

    lines = [f"⏳ *PRONOS EN ATTENTE ({len(pending)})*", ""]
    for b in pending:
        conf = int(b.get("confidence") or 0)
        stars = "⭐" * conf if conf else ""
        lines.append(
            f"• *{b.get('match', '')}*\n"
            f"  Marché : `{b.get('market', '')}`  @  *{b.get('market_odds', '')}*  {stars}\n"
            f"  Date : {b.get('date', '')}  ·  {b.get('competition', '—')}\n"
        )
    reply(chat_id, "\n".join(lines))


def cmd_help(chat_id: int) -> None:
    reply(chat_id, (
        "🎯 *Pronostiqueur — Commandes*\n\n"
        "/stats — Winrate (7j / 30j / global)\n"
        "/bets — Pronos en attente de résolution\n"
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

    if text.startswith("/stats"):
        cmd_stats(chat_id)
    elif text.startswith("/bets"):
        cmd_bets(chat_id)
    elif text.startswith("/help") or text.startswith("/start"):
        cmd_help(chat_id)
    elif text.startswith("/bankroll"):
        # Commande legacy — explique le pivot
        reply(chat_id, "ℹ️ Le mode bankroll a été retiré. Utilise /stats pour voir le winrate.")
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
