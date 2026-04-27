"""
Fun Predictor — pronostics "pour le fun" sur les top 5 matchs les plus
médiatiques du jour (score exact, buteurs, 1er buteur, scénario bonus).

À NE PAS SUIVRE sérieusement — c'est pour le plaisir et la discussion.

Pipeline :
  1. Pré-sélection en Python des 5 matchs les plus médiatiques (priorité ligue)
  2. Pré-fetch des effectifs des 10 équipes via API-Football (cache 24h)
  3. Pré-fetch des fixture_id (pour la résolution future)
  4. Appel Gemini avec prompt structuré + injection des effectifs réels
  5. Parsing JSON → message Telegram + persistance Supabase
"""

import json
import re
import signal
from datetime import date
from google import genai
from google.genai import types
import config


GEMINI_CALL_TIMEOUT = 180


# Hiérarchie de "médiatisme" — plus le score est bas, plus le match est prioritaire
MEDIA_PRIORITY = {
    "soccer_uefa_champs_league": 0,
    "soccer_uefa_europa_league": 1,
    "soccer_uefa_conference_league": 2,
    "soccer_epl": 3,
    "soccer_spain_la_liga": 4,
    "soccer_italy_serie_a": 5,
    "soccer_germany_bundesliga": 6,
    "soccer_france_ligue_one": 7,
    # secondaire
    "soccer_netherlands_eredivisie": 12,
    "soccer_portugal_primeira_liga": 13,
    "soccer_belgium_first_div": 14,
    "soccer_england_championship": 15,
    "soccer_turkey_super_lig": 16,
}

TOP_FUN_MATCHES = 5


class GeminiTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise GeminiTimeout("Appel Gemini fun timeout")


# ─────────────────────────────────────────────────────────────────────────────
# Pré-sélection des top matchs médiatiques
# ─────────────────────────────────────────────────────────────────────────────

def _media_score(match: dict) -> int:
    return MEDIA_PRIORITY.get(match.get("sport_key", ""), 99)


def _select_top_mediatic(matches: list[dict], n: int = TOP_FUN_MATCHES) -> list[dict]:
    sorted_matches = sorted(matches, key=_media_score)
    return sorted_matches[:n]


# ─────────────────────────────────────────────────────────────────────────────
# Mise en forme des effectifs pour injection prompt
# ─────────────────────────────────────────────────────────────────────────────

def _format_squad_block(team_name: str, squad: list[dict]) -> str:
    """Formate un effectif groupé par poste (Attaquants, Milieux, Défenseurs, Gardiens)."""
    if not squad:
        return f"🏟️ {team_name}\n   (effectif non disponible)"

    by_pos: dict[str, list[str]] = {
        "Attaquants": [],
        "Milieux": [],
        "Défenseurs": [],
        "Gardiens": [],
    }
    for p in squad:
        pos = (p.get("position") or "").lower()
        name = p.get("name", "")
        if not name:
            continue
        if pos.startswith("att") or "forward" in pos:
            by_pos["Attaquants"].append(name)
        elif pos.startswith("mil") or "midfield" in pos:
            by_pos["Milieux"].append(name)
        elif pos.startswith("déf") or pos.startswith("def"):
            by_pos["Défenseurs"].append(name)
        elif pos.startswith("gar") or "goal" in pos:
            by_pos["Gardiens"].append(name)
        else:
            by_pos["Milieux"].append(name)  # fallback

    lines = [f"🏟️ {team_name}"]
    for pos_label, names in by_pos.items():
        if names:
            lines.append(f"   {pos_label} : {', '.join(names)}")
    return "\n".join(lines)


def _build_squads_section(top_matches: list[dict], squads_by_team: dict[str, list[dict]]) -> str:
    if not squads_by_team:
        return ""

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "EFFECTIFS DES ÉQUIPES (saison en cours, données API-Football vérifiées)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    seen = set()
    for m in top_matches:
        for team in (m["home"], m["away"]):
            if team in seen:
                continue
            seen.add(team)
            lines.append(_format_squad_block(team, squads_by_team.get(team, [])))
            lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Gemini (sortie JSON)
