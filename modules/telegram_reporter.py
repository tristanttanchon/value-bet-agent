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


def send_full_report(full_analysis: str, bets: list[dict], bankroll: dict, matches_count: int = 0) -> None:
    """
    Envoie un résumé clair de la journée sur Telegram (pas de pavé brut).
    Un seul message concis : bankroll + paris recommandés (ou "aucun").
    Le rapport détaillé reste sauvegardé dans data/reports/ pour consultation.
    """
    from datetime import date
    today = date.today().isoformat()
    pl = bankroll["current"] - bankroll["initial"]
    roi = (pl / bankroll["initial"] * 100) if bankroll["initial"] else 0

    lines = [
        f"⚽ *VALUE BET — {today}*",
        f"━━━━━━━━━━━━━━━━━━━",
        f"💰 Bankroll : *{bankroll['current']:.2f}€*  ({pl:+.2f}€ · ROI {roi:+.1f}%)",
    ]
    if matches_count:
        lines.append(f"📊 {matches_count} match(s) analysé(s)")
    lines.append("")  # ligne vide

    if bets:
        lines.append(f"🎯 *{len(bets)} pari(s) recommandé(s)*")
        lines.append("")
        for b in bets:
            edge_pct = float(b.get("edge", 0)) * 100
            conf = int(b.get("confidence", 0))
            stars = "⭐" * conf if conf else "–"
            match = b.get("match", "")
            market = b.get("market", "")
            odds = b.get("market_odds", "")
            stake = float(b.get("sim_stake", 0))
            lines.append(f"✅ *{match}*")
            lines.append(f"   `{market}` @ *{odds}*  ·  edge *{edge_pct:.1f}%*  ·  {stars}")
            lines.append(f"   Mise : {stake:.2f}€")
            lines.append("")
    else:
        lines.append("❌ *Aucun pari recommandé*")
        lines.append("_Marché efficient — on passe notre tour_ 🧘")

    send_message("\n".join(lines).rstrip())


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
