"""
Line Alert — Détection des mouvements de lignes significatifs via Supabase.
"""

import requests
import config
from modules.db import get_client
from modules.telegram_reporter import send_message

ALERT_THRESHOLD = 0.05
SHARP_THRESHOLD = 0.10


def load_snapshot() -> dict:
    """Charge le dernier snapshot des cotes depuis Supabase."""
    db = get_client()
    resp = db.table("odds_snapshot").select("*").execute()
    snapshot = {}
    for row in (resp.data or []):
        snapshot[row["match_key"]] = {
            "1": row["odds_1"],
            "X": row["odds_x"],
            "2": row["odds_2"],
            "kickoff": row["kickoff"],
        }
    return snapshot


def save_snapshot(data: dict) -> None:
    """Sauvegarde le snapshot des cotes actuelles dans Supabase (upsert)."""
    db = get_client()
    rows = []
    for match_key, odds in data.items():
        rows.append({
            "match_key": match_key,
            "odds_1": odds.get("1"),
            "odds_x": odds.get("X"),
            "odds_2": odds.get("2"),
            "kickoff": odds.get("kickoff", ""),
        })
    if rows:
        db.table("odds_snapshot").upsert(rows, on_conflict="match_key").execute()

    # Supprimer les matchs qui ne sont plus dans le snapshot courant
    if data:
        current_keys = list(data.keys())
        db.table("odds_snapshot").delete().not_.in_("match_key", current_keys).execute()


def fetch_current_odds() -> dict:
    """Récupère les cotes actuelles pour toutes les compétitions."""
    current = {}

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
            if resp.status_code != 200:
                continue

            for game in resp.json():
                key = f"{game['home_team']} vs {game['away_team']}"
                odds = {"1": None, "X": None, "2": None, "kickoff": game.get("commence_time", "")}

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

                current[key] = odds

        except Exception as e:
            print(f"[LineAlert] Erreur {sport_key} : {e}")

    return current


def detect_movements(previous: dict, current: dict) -> list[dict]:
    """Compare les snapshots et retourne les mouvements significatifs."""
    movements = []

    for match_key, curr_odds in current.items():
        if match_key not in previous:
            continue

        prev_odds = previous[match_key]

        for outcome in ["1", "X", "2"]:
            prev = prev_odds.get(outcome)
            curr = curr_odds.get(outcome)

            if not prev or not curr:
                continue

            movement = (curr - prev) / prev

            if abs(movement) >= ALERT_THRESHOLD:
                is_sharp = abs(movement) >= SHARP_THRESHOLD
                signal = ""
                if movement < -SHARP_THRESHOLD:
                    signal = "SHARP MONEY DETECTE"
                elif movement < -ALERT_THRESHOLD:
                    signal = "Mouvement significatif"

                movements.append({
                    "match": match_key,
                    "outcome": outcome,
                    "prev_odds": prev,
                    "curr_odds": curr,
                    "movement_pct": movement * 100,
                    "direction": "BAISSE" if movement < 0 else "HAUSSE",
                    "is_sharp": is_sharp,
                    "signal": signal,
                    "kickoff": curr_odds.get("kickoff", ""),
                })

    movements.sort(key=lambda m: abs(m["movement_pct"]), reverse=True)
    return movements


def build_alert_message(movements: list[dict]) -> str:
    """Construit le message Telegram pour les alertes."""
    if not movements:
        return ""

    sharp_moves = [m for m in movements if m["is_sharp"]]
    lines = [f"*MOUVEMENTS DE LIGNES — {len(movements)} détecté(s)*\n"]

    if sharp_moves:
        lines.append("*SIGNAUX SHARP MONEY :*\n")
        for m in sharp_moves:
            lines.append(
                f"• *{m['match']}* [{m['outcome']}]\n"
                f"  {m['prev_odds']:.2f} → {m['curr_odds']:.2f}  "
                f"({m['movement_pct']:+.1f}%)  {m['signal']}\n"
            )

    other_moves = [m for m in movements if not m["is_sharp"]]
    if other_moves:
        lines.append("\n*Autres mouvements :*\n")
        for m in other_moves[:5]:
            lines.append(
                f"• {m['match']} [{m['outcome']}]  "
                f"{m['prev_odds']:.2f} → {m['curr_odds']:.2f}  "
                f"({m['movement_pct']:+.1f}%)"
            )

    return "\n".join(lines)


def run_line_monitor() -> None:
    """Vérifie les mouvements de lignes, alerte si nécessaire."""
    print("[LineAlert] Vérification des mouvements de lignes...")

    previous = load_snapshot()
    current = fetch_current_odds()

    if not current:
        print("[LineAlert] Aucune cote récupérée.")
        return

    if previous:
        movements = detect_movements(previous, current)
        if movements:
            print(f"[LineAlert] {len(movements)} mouvement(s) détecté(s).")
            message = build_alert_message(movements)
            if message and config.TELEGRAM_BOT_TOKEN:
                send_message(message)
        else:
            print("[LineAlert] Aucun mouvement significatif.")

    save_snapshot(current)


if __name__ == "__main__":
    run_line_monitor()
