"""
Telegram Reporter — envoie des messages via un bot Telegram.
Utilise l'API Telegram directement (pas de lib supplémentaire).
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

    # Découpe en morceaux si trop long
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


def send_full_report(full_analysis: str, bets: list[dict], bankroll: dict) -> None:
    """
    Envoie le rapport complet de la journée sur Telegram.
    1. Résumé bankroll + paris recommandés
    2. Rapport d'analyse complet (découpé si nécessaire)
    """
    from datetime import date
    today = date.today().isoformat()
    pl = bankroll["current"] - bankroll["initial"]
    roi = (pl / bankroll["initial"] * 100) if bankroll["initial"] else 0

    # ── Message 1 : Résumé ──────────────────────────────────────────────────
    lines = [
        f"⚽ *ANALYSE VALUE BET — {today}*\n",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"💰 *Bankroll : {bankroll['current']:.2f}€*  ({pl:+.2f}€  ROI {roi:+.1f}%)\n",
    ]

    if bets:
        lines.append(f"🎯 *{len(bets)} PARI(S) RECOMMANDÉ(S) :*\n")
        for b in bets:
            edge_pct = float(b.get("edge", 0)) * 100
            stars = "⭐" * int(b.get("confidence", 0))
            lines.append(
                f"✅ *{b.get('match', '')}*\n"
                f"  📌 Marché : `{b.get('market', '')}`  |  Cote : `{b.get('market_odds', '')}`\n"
                f"  📈 Edge : `{edge_pct:.1f}%`  |  Confiance : {stars}\n"
                f"  💶 Mise simulée : `{float(b.get('sim_stake', 0)):.2f}€`\n"
            )
    else:
        lines.append("❌ *Aucun pari recommandé aujourd'hui*\n")
        lines.append("_Le marché est bien pricé — patience est une vertu_ 🧘")

    send_message("\n".join(lines))

    # ── Message 2 : Analyse complète ────────────────────────────────────────
    if full_analysis:
        send_message(f"📋 *RAPPORT DÉTAILLÉ — {today}*\n\n{full_analysis}")


def send_daily_alert(bets: list[dict], bankroll: dict) -> None:
    """Alerte rapide si des paris sont trouvés — utilisée en cours d'analyse."""
    if not bets:
        return

    lines = [f"⚽ *VALUE BETS DU JOUR — {len(bets)} pari(s)*\n"]
    for b in bets:
        edge_pct = float(b.get("edge", 0)) * 100
        stars = "⭐" * int(b.get("confidence", 0))
        lines.append(
            f"• *{b.get('match', '')}*\n"
            f"  Marché : {b.get('market', '')}  |  Cote : {b.get('market_odds', '')}\n"
            f"  Edge : {edge_pct:.1f}%  |  Confiance : {stars}\n"
            f"  Mise simulée : {float(b.get('sim_stake', 0)):.2f}€\n"
        )

    pl = bankroll["current"] - bankroll["initial"]
    lines.append(f"\n💰 *Bankroll : {bankroll['current']:.2f}€*  ({pl:+.2f}€ depuis le début)")
    send_message("\n".join(lines))
