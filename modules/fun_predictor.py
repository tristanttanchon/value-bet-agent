"""
Fun Predictor — pronostics "pour le fun" sur les top 5 matchs les plus médiatiques
du jour. Score exact, buteurs probables, cartons rouges, corners, scénarios exotiques.

À NE PAS SUIVRE sérieusement — c'est pour le plaisir et la discussion.

Utilise un appel Gemini séparé avec un prompt dédié et retourne un unique
message formaté à envoyer sur Telegram.
"""

import signal
from datetime import date
from google import genai
from google.genai import types
import config


GEMINI_CALL_TIMEOUT = 180  # 3 min suffisent pour ce prompt plus court


class GeminiTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise GeminiTimeout("Appel Gemini fun timeout")


FUN_PROMPT = """
Tu es un pronostiqueur fun et audacieux qui fait des prédictions AMUSANTES pour
le plaisir. Ces pronos ne sont PAS à prendre au sérieux, ils sont là pour
animer la discussion entre amis.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MISSION

Parmi les matchs fournis, choisis les **5 matchs les plus médiatiques** (top
affiches du jour — les équipes les plus connues, les plus gros enjeux, les
dérbys, les chocs de classement).

Pour chaque match sélectionné, fournis des prédictions FUN :

  🎯 **Score exact prédit**         (ex: 2-1, 0-0, 3-2)
  ⚽ **2-3 buteurs probables**      (joueurs qui ont le plus de chance de marquer)
  🥇 **Qui marque en premier**      (équipe + intuition, "ex: 65% Liverpool")
  🟥 **Carton rouge ?**             (probable / improbable + joueur suspect si oui)
  🚩 **Corner count**               (estimation +/- : ex: "Plus de 9 corners")
  💥 **Prédiction bonus**           (un scénario marquant : "doublé de X", "but CSC",
                                     "penalty manqué", "but dans les 5 dernières min", etc.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚨 RÈGLE ABSOLUE SUR LES NOMS DE JOUEURS 🚨

Ta connaissance des effectifs date d'avant 2025 → tu vas inventer des joueurs
qui ne sont plus dans leur club si tu ne fais pas attention.

→ Pour citer un buteur, tu DOIS utiliser EXCLUSIVEMENT la liste **TOP BUTEURS
  ACTUELS** fournie ci-dessous (saison en cours, données API-Football vérifiées).
→ Si l'équipe d'un match n'est pas dans la liste : reste générique
  ("un attaquant", "le n°9", "un milieu offensif") — ne cite JAMAIS un nom
  que tu n'as pas vu dans la liste.
→ Pour les prédictions carton rouge / passeur / scénario bonus : même règle,
  cite uniquement des joueurs présents dans la liste, ou reste générique.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TON DE RÉDACTION

Sois dans le fun, un peu exagéré, accroche-cœur. Utilise des emojis. Donne
ton intuition même si elle est risquée — c'est fait pour ça ! Mais reste
factuel sur les NOMS de joueurs (cf. règle ci-dessus).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FORMAT DE SORTIE

Renvoie UNIQUEMENT un message formaté prêt à envoyer sur Telegram (markdown v1).
Pas de JSON, pas de préambule, pas de conclusion — juste le message.

Format exact attendu :

🎲 *PRONOS FUN DU JJ/MM/AAAA*
_Pour rire, pas pour parier !_

━━━━━━━━━━━━━━━━━━━

⚽ *Équipe A vs Équipe B*  |  HH:MM
🎯 Score : *2-1*
⚽ Buteurs : *Joueur1*, *Joueur2*, *Joueur3*
🥇 1er but : Équipe A (60%)
🟥 Carton rouge : Improbable
🚩 Corners : Plus de 10
💥 *Joueur X signe un doublé de la tête*

━━━━━━━━━━━━━━━━━━━

[... répéter pour chacun des 5 matchs ...]

━━━━━━━━━━━━━━━━━━━
⚠️ _Ces pronos sont purement récréatifs._
"""


def _format_topscorers_block(top_scorers: dict[str, list[dict]]) -> str:
    """Formate les top buteurs par compétition pour injection dans le prompt."""
    if not top_scorers:
        return ""

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "TOP BUTEURS ACTUELS — saison en cours (source : API-Football)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for comp, scorers in top_scorers.items():
        if not scorers:
            continue
        lines.append(f"🏆 {comp}")
        for s in scorers:
            lines.append(f"   - {s['name']}  ({s['team']})  →  {s['goals']} buts")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    return "\n".join(lines)


def build_fun_prompt(matches_text: str, top_scorers: dict[str, list[dict]] | None = None) -> str:
    today = date.today().strftime("%d/%m/%Y")
    scorers_block = _format_topscorers_block(top_scorers or {})
    return (
        f"DATE : {today}\n\n"
        f"MATCHS DU JOUR :\n\n{matches_text}\n\n"
        f"{scorers_block}"
        f"{FUN_PROMPT}"
    )


def generate_fun_predictions(matches_text: str, matches: list[dict] | None = None) -> str | None:
    """
    Génère un message Telegram contenant les pronos fun pour les top 5 matchs.

    Args:
        matches_text : texte formaté des matchs du jour (pour le prompt).
        matches      : liste brute des matchs (sert à détecter les ligues
                       distinctes pour pré-fetch des top buteurs réels).

    Retourne le message prêt à envoyer, ou None en cas d'échec.
    """
    # Pré-fetch des top buteurs (cachés 24h sur disque)
    top_scorers: dict[str, list[dict]] = {}
    if matches and config.API_FOOTBALL_KEY:
        try:
            from modules.data_enricher import get_top_scorers_for_competitions
            distinct_comps = sorted({m.get("competition", "") for m in matches if m.get("competition")})
            top_scorers = get_top_scorers_for_competitions(distinct_comps)
            print(f"[FunPredictor] Top buteurs récupérés pour {len(top_scorers)} ligue(s).")
        except Exception as e:
            print(f"[FunPredictor] Pré-fetch top buteurs KO (non bloquant) : {e}")

    prompt = build_fun_prompt(matches_text, top_scorers)

    gemini_keys = list(config.GEMINI_API_KEYS) if config.GEMINI_API_KEYS else []
    if not gemini_keys:
        print("[FunPredictor] Aucune clé Gemini configurée.")
        return None

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
                    "tools": [types.Tool(google_search=types.GoogleSearch())],
                    "temperature": 0.7,  # plus créatif pour le fun
                    "max_output_tokens": 16384,
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
        return None

    # Extraction texte
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

    full_text = full_text.strip()
    if not full_text:
        print("[FunPredictor] Réponse vide.")
        return None

    print(f"[FunPredictor] Message fun généré ({len(full_text)} car.)")
    return full_text
