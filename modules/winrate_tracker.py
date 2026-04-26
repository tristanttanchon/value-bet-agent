"""
Winrate Tracker — statistiques simples des pronos depuis Supabase.
Remplace stats_tracker.py (orienté bankroll/ROI) par une version light :
juste des compteurs de victoires/défaites et un winrate %.
"""

from modules.db import get_client


def get_winrate_stats(days: int | None = None) -> dict:
    """
    Retourne un résumé des pronos résolus.

    Args:
        days : si fourni, limite à ceux des N derniers jours (sur `date`).
               None = toute l'historique.

    Returns:
        {
          "total"       : pronos résolus (WIN + LOSS + PUSH),
          "wins"        : nombre de WIN,
          "losses"      : nombre de LOSS,
          "pushes"      : nombre de PUSH,
          "pending"     : nombre de pronos en attente,
          "winrate_pct" : % de victoires sur les résolus (hors PUSH)
        }
    """
    db = get_client()
    try:
        query = db.table("bets").select("status")
        if days is not None and days > 0:
            from datetime import date, timedelta
            cutoff = (date.today() - timedelta(days=days)).isoformat()
            query = query.gte("date", cutoff)
        resp = query.execute()
    except Exception as e:
        print(f"[WinrateTracker] Erreur lecture Supabase : {e}")
        return {"total": 0, "wins": 0, "losses": 0, "pushes": 0, "pending": 0, "winrate_pct": 0.0}

    rows = resp.data or []
    wins = sum(1 for r in rows if r.get("status") == "WIN")
    losses = sum(1 for r in rows if r.get("status") == "LOSS")
    pushes = sum(1 for r in rows if r.get("status") == "PUSH")
    pending = sum(1 for r in rows if r.get("status") == "PENDING")

    decisive = wins + losses  # PUSH exclu du calcul du winrate
    winrate_pct = (wins / decisive * 100) if decisive > 0 else 0.0

    return {
        "total": wins + losses + pushes,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "winrate_pct": winrate_pct,
    }


def record_pronos(pronos: list[dict]) -> None:
    """
    Enregistre les pronos du jour dans Supabase en statut PENDING.
    Pas de bankroll, pas de mise — juste le prono pour pouvoir le résoudre
    plus tard et suivre le winrate.
    """
    if not pronos:
        return

    db = get_client()
    from datetime import date
    today = date.today().isoformat()

    rows = []
    for p in pronos:
        rows.append({
            "date": today,
            "match": p.get("match", ""),
            "competition": p.get("competition", ""),
            "kickoff": p.get("kickoff", ""),
            "market": p.get("market", ""),
            "market_odds": float(p.get("market_odds", 0)) if p.get("market_odds") else None,
            "confidence": int(p.get("confidence", 0)) if p.get("confidence") else None,
            "status": "PENDING",
            "result": None,
            # Champs legacy (bankroll) : on les laisse null pour préserver le schéma
            "sim_stake": None,
            "model_probability": None,
            "edge": None,
            "data_reliability": None,
            "profit_loss": None,
            "bankroll_after": None,
        })

    try:
        db.table("bets").insert(rows).execute()
        print(f"[WinrateTracker] {len(rows)} prono(s) enregistré(s) en statut PENDING.")
    except Exception as e:
        print(f"[WinrateTracker] Erreur insertion Supabase : {e}")
