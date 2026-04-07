"""
db.py — Client Supabase centralisé.
Remplace les fichiers locaux (CSV, JSON) par une base de données cloud.
"""

from supabase import create_client, Client
import config

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise ValueError("SUPABASE_URL et SUPABASE_KEY doivent être définis dans .env")
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client
