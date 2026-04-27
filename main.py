"""
main.py — Pipeline quotidien du Pronostiqueur.

Flow :
  1. Fetcher : matchs du jour + cotes (Odds API, 23 compétitions)
  2. Enricher : données fraîches (blessés, forme, H2H) via API-Football
  3. Analyser : Gemini sélectionne 4-5 meilleurs pronos (1X2 / O/U / Double Chance)
  4. Telegraph : 1 page par prono avec analyse détaillée
  5. Telegram : message résumé avec winrate historique et liens Telegraph
  6. Fun predictor : Gemini prédit score exact + buteurs + cartons sur top 5
  7. Enregistrement Supabase (pronos sérieux uniquement) pour résolution

Usage :
  python main.py             # Analyse immédiate
  python main.py --dashboard # Ouvre le dashboard HTML
"""

import sys
import config
from modules.fetcher import get_todays_matches, format_matches_for_prompt, get_last_status
from modules.analyser import analyse_matches
from modules.data_enricher import enrich_matches
from modules.winrate_tracker import get_winrate_stats, record_pronos
from modules.telegram_reporter import send_message, send_pronos_report
from modules.fun_predictor import generate_fun_predictions


def run_analysis() -> None:
    """Lance le pipeline complet du jour."""

    print("\n🎯  PRONOSTIQUEUR — Démarrage de l'analyse...\n")

    # ── 0. Ping Telegram de démarrage ───────────────────────────────────────
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        ok = send_message("🎯 Pronostiqueur démarré — analyse en cours...")
        if not ok:
            print("[Main] ⚠️  Telegram non joignable — vérifie BOT_TOKEN et CHAT_ID")
    else:
        print("[Main] ⚠️  TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant dans les secrets")

    # ── 1. Récupération des matchs ──────────────────────────────────────────
    print("[1/5] Récupération des matchs et cotes du jour...")
    matches = get_todays_matches()

    if not matches:
        status = get_last_status()
        print(f"  → Aucun match trouvé (status={status}). Fin de l'analyse.")

        # Alerte Telegram selon la raison
        if config.TELEGRAM_BOT_TOKEN:
            if status == "keys_exhausted":
                send_message(
                    "🚨 *QUOTAS ODDS API ÉPUISÉS*\n\n"
                    "Toutes les clés The Odds API configurées sont à court de crédits.\n\n"
                    "📅 Prochain reset automatique : *1er du mois à 00h UTC*.\n\n"
                    "💡 Pour relancer plus tôt, ajoute une nouvelle clé gratuite sur "
                    "https://the-odds-api.com et colle-la dans le secret GitHub "
                    "`ODDS_API_KEY` (séparée par une virgule)."
                )
            elif status == "no_keys_configured":
                send_message(
                    "⚠️ *Configuration manquante*\n\n"
                    "Aucune clé `ODDS_API_KEY` configurée dans les secrets GitHub."
                )
            else:
                from datetime import date
                send_message(
                    f"😴 *Journée creuse — {date.today().isoformat()}*\n\n"
                    "Aucun match trouvé aujourd'hui sur les 23 compétitions suivies.\n"
                    "On se retrouve demain 🎯"
                )
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

    # ── 3. Analyse Gemini (pronos sérieux) ─────────────────────────────────
    print("\n[3/5] Analyse Gemini — sélection des 4-5 meilleurs pronos...")
    try:
        full_analysis, pronos = analyse_matches(matches_text + enriched_data)
    except Exception as e:
        print(f"  → Erreur Gemini : {e}")
        if config.TELEGRAM_BOT_TOKEN:
            send_message(f"❌ Analyse échouée : {str(e)[:200]}")
        return

    if not full_analysis:
        print("  → Erreur : aucune réponse Gemini.")
        if config.TELEGRAM_BOT_TOKEN:
            send_message("❌ Erreur analyse : Gemini n'a pas répondu. Vérifie GEMINI_API_KEY.")
        return

    print(f"  → {len(pronos)} prono(s) sélectionné(s) par Gemini.")

    # ── 4. Publication Telegraph par prono ──────────────────────────────────
    print("\n[4/5] Publication des analyses détaillées sur Telegraph...")
    if pronos and config.TELEGRAM_BOT_TOKEN:
        try:
            from modules.telegraph import publish_analysis
            published = 0
            for p in pronos:
                analysis_text = (p.get("analysis") or "").strip()
                if not analysis_text:
                    continue
                title = f"{p.get('match', 'Match')} — {p.get('market', '')}"
                conf = int(p.get("confidence", 0)) if p.get("confidence") else 0
                header = {
                    "Compétition": p.get("competition", "—"),
                    "Coup d'envoi": p.get("kickoff", "—"),
                    "Marché": p.get("market", "—"),
                    "Cote marché": p.get("market_odds", "—"),
                    "Confiance": f"{conf}/5" if conf else "—",
                }
                url = publish_analysis(title, analysis_text, header)
                if url:
                    p["telegraph_url"] = url
                    published += 1
                    print(f"  ✓ {title} → {url}")
            print(f"  → {published}/{len(pronos)} analyse(s) publiée(s).")
        except Exception as e:
            print(f"  → Telegraph publishing failed : {e}")

    # ── 5. Enregistrement Supabase + envoi Telegram ─────────────────────────
    print("\n[5/5] Enregistrement + envoi Telegram...")

    if pronos:
        record_pronos(pronos)

    winrate = get_winrate_stats(days=30)  # winrate sur les 30 derniers jours
    print(
        f"  → Historique 30j : {winrate['wins']}W / {winrate['losses']}L "
        f"(winrate {winrate['winrate_pct']:.0f}%)  |  {winrate['pending']} en attente"
    )

    if config.TELEGRAM_BOT_TOKEN:
        send_pronos_report(pronos, winrate_stats=winrate, matches_count=len(matches))

    # ── 6. Bonus : pronos FUN (score exact, buteurs, 1er buteur) ───────────
    print("\n[Bonus] Génération des pronos fun...")
    try:
        fun_message, fun_predictions = generate_fun_predictions(matches)
        if fun_message and config.TELEGRAM_BOT_TOKEN:
            send_message(fun_message)
            print("  → Message fun envoyé sur Telegram.")
        elif not fun_message:
            print("  → Génération fun échouée (non bloquant).")

        # Persistance Supabase pour résolution le lendemain
        if fun_predictions:
            try:
                from modules.fun_tracker import save_fun_predictions
                save_fun_predictions(fun_predictions)
            except Exception as e:
                print(f"  → Sauvegarde fun KO (non bloquant) : {e}")
    except Exception as e:
        print(f"  → Erreur pronos fun (non bloquant) : {e}")

    print("\n✅  Analyse terminée.\n")


def run_stats() -> None:
    """Affiche le winrate dans le terminal."""
    stats_7j = get_winrate_stats(days=7)
    stats_30j = get_winrate_stats(days=30)
    stats_all = get_winrate_stats()

    print("\n📊  STATISTIQUES PRONOSTIQUEUR\n")
    print(f"  7 derniers jours  : {stats_7j['wins']}W / {stats_7j['losses']}L  |  Winrate : {stats_7j['winrate_pct']:.1f}%")
    print(f"  30 derniers jours : {stats_30j['wins']}W / {stats_30j['losses']}L  |  Winrate : {stats_30j['winrate_pct']:.1f}%")
    print(f"  Toutes périodes   : {stats_all['wins']}W / {stats_all['losses']}L  |  Winrate : {stats_all['winrate_pct']:.1f}%")
    print(f"\n  Pronos en attente : {stats_all['pending']}")


if __name__ == "__main__":
    if "--dashboard" in sys.argv:
        from dashboard import open_dashboard
        open_dashboard()
    elif "--stats" in sys.argv:
        run_stats()
    else:
        run_analysis()
