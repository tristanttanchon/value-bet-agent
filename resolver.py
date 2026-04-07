"""
resolver.py — Résolution automatique des paris en attente via Supabase.
"""

import requests
from datetime import date
import config
from modules.db import get_client
from modules.simulation import load_bankroll, save_bankroll


# ─────────────────────────────────────────────────────────────────────────────
# 1. Récupération des résultats
# ─────────────────────────────────────────────────────────────────────────────

def fetch_scores(sport_key: str) -> list[dict]:
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "daysFrom": 2,
        "dateFormat": "iso",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        return [g for g in resp.json() if g.get("completed")]
    except Exception as e:
        print(f"[Resolver] Erreur fetch {sport_key} : {e}")
        return []


def get_all_results() -> dict[str, dict]:
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
                key = f"{home} vs {away}".lower().strip()
                results[key] = {
                    "home": home,
                    "away": away,
                    "home_score": home_score,
                    "away_score": away_score,
                }

    print(f"[Resolver] {len(results)} résultat(s) récupéré(s).")
    return results


def find_result(bet_match: str, results: dict) -> dict | None:
    key = bet_match.lower().strip()
    if key in results:
        return results[key]

    for result_key, result in results.items():
        home = result["home"].lower()
        away = result["away"].lower()
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

    outcomes = {
        "1": "WIN" if home_score > away_score else "LOSS",
        "X": "WIN" if home_score == away_score else "LOSS",
        "2": "WIN" if away_score > home_score else "LOSS",
        "Over 2.5": "WIN" if total > 2.5 else "LOSS",
        "Under 2.5": "WIN" if total < 2.5 else "LOSS",
        "BTTS": "WIN" if home_score > 0 and away_score > 0 else "LOSS",
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
