"""
Data Enricher — récupère les données fraîches via API-Football (RapidAPI).
Blessés/suspendus, forme récente, H2H, stats d'équipe.
Ces données sont injectées dans le prompt Gemini AVANT l'analyse.

Rotation multi-clés (4 clés × 100 req = 400 req/jour → tous les matchs).
Cache des team IDs pour éviter les lookups dupliqués.
"""

import json
import requests
from datetime import date
from pathlib import Path
import config


BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

# Cache des team IDs pour éviter les requêtes dupliquées
_team_id_cache: dict[str, int | None] = {}

# Gestion multi-clés avec rotation
_current_key_index = 0
_request_count = 0           # requêtes faites sur la clé courante
_total_requests_made = 0     # total réel cumulé sur toutes les clés (pour log)
QUOTA_PER_KEY = 95           # marge de sécurité sur les 100/clé

# Cap de matchs enrichis pour préserver le budget API
MAX_ENRICHED_MATCHES = 15

# Cache disque pour les top buteurs (refresh toutes les 24h)
TOPSCORERS_CACHE_FILE = config.DATA_DIR / "topscorers_cache.json"

# Cache disque pour les effectifs (refresh toutes les 24h)
SQUADS_CACHE_FILE = config.DATA_DIR / "squads_cache.json"

# Cache disque pour les fixtures (refresh par date)
FIXTURES_CACHE_FILE = config.DATA_DIR / "fixtures_cache.json"

# Ligues prioritaires pour l'enrichissement (les plus fiables en données)
PRIORITY_LEAGUES = [
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
    "soccer_germany_bundesliga", "soccer_france_ligue_one",
    "soccer_uefa_champs_league", "soccer_uefa_europa_league",
    "soccer_netherlands_eredivisie", "soccer_england_championship",
    "soccer_portugal_primeira_liga", "soccer_belgium_first_div",
]


def _get_current_key() -> str | None:
    """Retourne la clé API-Football courante."""
    keys = config.API_FOOTBALL_KEYS
    if not keys or _current_key_index >= len(keys):
        return None
    return keys[_current_key_index]


def _rotate_key() -> bool:
    """Passe à la clé suivante. Retourne False si plus de clés disponibles."""
    global _current_key_index, _request_count
    _current_key_index += 1
    _request_count = 0
    keys = config.API_FOOTBALL_KEYS
    if _current_key_index >= len(keys):
        print(f"[Enricher] Toutes les clés API-Football épuisées ({len(keys)} clé(s)).")
        return False
    print(f"[Enricher] Rotation vers clé API-Football #{_current_key_index + 1}/{len(keys)}")
    return True


def _european_season() -> int:
    """
    Retourne l'année de DÉBUT de la saison européenne (août → mai).
    Ex : avril 2026 → saison 2025-2026 → renvoie 2025.
    Pour Brésil/Argentine (calendrier civil) c'est moins précis mais
    API-Football reste tolérant et retourne quelque chose d'utile.
    """
    today = date.today()
    return today.year if today.month >= 7 else today.year - 1

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
    """Appel API-Football avec rotation multi-clés et compteur de quota."""
    global _request_count, _total_requests_made

    current_key = _get_current_key()
    if not current_key:
        return None

    # Rotation si quota atteint sur la clé courante
    if _request_count >= QUOTA_PER_KEY:
        if not _rotate_key():
            return None
        current_key = _get_current_key()
        if not current_key:
            return None

    headers = {
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com",
        "x-rapidapi-key": current_key,
    }

    try:
        resp = requests.get(
            f"{BASE_URL}/{endpoint}",
            headers=headers,
            params=params,
            timeout=10,
        )
        _request_count += 1
        _total_requests_made += 1
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            print(f"[Enricher] Quota clé #{_current_key_index + 1} épuisée (429).")
            if not _rotate_key():
                return None
            # Retry avec la nouvelle clé
            return _get(endpoint, params)
        return None
    except Exception as e:
        print(f"[Enricher] Erreur API-Football ({endpoint}) : {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Top buteurs par ligue (utilisé par fun_predictor)
# ─────────────────────────────────────────────────────────────────────────────

def _load_topscorers_cache() -> dict:
    if not TOPSCORERS_CACHE_FILE.exists():
        return {}
    try:
        with open(TOPSCORERS_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Enricher] Cache topscorers illisible : {e}")
        return {}


def _save_topscorers_cache(cache: dict) -> None:
    try:
        TOPSCORERS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOPSCORERS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Enricher] Sauvegarde cache topscorers KO : {e}")


