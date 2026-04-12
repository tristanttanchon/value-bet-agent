"""
Reflection — post-mortem hebdomadaire.

Une fois par semaine, on demande à Gemini d'analyser ses propres
paris résolus sur les 7-30 derniers jours et d'en extraire :
— des patterns récurrents d'erreur/réussite
— des règles concrètes applicables ("leçons apprises")

Les leçons sont stockées dans la table `learned_lessons` et injectées
automatiquement dans les analyses futures via `modules/learning.py`.
"""

import json
import re
from datetime import date, timedelta
from google import genai
from google.genai import types

import config
from modules.db import get_client
from modules.learning import record_lesson, get_active_lessons


REFLECTION_PROMPT = """
Tu es un coach de value betting qui audite les performances d'un modèle de pronostic.

Voici l'historique des paris résolus (WIN/LOSS) des 30 derniers jours, avec leurs
caractéristiques (compétition, marché, probabilité modèle, cote, edge, résultat).

Ta mission :
1. Identifie les patterns récurrents d'ERREURS (où le modèle se trompe systématiquement)
2. Identifie les patterns récurrents de RÉUSSITES (où le modèle excelle)
3. Produit des LEÇONS APPRISES concrètes et actionnables

Chaque leçon doit être :
— Spécifique (pas "fais mieux", mais "sur le marché X dans le contexte Y, applique Z")
— Vérifiable (basée sur les données fournies)
— Courte (1-2 phrases max)
— Actionnable dans les analyses futures

Format de sortie OBLIGATOIRE — un bloc JSON à la fin de ta réponse :

```json
{
  "analysis_period_days": 30,
  "total_bets_analyzed": 42,
  "key_patterns": [
    "Description courte d'un pattern observé"
  ],
  "lessons": [
    {
      "category": "market",
      "lesson": "La leçon actionnable (1-2 phrases)",
      "evidence": "Preuve statistique brève"
    }
  ]
}
```

Les catégories valides sont : "market", "competition", "tactical", "general".

Si moins de 10 paris résolus : retourne "lessons": [] et note dans "key_patterns"
que les données sont insuffisantes.

Sois rigoureux, factuel, ne force jamais une leçon si la donnée ne la supporte pas.
"""


def _load_recent_resolved_bets(days: int = 30) -> list[dict]:
    """Charge les paris WIN/LOSS des N derniers jours."""
    db = get_client()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        resp = (
            db.table("bets")
            .select("*")
            .in_("status", ["WIN", "LOSS"])
            .gte("date", cutoff)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Reflection] Erreur chargement paris : {e}")
        return []


def _format_bets_for_prompt(bets: list[dict]) -> str:
    """Formate les paris en texte lisible pour Gemini."""
    if not bets:
        return "Aucun pari résolu sur la période."

    lines = []
    for b in bets:
        prob = b.get("model_probability")
        prob_str = f"{float(prob):.2f}" if prob else "?"
        edge = b.get("edge", "?")
        pl = b.get("profit_loss")
        pl_str = f"{float(pl):+.2f}€" if pl is not None else "?"
        lines.append(
            f"- {b.get('date', '?')} | {b.get('competition', '?')} | "
            f"{b.get('match', '?')} | Marché: {b.get('market', '?')} "
            f"| Prob: {prob_str} | Cote: {b.get('market_odds', '?')} "
            f"| Edge: {edge} | Mise: {b.get('sim_stake', '?')}€ "
            f"| Résultat: {b.get('status', '?')} ({pl_str})"
        )
    return "\n".join(lines)


