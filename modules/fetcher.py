"""
Fetcher — récupère les matchs du jour et les meilleures cotes via The Odds API.
"""

import requests
import time
from datetime import datetime, timezone
import config


def get_todays_matches() -> list[dict]:
    """
    Retourne la liste des matchs programmés aujourd'hui avec leurs meilleures cotes.
    Format : [{ match, home, away, competition, kickoff, date, odds: {1, X, 2} }]

    Supporte la rotation automatique de plusieurs clés API : si la clé active
    est épuisée (401/OUT_OF_USAGE_CREDITS), bascule sur la suivante.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    matches = []

    # Pool de clés API avec rotation
    keys = list(config.ODDS_API_KEYS) if config.ODDS_API_KEYS else ([config.ODDS_API_KEY] if config.ODDS_API_KEY else [])
    if not keys:
        print("[Fetcher] Aucune clé ODDS_API_KEY configurée.")
        return []

    current_key_index = 0
    print(f"[Fetcher] {len(keys)} clé(s) API disponible(s).")

    premium_set = getattr(config, "PREMIUM_COMPETITIONS", set())

    for sport_key in config.COMPETITION_KEYS:
        try:
            is_premium = sport_key in premium_set
            # Premium : on récupère aussi Over/Under 2.5 (totals)
            # Note : `btts` n'est PAS supporté sur l'endpoint bulk /sports/{key}/odds
            # (seulement via /events/{id}/odds, trop cher en crédits)
            markets_str = "h2h,totals" if is_premium else "h2h"
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
            params = {
                "apiKey": keys[current_key_index],
                "regions": "eu",
                "markets": markets_str,
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
            resp = requests.get(url, params=params, timeout=10)

            # Clé épuisée ou invalide → rotation
            if resp.status_code == 401:
                print(f"[Fetcher] Clé #{current_key_index+1} épuisée/invalide.")
                if current_key_index + 1 < len(keys):
                    current_key_index += 1
                    print(f"[Fetcher] Rotation vers clé #{current_key_index+1}...")
                    # Retry immédiat avec la nouvelle clé
                    params["apiKey"] = keys[current_key_index]
                    resp = requests.get(url, params=params, timeout=10)
                    if resp.status_code == 401:
                        print(f"[Fetcher] Clé #{current_key_index+1} aussi épuisée. Arrêt.")
                        return matches
                else:
                    print("[Fetcher] Toutes les clés sont épuisées.")
                    return matches

            if resp.status_code == 422:
                # Compétition ou marché non disponible dans le plan
                body = resp.text[:200] if resp.text else ""
                print(f"[Fetcher] {sport_key} → HTTP 422 (markets={markets_str}) : {body}")
                # Fallback : si premium, réessayer en h2h seul pour au moins récupérer le 1X2
                if is_premium and markets_str != "h2h":
                    print(f"[Fetcher] {sport_key} → fallback h2h uniquement")
                    params["markets"] = "h2h"
                    resp = requests.get(url, params=params, timeout=10)
                    # Rotation de clé si le fallback tombe sur un 401
                    if resp.status_code == 401 and current_key_index + 1 < len(keys):
                        current_key_index += 1
                        print(f"[Fetcher] Fallback → rotation clé #{current_key_index+1}")
                        params["apiKey"] = keys[current_key_index]
                        resp = requests.get(url, params=params, timeout=10)
                    if resp.status_code != 200:
                        print(f"[Fetcher] {sport_key} → fallback aussi KO : HTTP {resp.status_code}")
                        continue
                    # Marquer comme non-premium pour la suite du parsing
                    is_premium = False
                else:
                    continue
            if resp.status_code == 429:
                print(f"[Fetcher] {sport_key} → HTTP 429 (rate limit), pause 2s...")
                time.sleep(2)
                continue
            if resp.status_code != 200:
                print(f"[Fetcher] {sport_key} → HTTP {resp.status_code}")
                continue

            games_today = 0
            games_total = 0
            for game in resp.json():
                games_total += 1
                commence = game.get("commence_time", "")
                if not commence.startswith(today):
                    continue

                home = game["home_team"]
                away = game["away_team"]
                competition = config.COMPETITION_NAMES.get(sport_key, sport_key)

                # Meilleure cote disponible sur les bookmakers européens
                # Marchés : 1X2 (toujours) + Over/Under 2.5 + BTTS (premium uniquement)
                best_odds: dict[str, float | None] = {
                    "1": None, "X": None, "2": None,
                    "Over 2.5": None, "Under 2.5": None,
                    "BTTS Yes": None, "BTTS No": None,
                }

                for bookmaker in game.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        mkey = market["key"]
                        if mkey == "h2h":
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
                        elif mkey == "totals":
                            # On ne garde que la ligne 2.5
                            for outcome in market["outcomes"]:
                                if float(outcome.get("point", 0)) != 2.5:
                                    continue
                                name = outcome["name"]  # "Over" / "Under"
                                price = float(outcome["price"])
                                slot = "Over 2.5" if name == "Over" else "Under 2.5"
                                if best_odds[slot] is None or price > best_odds[slot]:
                                    best_odds[slot] = price
                        elif mkey == "btts":
                            for outcome in market["outcomes"]:
                                name = outcome["name"]  # "Yes" / "No"
                                price = float(outcome["price"])
                                slot = "BTTS Yes" if name == "Yes" else "BTTS No"
                                if best_odds[slot] is None or price > best_odds[slot]:
                                    best_odds[slot] = price

                matches.append({
                    "match": f"{home} vs {away}",
                    "home": home,
                    "away": away,
                    "competition": competition,
                    "kickoff": commence[11:16],
                    "date": today,
                    "odds": best_odds,
                })
                games_today += 1

            # Log par compétition : utile pour diagnostiquer l'absence de matchs premium
            if is_premium or games_today > 0:
                tag = " [PREMIUM]" if is_premium else ""
                print(f"[Fetcher] {sport_key}{tag} → {games_today}/{games_total} match(s) aujourd'hui")

        except requests.exceptions.Timeout:
            print(f"[Fetcher] Timeout pour {sport_key}")
        except Exception as e:
            print(f"[Fetcher] Erreur inattendue pour {sport_key} : {e}")

    # Tri par heure de coup d'envoi
    matches.sort(key=lambda m: m["kickoff"])

    # Diagnostic : combien de matchs ont les cotes premium (Over/Under + BTTS)
    premium_names = {config.COMPETITION_NAMES.get(k, k) for k in premium_set}
    premium_matches = [m for m in matches if m["competition"] in premium_names]
    with_totals = sum(1 for m in premium_matches if m["odds"].get("Over 2.5") or m["odds"].get("Under 2.5"))
    with_btts = sum(1 for m in premium_matches if m["odds"].get("BTTS Yes") or m["odds"].get("BTTS No"))
    print(
        f"[Fetcher] Matchs premium : {len(premium_matches)} "
        f"(avec Over/Under 2.5 : {with_totals}, avec BTTS : {with_btts})"
    )

    return matches


def format_matches_for_prompt(matches: list[dict]) -> str:
    """Formate les matchs du jour pour l'injection dans le prompt Claude.

    Affiche 1X2 toujours, puis Over/Under 2.5 et BTTS quand dispos (premium).
    """
    lines = []
    for m in matches:
        o = m["odds"]
        parts = [f"1={o.get('1') or 'N/A'}  X={o.get('X') or 'N/A'}  2={o.get('2') or 'N/A'}"]
        # Marchés supplémentaires (premium)
        if o.get("Over 2.5") or o.get("Under 2.5"):
            parts.append(f"O2.5={o.get('Over 2.5') or 'N/A'}  U2.5={o.get('Under 2.5') or 'N/A'}")
        if o.get("BTTS Yes") or o.get("BTTS No"):
            parts.append(f"BTTS_Y={o.get('BTTS Yes') or 'N/A'}  BTTS_N={o.get('BTTS No') or 'N/A'}")
        cotes = "  |  ".join(parts)
        lines.append(
            f"  • {m['match']}  |  {m['competition']}  |  {m['kickoff']}  |  {cotes}"
        )
    return "\n".join(lines)
