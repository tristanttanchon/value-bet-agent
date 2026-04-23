"""
scheduler.py — Orchestre toutes les tâches automatiques.

Horaires :
  10:00 — Résolution automatique des paris de la veille
  11:00 — Analyse quotidienne des matchs du jour + rapport Telegram
  20:00 (dimanche) — Rapport hebdomadaire Telegram

Usage :
  python scheduler.py
"""

import schedule
import time
from datetime import datetime
import config
from main import run_analysis
from weekly_report import run_weekly_report
from resolver import run_resolver


def job_daily() -> None:
    _log("Analyse quotidienne")
    try:
        run_analysis()
    except Exception as e:
        print(f"[Scheduler] Erreur analyse : {e}")


def job_resolver() -> None:
    _log("Résolution automatique des paris")
    try:
        run_resolver()
    except Exception as e:
        print(f"[Scheduler] Erreur résolution : {e}")


def job_weekly() -> None:
    _log("Rapport hebdomadaire Telegram")
    try:
        run_weekly_report()
    except Exception as e:
        print(f"[Scheduler] Erreur rapport hebdo : {e}")


def _log(task: str) -> None:
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {task}...")


# ─────────────────────────────────────────────────────────────────────────────
# Planning
# ─────────────────────────────────────────────────────────────────────────────

print("⏰  Scheduler démarré\n")
print("   10:00 — Résolution automatique des paris")
print("   11:00 — Analyse quotidienne + rapport complet Telegram")
print("   Dimanche 20:00 — Rapport hebdomadaire Telegram")
print("\n   (Ctrl+C pour arrêter)\n")

schedule.every().day.at("10:00").do(job_resolver)         # résolution paris veille
schedule.every().day.at("11:00").do(job_daily)            # analyse du jour → rapport Telegram
schedule.every().sunday.at("20:00").do(job_weekly)        # rapport hebdo

while True:
    schedule.run_pending()
    time.sleep(30)
