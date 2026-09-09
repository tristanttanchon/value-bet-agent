"""
keepalive.py — Ping Supabase pour éviter l'auto-pause après 7j d'inactivité.

Lancé par le workflow `.github/workflows/keepalive.yml` tous les 3-4 jours.
Fait une requête minimale sur `bets` pour montrer à Supabase que la base
est encore utilisée. Retourne exit code 0 si OK, 1 si Supabase KO.
"""

import sys
from modules.db import get_client


def ping_supabase() -> bool:
    try:
        db = get_client()
        # Requête minimale : count sur bets (ne rapatrie pas les lignes)
        resp = db.table("bets").select("id", count="exact").limit(1).execute()
        n = resp.count or 0
        print(f"[Keepalive] ✅ Supabase répond — {n} ligne(s) dans `bets`.")
        return True
    except Exception as e:
        print(f"[Keepalive] ❌ Supabase KO : {e}")
        return False


if __name__ == "__main__":
    ok = ping_supabase()
    sys.exit(0 if ok else 1)
