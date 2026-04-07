"""
Data Enricher — récupère les données fraîches via API-Football (RapidAPI).
Blessés/suspendus, forme récente, H2H, stats d'équipe.
Ces données sont injectées dans le prompt Claude AVANT l'analyse.
"""

import requests
from datetime import date
import config


HEADERS = {
    "x-rapidapi-host": "api-football-v1.p.rapidapi.com",
    "x-rapidapi-key": config.API_FOOTBALL_KEY or "",
}
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

# Correspondance compétition → league_id API-Football
LEAGUE_IDS = {
    "soccer_epl": 39,
    "soccer_spain_la_liga": 140,
    "soccer_italy_serie_a": 135,
    "soccer_germany_bundesliga": 78,
    "soccer_france_ligue_one": 61,
    "soccer_uefa_champs_league": 2,
    "soccer_uefa_europa_league": 3,
    "soccer_uefa_conference_league": 848,
    "soccer_england_fa_cup": 45,
    "soccer_spain_copa_del_rey": 143,
    "soccer_italy_coppa_italia": 137,
    "soccer_germany_dfb_pokal": 81,
    "soccer_france_coupe_de_france": 66,
    "soccer_england_championship": 40,
    "soccer_netherlands_eredivisie": 88,
    "soccer_portugal_primeira_liga": 94,
    "soccer_turkey_super_lig": 203,
    "soccer_belgium_first_div": 144,
    "soccer_conmebol_copa_libertadores": 13,
    "soccer_conmebol_copa_sudamericana": 11,
    "soccer_brazil_campeonato": 71,
    "soccer_argentina_primera_division": 128,
    "soccer_mexico_ligamx": 262,
}


def _get(endpoint: str, params: dict) -> dict | None:
    """Appel API-Football avec gestion d'erreur."""
    if not config.API_FOOTBALL_KEY:
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/{endpoint}",
            headers=HEADERS,
            params=params,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        print(f"[Enricher] Erreur API-Football ({endpoint}) : {e}")
        return None


def get_team_id(team_name: str) -> int | None:
    """Cherche l'ID d'une équipe par son nom."""
    data = _get("teams", {"search": team_name})
    if data and data.get("results", 0) > 0:
        return data["response"][0]["team"]["id"]
    return None


def get_injuries(team_id: int, fixture_id: int | None = None) -> list[dict]:
    """Récupère les blessés et suspendus d'une équipe."""
    params = {"team": team_id, "season": date.today().year}
    if fixture_id:
        params["fixture"] = fixture_id

    data = _get("injuries", params)
    if not data:
        return []

    players = []
    for item in data.get("response", []):
        players.append({
            "name": item["player"]["name"],
            "type": item["player"]["type"],  # "injury" ou "suspension"
            "reason": item["player"]["reason"],
        })
    return players


def get_team_form(team_id: int, last: int = 5) -> list[dict]:
    """Récupère les N derniers matchs d'une équipe."""
    data = _get("fixtures", {
        "team": team_id,
        "last": last,
        "status": "FT",
    })
    if not data:
        return []

    matches = []
    for f in data.get("response", []):
        home = f["teams"]["home"]
        away = f["teams"]["away"]
        goals = f["goals"]
        is_home = home["id"] == team_id

        result = "W" if (is_home and home["winner"]) or (not is_home and away["winner"]) \
            else "L" if (is_home and away["winner"]) or (not is_home and home["winner"]) \
            else "D"

        matches.append({
            "date": f["fixture"]["date"][:10],
            "home": home["name"],
            "away": away["name"],
            "score": f"{goals['home']}-{goals['away']}",
            "result": result,
        })
    return matches


def get_h2h(team1_id: int, team2_id: int, last: int = 5) -> list[dict]:
    """Récupère les N derniers face-à-face entre deux équipes."""
    data = _get("fixtures/headtohead", {
        "h2h": f"{team1_id}-{team2_id}",
        "last": last,
        "status": "FT",
    })
    if not data:
        return []

    matches = []
    for f in data.get("response", []):
        goals = f["goals"]
        matches.append({
            "date": f["fixture"]["date"][:10],
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
            "score": f"{goals['home']}-{goals['away']}",
        })
    return matches


