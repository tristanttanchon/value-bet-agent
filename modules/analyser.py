"""
Analyser — envoie les matchs du jour à Gemini 2.0 Flash (gratuit) avec le master prompt v2.0.
Récupère l'analyse complète + le JSON structuré des paris recommandés.
"""

import re
import json
from datetime import date
from google import genai
from google.genai import types
import config

# ─────────────────────────────────────────────────────────────────────────────
# MASTER PROMPT V2.0
# ─────────────────────────────────────────────────────────────────────────────

MASTER_PROMPT = """
Tu es un Senior Football Data Scientist et Analyste Tactique Élite.
Ta mission est d'hybrider l'eye-test (analyse terrain) et la data science
(modèles prédictifs) pour identifier des opportunités de value bet sur les matchs
du jour. Tu es rigoureux, factuel, et tu ne forces jamais une analyse quand les
données sont insuffisantes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RÈGLE ABSOLUE : Tu dois analyser CHAQUE match de la liste fournie, sans exception.
Même si les données sont partielles, produis une analyse minimale avec ce que tu trouves.
Un match non analysé = une erreur. Commence par les matchs dont tu as le moins de données
pour t'assurer de les couvrir avant d'épuiser tes recherches.

ÉTAPE 1 — MATCHS DU JOUR (déjà fournis ci-dessus)
Les matchs et leurs cotes de marché actuelles te sont fournis dans le message.
Ne recherche que les matchs de cette liste. Ne force aucune analyse sur un match
non listé.

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
    · Edge > 5%  → value détectée
    · Edge > 10% → value forte
— Applique la même logique sur : AH0 (Draw No Bet), Over/Under 2.5, BTTS
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

Après le rapport complet, génère OBLIGATOIREMENT un bloc JSON entre les
balises ```json ... ``` avec exactement ce format (respecte les types) :

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
— Un rapport sans pari recommandé est un rapport réussi.
— La discipline est la première compétence du value bettor.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions
# ─────────────────────────────────────────────────────────────────────────────

def build_prompt(matches_text: str) -> str:
    today = date.today().isoformat()
    return (
        f"ANALYSE DU {today}\n\n"
        f"Voici les matchs du jour avec leurs meilleures cotes de marché :\n\n"
        f"{matches_text}\n\n"
        f"{MASTER_PROMPT}"
    )


def extract_json_block(text: str) -> list[dict]:
    """Extrait le bloc JSON structuré de la réponse."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        print("[Analyser] Avertissement : aucun bloc JSON trouvé dans la réponse.")
        return []
    try:
        data = json.loads(match.group(1))
        return data.get("recommended_bets", [])
    except json.JSONDecodeError as e:
        print(f"[Analyser] Erreur JSON : {e}")
        return []


def analyse_matches(matches_text: str) -> tuple[str, list[dict]]:
    """
    Envoie les matchs à Gemini 2.0 Flash via l'API avec Google Search activé.
    Retourne (texte_complet_analyse, liste_paris_recommandés).
    """
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = build_prompt(matches_text)

    print("[Analyser] Appel Gemini 2.5 Flash (Google Search activé)...")

    import time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
            )
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 30 * (attempt + 1)
                print(f"[Analyser] Quota dépassé, nouvelle tentative dans {wait}s... ({attempt+1}/{max_retries})")
                time.sleep(wait)
                if attempt == max_retries - 1:
                    print("[Analyser] Quota épuisé après plusieurs tentatives.")
                    raise
            else:
                print(f"[Analyser] Erreur API Gemini : {e}")
                raise

    # Gemini 2.5 Flash a un mode "thinking" — le texte peut être dans les parts
    full_text = ""
    try:
        if response.text:
            full_text = response.text
        elif response.candidates:
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        full_text += part.text
    except Exception as e:
        print(f"[Analyser] Avertissement extraction texte : {e}")

    print(f"[Analyser] Réponse reçue ({len(full_text)} caractères).")
    bets = extract_json_block(full_text)
    print(f"[Analyser] {len(bets)} pari(s) extrait(s) du JSON.")
    return full_text, bets