def _fetch_top_scorers(league_id: int, season: int, top_n: int = 15) -> list[dict]:
    """Top N buteurs d'une ligue pour la saison donnée."""
    data = _get("players/topscorers", {"league": league_id, "season": season})
    if not data or not data.get("response"):
        return []

    out = []
    for item in data["response"][:top_n]:
        player = item.get("player") or {}
        stats = (item.get("statistics") or [{}])[0]
        team = (stats.get("team") or {}).get("name", "")
        goals = (stats.get("goals") or {}).get("total", 0)
        if not player.get("name") or goals is None:
            continue
        out.append({
            "name": player["name"],
            "team": team,
            "goals": goals,
        })
    return out


def get_top_scorers_for_competitions(competition_names: list[str]) -> dict[str, list[dict]]:
    """
    Pour chaque compétition fournie, retourne la liste des top buteurs
    (cachée 24h sur disque pour limiter la conso API-Football).

    Renvoie : { "Premier League": [{"name", "team", "goals"}, ...], ... }
    """
    if not config.API_FOOTBALL_KEY:
        return {}

    today = date.today().isoformat()
    season = _european_season()
    cache = _load_topscorers_cache()
    today_bucket = cache.get(today, {})

    # Map nom compétition → sport_key (clef inverse)
    comp_to_sport = {v: k for k, v in config.COMPETITION_NAMES.items()}

    result: dict[str, list[dict]] = {}
    new_fetches = 0

    for comp_name in competition_names:
        sport_key = comp_to_sport.get(comp_name)
        if not sport_key:
            continue
        league_id = LEAGUE_IDS.get(sport_key)
        if not league_id:
            continue

        cache_key = str(league_id)
        cached = today_bucket.get(cache_key)
        if cached is not None:
            result[comp_name] = cached
            continue

        # Cache miss → fetch
        scorers = _fetch_top_scorers(league_id, season)
        today_bucket[cache_key] = scorers
        result[comp_name] = scorers
        new_fetches += 1

    # Purge des dates anciennes (garde uniquement aujourd'hui)
    cache = {today: today_bucket}
    _save_topscorers_cache(cache)

    if new_fetches > 0:
        print(f"[Enricher] Top buteurs : {new_fetches} ligue(s) fetched, "
              f"{len(result) - new_fetches} servies depuis le cache.")
    else:
        print(f"[Enricher] Top buteurs : {len(result)} ligue(s) servies depuis le cache.")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Effectifs des équipes (utilisé par fun_predictor pour avoir des noms réels)
# ─────────────────────────────────────────────────────────────────────────────

def _load_squads_cache() -> dict:
    if not SQUADS_CACHE_FILE.exists():
        return {}
    try:
        with open(SQUADS_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_squads_cache(cache: dict) -> None:
    try:
        SQUADS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SQUADS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Enricher] Sauvegarde cache squads KO : {e}")


def _fetch_squad(team_id: int) -> list[dict]:
    """Effectif actuel d'une équipe via API-Football."""
    data = _get("players/squads", {"team": team_id})
    if not data or not data.get("response"):
        return []
    players = data["response"][0].get("players", [])
    return [
        {
            "name": p.get("name", ""),
            "position": p.get("position", "") or "",
            "number": p.get("number"),
        }
        for p in players if p.get("name")
    ]