def get_team_stats(team_id: int, league_id: int) -> dict:
    """Récupère les stats de la saison (xG, buts marqués/encaissés, forme)."""
    data = _get("teams/statistics", {
        "team": team_id,
        "league": league_id,
        "season": date.today().year,
    })
    if not data or not data.get("response"):
        return {}

    r = data["response"]
    goals_for = r.get("goals", {}).get("for", {})
    goals_against = r.get("goals", {}).get("against", {})

    return {
        "played": r.get("fixtures", {}).get("played", {}).get("total", 0),
        "wins": r.get("fixtures", {}).get("wins", {}).get("total", 0),
        "draws": r.get("fixtures", {}).get("draws", {}).get("total", 0),
        "losses": r.get("fixtures", {}).get("losses", {}).get("total", 0),
        "goals_for_avg": goals_for.get("average", {}).get("total", "N/A"),
        "goals_against_avg": goals_against.get("average", {}).get("total", "N/A"),
        "form": r.get("form", "N/A"),
        "clean_sheets": r.get("clean_sheet", {}).get("total", "N/A"),
        "failed_to_score": r.get("failed_to_score", {}).get("total", "N/A"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fonction principale : enrichit tous les matchs du jour
# ─────────────────────────────────────────────────────────────────────────────

def enrich_matches(matches: list[dict]) -> str:
    """
    Pour chaque match, récupère les données fraîches et retourne
    un bloc texte structuré à injecter dans le prompt Claude.
    """
    if not config.API_FOOTBALL_KEY:
        return ""

    print(f"[Enricher] Enrichissement de {len(matches)} match(s)...")
    lines = ["\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    lines.append("DONNÉES FRAÎCHES — API-FOOTBALL (injectées automatiquement)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    for match in matches:
        home_name = match["home"]
        away_name = match["away"]
        competition = match["competition"]

        lines.append(f"▶ {home_name} vs {away_name}  ({competition})")

        # Récupère les IDs des équipes
        home_id = get_team_id(home_name)
        away_id = get_team_id(away_name)

        if not home_id or not away_id:
            lines.append("  [Données non disponibles pour ce match]\n")
            continue

        # Trouve le league_id correspondant
        league_id = None
        for sport_key, comp_name in config.COMPETITION_NAMES.items():
            if comp_name == competition:
                league_id = LEAGUE_IDS.get(sport_key)
                break

        # ── Blessés / Suspendus ──────────────────────────────────────────
        home_injuries = get_injuries(home_id)
        away_injuries = get_injuries(away_id)

        if home_injuries:
            lines.append(f"  🔴 Absences {home_name} :")
            for p in home_injuries:
                lines.append(f"     - {p['name']} ({p['type']} : {p['reason']})")
        else:
            lines.append(f"  🔴 Absences {home_name} : aucune confirmée")

        if away_injuries:
            lines.append(f"  🔴 Absences {away_name} :")
            for p in away_injuries:
                lines.append(f"     - {p['name']} ({p['type']} : {p['reason']})")
        else:
            lines.append(f"  🔴 Absences {away_name} : aucune confirmée")

        # ── Forme récente ────────────────────────────────────────────────
        home_form = get_team_form(home_id)
        away_form = get_team_form(away_id)

        if home_form:
            lines.append(f"  📊 Forme {home_name} (5 derniers) :")
            for m in home_form:
                lines.append(f"     {m['date']}  {m['home']} {m['score']} {m['away']}  [{m['result']}]")

        if away_form:
            lines.append(f"  📊 Forme {away_name} (5 derniers) :")
            for m in away_form:
                lines.append(f"     {m['date']}  {m['home']} {m['score']} {m['away']}  [{m['result']}]")

        # ── H2H ─────────────────────────────────────────────────────────
        h2h = get_h2h(home_id, away_id)
        if h2h:
            lines.append(f"  ⚔️  H2H (5 derniers face-à-face) :")
            for m in h2h:
                lines.append(f"     {m['date']}  {m['home']} {m['score']} {m['away']}")

        # ── Stats saison ─────────────────────────────────────────────────
        if league_id:
            home_stats = get_team_stats(home_id, league_id)
            away_stats = get_team_stats(away_id, league_id)

            if home_stats:
                lines.append(f"  📈 Stats saison {home_name} :")
                lines.append(
                    f"     {home_stats['played']} matchs  "
                    f"{home_stats['wins']}V {home_stats['draws']}N {home_stats['losses']}D  "
                    f"| Moy buts marqués : {home_stats['goals_for_avg']}  "
                    f"| Moy buts encaissés : {home_stats['goals_against_avg']}  "
                    f"| Clean sheets : {home_stats['clean_sheets']}"
                )

            if away_stats:
                lines.append(f"  📈 Stats saison {away_name} :")
                lines.append(
                    f"     {away_stats['played']} matchs  "
                    f"{away_stats['wins']}V {away_stats['draws']}N {away_stats['losses']}D  "
                    f"| Moy buts marqués : {away_stats['goals_for_avg']}  "
                    f"| Moy buts encaissés : {away_stats['goals_against_avg']}  "
                    f"| Clean sheets : {away_stats['clean_sheets']}"
                )

        lines.append("")

    return "\n".join(lines)