# ─────────────────────────────────────────────────────────────────────────────

FUN_PROMPT_INSTRUCTIONS = """
Tu es un pronostiqueur fun et audacieux. Tes prédictions sont AMUSANTES et
audacieuses — pas à prendre au sérieux, juste pour animer la discussion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MISSION

Pour CHACUN des matchs listés sous "MATCHS À PRONOSTIQUER" (5 matchs au total),
tu génères un prono fun structuré.

Pour chaque match :

  • predicted_score : score exact (ex: "2-1", "0-0", "3-2")
  • predicted_scorers : 2-3 buteurs probables (objet { name, team })
  • predicted_first_scorer_team : "home" ou "away"
  • predicted_first_scorer_pct : entier 50-80 (ton intuition)
  • bonus_scenario : 1 phrase fun (ex: "Salah signe un doublé", "but CSC à la 89e",
                     "penalty manqué", "but dans les 5 dernières minutes", etc.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚨 RÈGLE ABSOLUE SUR LES NOMS DE JOUEURS 🚨

Ta connaissance des effectifs date d'avant 2025. Sans la liste injectée
ci-dessous, tu vas inventer des joueurs qui ne sont plus dans leur club.

→ Tu DOIS utiliser EXCLUSIVEMENT des noms présents dans la section
  "EFFECTIFS DES ÉQUIPES" (ci-dessus dans le prompt).
→ Pour predicted_scorers : pioche dans les attaquants/milieux des effectifs.
→ Pour bonus_scenario : si tu cites un nom, il DOIT venir des effectifs
  fournis. Sinon reste générique ("le n°9", "un défenseur").
→ Si un effectif est marqué "(effectif non disponible)" → uniquement noms
  génériques pour cette équipe.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FORMAT DE SORTIE (JSON STRICT, rien d'autre)

{
  "predictions": [
    {
      "match_index": 0,
      "predicted_score": "2-1",
      "predicted_scorers": [
        { "name": "Mohamed Salah", "team": "Liverpool" },
        { "name": "Bukayo Saka",   "team": "Arsenal"  }
      ],
      "predicted_first_scorer_team": "home",
      "predicted_first_scorer_pct": 60,
      "bonus_scenario": "Salah signe un doublé sur penalty"
    },
    ... (5 entrées au total, dans le même ordre que MATCHS À PRONOSTIQUER)
  ]
}

Renvoie UNIQUEMENT ce JSON, sans préambule, sans markdown, sans commentaire.
"""


def _build_top_matches_block(top_matches: list[dict]) -> str:
    lines = ["MATCHS À PRONOSTIQUER (5) :", ""]
    for i, m in enumerate(top_matches):
        lines.append(
            f"[{i}] {m['home']} vs {m['away']}  |  "
            f"{m.get('competition', '—')}  |  "
            f"Coup d'envoi : {m.get('kickoff', '—')}"
        )
    lines.append("")
    return "\n".join(lines)


