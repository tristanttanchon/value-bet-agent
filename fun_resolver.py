"""
fun_resolver.py — Résolution + récap Telegram des pronos fun de la veille.

Lancé chaque jour à 18h CEST par le workflow 18h-fun-recap.yml.

Flux :
  1. Charge depuis Supabase les pronos fun de la veille en statut PENDING
  2. Pour chaque prono avec un fixture_id : fetch score réel + buteurs
     (API-Football /fixtures + /fixtures/events)
  3. Compare prédictions vs réalité (score exact, buteurs trouvés, 1er but)
  4. Met à jour Supabase (status RESOLVED) + envoie un récap global Telegram
"""

import unicodedata
from datetime import date, timedelta

import config
from modules.fun_tracker import load_pending_for_date, update_resolution
from modules.telegram_reporter import send_message


def _normalize(s: str) -> str:
    """Lowercase + retire accents — pour matching des noms."""
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _name_match(predicted: str, actual: str) -> bool:
    """Match approximatif : un nom est trouvé si tous ses tokens >2 lettres
    sont présents dans le nom réel (ou vice-versa)."""
    p = _normalize(predicted)
    a = _normalize(actual)
    if not p or not a:
        return False
    if p == a or p in a or a in p:
        return True
    # Match par nom de famille (dernier token)
    p_tokens = [t for t in p.split() if len(t) > 2]
    a_tokens = [t for t in a.split() if len(t) > 2]
    if not p_tokens or not a_tokens:
        return False
    # Au moins 1 token commun de plus de 3 lettres
    common = set(p_tokens) & set(a_tokens)
    return any(len(t) > 3 for t in common)


def _evaluate(prediction: dict, events: dict) -> dict:
    """
    Compare une prédiction au résultat réel.
    Retourne le dict de résolution prêt pour update_resolution().
    """
    actual_score = events.get("score")
    actual_scorers = events.get("scorers") or []
    actual_first_team = events.get("first_scorer_team")

    predicted_score = (prediction.get("predicted_score") or "").strip()
    predicted_scorers = prediction.get("predicted_scorers") or []
    predicted_first_team = prediction.get("predicted_first_scorer_team")

    score_correct = bool(actual_score) and (predicted_score == actual_score)

    actual_names = [s.get("name", "") for s in actual_scorers if s.get("name")]
    hits = 0
    for ps in predicted_scorers:
        pname = ps.get("name", "") if isinstance(ps, dict) else str(ps)
        if any(_name_match(pname, an) for an in actual_names):
            hits += 1

    first_correct = bool(actual_first_team) and (predicted_first_team == actual_first_team)

    return {
        "actual_score": actual_score,
        "actual_scorers": [{"name": s.get("name"), "team": s.get("team"), "minute": s.get("minute")}
                           for s in actual_scorers],
        "actual_first_scorer_team": actual_first_team,
        "score_correct": score_correct,
        "scorers_hit_count": hits,
        "scorers_predicted_count": len(predicted_scorers),
        "first_scorer_correct": first_correct,
    }


def _build_recap_message(date_iso: str, results: list[dict]) -> str:
    """Construit le message Telegram de récap."""
    if not results:
        return f"🎲 *BILAN FUN PRONOS — {date_iso}*\n\n_Aucun prono résolu (résultats non disponibles)._"

    score_hits = sum(1 for r in results if r["resolution"]["score_correct"])
    total_scorers_hit = sum(r["resolution"]["scorers_hit_count"] for r in results)
    total_scorers_pred = sum(r["resolution"]["scorers_predicted_count"] for r in results)
    first_hits = sum(1 for r in results if r["resolution"]["first_scorer_correct"])
    n = len(results)

    lines = [
        f"🎲 *BILAN FUN PRONOS — {date_iso}*",
        "",
        f"✅ Scores exacts : *{score_hits}/{n}*",
        f"⚽ Buteurs trouvés : *{total_scorers_hit}/{total_scorers_pred}*",
        f"🥇 1er buteur correct : *{first_hits}/{n}*",
        "",
        "━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for r in results:
        pred = r["prediction"]
        res = r["resolution"]
        actual_score = res.get("actual_score") or "N/A"

        score_icon = "✅" if res["score_correct"] else "❌"
        first_icon = "✅" if res["first_scorer_correct"] else ("❌" if res.get("actual_first_scorer_team") else "—")

        lines.append(f"⚽ *{pred.get('home_team', '')} vs {pred.get('away_team', '')}*")
        lines.append(f"   {score_icon} Score : prédit *{pred.get('predicted_score', '?')}* — réel *{actual_score}*")

        # Buteurs
        n_pred = res["scorers_predicted_count"]
        n_hit = res["scorers_hit_count"]
        actual_scorers = res.get("actual_scorers") or []
        actual_names = ", ".join(s["name"] for s in actual_scorers if s.get("name")) or "aucun"
        lines.append(f"   ⚽ Buteurs : *{n_hit}/{n_pred}*  _(réels : {actual_names})_")

        lines.append(f"   🥇 1er but : {first_icon}")
        lines.append("")

    lines.append("_Les pronos fun sont récréatifs — pas pris en compte dans le winrate._")
    return "\n".join(lines)


def run_fun_resolver(target_date: str | None = None) -> None:
    """
    Résout les pronos fun de la date cible (par défaut : la veille).
    """
    if target_date is None:
        target_date = (date.today() - timedelta(days=1)).isoformat()

    print(f"\n🎲 Résolution des pronos fun du {target_date}...")
    pending = load_pending_for_date(target_date)
    if not pending:
        print(f"[FunResolver] Aucun prono fun PENDING pour {target_date}.")
        return

    print(f"[FunResolver] {len(pending)} prono(s) fun à résoudre.")

    # Lazy import pour éviter d'importer si rien à faire
    from modules.data_enricher import get_fixture_events, get_fixture_id

    results: list[dict] = []
    for p in pending:
        fixture_id = p.get("fixture_id")

        # Si pas de fixture_id (résolution échouée à la création) on retente
        if not fixture_id:
            fixture_id = get_fixture_id(
                p.get("home_team", ""),
                p.get("away_team", ""),
                # On essaie sans sport_key — la fonction va return None
                "",
                target_date,
            )

        if not fixture_id:
            print(f"[FunResolver] {p['match']} → fixture_id introuvable, skip.")
            continue

        events = get_fixture_events(fixture_id)
        if not events.get("score"):
            print(f"[FunResolver] {p['match']} → score non disponible, skip (match pas fini ?).")
            continue

        resolution = _evaluate(p, events)
        update_resolution(p["id"], resolution)
        results.append({"prediction": p, "resolution": resolution})

        score_ok = "✅" if resolution["score_correct"] else "❌"
        print(f"[FunResolver]   {score_ok} {p['match']} → {resolution['actual_score']} "
              f"(scorers {resolution['scorers_hit_count']}/{resolution['scorers_predicted_count']})")

    if not results:
        print("[FunResolver] Aucun prono résolu — pas de message envoyé.")
        return

    # Récap Telegram
    if config.TELEGRAM_BOT_TOKEN:
        message = _build_recap_message(target_date, results)
        send_message(message)
        print("[FunResolver] Récap Telegram envoyé.")


if __name__ == "__main__":
    run_fun_resolver()
