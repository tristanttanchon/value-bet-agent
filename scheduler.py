"""
scheduler.py — Orchestre toutes les tâches automatiques.

Horaires :
  09:00 — Snapshot des cotes (baseline du jour)
  10:00 — Résolution automatique des paris de la veille
  11:00 — Snapshot des cotes + détection mouvements de lignes
  12:00 — Analyse quotidienne des matchs du jour
  17:00 — Snapshot des cotes + alertes pré-match (sharp money)
  19:00 — Snapshot des cotes + alertes pré-match (dernière chance)
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
from modules.line_alert import run_line_monitor


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


def job_line_monitor() -> None:
    _log("Surveillance mouvements de lignes")
    try:
        run_line_monitor()
    except Exception as e:
        print(f"[Scheduler] Erreur line monitor : {e}")


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
print("   09:00 — Snapshot cotes (baseline)")
print("   10:00 — Résolution automatique des paris")
print("   10:30 — Détection mouvements de lignes")
print("   11:00 — Analyse quotidienne + rapport complet Telegram")
print("   17:00 — Alertes pré-match (sharp money)")
print("   19:00 — Alertes pré-match (dernière chance)")
print("   Dimanche 20:00 — Rapport hebdomadaire Telegram")
print("\n   (Ctrl+C pour arrêter)\n")

schedule.every().day.at("09:00").do(job_line_monitor)    # baseline cotes matin
schedule.every().day.at("10:00").do(job_resolver)         # résolution paris veille
schedule.every().day.at("10:30").do(job_line_monitor)    # 1er check mouvement
schedule.every().day.at("11:00").do(job_daily)            # analyse du jour → rapport Telegram
schedule.every().day.at("17:00").do(job_line_monitor)    # alerte pré-match
schedule.every().day.at("19:00").do(job_line_monitor)    # alerte finale
schedule.every().sunday.at("20:00").do(job_weekly)        # rapport hebdo

while True:
    schedule.run_pending()
    time.sleep(30)