def _extract_lessons_json(text: str) -> dict:
    """Extrait le bloc JSON de la réponse Gemini."""
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```JSON\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    # Fallback : brace matching sur "lessons"
    idx = text.rfind('"lessons"')
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
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
    return {}


def _deactivate_old_lessons(max_age_days: int = 60) -> int:
    """Désactive les leçons trop anciennes pour éviter l'accumulation."""
    db = get_client()
    cutoff = (date.today() - timedelta(days=max_age_days)).isoformat()
    try:
        resp = (
            db.table("learned_lessons")
            .update({"active": False})
            .eq("active", True)
            .lt("created_at", cutoff)
            .execute()
        )
        return len(resp.data or [])
    except Exception as e:
        print(f"[Reflection] Erreur désactivation anciennes leçons : {e}")
        return 0


def run_reflection(days: int = 30) -> dict:
    """
    Lance une session de réflexion hebdomadaire.
    Charge les paris récents, demande à Gemini de les analyser,
    enregistre les leçons apprises en base.

    Retourne un dict avec : status, n_bets, n_lessons_new, n_lessons_deactivated
    """
    print("\n🧠 REFLECTION — Post-mortem hebdomadaire\n" + "═" * 50)

    # 1. Désactive les vieilles leçons
    deactivated = _deactivate_old_lessons(max_age_days=60)
    if deactivated:
        print(f"[Reflection] {deactivated} leçon(s) ancienne(s) désactivée(s).")

    # 2. Charge les paris récents
    bets = _load_recent_resolved_bets(days=days)
    n = len(bets)
    print(f"[Reflection] {n} pari(s) résolu(s) sur les {days} derniers jours.")

    if n < 10:
        print("[Reflection] Données insuffisantes (<10 paris). Abandon.")
        return {
            "status": "insufficient_data",
            "n_bets": n,
            "n_lessons_new": 0,
            "n_lessons_deactivated": deactivated,
        }

    # 3. Leçons déjà actives (pour éviter les doublons)
    existing = get_active_lessons(limit=50)
    existing_texts = {l["lesson"].strip().lower() for l in existing}

    # 4. Formate le prompt
    bets_text = _format_bets_for_prompt(bets)
    prompt = (
        f"PÉRIODE ANALYSÉE : {days} derniers jours\n"
        f"NOMBRE DE PARIS : {n}\n\n"
        f"DONNÉES BRUTES :\n{bets_text}\n\n"
        f"{REFLECTION_PROMPT}"
    )

    # 5. Appel Gemini (rotation multi-clés, sans Google Search)
    gemini_keys = list(config.GEMINI_API_KEYS) if config.GEMINI_API_KEYS else []
    if not gemini_keys:
        gemini_keys = [config.GEMINI_API_KEY] if config.GEMINI_API_KEY else []
    models_to_try = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]
    response = None

    for key_idx, api_key in enumerate(gemini_keys):
        if response is not None:
            break
        client = genai.Client(api_key=api_key)
        for model_name in models_to_try:
            try:
                print(f"[Reflection] Appel {model_name} (clé #{key_idx + 1})...")
                gen_kwargs = {
                    "temperature": 0.2,
                    "max_output_tokens": 8192,
                }
                if "2.5" in model_name:
                    try:
                        gen_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                    except Exception:
                        pass
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**gen_kwargs),
                )
                print(f"[Reflection] Modèle utilisé : {model_name} (clé #{key_idx + 1})")
                break
            except Exception as e:
                err = str(e).lower()
                if "resource_exhausted" in err or "429" in err:
                    print(f"[Reflection] Quota épuisé (clé #{key_idx + 1}), rotation...")
                    break
                print(f"[Reflection] Échec {model_name} : {e}")
                continue

    if response is None:
        print("[Reflection] Aucun modèle disponible. Abandon.")
        return {
            "status": "gemini_unavailable",
            "n_bets": n,
            "n_lessons_new": 0,
            "n_lessons_deactivated": deactivated,
        }

    # 6. Extraction texte
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
        except Exception:
            pass

    print(f"[Reflection] Réponse reçue ({len(full_text)} caractères).")

    # 7. Extraction JSON
    data = _extract_lessons_json(full_text)
    new_lessons = data.get("lessons", [])
    patterns = data.get("key_patterns", [])

    if patterns:
        print(f"[Reflection] Patterns détectés :")
        for p in patterns:
            print(f"  • {p}")

    # 8. Enregistre les nouvelles leçons en base (dédupliquées)
    added = 0
    for lesson in new_lessons:
        text = (lesson.get("lesson") or "").strip()
        if not text:
            continue
        if text.lower() in existing_texts:
            print(f"[Reflection] Leçon déjà connue (ignorée) : {text[:60]}...")
            continue
        category = lesson.get("category", "general")
        evidence = lesson.get("evidence", "")
        if record_lesson(category=category, lesson=text, context=evidence, expires_days=60):
            added += 1
            print(f"[Reflection] ✅ Nouvelle leçon [{category}] : {text[:80]}...")

    print(f"\n[Reflection] Terminé — {added} nouvelle(s) leçon(s) ajoutée(s).")
    return {
        "status": "ok",
        "n_bets": n,
        "n_lessons_new": added,
        "n_lessons_deactivated": deactivated,
        "patterns": patterns,
    }


if __name__ == "__main__":
    result = run_reflection(days=30)
    print(f"\nRésultat final : {result}")
