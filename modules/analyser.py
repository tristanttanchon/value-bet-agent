"""
Analyser — envoie les matchs du jour à Gemini 2.0 Flash (gratuit) avec le master prompt v2.0.
Récupère l'analyse complète + le JSON structuré des paris recommandés.
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
# MASTER PROMPT V2.0
# ─────────────────────────────────────────────────────────────────────────────

MASTER_PROMPT = """
Tu es un Senior Football Data Scientist et Value Betting Expert.
Ta mission est de trouver des edges exploitables en comparant tes estimations
de probabilités aux cotes du marché. Tu es méthodique, factuel, et tu cherches
activement la value — un edge de 3% bien fondé est jouable.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RÈGLE ABSOLUE : Tu dois analyser CHAQUE match de la liste fournie, sans exception.
Pour CHAQUE match, explore TOUS les marchés disponibles (1X2, Over/Under 2.5, BTTS)
et calcule un edge pour chacun. Ne te limite pas à un seul marché par match.
Un edge ≥ 3% = value jouable. Un edge ≥ 7% = value forte.

ÉTAPE 1 — MATCHS DU JOUR (déjà fournis ci-dessus)
Les matchs et leurs cotes de marché actuelles te sont fournis dans le message.
Ne recherche que les matchs de cette liste.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 2 — COLLECTE DE DONNÉES (pour chaque match)
Utilise Google Search pour trouver les informations suivantes. Si une donnée est
introuvable, note-la dans "DONNÉES MANQUANTES".

▸ CONTEXTE & ABSENCES
  — Absences confirmées (blessés, suspendus) et impact tactique réel
  — Retours de blessure : niveau de forme attendu, titulaire ou entrant ?
  — Contexte : enjeu, fatigue, rotations probables en coupe
  — Changements récents de staff/entraîneur
  — Profondeur du banc par poste

▸ H2H — CONFRONTATIONS DIRECTES
  — 5 derniers face-à-face : scores, contexte, buts
  — Équipe historiquement dominante
  — Tendance buts dans ce H2H

▸ FORME RÉCENTE
  — 5 derniers matchs de chaque équipe avec scores et contexte
  — Comportement domicile vs extérieur (10 derniers matchs)
  — Stats first half / second half

▸ CONDITIONS EXTÉRIEURES
  — Météo prévue et impact potentiel sur le jeu

▸ STATISTIQUES AVANCÉES (FBRef · Understat · Sofascore · WhoScored)
  — xG et xGA moyens (10 derniers matchs)
  — Analyse de variance : sur/sous-performance des xG ?
  — PPDA (intensité du pressing)
  — Field Tilt (domination territoriale réelle)
  — Post-Shot xG (PSxG) : forme réelle du gardien
  — Expected Threat (xT) si disponible

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 3 — ANALYSE TACTIQUE

▸ ANALYSE DE JEU
  — Systèmes de jeu et circuits de passe attendus
  — Exploitation des demi-espaces et Zone 14
  — Qui domine les 30 derniers mètres adverses ?
  — Pressing : intensité, organisation
  — Résilience après avoir concédé en premier
  — Force/Faiblesse sur CPA (coups de pied arrêtés)
  — Hauteur de ligne défensive

▸ DUELS INDIVIDUELS CLÉS
  — 1 à 2 matchups déterminants et asymétries exploitables

▸ MATCHS DE COUPE
  — Rotations probables, prolongations/TAB à anticiper

▸ MOUVEMENT DE LIGNES
  — Comparer cote d'ouverture vs cote actuelle
  — Baisse de cote malgré afflux grand public = signal sharp money

▸ ANALYSE DE L'ARBITRE
  — Moyenne cartons/match, tendance penalties, biais domicile

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 4 — MODÉLISATION & CALCUL DE VALUE

— Calcule tes propres probabilités : prob1 + probX + prob2 = 100%
— Estime les cotes fair value (1/prob)
— Compare avec les cotes marché fournies
— Calcule l'edge : (prob_modèle × cote_marché) − 1
    · Edge ≥ 3%  → value jouable, RECOMMANDE le pari
    · Edge ≥ 7%  → value forte, RECOMMANDE avec haute confiance
    · Edge ≥ 12% → value exceptionnelle
— IMPORTANT : Analyse CHAQUE marché séparément pour chaque match :
    · 1X2 (victoire domicile, nul, victoire extérieur)
    · Over/Under 2.5 buts
    · BTTS (les deux équipes marquent)
    · AH0 / Draw No Bet (si pertinent)
  Un match peut avoir 0, 1 ou PLUSIEURS paris value sur des marchés différents.
