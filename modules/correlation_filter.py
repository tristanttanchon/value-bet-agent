"""
Correlation Filter — Filtre anti-corrélation.
Évite de surexposer le bankroll sur un même match en jouant des paris liés.
Ex : PSG gagne (1) + Over 2.5 sur PSG vs OM = deux paris corrélés = risque doublé.
"""


# Marchés qui sont positivement corrélés entre eux sur le même match
CORRELATED_GROUPS = [
    {"1", "AH0_home", "Over 2.5"},   # Victoire domicile corrélée à Over si équipe offensive
    {"2", "AH0_away"},               # Victoire extérieur
    {"BTTS", "Over 2.5"},            # Les deux marquent et Over 2.5 sont très liés
]

# Exposition max autorisée sur un même match (en % du bankroll)
MAX_EXPOSURE_PER_MATCH = 0.08   # 8% max sur un seul match


def get_match_key(bet: dict) -> str:
    """Retourne une clé unique pour identifier le match."""
    return bet.get("match", "").lower().strip()


def are_correlated(market1: str, market2: str) -> bool:
    """Vérifie si deux marchés sont corrélés."""
    m1 = market1.strip()
    m2 = market2.strip()
    for group in CORRELATED_GROUPS:
        if m1 in group and m2 in group:
            return True
    return False


def filter_correlated_bets(bets: list[dict], bankroll: float) -> list[dict]:
    """
    Filtre les paris corrélés sur un même match.
    - Si deux paris corrélés sur le même match : garde celui avec le meilleur edge
    - Vérifie l'exposition totale par match (max 8% du bankroll)
    Retourne la liste filtrée.
    """
    if not bets:
        return bets

    # Grouper par match
    match_groups: dict[str, list[dict]] = {}
    for bet in bets:
        key = get_match_key(bet)
        if key not in match_groups:
            match_groups[key] = []
        match_groups[key].append(bet)

    filtered = []
    max_exposure = bankroll * MAX_EXPOSURE_PER_MATCH

    for match_key, match_bets in match_groups.items():
        if len(match_bets) == 1:
            filtered.extend(match_bets)
            continue

        # Tri par edge décroissant
        match_bets_sorted = sorted(
            match_bets,
            key=lambda b: float(b.get("edge", 0)),
            reverse=True
        )

        kept = []
        total_stake = 0.0

        for bet in match_bets_sorted:
            stake = float(bet.get("sim_stake", 0))
            market = bet.get("market", "")

            # Vérifie la corrélation avec les paris déjà gardés
            correlated = any(are_correlated(market, k.get("market", "")) for k in kept)
            if correlated:
                print(
                    f"[CorrFilter] Pari écarté (corrélation) : "
                    f"{bet.get('match')} [{market}]"
                )
                continue

            # Vérifie l'exposition totale sur ce match
            if total_stake + stake > max_exposure:
                print(
                    f"[CorrFilter] Pari écarté (exposition max {MAX_EXPOSURE_PER_MATCH*100:.0f}%) : "
                    f"{bet.get('match')} [{market}]"
                )
                continue

            kept.append(bet)
            total_stake += stake

        filtered.extend(kept)

    return filtered
