"""
Bankroll Guard — Protection automatique du bankroll.
- Stop loss à -20% : suspend les paris si le bankroll chute trop
- Alerte Telegram si stop loss déclenché
- Réduction automatique des mises en cas de drawdown
"""

import config
from modules.simulation import load_bankroll

STOP_LOSS_PCT = 0.20       # Suspend si perte > 20% du bankroll initial
REDUCED_KELLY = 0.10       # Kelly réduite à 10% si drawdown entre 10% et 20%
NORMAL_KELLY = 0.25        # Kelly normale


def get_drawdown(bankroll: dict | None = None) -> float:
    """Retourne le drawdown actuel en % (positif = perte)."""
    if bankroll is None:
        bankroll = load_bankroll()
    initial = bankroll["initial"]
    current = bankroll["current"]
    if initial <= 0:
        return 0.0
    return (initial - current) / initial


def is_betting_suspended(bankroll: dict | None = None) -> bool:
    """Retourne True si le stop loss est déclenché."""
    return get_drawdown(bankroll) >= STOP_LOSS_PCT


def get_kelly_fraction(bankroll: dict | None = None) -> float:
    """
    Retourne la fraction Kelly à utiliser selon le drawdown actuel.
    - Drawdown < 10%  → Kelly normale (0.25)
    - Drawdown 10-20% → Kelly réduite (0.10)
    - Drawdown > 20%  → Suspendu (0.0)
    """
    dd = get_drawdown(bankroll)
    if dd >= STOP_LOSS_PCT:
        return 0.0
    elif dd >= 0.10:
        return REDUCED_KELLY
    return NORMAL_KELLY


def check_and_alert(bankroll: dict | None = None) -> str | None:
    """
    Vérifie l'état du bankroll et retourne un message d'alerte si nécessaire.
    Retourne None si tout va bien.
    """
    if bankroll is None:
        bankroll = load_bankroll()

    dd = get_drawdown(bankroll)
    current = bankroll["current"]
    initial = bankroll["initial"]
    pl = current - initial

    if dd >= STOP_LOSS_PCT:
        return (
            f"🚨 STOP LOSS DÉCLENCHÉ\n\n"
            f"Bankroll : {current:.2f}€ ({pl:+.2f}€)\n"
            f"Drawdown : -{dd*100:.1f}% (seuil : -{STOP_LOSS_PCT*100:.0f}%)\n\n"
            f"Les paris sont SUSPENDUS automatiquement.\n"
            f"Analyse les résultats récents avant de reprendre."
        )
    elif dd >= 0.10:
        return (
            f"⚠️ ALERTE DRAWDOWN\n\n"
            f"Bankroll : {current:.2f}€ ({pl:+.2f}€)\n"
            f"Drawdown : -{dd*100:.1f}%\n\n"
            f"Mises réduites automatiquement (Kelly x0.10 au lieu de x0.25)."
        )
    return None


def get_status_line(bankroll: dict | None = None) -> str:
    """Retourne une ligne de statut courte pour les rapports."""
    if bankroll is None:
        bankroll = load_bankroll()
    dd = get_drawdown(bankroll)
    kelly = get_kelly_fraction(bankroll)

    if kelly == 0.0:
        status = "🚨 SUSPENDU"
    elif kelly == REDUCED_KELLY:
        status = "⚠️ MISES RÉDUITES"
    else:
        status = "✅ NORMAL"

    return f"{status}  |  Drawdown : -{dd*100:.1f}%  |  Kelly : x{kelly}"
