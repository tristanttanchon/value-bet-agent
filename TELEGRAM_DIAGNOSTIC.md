# Telegram diagnostic
_Généré : 2026-09-10T11:14:28.717627+00:00 UTC_

## Secrets détectés

- `TELEGRAM_BOT_TOKEN` présent : **oui**
- `TELEGRAM_BOT_TOKEN` longueur : **46** caractères
- `TELEGRAM_BOT_TOKEN` masqué (4 derniers chars) : `******************************************pUZY`
- `TELEGRAM_BOT_TOKEN` contient un caractère bizarre en fin ? : **non**
- `TELEGRAM_CHAT_ID` : `******6657`

## Test 1 — `getMe`

- **HTTP** : `200`
- **Réponse** :
```json
{
  "ok": true,
  "result": {
    "id": 8641687590,
    "is_bot": true,
    "first_name": "Traiding Agent IA",
    "username": "Mytradingbo_bot",
    "can_join_groups": true,
    "can_read_all_group_messages": false,
    "supports_inline_queries": false,
    "supports_guest_queries": false,
    "can_connect_to_business": false,
    "has_main_web_app": false,
    "has_topics_enabled": false,
    "allows_users_to_create_topics": false,
    "can_manage_bots": false,
    "supports_join_request_queries": false
  }
}
```

## Test 2 — `sendMessage`

- **HTTP** : `200`
- Message envoyé (visé) : `[diag auto] 2026-09-10T11:14:29.077473+00:00 UTC`
- **Réponse** :
```json
{
  "ok": true,
  "result": {
    "message_id": 268,
    "from": {
      "id": 8641687590,
      "is_bot": true,
      "first_name": "Traiding Agent IA",
      "username": "Mytradingbo_bot"
    },
    "chat": {
      "id": 1741606657,
      "first_name": "*****on",
      "last_name": "*****an",
      "type": "private"
    },
    "date": 1789038869,
    "text": "[diag auto] 2026-09-10T11:14:29.077473+00:00 UTC"
  }
}
```

---

## Interprétation rapide

- **Test 1 HTTP 200 + `ok: true`** → token valide côté Telegram ✅
- **Test 1 HTTP 401 + `Unauthorized`** → token invalide (mauvais, mal collé, ou révoqué)
- **Test 2 HTTP 200 + `ok: true` + tu reçois `[diag auto] ...` sur Telegram** → tout est bon ✅
- **Test 2 `chat not found`** → `TELEGRAM_CHAT_ID` invalide
- **Test 2 `bot was blocked by the user`** → tu as bloqué le bot sur Telegram
