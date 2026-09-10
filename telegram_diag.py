"""
telegram_diag.py — Diagnostic complet du bot Telegram.

Teste getMe + sendMessage avec les secrets courants et écrit le résultat
dans TELEGRAM_DIAGNOSTIC.md (committé au repo par le workflow associé).

Token et chat_id sont masqués — aucune donnée sensible n'est écrite.
"""

import json
import os
from datetime import datetime, timezone

import requests


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def mask(s: str, keep_last: int = 4) -> str:
    if not s:
        return "(VIDE)"
    if len(s) <= keep_last:
        return "*" * len(s)
    return "*" * (len(s) - keep_last) + s[-keep_last:]


def _redact(body: dict) -> dict:
    """Retire les infos sensibles éventuelles de la réponse Telegram."""
    if not isinstance(body, dict):
        return body
    result = body.get("result")
    if isinstance(result, dict):
        # Chat info dans un résultat sendMessage : on masque le username/first_name
        chat = result.get("chat")
        if isinstance(chat, dict):
            for k in ("username", "first_name", "last_name"):
                if k in chat and chat[k]:
                    chat[k] = mask(str(chat[k]), 2)
    return body


def _pretty(obj) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)


def run() -> str:
    lines = [
        "# Telegram diagnostic",
        f"_Généré : {datetime.now(timezone.utc).isoformat()} UTC_",
        "",
        "## Secrets détectés",
        "",
        f"- `TELEGRAM_BOT_TOKEN` présent : **{'oui' if TOKEN else 'NON ❌'}**",
        f"- `TELEGRAM_BOT_TOKEN` longueur : **{len(TOKEN)}** caractères",
        f"- `TELEGRAM_BOT_TOKEN` masqué (4 derniers chars) : `{mask(TOKEN)}`",
        f"- `TELEGRAM_BOT_TOKEN` contient un caractère bizarre en fin ? : "
        f"**{'OUI (à corriger)' if TOKEN and TOKEN.strip() != TOKEN else 'non'}**",
        f"- `TELEGRAM_CHAT_ID` : `{mask(CHAT_ID, 4)}`",
        "",
        "## Test 1 — `getMe`",
        "",
    ]

    if not TOKEN:
        lines.append("❌ Impossible de tester : token vide dans les secrets GitHub.")
    else:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TOKEN.strip()}/getMe",
                timeout=10,
            )
            lines.append(f"- **HTTP** : `{r.status_code}`")
            lines.append("- **Réponse** :")
            lines.append("```json")
            try:
                body = _redact(r.json())
                lines.append(_pretty(body))
            except Exception:
                lines.append(r.text[:500])
            lines.append("```")
        except Exception as e:
            lines.append(f"- ❌ Exception réseau : `{type(e).__name__}` — {e}")

    lines += [
        "",
        "## Test 2 — `sendMessage`",
        "",
    ]

    if not TOKEN or not CHAT_ID:
        lines.append("❌ Impossible de tester : token ou chat_id vide.")
    else:
        try:
            text = f"[diag auto] {datetime.now(timezone.utc).isoformat()} UTC"
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN.strip()}/sendMessage",
                json={"chat_id": CHAT_ID.strip(), "text": text},
                timeout=10,
            )
            lines.append(f"- **HTTP** : `{r.status_code}`")
            lines.append(f"- Message envoyé (visé) : `{text}`")
            lines.append("- **Réponse** :")
            lines.append("```json")
            try:
                body = _redact(r.json())
                lines.append(_pretty(body))
            except Exception:
                lines.append(r.text[:500])
            lines.append("```")
        except Exception as e:
            lines.append(f"- ❌ Exception réseau : `{type(e).__name__}` — {e}")

    lines += [
        "",
        "---",
        "",
        "## Interprétation rapide",
        "",
        "- **Test 1 HTTP 200 + `ok: true`** → token valide côté Telegram ✅",
        "- **Test 1 HTTP 401 + `Unauthorized`** → token invalide (mauvais, mal collé, ou révoqué)",
        "- **Test 2 HTTP 200 + `ok: true` + tu reçois `[diag auto] ...` sur Telegram** → tout est bon ✅",
        "- **Test 2 `chat not found`** → `TELEGRAM_CHAT_ID` invalide",
        "- **Test 2 `bot was blocked by the user`** → tu as bloqué le bot sur Telegram",
        "",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    output = run()
    print(output)
    with open("TELEGRAM_DIAGNOSTIC.md", "w", encoding="utf-8") as f:
        f.write(output)
    print("\n→ écrit dans TELEGRAM_DIAGNOSTIC.md")
