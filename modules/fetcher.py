"""
Fetcher — récupère les matchs du jour et les meilleures cotes via The Odds API.
"""

import requests
from datetime import datetime, timezone
import config


def get_todays_matches() -> list[dict]:
    """
    Retourne la liste des matchs programmés aujourd'hui avec leurs meilleures cotes.
    Format : [{ match, home, away, competition, kickoff, date, odds: {1, X, 2} }]
    """
    today = datetime.now(timezone.utc).date().isoformat()
    matches = []

    for sport_key in config.COMPETITION_KEYS:
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
            params = {
                "apiKey": config.ODDS_API_KEY,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
            resp = requests.get(url, params=params, timeout=10)

            if resp.status_code == 401:
                print("[Fetcher] Clé API The Odds API invalide.")
                return []
            if resp.status_code == 422:
                # Compétition non disponible dans le plan
                continue
            if resp.status_code != 200:
                print(f"[Fetcher] {sport_key} → HTTP {resp.status_code}")
                continue

            for game in resp.json():
                commence = game.get("commence_time", "")
                if not commence.startswith(today):
                    continue

                home = game["home_team"]
                away = game["away_team"]
                competition = config.COMPETITION_NAMES.get(sport_key, sport_key)

                # Meilleure cote disponible sur les bookmakers européens
                best_odds: dict[str, float | None] = {"1": None, "X": None, "2": None}

                for bookmaker in game.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        if market["key"] != "h2h":
                            continue
                        for outcome in market["outcomes"]:
                            name = outcome["name"]
                            price = float(outcome["price"])
                            if name == home:
                                if best_odds["1"] is None or price > best_odds["1"]:
                                    best_odds["1"] = price
                            elif name == away:
                                if best_odds["2"] is None or price > best_odds["2"]:
                                    best_odds["2"] = price
                            elif name == "Draw":
                                if best_odds["X"] is None or price > best_odds["X"]:
                                    best_odds["X"] = price

                matches.append({
                    "match": f"{home} vs {away}",
                    "home": home,
                    "away": away,
                    "competition": competition,
                    "kickoff": commence[11:16],
                    "date": today,
                    "odds": best_odds,
                })

        except requests.exceptions.Timeout:
            print(f"[Fetcher] Timeout pour {sport_key}")
        except Exception as e:
            print(f"[Fetcher] Erreur inattendue pour {sport_key} : {e}")

    # Tri par heure de coup d'envoi
    matches.sort(key=lambda m: m["kickoff"])
    return matches


def format_matches_for_prompt(matches: list[dict]) -> str:
    """Formate les matchs du jour pour l'injection dans le prompt Claude."""
    lines = []
    for m in matches:
        o = m["odds"]
        cotes = f"1={o['1'] or 'N/A'}  X={o['X'] or 'N/A'}  2={o['2'] or 'N/A'}"
        lines.append(
            f"  • {m['match']}  |  {m['competition']}  |  {m['kickoff']}  |  {cotes}"
        )
    return "\n".join(lines)
