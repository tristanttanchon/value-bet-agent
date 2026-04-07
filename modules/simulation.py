"""
Simulation — gère le bankroll virtuel et le journal des paris via Supabase.
"""

from datetime import date
import config
from modules.db import get_client


# ─────────────────────────────────────────────────────────────────────────────
# Bankroll
# ─────────────────────────────────────────────────────────────────────────────

def load_bankroll() -> dict:
    db = get_client()
    resp = db.table("bankroll").select("*").eq("id", 1).execute()
    if resp.data:
        return resp.data[0]
    return _create_bankroll()


def save_bankroll(state: dict) -> None:
    db = get_client()
    state["id"] = 1
    db.table("bankroll").upsert(state).execute()


def _create_bankroll() -> dict:
    state = {
        "id": 1,
        "initial": config.INITIAL_BANKROLL,
        "current": config.INITIAL_BANKROLL,
        "reserved": 0.0,
        "total_bets": 0,
        "wins": 0,
        "losses": 0,
        "pending": 0,
        "total_staked": 0.0,
        "total_returned": 0.0,
    }
    save_bankroll(state)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Enregistrement des paris
# ─────────────────────────────────────────────────────────────────────────────

def record_bets(bets: list[dict]) -> dict:
    """
    Enregistre les paris dans Supabase et met à jour le bankroll.
    Les paris sont en statut PENDING en attendant résolution.
    """
    db = get_client()
    bankroll = load_bankroll()
    today = date.today().isoformat()

    rows = []
    for bet in bets:
        stake = float(bet.get("sim_stake", 0))
        bankroll["reserved"] = round(bankroll.get("reserved", 0) + stake, 2)
        bankroll["total_bets"] += 1
        bankroll["pending"] += 1
        bankroll["total_staked"] = round(bankroll.get("total_staked", 0) + stake, 2)

        rows.append({
            "date": today,
            "match": bet.get("match", ""),
            "competition": bet.get("competition", ""),
            "kickoff": bet.get("kickoff", ""),
            "market": bet.get("market", ""),
            "model_probability": float(bet.get("model_probability", 0)) if bet.get("model_probability") else None,
            "market_odds": float(bet.get("market_odds", 0)) if bet.get("market_odds") else None,
            "edge": f"{float(bet.get('edge', 0)):.1%}",
            "confidence": int(bet.get("confidence", 0)) if bet.get("confidence") else None,
            "data_reliability": bet.get("data_reliability", ""),
            "sim_stake": round(stake, 2),
            "status": "PENDING",
            "result": None,
            "profit_loss": None,
            "bankroll_after": None,
        })

    if rows:
        db.table("bets").insert(rows).execute()

    save_bankroll(bankroll)
    return bankroll


# ─────────────────────────────────────────────────────────────────────────────
# Résolution manuelle d'un pari
# ─────────────────────────────────────────────────────────────────────────────

def resolve_bet(match: str, market: str, won: bool) -> str:
    """
    Marque un pari PENDING comme gagné (WIN) ou perdu (LOSS).
    """
    db = get_client()
    resp = db.table("bets").select("*").eq("status", "PENDING").execute()
    pending = resp.data or []

    target = None
    for row in pending:
        if match.lower() in row["match"].lower() and market.lower() in row["market"].lower():
            target = row
            break

    if not target:
        return f"Pari non trouvé : '{match}' — '{market}'"

    stake = float(target["sim_stake"])
    odds = float(target["market_odds"])
    bankroll = load_bankroll()

    if won:
        profit = round(stake * odds - stake, 2)
        bankroll["wins"] += 1
        bankroll["total_returned"] = round(bankroll.get("total_returned", 0) + stake * odds, 2)
    else:
        profit = -stake
        bankroll["losses"] += 1

    bankroll["current"] = round(bankroll["current"] + profit, 2)
    bankroll["reserved"] = round(bankroll.get("reserved", 0) - stake, 2)
    bankroll["pending"] -= 1
    save_bankroll(bankroll)

    db.table("bets").update({
        "status": "WIN" if won else "LOSS",
        "result": "Gagné" if won else "Perdu",
        "profit_loss": profit,
        "bankroll_after": bankroll["current"],
    }).eq("id", target["id"]).execute()

    return f"Pari résolu : {'WIN' if won else 'LOSS'}"
