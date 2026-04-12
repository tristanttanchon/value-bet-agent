"""
main.py — Orchestrateur principal.
Lance une analyse complète : fetch → enrich → analyse → décision → simulation → rapport.

Usage :
  python main.py             # Analyse immédiate
  python main.py --resolve   # Mode résolution de paris (interactif)
  python main.py --dashboard # Ouvre le dashboard HTML
  python main.py --stats     # Affiche les stats de performance
"""

import sys
import config
from modules.fetcher import get_todays_matches, format_matches_for_prompt
from modules.analyser import analyse_matches
from modules.decision_engine import filter_and_size_bets
from modules.simulation import load_bankroll, record_bets, resolve_bet
from modules.reporter import generate_report, print_summary
from modules.data_enricher import enrich_matches
from modules.clv_tracker import record_opening_odds
from modules.bankroll_guard import is_betting_suspended, get_kelly_fraction, check_and_alert, get_status_line
from modules.stats_tracker import get_full_stats, format_stats_for_report
from modules.correlation_filter import filter_correlated_bets
from modules.telegram_reporter import send_daily_alert, send_full_report


def run_analysis() -> None:
    """Lance l'analyse complète du jour."""

    print("\n⚽  VALUE BET AGENT — Démarrage de l'analyse...\n")

    # ── 0. Test Telegram + Vérification bankroll guard ──────────────────────
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        from modules.telegram_reporter import send_message
        ok = send_message("⚽ Analyse Value Bet démarrée...")
        if not ok:
            print("[Main] ⚠️  Telegram non joignable — vérifiez BOT_TOKEN et CHAT_ID")
    else:
        print("[Main] ⚠️  TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant dans les secrets")

    bankroll = load_bankroll()
    alert_msg = check_and_alert(bankroll)
    if alert_msg and config.TELEGRAM_BOT_TOKEN:
        from modules.telegram_reporter import send_message
        send_message(alert_msg)

    if is_betting_suspended(bankroll):
        print("🚨 STOP LOSS DÉCLENCHÉ — Paris suspendus. Analyse annulée.")
        print(f"   {get_status_line(bankroll)}")
        return

    print(f"   {get_status_line(bankroll)}\n")

    # ── 0b. État de l'apprentissage ────────────────────────────────────────
    try:
        from modules.learning import print_learning_status
        print_learning_status()
    except Exception as e:
        print(f"[Main] Apprentissage indisponible : {e}")

    # ── 1. Récupération des matchs ──────────────────────────────────────────
    print("[1/5] Récupération des matchs et cotes du jour...")
    matches = get_todays_matches()

    if not matches:
        print("  → Aucun match trouvé aujourd'hui. Fin de l'analyse.")
        return

    print(f"  → {len(matches)} match(s) trouvé(s)")
    matches_text = format_matches_for_prompt(matches)

    # ── 2. Enrichissement via API-Football ─────────────────────────────────
    enriched_data = ""
    if config.API_FOOTBALL_KEY:
        print("\n[2/5] Enrichissement des données (API-Football)...")
        enriched_data = enrich_matches(matches)
        print("  → Données fraîches injectées (blessés, forme, H2H, stats)")
    else:
        print("\n[2/5] API-Football non configurée — enrichissement ignoré.")

    # ── 3. Analyse Gemini ───────────────────────────────────────────────────
    print("\n[3/5] Analyse en cours (Gemini 2.0 Flash + Google Search)...")
    full_analysis, raw_bets = analyse_matches(matches_text + enriched_data)

    if not full_analysis:
        print("  → Erreur : aucune réponse. Vérifiez votre clé GEMINI_API_KEY.")
        if config.TELEGRAM_BOT_TOKEN:
            from modules.telegram_reporter import send_message
            send_message("❌ Erreur analyse : Gemini n'a pas répondu. Vérifiez GEMINI_API_KEY.")
        return

    print(f"  → Analyse reçue. {len(raw_bets)} pari(s) brut(s) identifié(s).")

    # ── 4. Filtre, sizing Kelly + anti-corrélation ──────────────────────────
    print("\n[4/5] Filtrage, Kelly et anti-corrélation...")
    kelly_fraction = get_kelly_fraction(bankroll)
    valid_bets = filter_and_size_bets(raw_bets, bankroll["current"], kelly_override=kelly_fraction)
    print(f"  → {len(valid_bets)} pari(s) après filtre edge (≥5%)")

    valid_bets = filter_correlated_bets(valid_bets, bankroll["current"])
    print(f"  → {len(valid_bets)} pari(s) après filtre anti-corrélation")

    # ── 5. Simulation, CLV, rapport ─────────────────────────────────────────
    print("\n[5/5] Enregistrement simulation + CLV + rapport...")

    if valid_bets:
        bankroll = record_bets(valid_bets)
        record_opening_odds(valid_bets)

    stats = get_full_stats()
    stats_text = format_stats_for_report(stats)
    report_path = generate_report(full_analysis + "\n\n" + stats_text, valid_bets, bankroll)

    # Envoi résumé clair sur Telegram (pas le pavé brut)
    if config.TELEGRAM_BOT_TOKEN:
        send_full_report(full_analysis, valid_bets, bankroll, matches_count=len(matches))

    print_summary(valid_bets, bankroll)
    print(f"\n  Rapport : {report_path}")
    print(f"  Dashboard : python dashboard.py\n")


def run_resolve() -> None:
    """Mode interactif pour résoudre des paris en attente."""
    print("\n📋  MODE RÉSOLUTION DE PARIS\n")
    match = input("  Nom du match (ou partie du nom) : ").strip()
    market = input("  Marché (ex: 1, Over 2.5, BTTS) : ").strip()
    result = input("  Résultat (w = gagné / l = perdu) : ").strip().lower()

    if result not in ("w", "l"):
        print("  Réponse invalide. Utilisez 'w' ou 'l'.")
        return

    msg = resolve_bet(match, market, won=(result == "w"))
    print(f"\n  → {msg}\n")

    bankroll = load_bankroll()
    pl = bankroll["current"] - bankroll["initial"]
    roi = (pl / bankroll["initial"]) * 100
    print(f"  Bankroll : {bankroll['current']:.2f}€  ({pl:+.2f} / ROI {roi:+.1f}%)\n")


def run_stats() -> None:
    """Affiche les statistiques de performance dans le terminal."""
    from modules.stats_tracker import get_full_stats, format_stats_for_report
    from modules.clv_tracker import get_clv_summary
    stats = get_full_stats()
    clv = get_clv_summary()
    print(format_stats_for_report(stats))
    if clv.get("total", 0) > 0:
        print(f"  CLV moyen : {clv['avg_clv']:+.1f}%  |  "
              f"Bat la closing line : {clv['beat_closing_line_pct']:.0f}%  |  "
              f"Qualité modèle : {clv['model_quality']}")


if __name__ == "__main__":
    if "--resolve" in sys.argv:
        run_resolve()
    elif "--dashboard" in sys.argv:
        from dashboard import open_dashboard
        open_dashboard()
    elif "--stats" in sys.argv:
        run_stats()
    else:
        run_analysis()
