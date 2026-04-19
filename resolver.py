"""
resolver.py — Résolution automatique des paris en attente via Supabase.
"""

import requests
import unicodedata
from datetime import date
import config
from modules.db import get_client
from modules.simulation import load_bankroll, save_bankroll
from modules.telegram_reporter import send_message


# ─────────────────────────────────────────────────────────────────────────────
# État global de rotation des clés Odds API (partagé entre les appels)
# ─────────────────────────────────────────────────────────────────────────────
_odds_keys: list[str] = []
_odds_key_index: int = 0


def _init_keys() -> None:
    global _odds_keys, _odds_key_index
    if _odds_keys:
        return
    keys = list(config.ODDS_API_KEYS) if config.ODDS_API_KEYS else []
    if not keys and config.ODDS_API_KEY:
        keys = [config.ODDS_API_KEY]
    _odds_keys = keys
    _odds_key_index = 0
    print(f"[Resolver] {len(_odds_keys)} clé(s) Odds API disponible(s).")


def _current_key() -> str | None:
    if not _odds_keys or _odds_key_index >= len(_odds_keys):
        return None
    return _odds_keys[_odds_key_index]


def _rotate_key() -> bool:
    """Passe à la clé suivante. Retourne True si dispo, False si toutes épuisées."""
    global _odds_key_index
    _odds_key_index += 1
    if _odds_key_index < len(_odds_keys):
        print(f"[Resolver] Rotation vers clé Odds #{_odds_key_index + 1}...")
        return True
    print(f"[Resolver] Toutes les clés Odds API sont épuisées.")
    return False


def _normalize(s: str) -> str:
    """Retire accents et met en lowercase pour matcher les noms d'équipes."""
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Récupération des résultats
# ─────────────────────────────────────────────────────────────────────────────