def get_squad_for_team(team_name: str) -> list[dict]:
    """
    Retourne l'effectif d'une équipe (cache disque 24h, clé = nom équipe + date).
    """
    if not config.API_FOOTBALL_KEY:
        return []

    today = date.today().isoformat()
    cache = _load_squads_cache()
    today_bucket = cache.get(today, {})

    if team_name in today_bucket:
        return today_bucket[team_name]

    # Cache miss
    team_id = get_team_id(team_name)
    if not team_id:
        today_bucket[team_name] = []
        cache = {today: today_bucket}
        _save_squads_cache(cache)
        return []

    squad = _fetch_squad(team_id)
    today_bucket[team_name] = squad
    cache = {today: today_bucket}  # purge des autres dates
    _save_squads_cache(cache)
    return squad


# ─────────────────────────────────────────────────────────────────────────────
# Recherche fixture_id et events (utilisé par fun_resolver)
# ─────────────────────────────────────────────────────────────────────────────

def _load_fixtures_cache() -> dict:
    if not FIXTURES_CACHE_FILE.exists():
        return {}
    try:
        with open(FIXTURES_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_fixtures_cache(cache: dict) -> None:
    try:
        FIXTURES_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FIXTURES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Enricher] Sauvegarde cache fixtures KO : {e}")


def _normalize_team(s: str) -> str:
    return (s or "").lower().strip()


def get_fixture_id(home_team: str, away_team: str, sport_key: str, match_date: str) -> int | None:
    """
    Trouve l'ID API-Football d'un match précis pour une date donnée.
    Utilise un cache disque par (date, league_id) pour réduire les appels.
    """
    if not config.API_FOOTBALL_KEY:
        return None

    league_id = LEAGUE_IDS.get(sport_key)
    if not league_id:
        return None

    season = _european_season()
    cache_key = f"{match_date}_{league_id}_{season}"

    cache = _load_fixtures_cache()
    fixtures = cache.get(cache_key)

    if fixtures is None:
        data = _get("fixtures", {"date": match_date, "league": league_id, "season": season})
        if not data or not data.get("response"):
            cache[cache_key] = []
            _save_fixtures_cache(cache)
            return None
        fixtures = []
        for f in data["response"]:
            fixtures.append({
                "id": f["fixture"]["id"],
                "home": f["teams"]["home"]["name"],
                "away": f["teams"]["away"]["name"],
            })
        cache[cache_key] = fixtures
        _save_fixtures_cache(cache)

    # Match approximatif sur les noms d'équipes
    bh = _normalize_team(home_team)
    ba = _normalize_team(away_team)
    for f in fixtures:
        fh = _normalize_team(f["home"])
        fa = _normalize_team(f["away"])
        if (bh in fh or fh in bh) and (ba in fa or fa in ba):
            return f["id"]
    return None


def get_fixture_events(fixture_id: int) -> dict:
    """
    Retourne les events d'un match :
      {
        "score": "2-1" | None,
        "scorers": [{"name", "team", "minute"}],
        "first_scorer_team": "home" | "away" | None,
      }
    """
    data = _get("fixtures", {"id": fixture_id})
    score = None
    home_team = away_team = ""
    if data and data.get("response"):
        f = data["response"][0]
        goals = f.get("goals") or {}
        h = goals.get("home")
        a = goals.get("away")
        if h is not None and a is not None:
            score = f"{h}-{a}"
        home_team = f["teams"]["home"]["name"]
        away_team = f["teams"]["away"]["name"]

    events_data = _get("fixtures/events", {"fixture": fixture_id})
    scorers: list[dict] = []
    first_scorer_team: str | None = None

    if events_data and events_data.get("response"):
        for ev in events_data["response"]:
            if ev.get("type") == "Goal" and ev.get("detail") not in ("Missed Penalty",):
                player = (ev.get("player") or {}).get("name") or ""
                team_name = (ev.get("team") or {}).get("name") or ""
                minute = (ev.get("time") or {}).get("elapsed")
                if not player:
                    continue
                scorers.append({"name": player, "team": team_name, "minute": minute})

        if scorers:
            first_team = scorers[0]["team"]
            if home_team and _normalize_team(first_team) == _normalize_team(home_team):
                first_scorer_team = "home"
            elif away_team and _normalize_team(first_team) == _normalize_team(away_team):
                first_scorer_team = "away"

    return {
        "score": score,
        "scorers": scorers,
        "first_scorer_team": first_scorer_team,
        "home_team": home_team,
        "away_team": away_team,
    }


