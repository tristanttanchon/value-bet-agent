"""
Learning — couche d'apprentissage continue de l'agent.

Trois mécanismes :
1. Mémoire contextuelle  → injecte les stats passées dans le prompt Gemini
2. Auto-blacklist         → filtre les couples (compétition, marché) perdants
3. Leçons apprises        → stockées en DB via reflection hebdomadaire

Tout est backwards-compatible : fonctionne dès le premier pari résolu,
sans jamais bloquer le pipeline si la table est vide.
"""

from collections import defaultdict
from datetime import date, timedelta
from modules.db import get_client

# ─────────────────────────────────────────────────────────────────────────────
# Paramètres de l'apprentissage
# ─────────────────────────────────────────────────────────────────────────────

# Nombre minimum de paris résolus avant d'activer la mémoire contextuelle
MIN_BETS_FOR_MEMORY = 10

# Nombre minimum de paris sur un couple (comp, market) pour envisager un blacklist
MIN_BETS_FOR_BLACKLIST = 15

# Yield en-dessous duquel un couple (comp, market) est blacklisté (-10%)
BLACKLIST_YIELD_THRESHOLD = -10.0

# Yield au-dessus duquel un couple est considéré comme "edge prouvée" (+8%)
WHITELIST_YIELD_THRESHOLD = 8.0

# Nombre de paris minimum pour considérer une stat "significative" (affichage)
MIN_BETS_SIGNIFICANT = 5


# ─────────────────────────────────────────────────────────────────────────────
# 1. Chargement brut des paris résolus
# ─────────────────────────────────────────────────────────────────────────────

def _load_resolved_bets() -> list[dict]:
    """Charge tous les paris WIN/LOSS depuis Supabase."""
    try:
        db = get_client()
        resp = db.table("bets").select("*").in_("status", ["WIN", "LOSS"]).execute()
        return resp.data or []
    except Exception as e:
        print(f"[Learning] Erreur chargement paris : {e}")
        return []


def _compute_group_stats(bets: list[dict], key: str) -> dict:
    """Stats groupées par clé (competition ou market)."""
    groups = defaultdict(lambda: {"total": 0, "wins": 0, "staked": 0.0, "pl": 0.0})
    for b in bets:
        g = groups[b.get(key) or "Inconnu"]
        g["total"] += 1
        stake = float(b["sim_stake"] or 0)
        g["staked"] += stake
        if b["status"] == "WIN":
            g["wins"] += 1
        g["pl"] += float(b["profit_loss"] or 0)

    result = {}
    for name, g in groups.items():
        if g["staked"] > 0:
            g["yield_pct"] = round(g["pl"] / g["staked"] * 100, 1)
        else:
            g["yield_pct"] = 0.0
        g["wr"] = round(g["wins"] / g["total"] * 100, 1) if g["total"] else 0
        result[name] = g
    return result


def _compute_combo_stats(bets: list[dict]) -> dict:
    """Stats groupées par couple (competition, market) pour la blacklist."""
    combos = defaultdict(lambda: {"total": 0, "wins": 0, "staked": 0.0, "pl": 0.0})
    for b in bets:
        key = (b.get("competition") or "Inconnu", b.get("market") or "Inconnu")
        g = combos[key]
        g["total"] += 1
        stake = float(b["sim_stake"] or 0)
        g["staked"] += stake
        if b["status"] == "WIN":
            g["wins"] += 1
        g["pl"] += float(b["profit_loss"] or 0)

    result = {}
    for key, g in combos.items():
        if g["staked"] > 0:
            g["yield_pct"] = round(g["pl"] / g["staked"] * 100, 1)
        else:
            g["yield_pct"] = 0.0
        result[key] = g
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Auto-blacklist : couples (compétition, marché) à exclure
# ─────────────────────────────────────────────────────────────────────────────

def get_blacklisted_combos() -> list[tuple[str, str]]:
    """
    Retourne la liste des couples (compétition, marché) à exclure
    car historiquement perdants de manière statistiquement significative.
    """
    bets = _load_resolved_bets()
    if len(bets) < MIN_BETS_FOR_BLACKLIST:
        return []

    combos = _compute_combo_stats(bets)
    blacklist = []
    for (comp, market), g in combos.items():
        if g["total"] >= MIN_BETS_FOR_BLACKLIST and g["yield_pct"] <= BLACKLIST_YIELD_THRESHOLD:
            blacklist.append((comp, market))
    return blacklist


def is_blacklisted(competition: str, market: str, blacklist: list[tuple[str, str]] | None = None) -> bool:
    """Retourne True si le couple est blacklisté."""
    if blacklist is None:
        blacklist = get_blacklisted_combos()
    return (competition, market) in blacklist