— Closing Line Value : note si la cote semble proche de son plancher
— Mise Kelly : [edge / (cote − 1)] × 0.25 | plafond absolu 5% du bankroll

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 5 — RAPPORT PAR MATCH

Pour chaque match :
  📍 Compétition · Heure · Lieu · Météo
  ⚔️  H2H (5 derniers face-à-face)
  🔴 Absences clés et impact tactique
  📊 Forme récente + stats first/second half
  🧠 Analyse tactique, duels clés, stats avancées
  📈 Mouvement de lignes + signal sharp money
  🧑‍⚖️ Profil arbitre (si pertinent)
  💰 Tableau de value :
     Marché | Prob modèle | Cote marché | Edge
  ✅ Pari recommandé (ou "AUCUN")
  ⭐ Indice de confiance /5
  🔒 Fiabilité des données : A / B / C
  ⚠️  Données manquantes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 6 — RÉCAPITULATIF FINAL

Tableau des paris recommandés classés par edge décroissant.
Liste des matchs analysés sans value (avec raison courte).
Données manquantes globales.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ÉTAPE 7 — SORTIE JSON STRUCTURÉE (OBLIGATOIRE)

Tu dois IMPÉRATIVEMENT analyser TOUS les matchs de la liste en détail avec les
étapes 2 à 6 ci-dessus, puis, à la TOUTE FIN de ta réponse, générer un bloc JSON
valide résumant les paris recommandés.

⚠️ NE JAMAIS commencer par le bloc JSON. L'analyse détaillée passe d'abord,
puis le JSON vient en conclusion. Si tu omets ce JSON final, le système échoue.

Format exact à respecter (commence par ```json et finit par ```) :

```json
{
  "analysis_date": "YYYY-MM-DD",
  "recommended_bets": [
    {
      "match": "Équipe A vs Équipe B",
      "competition": "Nom compétition",
      "kickoff": "HH:MM",
      "market": "1|X|2|Over 2.5|Under 2.5|BTTS|AH0",
      "model_probability": 0.55,
      "market_odds": 1.85,
      "edge": 0.0175,
      "confidence": 3,
      "data_reliability": "A",
      "recommended_stake_pct": 0.018
    }
  ],
  "no_value_matches": ["match1", "match2"]
}
```

Si aucun pari recommandé, "recommended_bets" doit être un tableau vide [].

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RAPPELS FONDAMENTAUX
— Les cotes sont le thermomètre, pas le diagnostic.
— La value naît de l'analyse terrain, des absences et du contexte.
— Cherche activement la value sur TOUS les marchés de chaque match.
— Un edge de 3% avec des données fiables (A ou B) est jouable.
— Ne te réfugie pas derrière "données insuffisantes" — Google Search te
  donne accès aux infos récentes. Utilise-les pour estimer des probabilités.
— Sur 20+ matchs, tu devrais typiquement trouver 3 à 8 paris value.
  Si tu en trouves 0, c'est probablement que tu es trop conservateur.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions
# ─────────────────────────────────────────────────────────────────────────────

def build_prompt(matches_text: str) -> str:
    today = date.today().isoformat()

    # Contexte d'apprentissage (historique de performance, blacklist, leçons)
    try:
        from modules.learning import build_performance_context
        learning_context = build_performance_context()
    except Exception as e:
        print(f"[Analyser] Contexte d'apprentissage indisponible : {e}")
        learning_context = ""

    return (
        f"ANALYSE DU {today}\n\n"
        f"Voici les matchs du jour avec leurs meilleures cotes de marché :\n\n"
        f"{matches_text}\n"
        f"{learning_context}\n"
        f"{MASTER_PROMPT}"
    )


def extract_json_block(text: str) -> list[dict]:
    """
    Extrait le bloc JSON structuré de la réponse.
    Tente plusieurs formats : ```json ... ```, ``` ... ```, puis brace-matching.
    """
    # Pattern 1 : ```json { ... } ```
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
                return data.get("recommended_bets", [])
            except json.JSONDecodeError:
                continue

    # Pattern 2 : recherche du dernier objet JSON contenant "recommended_bets"
    idx = text.rfind('"recommended_bets"')
    if idx != -1:
        # Remonte au { d'ouverture
        start = text.rfind('{', 0, idx)
        if start != -1:
            # Trouve le } fermant correspondant (brace matching)
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
                    return data.get("recommended_bets", [])
                except json.JSONDecodeError as e:
                    print(f"[Analyser] Erreur JSON (brace matching) : {e}")

    print("[Analyser] Avertissement : aucun bloc JSON trouvé dans la réponse.")
    # Debug : afficher les 500 derniers caractères pour comprendre le format
    print(f"[Analyser] Fin de la réponse (debug) :\n---\n{text[-500:]}\n---")
    return []