def _build_prompt(top_matches: list[dict], squads_section: str) -> str:
    today = date.today().strftime("%d/%m/%Y")
    return (
        f"DATE : {today}\n\n"
        f"{_build_top_matches_block(top_matches)}"
        f"{squads_section}"
        f"{FUN_PROMPT_INSTRUCTIONS}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Parsing du JSON Gemini
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    # Strip markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    # Premier objet JSON
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception as e:
        print(f"[FunPredictor] JSON invalide : {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Formatage du message Telegram à partir du JSON
# ─────────────────────────────────────────────────────────────────────────────

def _format_telegram_message(predictions: list[dict]) -> str:
    today = date.today().strftime("%d/%m/%Y")
    lines = [
        f"🎲 *PRONOS FUN DU {today}*",
        "_Pour rire, pas pour parier !_",
        "",
        "━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for p in predictions:
        scorers_names = [s.get("name", "") for s in (p.get("predicted_scorers") or []) if s.get("name")]
        scorers_str = ", ".join(f"*{n}*" for n in scorers_names) or "—"

        first_team_label = p.get("home_team", "") if p.get("predicted_first_scorer_team") == "home" else p.get("away_team", "")
        first_pct = p.get("predicted_first_scorer_pct") or 50

        kickoff = p.get("kickoff") or "—"

        lines.append(f"⚽ *{p.get('home_team', '')} vs {p.get('away_team', '')}*  |  {kickoff}")
        lines.append(f"🎯 Score : *{p.get('predicted_score', '?')}*")
        lines.append(f"⚽ Buteurs : {scorers_str}")
        lines.append(f"🥇 1er but : {first_team_label} ({first_pct}%)")
        if p.get("bonus_scenario"):
            lines.append(f"💥 _{p['bonus_scenario']}_")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━")
        lines.append("")

    lines.append("⚠️ _Ces pronos sont purement récréatifs._")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Appel Gemini (avec rotation clés + fallback modèles)
# ─────────────────────────────────────────────────────────────────────────────

def _call_gemini(prompt: str) -> str:
    gemini_keys = list(config.GEMINI_API_KEYS) if config.GEMINI_API_KEYS else []
    if not gemini_keys:
        print("[FunPredictor] Aucune clé Gemini configurée.")
        return ""

    models_to_try = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]
    response = None

    for key_index, api_key in enumerate(gemini_keys):
        if response is not None:
            break
        try:
            client = genai.Client(api_key=api_key)
        except Exception as e:
            print(f"[FunPredictor] Client KO clé #{key_index + 1} : {e}")
            continue

        for model_name in models_to_try:
            if response is not None:
                break
            try:
                gen_config_kwargs = {
                    "temperature": 0.7,
                    "max_output_tokens": 16384,
                    "response_mime_type": "application/json",
                }
                if "2.5" in model_name or "flash-preview" in model_name:
                    try:
                        gen_config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                    except Exception:
                        pass

                try:
                    signal.signal(signal.SIGALRM, _timeout_handler)
                    signal.alarm(GEMINI_CALL_TIMEOUT)
                except (AttributeError, OSError):
                    pass

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**gen_config_kwargs),
                )

                try:
                    signal.alarm(0)
                except (AttributeError, OSError):
                    pass

                print(f"[FunPredictor] Modèle {model_name} (clé #{key_index + 1}) OK")
                break
            except Exception as e:
                try:
                    signal.alarm(0)
                except (AttributeError, OSError):
                    pass
                err = str(e).lower()
                if "resource_exhausted" in err or "429" in err:
                    print(f"[FunPredictor] Quota épuisé clé #{key_index + 1}, rotation...")
                    break
                print(f"[FunPredictor] {model_name} erreur : {e}")

    if response is None:
        print("[FunPredictor] Aucun modèle disponible.")
        return ""

    full_text = ""
    try:
        if response.text:
            full_text = response.text
    except Exception:
        pass
    if not full_text:
        try:
            for candidate in (response.candidates or []):
                if not candidate or not candidate.content:
                    continue
                for part in (candidate.content.parts or []):
                    if hasattr(part, "text") and part.text:
                        if hasattr(part, "thought") and part.thought:
                            continue
                        full_text += part.text
        except Exception as e:
            print(f"[FunPredictor] Extraction texte KO : {e}")

    return full_text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée principal
# ─────────────────────────────────────────────────────────────────────────────

