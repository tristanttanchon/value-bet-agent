"""
Telegram Reporter — envoie des messages via un bot Telegram.
Utilise l'API Telegram directement (pas de lib supplémentaire).

Mode pronostiqueur : plus de bankroll, plus de mises, plus de P&L.
Juste des pronos + winrate historique.
"""

import requests
import config

# Telegram limite les messages à 4096 caractères
MAX_MSG_LENGTH = 4000


def send_message(text: str) -> bool:
    """
    Envoie un message texte (Markdown) via le bot Telegram.
    Découpe automatiquement si le texte dépasse 4000 caractères.
    Retourne True si succès, False sinon.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[Telegram] Clés manquantes dans .env (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False

    chunks = [text[i:i+MAX_MSG_LENGTH] for i in range(0, len(text), MAX_MSG_LENGTH)]
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    success = True

    for chunk in chunks:
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print("[Telegram] Message envoyé.")
            else:
                # Retry sans Markdown si erreur de parsing
                payload["parse_mode"] = ""
                resp2 = requests.post(url, json=payload, timeout=10)
                if resp2.status_code != 200:
                    print(f"[Telegram] Erreur {resp2.status_code}")
                    success = False
        except Exception as e:
            print(f"[Telegram] Erreur réseau : {e}")
            success = False

    return success


def send_pronos_report(pronos: list[dict], winrate_stats: dict | None = None, matches_count: int = 0) -> None:
    """
    Envoie le message principal du jour : pronos + winrate historique.

    pronos : liste de dicts avec au moins { match, market, market_odds, confidence,
             competition, kickoff, telegraph_url (opt) }
    winrate_stats : dict avec { total, wins, losses, pending, winrate_pct } (opt)
    matches_count : nombre total de matchs analysés (opt)
    """
    from datetime import date
    today = date.today().isoformat()

    lines = [
        f"🎯 *PRONOS DU JOUR — {today}*",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    # Historique : winrate sur résolu (pas de bankroll, pas d'€)
    if winrate_stats and winrate_stats.get("total", 0) > 0:
        wr = winrate_stats.get("winrate_pct", 0)
        w = winrate_stats.get("wins", 0)
        l = winrate_stats.get("losses", 0)
        lines.append(f"📊 Historique : *{w}W / {l}L*  |  Winrate : *{wr:.0f}%*")

    if matches_count:
        lines.append(f"🔍 {matches_count} match(s) analysé(s)")
    lines.append("")

    if pronos:
        lines.append(f"✨ *{len(pronos)} prono(s) sélectionné(s)*")
        lines.append("")
        for p in pronos:
            conf = int(p.get("confidence", 0))
            stars = "⭐" * conf if conf else "–"
            match = p.get("match", "")
            market = p.get("market", "")
            odds = p.get("market_odds", "")
            kickoff = p.get("kickoff", "")
            competition = p.get("competition", "")

            lines.append(f"✅ *{match}*")
            lines.append(f"   {competition}  ·  {kickoff}")
            lines.append(f"   Prono : `{market}`  @  *{odds}*  ·  {stars}")

            tg_url = p.get("telegraph_url")
            if tg_url:
                lines.append(f"   📖 [Analyse détaillée]({tg_url})")
            lines.append("")
    else:
        lines.append("😐 *Aucun prono fiable aujourd'hui*")
        lines.append("_Journée où aucun match n'atteint le seuil de confiance 3/5._")

    send_message("\n".join(lines).rstrip())