def analyse_matches(matches_text: str) -> tuple[str, list[dict]]:
    """
    Envoie les matchs à Gemini 2.0 Flash via l'API avec Google Search activé.
    Supporte la rotation multi-clés Gemini (séparées par virgule dans le secret).
    Retourne (texte_complet_analyse, liste_paris_recommandés).
    """
    prompt = build_prompt(matches_text)

    import time

    # Clés Gemini disponibles (rotation si quota épuisé)
    gemini_keys = list(config.GEMINI_API_KEYS) if config.GEMINI_API_KEYS else []
    if not gemini_keys:
        raise RuntimeError("[Analyser] Aucune clé GEMINI_API_KEY configurée.")
    print(f"[Analyser] {len(gemini_keys)} clé(s) Gemini disponible(s).")

    # gemini-2.5-flash avec thinking_budget=0 (pas de thinking mode)
    # Fallback : gemini-flash-latest et gemini-2.0-flash
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
            success = False
            quota_exhausted = False
            for attempt in range(max_retries):
                try:
                    # Config de base commune
                    gen_config_kwargs = {
                        "tools": [types.Tool(google_search=types.GoogleSearch())],
                        "temperature": 0.3,
                        "max_output_tokens": 32768,
                    }

                    # Désactive le mode "thinking" pour gemini-2.5-flash
                    if "2.5" in model_name:
                        try:
                            gen_config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                        except Exception:
                            pass

                    # Timeout de 5 min pour éviter les hangs infinis
                    try:
                        signal.signal(signal.SIGALRM, _timeout_handler)
                        signal.alarm(GEMINI_CALL_TIMEOUT)
                    except (AttributeError, OSError):
                        pass  # Windows n'a pas SIGALRM — on skip

                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(**gen_config_kwargs),
                    )

                    try:
                        signal.alarm(0)  # Annule le timeout
                    except (AttributeError, OSError):
                        pass

                    print(f"[Analyser] Modèle utilisé : {model_name} (clé #{key_index + 1})")
                    success = True
                    break
                except Exception as e:
                    try:
                        signal.alarm(0)
                    except (AttributeError, OSError):
                        pass
                    err = str(e).lower()
                    # Erreurs fatales (mauvaise clé, etc.) → on crash immédiatement
                    fatal = "invalid_api_key" in err or "permission_denied" in err
                    if fatal:
                        print(f"[Analyser] Erreur fatale ({model_name}) : {e}")
                        raise
                    # Quota épuisé → on passe directement à la clé suivante
                    if "resource_exhausted" in err or "429" in err:
                        print(f"[Analyser] Quota épuisé ({model_name}, clé #{key_index + 1})")
                        quota_exhausted = True
                        break
                    # Toutes les autres erreurs (réseau, 503, disconnect...) → retry puis modèle suivant
                    if attempt < max_retries - 1:
                        wait = 15
                        print(f"[Analyser] {model_name} erreur transitoire, retry dans {wait}s... ({attempt+1}/{max_retries})")
                        print(f"[Analyser]   → {e}")
                        time.sleep(wait)
                    else:
                        print(f"[Analyser] {model_name} échec après {max_retries} essais, modèle suivant...")
                        print(f"[Analyser]   → {e}")

            # Si quota épuisé sur cette clé → skip tous les modèles restants, passe à la clé suivante
            if quota_exhausted:
                print(f"[Analyser] Clé #{key_index + 1} épuisée, rotation vers clé suivante...")
                break

    if response is None:
        raise RuntimeError("[Analyser] Tous les modèles Gemini sont indisponibles (toutes les clés épuisées).")

    # Log du finish_reason pour debug (MAX_TOKENS, STOP, SAFETY, etc.)
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

    # Gemini 2.5 Flash a un mode "thinking" — le texte peut être dans les parts
    full_text = ""

    # Tentative 1 : accès direct response.text
    try:
        if response.text:
            full_text = response.text
    except Exception:
        pass

    # Tentative 2 : parcours des candidates/parts (mode thinking)
    if not full_text:
        try:
            for candidate in (response.candidates or []):
                if not candidate or not candidate.content:
                    continue
                for part in (candidate.content.parts or []):
                    if hasattr(part, "text") and part.text:
                        # Ignorer les parts "thinking" (pensées internes du modèle)
                        if hasattr(part, "thought") and part.thought:
                            continue
                        full_text += part.text
        except Exception as e:
            print(f"[Analyser] Avertissement extraction texte : {e}")

    print(f"[Analyser] Réponse reçue ({len(full_text)} caractères).")
    bets = extract_json_block(full_text)
    print(f"[Analyser] {len(bets)} pari(s) extrait(s) du JSON.")
    return full_text, bets
