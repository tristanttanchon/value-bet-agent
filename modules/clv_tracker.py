"""
CLV Tracker — Closing Line Value via Supabase.
"""

from datetime import date
import requests
import config
from modules.db import get_client


def record_opening_odds(bets: list[dict]) -> None:
    """Enregistre les cotes d'ouverture pour chaque pari joué."""
    db = get_client()
    today = date.today().isoformat()

    rows = []
    for bet in bets:
        rows.append({
            "date": today,
            "match": bet.get("match", ""),
            "competition": bet.get("competition", ""),
            "market": bet.get("market", ""),
            "opening_odds": float(bet.get("market_odds", 0)) if bet.get("market_odds") else None,
            "closing_odds": None,
            "clv_pct": None,
            "model_probability": float(bet.get("model_probability", 0)) if bet.get("model_probability") else None,
            "edge_at_open": f"{float(bet.get('edge', 0)):.1%}",
        })

    if rows:
        db.table("clv_log").insert(rows).execute()


def fetch_closing_odds(match_home: str, match_away: str, sport_key: str) -> dict[str, float]:
    """Récupère les cotes actuelles (closing) pour un match."""
    try:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        params = {
            "apiKey": config.ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return {}

        for game in resp.json():
            if match_home.lower() in game["home_team"].lower() or \
               match_away.lower() in game["away_team"].lower():
                odds = {"1": None, "X": None, "2": None}
                for bm in game.get("bookmakers", []):
                    for market in bm.get("markets", []):
                        if market["key"] != "h2h":
                            continue
                        for outcome in market["outcomes"]:
                            price = float(outcome["price"])
                            if outcome["name"] == game["home_team"]:
                                if odds["1"] is None or price > odds["1"]:
                                    odds["1"] = price
                            elif outcome["name"] == game["away_team"]:
                                if odds["2"] is None or price > odds["2"]:
                                    odds["2"] = price
                            elif outcome["name"] == "Draw":
                                if odds["X"] is None or price > odds["X"]:
                                    odds["X"] = price
                return odds
    except Exception as e:
        print(f"[CLV] Erreur fetch closing odds : {e}")
    return {}


def update_closing_odds() -> int:
    """Met à jour les cotes de fermeture pour les paris sans closing_odds."""
    db = get_client()
    resp = db.table("clv_log").select("*").is_("closing_odds", "null").execute()
    rows = resp.data or []

    updated = 0
    for row in rows:
        match = row["match"]
        parts = match.split(" vs ")
        if len(parts) != 2:
            continue

        home, away = parts[0].strip(), parts[1].strip()

        for sport_key in config.COMPETITION_KEYS:
            closing = fetch_closing_odds(home, away, sport_key)
            if closing:
                market = row["market"]
                closing_odd = closing.get(market)
                if closing_odd and row["opening_odds"]:
                    opening_odd = float(row["opening_odds"])
                    clv = ((closing_odd - opening_odd) / opening_odd) * 100
                    db.table("clv_log").update({
                        "closing_odds": round(closing_odd, 2),
                        "clv_pct": round(clv, 1),
                    }).eq("id", row["id"]).execute()
                    updated += 1
                break

    return updated


def get_clv_summary() -> dict:
    """Calcule les stats CLV globales du modèle."""
    db = get_client()
    resp = db.table("clv_log").select("clv_pct").not_.is_("closing_odds", "null").execute()
    rows = resp.data or []

    if not rows:
        return {"total": 0}

    clv_values = [float(r["clv_pct"]) for r in rows if r["clv_pct"] is not None]
    if not clv_values:
        return {"total": 0}

    total = len(clv_values)
    positive = sum(1 for v in clv_values if v > 0)
    avg_clv = sum(clv_values) / total
    beat_rate = (positive / total * 100) if total > 0 else 0

    return {
        "total": total,
        "avg_clv": avg_clv,
        "beat_closing_line_pct": beat_rate,
        "model_quality": "Excellent" if avg_clv > 2 else "Bon" if avg_clv > 0 else "À revoir",
    }
