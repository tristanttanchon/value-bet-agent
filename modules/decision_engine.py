"""
Decision Engine — filtre les paris par edge, applique la blacklist
apprise et calcule les mises Kelly.
"""

import config


def calculate_kelly_stake(bankroll: float, edge: float, odds: float, kelly_override: float | None = None) -> float:
    """
    Mise Kelly fractionnée avec plafond à MAX_BET_PCT du bankroll.
    Formule : [edge / (odds − 1)] × KELLY_FRACTION
    """
    if edge <= 0 or odds <= 1.0:
        return 0.0

    fraction = kelly_override if kelly_override is not None else config.MAX_KELLY_FRACTION
    kelly_pct = (edge / (odds - 1.0)) * fraction
    kelly_pct = min(kelly_pct, config.MAX_BET_PCT)
    stake = round(bankroll * kelly_pct, 2)
    return stake


def filter_and_size_bets(raw_bets: list[dict], bankroll: float, kelly_override: float | None = None) -> list[dict]:
    """
    Filtre les paris dont l'edge >= MIN_EDGE_THRESHOLD,
    applique la blacklist apprise (combos historiquement perdants),
    calcule la mise simulée et trie par edge décroissant.
    """
    # Charge la blacklist apprise (couples compétition/marché à exclure)
    try:
        from modules.learning import get_blacklisted_combos
        blacklist = get_blacklisted_combos()
    except Exception as e:
        print(f"[Decision] Blacklist indisponible : {e}")
        blacklist = []

    valid = []
    blacklisted_count = 0

    for bet in raw_bets:
        edge = float(bet.get("edge", 0))
        if edge < config.MIN_EDGE_THRESHOLD:
            continue

        # Filtre auto-blacklist
        combo = (bet.get("competition") or "Inconnu", bet.get("market") or "Inconnu")
        if combo in blacklist:
            blacklisted_count += 1
            print(
                f"[Decision] ⛔ Pari blacklisté : {bet.get('match', '')} "
                f"({combo[0]} / {combo[1]}) — historique défavorable"
            )
            continue

        odds = float(bet.get("market_odds", 0))
        stake = calculate_kelly_stake(bankroll, edge, odds, kelly_override)

        if stake < config.MIN_STAKE:
            continue

        bet = dict(bet)  # copie pour ne pas muter l'original
        bet["sim_stake"] = stake
        valid.append(bet)

    if blacklisted_count:
        print(f"[Decision] {blacklisted_count} pari(s) exclu(s) par la blacklist apprise.")

    valid.sort(key=lambda b: float(b.get("edge", 0)), reverse=True)
    return valid
