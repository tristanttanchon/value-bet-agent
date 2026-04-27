"""
Fun Tracker — persistance Supabase des pronos fun (table `fun_predictions`).

Schéma attendu (cf. migrations/001_fun_predictions.sql) :
  id, date, competition, kickoff, match, home_team, away_team,
  fixture_id, predicted_score, predicted_scorers (jsonb),
  predicted_first_scorer_team, predicted_first_scorer_pct,
  bonus_scenario, status, actual_score, actual_scorers (jsonb),
  actual_first_scorer_team, score_correct, scorers_hit_count,
  scorers_predicted_count, first_scorer_correct, resolved_at, created_at
"""

from datetime import date, timedelta
from modules.db import get_client


def save_fun_predictions(predictions: list[dict]) -> int:
    """
    Enregistre les pronos fun du jour en statut PENDING.

    `predictions` doit avoir le format :
      [{
        "match": "Liverpool vs Arsenal",
        "competition": "Premier League",
        "kickoff": "20:45",
        "home_team": "Liverpool",
        "away_team": "Arsenal",
        "fixture_id": 12345 | None,
        "predicted_score": "2-1",
        "predicted_scorers": [{"name": "Salah", "team": "Liverpool"}, ...],
        "predicted_first_scorer_team": "home" | "away",
        "predicted_first_scorer_pct": 60,
        "bonus_scenario": "Salah marque sur penalty",
      }, ...]

    Retourne le nombre de lignes insérées.
    """
    if not predictions:
        return 0

    db = get_client()
    today = date.today().isoformat()

    rows = []
    for p in predictions:
        rows.append({
            "date": today,
            "competition": p.get("competition", ""),
            "kickoff": p.get("kickoff", ""),
            "match": p.get("match", ""),
            "home_team": p.get("home_team", ""),
            "away_team": p.get("away_team", ""),
            "fixture_id": p.get("fixture_id"),
            "predicted_score": p.get("predicted_score", ""),
            "predicted_scorers": p.get("predicted_scorers") or [],
            "predicted_first_scorer_team": p.get("predicted_first_scorer_team"),
            "predicted_first_scorer_pct": p.get("predicted_first_scorer_pct"),
            "bonus_scenario": p.get("bonus_scenario", ""),
            "status": "PENDING",
        })

    try:
        db.table("fun_predictions").insert(rows).execute()
        print(f"[FunTracker] {len(rows)} prono(s) fun enregistré(s) en PENDING.")
        return len(rows)
    except Exception as e:
        print(f"[FunTracker] Erreur insertion Supabase : {e}")
        return 0


def load_pending_for_date(target_date: str) -> list[dict]:
    """Charge les pronos fun PENDING d'une date donnée."""
    db = get_client()
    try:
        resp = (
            db.table("fun_predictions")
            .select("*")
            .eq("status", "PENDING")
            .eq("date", target_date)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[FunTracker] Erreur lecture Supabase : {e}")
        return []


def load_yesterday_pending() -> list[dict]:
    """Raccourci pour charger les pronos fun PENDING de la veille."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    return load_pending_for_date(yesterday)


def update_resolution(prediction_id: int, resolution: dict) -> None:
    """
    Met à jour une prédiction avec le résultat réel.

    `resolution` doit contenir :
      actual_score, actual_scorers (list), actual_first_scorer_team,
      score_correct (bool), scorers_hit_count (int),
      scorers_predicted_count (int), first_scorer_correct (bool)
    """
    db = get_client()
    payload = {
        "status": "RESOLVED",
        "actual_score": resolution.get("actual_score"),
        "actual_scorers": resolution.get("actual_scorers") or [],
        "actual_first_scorer_team": resolution.get("actual_first_scorer_team"),
        "score_correct": resolution.get("score_correct"),
        "scorers_hit_count": resolution.get("scorers_hit_count"),
        "scorers_predicted_count": resolution.get("scorers_predicted_count"),
        "first_scorer_correct": resolution.get("first_scorer_correct"),
        "resolved_at": "now()",
    }
    # Supabase Python ne fait pas l'expression "now()" — on laisse le default DB
    payload.pop("resolved_at", None)

    try:
        db.table("fun_predictions").update(payload).eq("id", prediction_id).execute()
    except Exception as e:
        print(f"[FunTracker] Erreur update id={prediction_id} : {e}")