def fetch_scores(sport_key: str) -> list[dict]:
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = {
        "apiKey": _current_key(),
        "daysFrom": 5,
        "dateFormat": "iso",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        # Clé épuisée / invalide → rotation et retry
        while resp.status_code == 401:
            print(f"[Resolver] Clé Odds #{_odds_key_index + 1} épuisée ou invalide (401) sur {sport_key}.")
            if not _rotate_key():
                return []
            params["apiKey"] = _current_key()
            resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 429:
            print(f"[Resolver] {sport_key} → 429 (rate limit)")
            return []
        if resp.status_code == 422:
            # Compétition non dispo dans le plan — silencieux
            return []
        if resp.status_code != 200:
            print(f"[Resolver] {sport_key} → HTTP {resp.status_code}")
            return []
        return [g for g in resp.json() if g.get("completed")]
    except Exception as e:
        print(f"[Resolver] Erreur fetch {sport_key} : {e}")
        return []


def get_all_results() -> dict[str, dict]:
    _init_keys()
    results = {}
    for sport_key in config.COMPETITION_KEYS:
        games = fetch_scores(sport_key)
        for game in games:
            home = game["home_team"]
            away = game["away_team"]
            scores = game.get("scores") or []

            home_score = away_score = None
            for s in scores:
                if s["name"] == home:
                    home_score = int(s["score"])
                elif s["name"] == away:
                    away_score = int(s["score"])

            if home_score is not None and away_score is not None:
                # Clé normalisée (sans accents, lowercase) pour matching robuste
                key = _normalize(f"{home} vs {away}")
                results[key] = {
                    "home": home,
                    "away": away,
                    "home_score": home_score,
                    "away_score": away_score,
                }

    print(f"[Resolver] {len(results)} résultat(s) récupéré(s).")
    return results


def find_result(bet_match: str, results: dict) -> dict | None:
    key = _normalize(bet_match)
    if key in results:
        return results[key]

    # Match approximatif sur des noms partiels (ex: "Man United" dans "Manchester United")
    for result_key, result in results.items():
        home = _normalize(result["home"])
        away = _normalize(result["away"])
        parts = key.split(" vs ")
        if len(parts) == 2:
            bet_home = parts[0].strip()
            bet_away = parts[1].strip()
            if bet_home in home or home in bet_home:
                if bet_away in away or away in bet_away:
                    return result
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Calcul du résultat d'un pari
# ─────────────────────────────────────────────────────────────────────────────

def determine_outcome(market: str, home_score: int, away_score: int) -> str | None:
    market = market.strip()
    total = home_score + away_score

    btts_yes = home_score > 0 and away_score > 0
    outcomes = {
        "1": "WIN" if home_score > away_score else "LOSS",
        "X": "WIN" if home_score == away_score else "LOSS",
        "2": "WIN" if away_score > home_score else "LOSS",
        "Over 2.5": "WIN" if total > 2.5 else "LOSS",
        "Under 2.5": "WIN" if total < 2.5 else "LOSS",
        "BTTS": "WIN" if btts_yes else "LOSS",
        "BTTS Yes": "WIN" if btts_yes else "LOSS",
        "BTTS No": "WIN" if not btts_yes else "LOSS",
    }

    if market in outcomes:
        return outcomes[market]

    if market.upper() in ("AH0", "DNB", "DRAW NO BET"):
        if home_score > away_score:
            return "WIN"
        elif away_score > home_score:
            return "LOSS"
        else:
            return "PUSH"

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Mise à jour Supabase et bankroll
# ─────────────────────────────────────────────────────────────────────────────

def resolve_pending_bets(results: dict) -> tuple[int, int, int]:
    db = get_client()
    resp = db.table("bets").select("*").eq("status", "PENDING").execute()
    pending = resp.data or []

    if not pending:
        print("[Resolver] Aucun pari PENDING.")
        return 0, 0, 0

    resolved = wins = losses = pushes = 0
    bankroll = load_bankroll()

    for row in pending:
        result = find_result(row["match"], results)
        if result is None:
            continue

        outcome = determine_outcome(row["market"], result["home_score"], result["away_score"])
        if outcome is None:
            continue

        stake = float(row["sim_stake"] or 0)
        odds = float(row["market_odds"] or 0)

        if outcome == "WIN":
            profit = round(stake * odds - stake, 2)
            bankroll["wins"] += 1
            bankroll["total_returned"] = round(bankroll.get("total_returned", 0) + stake * odds, 2)
            wins += 1
        elif outcome == "PUSH":
            profit = 0.0
            bankroll["total_returned"] = round(bankroll.get("total_returned", 0) + stake, 2)
            pushes += 1
        else:
            profit = -stake
            bankroll["losses"] += 1
            losses += 1

        bankroll["current"] = round(bankroll["current"] + profit, 2)
        bankroll["reserved"] = round(bankroll.get("reserved", 0) - stake, 2)
        bankroll["pending"] -= 1

        db.table("bets").update({
            "status": outcome,
            "result": f"{result['home_score']}-{result['away_score']}",
            "profit_loss": profit,
            "bankroll_after": bankroll["current"],
        }).eq("id", row["id"]).execute()

        # Notification Telegram WIN/LOSS
        if config.TELEGRAM_BOT_TOKEN:
            emoji = "✅" if outcome == "WIN" else ("↩️" if outcome == "PUSH" else "❌")
            pl_str = f"{profit:+.2f}€" if outcome != "PUSH" else "Remboursé"
            send_message(
                f"{emoji} *{outcome}* — {row['match']}\n"
                f"Marché : `{row['market']}` @ `{row['market_odds']}`\n"
                f"Score : {result['home_score']}-{result['away_score']}  |  P&L : *{pl_str}*\n"
                f"Bankroll : *{bankroll['current']:.2f}€*"
            )

        resolved += 1

    if resolved > 0:
        save_bankroll(bankroll)

    return resolved, wins, losses


# ─────────────────────────────────────────────────────────────────────────────
# 4. Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────

def run_resolver() -> None:
    print("\n Résolution automatique des paris en attente...")

    results = get_all_results()
    if not results:
        print("[Resolver] Aucun résultat disponible pour le moment.")
        return

    resolved, wins, losses = resolve_pending_bets(results)

    if resolved == 0:
        print("[Resolver] Aucun pari résolu (résultats pas encore disponibles ou aucun PENDING).")
    else:
        bankroll = load_bankroll()
        pl = bankroll["current"] - bankroll["initial"]
        print(f"\n {resolved} pari(s) résolu(s) : {wins} WIN  {losses} LOSS")
        print(f"   Bankroll : {bankroll['current']:.2f}€  ({pl:+.2f}€ depuis le début)")


if __name__ == "__main__":
    run_resolver()
