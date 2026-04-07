"""
Reporter — génère le rapport texte quotidien et affiche le résumé terminal.
"""

from datetime import date
import config


def _pl_color(value: float) -> str:
    """Préfixe + ou − pour l'affichage."""
    return f"+{value:.2f}" if value >= 0 else f"{value:.2f}"


def generate_report(
    full_analysis: str,
    bets: list[dict],
    bankroll: dict,
) -> str:
    """
    Sauvegarde le rapport complet en .txt dans data/reports/.
    Retourne le chemin du fichier créé.
    """
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    report_path = config.REPORTS_DIR / f"report_{today}.txt"

    pl = bankroll["current"] - bankroll["initial"]
    roi = (pl / bankroll["initial"]) * 100 if bankroll["initial"] else 0

    with open(report_path, "w", encoding="utf-8") as f:

        # En-tête
        f.write("=" * 65 + "\n")
        f.write(f"  RAPPORT VALUE BET — {today}\n")
        f.write("=" * 65 + "\n\n")

        # Analyse Claude
        f.write(full_analysis)

        # Séparateur simulation
        f.write("\n\n" + "=" * 65 + "\n")
        f.write("  SIMULATION BANKROLL\n")
        f.write("=" * 65 + "\n\n")
        f.write(f"  Bankroll initiale    : {bankroll['initial']:.2f} EUR\n")
        f.write(f"  Bankroll actuelle    : {bankroll['current']:.2f} EUR\n")
        f.write(f"  Réservé (en attente) : {bankroll.get('reserved', 0):.2f} EUR\n")
        f.write(f"  P&L total            : {_pl_color(pl)} EUR  ({roi:+.1f}%)\n\n")
        f.write(f"  Paris totaux    : {bankroll['total_bets']}\n")
        f.write(f"  En attente      : {bankroll['pending']}\n")
        f.write(f"  Victoires       : {bankroll['wins']}\n")
        f.write(f"  Défaites        : {bankroll['losses']}\n")

        total_staked = bankroll.get("total_staked", 0)
        total_returned = bankroll.get("total_returned", 0)
        if total_staked > 0:
            yield_pct = ((total_returned - total_staked) / total_staked) * 100
            f.write(f"  Yield           : {yield_pct:+.1f}%\n")

        # Paris du jour
        if bets:
            f.write("\n" + "=" * 65 + "\n")
            f.write("  PARIS ENREGISTRES AUJOURD'HUI\n")
            f.write("=" * 65 + "\n\n")
            for b in bets:
                edge_pct = float(b.get("edge", 0)) * 100
                f.write(
                    f"  {b.get('match', '')}  —  {b.get('market', '')}\n"
                    f"  Cote: {b.get('market_odds', '')}  |  "
                    f"Edge: {edge_pct:.1f}%  |  "
                    f"Confiance: {'⭐' * int(b.get('confidence', 0))}  |  "
                    f"Fiabilité: {b.get('data_reliability', '')}  |  "
                    f"Mise: {b.get('sim_stake', ''):.2f} EUR\n\n"
                )
        else:
            f.write("\n  Aucun pari recommandé aujourd'hui.\n")

    return str(report_path)


def print_summary(bets: list[dict], bankroll: dict) -> None:
    """Affiche un résumé concis dans le terminal."""
    pl = bankroll["current"] - bankroll["initial"]
    roi = (pl / bankroll["initial"]) * 100 if bankroll["initial"] else 0

    print("\n" + "─" * 55)
    print(f"  Bankroll : {bankroll['current']:.2f} EUR  "
          f"({_pl_color(pl)} EUR  /  ROI {roi:+.1f}%)")
    print(f"  Paris : {bankroll['total_bets']} total  "
          f"| {bankroll['wins']}W  {bankroll['losses']}L  "
          f"{bankroll['pending']} en attente")

    if bets:
        print(f"\n  Paris du jour ({len(bets)}) :")
        for b in bets:
            edge_pct = float(b.get("edge", 0)) * 100
            print(
                f"    • {b.get('match', '')}  [{b.get('market', '')}]  "
                f"@ {b.get('market_odds', '')}  "
                f"edge={edge_pct:.1f}%  "
                f"mise={b.get('sim_stake', 0):.2f}€"
            )
    else:
        print("\n  Aucun pari recommandé aujourd'hui.")

    print("─" * 55)
