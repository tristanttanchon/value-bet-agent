import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
BANKROLL_FILE = DATA_DIR / "bankroll.json"
BETS_LOG_FILE = DATA_DIR / "bets_log.csv"

# API Keys — supporte plusieurs clés Gemini séparées par virgule (rotation auto)
_gemini_raw = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEYS = [k.strip() for k in _gemini_raw.split(",") if k.strip()]
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else None

# Supporte plusieurs clés Odds API séparées par virgule (rotation auto)
_odds_raw = os.getenv("ODDS_API_KEY", "")
ODDS_API_KEYS = [k.strip() for k in _odds_raw.split(",") if k.strip()]
ODDS_API_KEY = ODDS_API_KEYS[0] if ODDS_API_KEYS else None

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Supporte plusieurs clés API-Football séparées par virgule (rotation auto)
_football_raw = os.getenv("API_FOOTBALL_KEY", "")
API_FOOTBALL_KEYS = [k.strip() for k in _football_raw.split(",") if k.strip()]
API_FOOTBALL_KEY = API_FOOTBALL_KEYS[0] if API_FOOTBALL_KEYS else None

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://hltoumodbdpxqespjcsb.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Simulation settings
INITIAL_BANKROLL = 50.0
MIN_EDGE_THRESHOLD = 0.05   # 5% minimum pour jouer
MAX_KELLY_FRACTION = 0.25   # Kelly fractionnée x0.25
MAX_BET_PCT = 0.05          # 5% max du bankroll par pari
MIN_STAKE = 0.10            # Mise minimale 10 centimes

# Scheduler
ANALYSIS_HOUR = 12

# Compétitions suivies (clés The Odds API)
COMPETITION_KEYS = [
    # Ligues européennes majeures
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    # Coupes européennes UEFA
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_conference_league",
    # Coupes nationales
    "soccer_england_fa_cup",
    "soccer_spain_copa_del_rey",
    "soccer_italy_coppa_italia",
    "soccer_germany_dfb_pokal",
    "soccer_france_coupe_de_france",
    # Ligues européennes secondaires (moins efficientes = plus d'edge)
    "soccer_england_championship",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_turkey_super_lig",
    "soccer_belgium_first_div",
    # Amériques
    "soccer_conmebol_copa_libertadores",
    "soccer_conmebol_copa_sudamericana",
    "soccer_brazil_campeonato",
    "soccer_argentina_primera_division",
    "soccer_mexico_ligamx",
]

COMPETITION_NAMES = {
    # Ligues européennes majeures
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "La Liga",
    "soccer_italy_serie_a": "Serie A",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_france_ligue_one": "Ligue 1",
    # Coupes UEFA
    "soccer_uefa_champs_league": "Ligue des Champions",
    "soccer_uefa_europa_league": "Europa League",
    "soccer_uefa_conference_league": "Conference League",
    # Coupes nationales
    "soccer_england_fa_cup": "FA Cup",
    "soccer_spain_copa_del_rey": "Copa del Rey",
    "soccer_italy_coppa_italia": "Coppa Italia",
    "soccer_germany_dfb_pokal": "DFB Pokal",
    "soccer_france_coupe_de_france": "Coupe de France",
    # Ligues européennes secondaires
    "soccer_england_championship": "Championship",
    "soccer_netherlands_eredivisie": "Eredivisie",
    "soccer_portugal_primeira_liga": "Liga Portugal",
    "soccer_turkey_super_lig": "Süper Lig",
    "soccer_belgium_first_div": "Jupiler Pro League",
    # Amériques
    "soccer_conmebol_copa_libertadores": "Copa Libertadores",
    "soccer_conmebol_copa_sudamericana": "Copa Sudamericana",
    "soccer_brazil_campeonato": "Brasileirao",
    "soccer_argentina_primera_division": "Primera División Argentine",
    "soccer_mexico_ligamx": "Liga MX",
}
