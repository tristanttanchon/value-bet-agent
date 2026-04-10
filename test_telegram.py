"""
Test diagnostic Telegram — vérifie token + envoi de message.
Affiche TOUTES les erreurs pour debug.
"""

import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

print("=" * 60)
print("DIAGNOSTIC TELEGRAM")
print("=" * 60)

# 1. Vérification présence des secrets
if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN absent ou vide")
    exit(1)
if not CHAT_ID:
    print("❌ TELEGRAM_CHAT_ID absent ou vide")
    exit(1)

print(f"✅ TELEGRAM_BOT_TOKEN présent (longueur: {len(TOKEN)} caractères)")
print(f"✅ TELEGRAM_CHAT_ID présent : {CHAT_ID}")
print(f"   Format token : {TOKEN[:10]}...{TOKEN[-5:]}")

# 2. Test getMe (valide le token)
print("\n[1/2] Test du token via /getMe...")
try:
    resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
    print(f"   Status HTTP : {resp.status_code}")
    print(f"   Réponse : {resp.text[:300]}")
    if resp.status_code != 200:
        print("❌ TOKEN INVALIDE — il faut le régénérer via @BotFather")
        exit(1)
    bot_info = resp.json().get("result", {})
    print(f"✅ Token valide. Bot : @{bot_info.get('username')} ({bot_info.get('first_name')})")
except Exception as e:
    print(f"❌ Erreur réseau : {e}")
    exit(1)

# 3. Test sendMessage
print("\n[2/2] Test envoi message...")
try:
    resp = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": "🧪 Test diagnostic Telegram OK !"},
        timeout=10,
    )
    print(f"   Status HTTP : {resp.status_code}")
    print(f"   Réponse : {resp.text[:500]}")
    if resp.status_code == 200:
        print("✅ Message envoyé avec succès. Vérifie ton Telegram !")
    elif resp.status_code == 400:
        print("❌ CHAT_ID invalide ou conversation jamais initiée avec le bot")
        print("   Solution : envoie /start à ton bot dans Telegram puis relance ce test")
    elif resp.status_code == 401:
        print("❌ TOKEN INVALIDE")
    elif resp.status_code == 403:
        print("❌ Bot bloqué par l'utilisateur ou conversation pas démarrée")
    else:
        print(f"❌ Erreur inconnue : {resp.status_code}")
except Exception as e:
    print(f"❌ Erreur réseau : {e}")

print("\n" + "=" * 60)