def generate_fun_predictions(matches: list[dict]) -> tuple[str, list[dict]]:
    """
    Génère les pronos fun sur les 5 matchs les plus médiatiques.

    Retourne :
      (telegram_message, structured_predictions)
      - telegram_message : str prêt à envoyer (ou "" si échec)
      - structured_predictions : list[dict] enrichie avec les infos
                                 nécessaires pour persistance + résolution.
                                 Vide si échec.
    """
    if not matches:
        return "", []

    # 1. Pré-sélection
    top_matches = _select_top_mediatic(matches, TOP_FUN_MATCHES)
    if not top_matches:
        return "", []

    print(f"[FunPredictor] {len(top_matches)} match(s) sélectionné(s) pour les pronos fun.")
    for i, m in enumerate(top_matches):
        print(f"  [{i}] {m['home']} vs {m['away']} ({m.get('competition', '')})")

    # 2. Pré-fetch effectifs (cache 24h)
    squads_by_team: dict[str, list[dict]] = {}
    if config.API_FOOTBALL_KEY:
        try:
            from modules.data_enricher import get_squad_for_team
            for m in top_matches:
                for team in (m["home"], m["away"]):
                    if team not in squads_by_team:
                        squads_by_team[team] = get_squad_for_team(team)
            n_with_squad = sum(1 for s in squads_by_team.values() if s)
            print(f"[FunPredictor] Effectifs récupérés pour {n_with_squad}/{len(squads_by_team)} équipes.")
        except Exception as e:
            print(f"[FunPredictor] Pré-fetch effectifs KO (non bloquant) : {e}")

    # 3. Pré-fetch fixture_ids (pour résolution future)
    fixture_ids: list[int | None] = []
    if config.API_FOOTBALL_KEY:
        try:
            from modules.data_enricher import get_fixture_id
            today_iso = date.today().isoformat()
            for m in top_matches:
                fid = get_fixture_id(m["home"], m["away"], m.get("sport_key", ""), today_iso)
                fixture_ids.append(fid)
            n_resolved = sum(1 for f in fixture_ids if f)
            print(f"[FunPredictor] fixture_id résolus : {n_resolved}/{len(top_matches)}")
        except Exception as e:
            print(f"[FunPredictor] Pré-fetch fixture_ids KO (non bloquant) : {e}")
            fixture_ids = [None] * len(top_matches)
    else:
        fixture_ids = [None] * len(top_matches)

    # 4. Construction prompt + appel Gemini
    squads_section = _build_squads_section(top_matches, squads_by_team)
    prompt = _build_prompt(top_matches, squads_section)

    raw = _call_gemini(prompt)
    if not raw:
        return "", []

    parsed = _extract_json(raw)
    if not parsed or "predictions" not in parsed:
        print("[FunPredictor] JSON Gemini illisible ou sans 'predictions'.")
        return "", []

    raw_predictions = parsed.get("predictions") or []
    if not raw_predictions:
        return "", []

    # 5. Fusion avec les infos des matchs (kickoff, équipes, fixture_id)
    structured: list[dict] = []
    for i, raw_pred in enumerate(raw_predictions[:TOP_FUN_MATCHES]):
        idx = raw_pred.get("match_index", i)
        if idx >= len(top_matches):
            idx = i
        m = top_matches[idx]
        structured.append({
            "match": f"{m['home']} vs {m['away']}",
            "competition": m.get("competition", ""),
            "kickoff": m.get("kickoff", ""),
            "home_team": m["home"],
            "away_team": m["away"],
            "fixture_id": fixture_ids[idx] if idx < len(fixture_ids) else None,
            "predicted_score": raw_pred.get("predicted_score", ""),
            "predicted_scorers": raw_pred.get("predicted_scorers") or [],
            "predicted_first_scorer_team": raw_pred.get("predicted_first_scorer_team"),
            "predicted_first_scorer_pct": raw_pred.get("predicted_first_scorer_pct"),
            "bonus_scenario": raw_pred.get("bonus_scenario", ""),
        })

    message = _format_telegram_message(structured)
    print(f"[FunPredictor] Message fun généré ({len(structured)} prédictions).")
    return message, structured
