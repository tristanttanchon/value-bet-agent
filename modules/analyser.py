"""
Analyser — envoie les matchs du jour à Gemini 2.5 Flash avec le master prompt
Pronostiqueur. Retourne 4-5 pronos avec fort taux de confiance, 1 par match,
sur les marchés 1X2, Over/Under 2.5 et Double Chance.

Pas de calcul d'edge, pas de Kelly, pas de bankroll — juste des prédictions
argumentées que l'utilisateur suivra ou non.
"""

import re
import json
import signal
from datetime import date
from google import genai
from google.genai import types
import config


# ─────────────────────────────────────────────────────────────────────────────
# Timeout pour les appels API (évite les hangs infinis)
# ─────────────────────────────────────────────────────────────────────────────
GEMINI_CALL_TIMEOUT = 300  # 5 minutes max par appel


class GeminiTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise GeminiTimeout("Appel Gemini timeout après 5 minutes")


# ─────────────────────────────────────────────────────────────────────────────
# MASTER PROMPT — PRONOSTIQUEUR
# ─────────────────────────────────────────────────────────────────────────────

MASTER_PROMPT = """
Tu es un Expert Pronostiqueur Football réputé pour ton taux de réussite élevé.
Ta mission : sélectionner les 4 à 5 MEILLEURS pronostics du jour parmi les matchs
fournis. Un seul pronostic par match — celui sur lequel tu es le plus confiant.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OBJECTIF : VISER UN TAUX DE RÉUSSITE ÉLEVÉ (> 65%)

Tu n'es pas là pour chasser la grosse cote ou prendre des risques. Tu es là pour
identifier les pronostics les plus SÛRS possibles. Privilégie systématiquement :
  • Les favoris très solides à domicile
  • Les Double Chance quand le match est serré (1X ou X2 réduit le risque)
  • Les Over/Under 2.5 quand le profil offensif/défensif des deux équipes est clair
  • Les matchs où tu as des informations fiables (forme, absences, H2H clairs)

Évite absolument :
  ✗ Les paris "coup de coeur" sans fondement factuel
  ✗ Les matchs avec trop de données manquantes
  ✗ Les scénarios improbables (outsider à grosse cote, etc.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MARCHÉS AUTORISÉS (3 uniquement)

1. **1X2** (issue du match)
   • "1" = victoire équipe domicile
   • "X" = match nul
   • "2" = victoire équipe extérieur

2. **Over/Under 2.5 buts**
   • "Over 2.5"  = 3 buts ou plus dans le match
   • "Under 2.5" = 2 buts ou moins dans le match

3. **Double Chance** (deux issues possibles couvertes)
   • "1X" = victoire domicile OU nul
   • "12" = victoire domicile OU victoire extérieur (pas de nul)
   • "X2" = nul OU victoire extérieur

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 1 — ANALYSE DE CHAQUE MATCH

Pour chaque match fourni, étudie :
  • Forme récente (5 derniers matchs) des deux équipes
  • H2H (5 dernières confrontations)
  • Absences clés (blessés, suspendus) et impact tactique
  • Contexte (enjeu, fatigue, rotations coupe, motivation)
  • Style de jeu (offensif/défensif) — utile pour Over/Under
  • Domicile/extérieur : performances respectives
  • Cotes du marché (indicateur de probabilité perçue)

Exploite les DONNÉES ENRICHIES fournies dans le prompt (blessés, xG, forme API-Football).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 2 — SÉLECTION DES 4-5 MEILLEURS PRONOS

Parmi tous les matchs analysés, sélectionne UNIQUEMENT les 4 à 5 pronostics sur
lesquels tu as le plus de confiance. Pour chaque match retenu :

  1. Choisis LE SEUL marché où tu es le plus confiant
  2. Attribue une note de confiance de 1 à 5 étoiles :
     ⭐        = 1/5 — Faible, à éviter (ne retiens pas ce prono)
     ⭐⭐       = 2/5 — Moyen, à éviter
     ⭐⭐⭐      = 3/5 — Correct, jouable avec réserve
     ⭐⭐⭐⭐     = 4/5 — Fort, recommandé
     ⭐⭐⭐⭐⭐    = 5/5 — Très fort, haute conviction

  IMPORTANT : ne retiens QUE les pronos notés 3/5 ou plus.
  Si tu n'as aucun prono ≥ 3/5, renvoie une liste vide.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 3 — RAPPORT DÉTAILLÉ PAR MATCH RETENU

Pour chaque prono sélectionné, rédige une analyse complète (250-400 mots) en
markdown simple. Structure recommandée :

  ## Contexte
  (Compétition, enjeu, forme générale, classement)

  ## Forme récente
  (5 derniers matchs chaque équipe, tendances)

  ## Facteurs clés
  (Absences, H2H, duels décisifs, conditions)

  ## Pourquoi ce prono
  (Justification factuelle du choix de marché)

  ## Facteurs de risque
  (Ce qui pourrait faire perdre ce prono)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 4 — SORTIE JSON STRUCTURÉE (À LA FIN DE TA RÉPONSE)

Conclus ta réponse par un bloc JSON valide, délimité par ```json et ```.

Format EXACT à respecter :

```json
{
  "analysis_date": "YYYY-MM-DD",
  "pronos": [
    {
      "match": "Équipe A vs Équipe B",
      "competition": "Nom compétition",
      "kickoff": "HH:MM",
      "market": "1|X|2|Over 2.5|Under 2.5|1X|12|X2",
      "market_odds": 1.85,
      "confidence": 4,
      "analysis": "Analyse markdown complète 250-400 mots avec les sections Contexte / Forme récente / Facteurs clés / Pourquoi ce prono / Facteurs de risque. Utilise **gras** pour les points importants, ## pour les sous-titres, - pour les puces."
    }
  ],
  "skipped_matches": ["match1 (raison)", "match2 (raison)"]
}
```

Règles :
  • 4 à 5 éléments dans "pronos" (idéalement 5 pour maximiser la diversité)
  • Si aucun prono ≥ 3/5 de confiance, renvoie "pronos": []
  • "market_odds" = la cote du marché choisi telle que fournie (pour info)
  • "analysis" est OBLIGATOIRE — elle sera publiée sur Telegraph

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RAPPELS FONDAMENTAUX
— Tu cherches la FIABILITÉ, pas le gain maximum.
— Si un match est trop incertain, ne le retiens pas.
— Un prono à 5⭐ sur un favori solide vaut mieux qu'un prono à 3⭐ sur un outsider.
— Justifie toujours factuellement (données, forme, absences), jamais "au feeling".
— Utilise 1 seul marché par match : le plus sûr.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions
# ─────────────────────────────────────────────────────────────────────────────

def build_prompt(matches_text: str) -> str:
    today = date.today().isoformat()
    return (
        f"ANALYSE DU {today}\n\n"
        f"Voici les matchs du jour avec leurs meilleures cotes de marché :\n\n"
        f"{matches_text}\n"
        f"{MASTER_PROMPT}"
    )


def extract_json_block(text: str) -> list[dict]:
    """
    Extrait la liste `pronos` du bloc JSON structuré renvoyé par Gemini.
    """
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```JSON\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return data.get("pronos", [])
            except json.JSONDecodeError:
                continue

    # Fallback : recherche du dernier objet contenant "pronos"
    idx = text.rfind('"pronos"')
    if idx != -1:
        start = text.rfind('{', 0, idx)
        if start != -1:
            depth = 0
            in_string = False
            escape = False
            end = -1
            for i in range(start, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == '\\':
                    escape = True
                    continue
                if c == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                try:
                    data = json.loads(text[start:end])
                    return data.get("pronos", [])
                except json.JSONDecodeError as e:
                    print(f"[Analyser] Erreur JSON (brace matching) : {e}")

    print("[Analyser] Avertissement : aucun bloc JSON trouvé dans la réponse.")
    print(f"[Analyser] Fin de la réponse (debug) :\n---\n{text[-500:]}\n---")
    return []


def analyse_matches(matches_text: str) -> tuple[str, list[dict]]:
    """
    Envoie les matchs à Gemini et retourne (texte_complet, liste_pronos).
    Supporte la rotation multi-clés Gemini.
    """
    prompt = build_prompt(matches_text)

    import time

    gemini_keys = list(config.GEMINI_API_KEYS) if config.GEMINI_API_KEYS else []
    if not gemini_keys:
        raise RuntimeError("[Analyser] Aucune clé GEMINI_API_KEY configurée.")
    print(f"[Analyser] {len(gemini_keys)} clé(s) Gemini disponible(s).")

    models_to_try = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]
    response = None

    for key_index, api_key in enumerate(gemini_keys):
        if response is not None:
            break
        client = genai.Client(api_key=api_key)
        print(f"[Analyser] Utilisation clé Gemini #{key_index + 1}")

        for model_name in models_to_try:
            if response is not None:
                break
            print(f"[Analyser] Appel {model_name} (Google Search activé)...")
            max_retries = 2
            quota_exhausted = False
            for attempt in range(max_retries):
                try:
                    gen_config_kwargs = {
                        "tools": [types.Tool(google_search=types.GoogleSearch())],
                        "temperature": 0.3,
                        "max_output_tokens": 65536,
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

                    print(f"[Analyser] Modèle utilisé : {model_name} (clé #{key_index + 1})")
                    break
                except Exception as e:
                    try:
                        signal.alarm(0)
                    except (AttributeError, OSError):
                        pass
                    err = str(e).lower()
                    fatal = "invalid_api_key" in err or "permission_denied" in err
                    if fatal:
                        print(f"[Analyser] Erreur fatale ({model_name}) : {e}")
                        raise
                    if "resource_exhausted" in err or "429" in err:
                        print(f"[Analyser] Quota épuisé ({model_name}, clé #{key_index + 1})")
                        print(f"[Analyser]   → Détail erreur : {e}")
                        quota_exhausted = True
                        break
                    if attempt < max_retries - 1:
                        wait = 15
                        print(f"[Analyser] {model_name} erreur transitoire, retry dans {wait}s... ({attempt+1}/{max_retries})")
                        print(f"[Analyser]   → {e}")
                        time.sleep(wait)
                    else:
                        print(f"[Analyser] {model_name} échec après {max_retries} essais, modèle suivant...")
                        print(f"[Analyser]   → {e}")

            if quota_exhausted:
                print(f"[Analyser] Clé #{key_index + 1} épuisée, rotation vers clé suivante...")
                break

    if response is None:
        raise RuntimeError("[Analyser] Tous les modèles Gemini sont indisponibles.")

    try:
        for i, candidate in enumerate(response.candidates or []):
            fr = getattr(candidate, "finish_reason", None)
            print(f"[Analyser] Candidate {i} finish_reason : {fr}")
        usage = getattr(response, "usage_metadata", None)
        if usage:
            print(f"[Analyser] Tokens : prompt={getattr(usage, 'prompt_token_count', '?')}, "
                  f"output={getattr(usage, 'candidates_token_count', '?')}, "
                  f"total={getattr(usage, 'total_token_count', '?')}")
    except Exception as e:
        print(f"[Analyser] Debug finish_reason erreur : {e}")

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
            print(f"[Analyser] Avertissement extraction texte : {e}")

    print(f"[Analyser] Réponse reçue ({len(full_text)} caractères).")
    pronos = extract_json_block(full_text)
    print(f"[Analyser] {len(pronos)} prono(s) extrait(s) du JSON.")
    return full_text, pronos