def get_team_id(team_name: str) -> int | None:
    """Cherche l'ID d'une équipe par son nom (avec cache)."""
    if team_name in _team_id_cache:
        return _team_id_cache[team_name]
    data = _get("teams", {"search": team_name})
    if data and data.get("results", 0) > 0:
        tid = data["response"][0]["team"]["id"]
        _team_id_cache[team_name] = tid
        return tid
    _team_id_cache[team_name] = None
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
    Enrichit les matchs du jour avec des données fraîches.
    Priorise les top ligues et limite à MAX_ENRICHED_MATCHES pour
    rester dans le quota gratuit (100 req/jour/clé).
    """
    global _request_count, _current_key_index, _total_requests_made
    if not config.API_FOOTBALL_KEY:
        return ""

    # Reset compteurs
    _request_count = 0
    _current_key_index = 0
    _total_requests_made = 0
    n_keys = len(config.API_FOOTBALL_KEYS)
    total_quota = n_keys * QUOTA_PER_KEY

    # Trie les matchs : top ligues d'abord
    def priority_sort(m):
        sport_key = m.get("sport_key", "")
        if sport_key in PRIORITY_LEAGUES:
            return PRIORITY_LEAGUES.index(sport_key)
        return 999

    sorted_matches = sorted(matches, key=priority_sort)

    # Cap pour préserver le budget API
    if len(sorted_matches) > MAX_ENRICHED_MATCHES:
        skipped = len(sorted_matches) - MAX_ENRICHED_MATCHES
        sorted_matches = sorted_matches[:MAX_ENRICHED_MATCHES]
        print(f"[Enricher] Cap à {MAX_ENRICHED_MATCHES} matchs prioritaires "
              f"({skipped} match(s) hors top ligues ignorés pour économiser le quota).")

    print(f"[Enricher] {n_keys} clé(s) API-Football ({total_quota} req max)")
    print(f"[Enricher] Enrichissement de {len(sorted_matches)} match(s) (top ligues en priorité)...")

    lines = ["\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    lines.append("DONNÉES FRAÎCHES — API-FOOTBALL (injectées automatiquement)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    enriched_count = 0
    for match in sorted_matches:
        # Stop si plus de clés disponibles
        if _get_current_key() is None:
            remaining = len(sorted_matches) - enriched_count
            print(f"[Enricher] Quota total épuisé, {remaining} match(s) non enrichi(s).")
            break
        home_name = match["home"]
        away_name = match["away"]
        competition = match["competition"]

        lines.append(f"▶ {home_name} vs {away_name}  ({competition})")

        # Récupère les IDs des équipes
        home_id = get_team_id(home_name)
        away_id = get_team_id(away_name)

        enriched_count += 1

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

    n_keys = len(config.API_FOOTBALL_KEYS)
    keys_used = _current_key_index + 1 if _request_count > 0 else _current_key_index
    print(f"[Enricher] Terminé — {enriched_count} match(s) enrichi(s), "
          f"{_total_requests_made} requête(s) réelles utilisées "
          f"sur {keys_used}/{n_keys} clé(s).")
    return "\n".join(lines)