# ─────────────────────────────────────────────────────────────────────────────
# 3. Leçons apprises (stockées en DB)
# ─────────────────────────────────────────────────────────────────────────────

def get_active_lessons(limit: int = 10) -> list[dict]:
    """Charge les leçons apprises actives depuis Supabase."""
    try:
        db = get_client()
        today = date.today().isoformat()
        resp = (
            db.table("learned_lessons")
            .select("*")
            .eq("active", True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        lessons = resp.data or []
        # Filtre les leçons expirées
        return [l for l in lessons if not l.get("expires_at") or l["expires_at"] >= today]
    except Exception as e:
        print(f"[Learning] Erreur chargement leçons : {e}")
        return []


def record_lesson(category: str, lesson: str, context: str | None = None, expires_days: int | None = 60) -> bool:
    """Enregistre une nouvelle leçon apprise."""
    try:
        db = get_client()
        row = {
            "category": category,
            "lesson": lesson,
            "context": context,
            "active": True,
        }
        if expires_days:
            row["expires_at"] = (date.today() + timedelta(days=expires_days)).isoformat()
        db.table("learned_lessons").insert(row).execute()
        return True
    except Exception as e:
        print(f"[Learning] Erreur enregistrement leçon : {e}")
        return False


def deactivate_lesson(lesson_id: int) -> bool:
    """Désactive une leçon (par exemple si elle ne tient plus sur données récentes)."""
    try:
        db = get_client()
        db.table("learned_lessons").update({"active": False}).eq("id", lesson_id).execute()
        return True
    except Exception as e:
        print(f"[Learning] Erreur désactivation leçon : {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Génération du contexte de performance (injecté dans le prompt Gemini)
# ─────────────────────────────────────────────────────────────────────────────

def build_performance_context() -> str:
    """
    Construit un bloc texte à injecter dans le prompt Gemini avec :
    — stats globales sur la période écoulée
    — meilleurs/pires marchés
    — meilleures/pires compétitions
    — couples blacklistés
    — leçons apprises actives

    Retourne une chaîne vide si pas assez de données pour être pertinent.
    """
    bets = _load_resolved_bets()
    n = len(bets)

    if n < MIN_BETS_FOR_MEMORY:
        # Pas assez de données — on retourne un message neutre
        return (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 MÉMOIRE D'APPRENTISSAGE\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Historique : {n} pari(s) résolu(s). Données insuffisantes "
            f"(minimum {MIN_BETS_FOR_MEMORY}) pour activer la mémoire contextuelle. "
            "Analyse sans biais historique.\n"
        )

    # Stats globales
    wins = sum(1 for b in bets if b["status"] == "WIN")
    total_staked = sum(float(b["sim_stake"] or 0) for b in bets)
    total_pl = sum(float(b["profit_loss"] or 0) for b in bets)
    wr = round(wins / n * 100, 1)
    yield_pct = round(total_pl / total_staked * 100, 1) if total_staked > 0 else 0.0

    # Stats par compétition et marché
    by_comp = _compute_group_stats(bets, "competition")
    by_market = _compute_group_stats(bets, "market")

    # Top 3 / Bottom 3 significatifs
    sig_comps = {k: v for k, v in by_comp.items() if v["total"] >= MIN_BETS_SIGNIFICANT}
    sig_markets = {k: v for k, v in by_market.items() if v["total"] >= MIN_BETS_SIGNIFICANT}

    top_comps = sorted(sig_comps.items(), key=lambda x: x[1]["yield_pct"], reverse=True)[:3]
    bot_comps = sorted(sig_comps.items(), key=lambda x: x[1]["yield_pct"])[:3]
    top_markets = sorted(sig_markets.items(), key=lambda x: x[1]["yield_pct"], reverse=True)[:3]
    bot_markets = sorted(sig_markets.items(), key=lambda x: x[1]["yield_pct"])[:3]

    # Blacklist
    blacklist = get_blacklisted_combos()

    # Leçons actives
    lessons = get_active_lessons(limit=8)

    # Construction du bloc texte
    lines = [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🧠 MÉMOIRE D'APPRENTISSAGE — TON HISTORIQUE RÉEL",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "Voici tes performances réelles passées. Utilise ces patterns pour calibrer "
        "ta confiance, éviter tes erreurs récurrentes et privilégier tes domaines de force.",
        "",
        f"📊 STATS GLOBALES :",
        f"   • {n} paris résolus | WR {wr}% | Yield {yield_pct:+.1f}% | P&L {total_pl:+.2f}€",
        "",
    ]

    if top_markets:
        lines.append("✅ MARCHÉS OÙ TU EXCELLES :")
        for name, s in top_markets:
            if s["yield_pct"] > 0:
                lines.append(
                    f"   • {name} → Yield {s['yield_pct']:+.1f}% sur {s['total']} paris "
                    f"(WR {s['wr']}%)"
                )
        lines.append("")

    if bot_markets:
        worst = [m for m in bot_markets if m[1]["yield_pct"] < 0]
        if worst:
            lines.append("⚠️ MARCHÉS OÙ TU TE PLANTES :")
            for name, s in worst:
                lines.append(
                    f"   • {name} → Yield {s['yield_pct']:+.1f}% sur {s['total']} paris "
                    f"(WR {s['wr']}%) — SOIS PRUDENT"
                )
            lines.append("")

    if top_comps:
        lines.append("🏆 COMPÉTITIONS FAVORABLES :")
        for name, s in top_comps:
            if s["yield_pct"] > 0:
                lines.append(
                    f"   • {name} → Yield {s['yield_pct']:+.1f}% sur {s['total']} paris"
                )
        lines.append("")

    if bot_comps:
        worst = [c for c in bot_comps if c[1]["yield_pct"] < 0]
        if worst:
            lines.append("🚫 COMPÉTITIONS DÉFAVORABLES :")
            for name, s in worst:
                lines.append(
                    f"   • {name} → Yield {s['yield_pct']:+.1f}% sur {s['total']} paris "
                    f"— ÉVITE LES PICKS FORCÉS ICI"
                )
            lines.append("")

    if blacklist:
        lines.append("⛔ COMBOS BLACKLISTÉS (auto-exclus par le filtre) :")
        for comp, market in blacklist:
            lines.append(f"   • {comp} / {market}")
        lines.append("   → Ne propose PAS de pari sur ces couples, ils seront filtrés.")
        lines.append("")

    if lessons:
        lines.append("📚 LEÇONS APPRISES (applique ces règles) :")
        for l in lessons:
            lines.append(f"   • [{l['category']}] {l['lesson']}")
        lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "RAPPEL : Ces stats ne sont PAS des garanties, mais des signaux statistiques. ",
        "Si ton analyse tactique du jour contredit fortement un pattern historique, ",
        "documente la contradiction dans ton raisonnement et reste rationnel.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Calibration bayésienne (Option 4 — stub, activable plus tard)
# ─────────────────────────────────────────────────────────────────────────────

def get_calibration_factor(raw_prob: float, min_bets: int = 50) -> float:
    """
    Retourne un facteur correctif appliqué à la probabilité Gemini.
    Non-actif tant qu'on n'a pas assez de données (≥50 paris résolus).
    Retourne 1.0 (pas de correction) par défaut.
    """
    bets = _load_resolved_bets()
    if len(bets) < min_bets:
        return 1.0

    # Buckets par tranches de 10%
    buckets = defaultdict(lambda: {"total": 0, "wins": 0})
    for b in bets:
        p = b.get("model_probability")
        if p is None:
            continue
        bucket_key = int(float(p) * 10)  # 0..9
        buckets[bucket_key]["total"] += 1
        if b["status"] == "WIN":
            buckets[bucket_key]["wins"] += 1

    target_bucket = int(raw_prob * 10)
    b = buckets.get(target_bucket)
    if not b or b["total"] < 10:
        return 1.0

    observed = b["wins"] / b["total"]
    expected = (target_bucket + 0.5) / 10  # centre du bucket
    if expected <= 0:
        return 1.0

    factor = observed / expected
    # Clamp entre 0.7 et 1.3 pour éviter les corrections extrêmes
    return max(0.7, min(1.3, factor))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Résumé debug (pour tests locaux)
# ─────────────────────────────────────────────────────────────────────────────

def print_learning_status() -> None:
    """Affiche dans la console l'état actuel de l'apprentissage."""
    bets = _load_resolved_bets()
    blacklist = get_blacklisted_combos()
    lessons = get_active_lessons(limit=20)

    print(f"\n[Learning] État de l'apprentissage :")
    print(f"  • Paris résolus : {len(bets)}")
    print(f"  • Mémoire contextuelle active : {'✅' if len(bets) >= MIN_BETS_FOR_MEMORY else '❌'}")
    print(f"  • Combos blacklistés : {len(blacklist)}")
    for comp, market in blacklist:
        print(f"      - {comp} / {market}")
    print(f"  • Leçons apprises actives : {len(lessons)}")
    for l in lessons:
        print(f"      - [{l['category']}] {l['lesson'][:80]}...")


if __name__ == "__main__":
    print_learning_status()
    print("\n" + build_performance_context())
