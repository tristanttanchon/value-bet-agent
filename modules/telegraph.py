"""
Telegraph Publisher — publie les analyses de matchs sur telegra.ph
pour obtenir une URL courte, affichable en preview natif dans Telegram.

API doc : https://telegra.ph/api

Un compte est créé au premier appel du run (token gardé en mémoire).
Telegraph ne limite pas la création de comptes ni de pages, c'est gratuit
et sans authentification.
"""

import re
import json
import requests
from datetime import date


TELEGRAPH_API = "https://api.telegra.ph"

# Token créé à la volée et caché pendant la durée du process
_access_token: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Authentification
# ─────────────────────────────────────────────────────────────────────────────

def _get_access_token() -> str | None:
    """Crée un compte Telegraph anonyme et retourne le token (caché pour le run)."""
    global _access_token
    if _access_token:
        return _access_token
    try:
        resp = requests.post(
            f"{TELEGRAPH_API}/createAccount",
            data={
                "short_name": "ValueBet",
                "author_name": "Value Bet Agent",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            _access_token = data["result"]["access_token"]
            return _access_token
        print(f"[Telegraph] createAccount KO : {data}")
    except Exception as e:
        print(f"[Telegraph] Erreur createAccount : {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Conversion markdown → nodes Telegraph
# ─────────────────────────────────────────────────────────────────────────────
# Format Telegraph : liste de strings (texte) ou dicts {"tag","attrs","children"}
# Tags autorisés : a, aside, b, blockquote, br, code, em, figcaption, figure,
#                  h3, h4, hr, i, iframe, img, li, ol, p, pre, s, strong, u, ul, video

def _parse_inline(text: str) -> list:
    """Parse les styles inline : **bold** et *italic*."""
    result = []
    # Étape 1 : split sur **bold**
    parts = re.split(r"(\*\*[^*\n]+\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            result.append({"tag": "b", "children": [part[2:-2]]})
        else:
            # Étape 2 : split sur *italic* à l'intérieur
            sub = re.split(r"(\*[^*\n]+\*)", part)
            for sp in sub:
                if not sp:
                    continue
                if sp.startswith("*") and sp.endswith("*") and len(sp) >= 3:
                    result.append({"tag": "i", "children": [sp[1:-1]]})
                else:
                    result.append(sp)
    return result


def _markdown_to_nodes(text: str) -> list:
    """Convertit un texte markdown simple en arbre de nodes Telegraph."""
    text = (text or "").strip()
    if not text:
        return []

    nodes = []
    blocks = re.split(r"\n\s*\n", text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Titres markdown
        if block.startswith("### "):
            nodes.append({"tag": "h4", "children": _parse_inline(block[4:].strip())})
            continue
        if block.startswith("## "):
            nodes.append({"tag": "h3", "children": _parse_inline(block[3:].strip())})
            continue

        # Bloc "liste" si toutes les lignes commencent par -, • ou *
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if lines and all(re.match(r"^\s*[-•]\s+", ln) for ln in lines):
            items = []
            for ln in lines:
                content = re.sub(r"^\s*[-•]\s+", "", ln)
                items.append({"tag": "li", "children": _parse_inline(content)})
            nodes.append({"tag": "ul", "children": items})
            continue

        # Paragraphe standard (\n simple → <br>)
        children = []
        for i, ln in enumerate(block.split("\n")):
            children.extend(_parse_inline(ln))
            if i < len(block.split("\n")) - 1:
                children.append({"tag": "br"})
        nodes.append({"tag": "p", "children": children})

    return nodes


# ─────────────────────────────────────────────────────────────────────────────
# Publication
# ─────────────────────────────────────────────────────────────────────────────

def publish_analysis(
    title: str,
    body: str,
    header_fields: dict | None = None,
) -> str | None:
    """
    Publie une analyse de match sur Telegraph.

    Args:
        title         : titre de l'article (ex: "Everton vs Liverpool — [1]")
        body          : contenu markdown simple (paragraphes, listes, bold/italic)
        header_fields : dict optionnel affiché en en-tête sous forme de liste
                        (ex: {"Marché": "1", "Cote": "11.0", "Edge": "32%"})

    Returns:
        URL publique Telegraph, ou None si échec.
    """
    token = _get_access_token()
    if not token:
        return None

    nodes: list = []

    # En-tête : récap des caractéristiques du pari
    if header_fields:
        items = []
        for k, v in header_fields.items():
            items.append({
                "tag": "li",
                "children": [
                    {"tag": "b", "children": [f"{k} : "]},
                    str(v),
                ],
            })
        nodes.append({"tag": "ul", "children": items})
        nodes.append({"tag": "hr"})

    # Corps de l'analyse
    nodes.extend(_markdown_to_nodes(body))

    # Footer
    nodes.append({"tag": "hr"})
    nodes.append({
        "tag": "p",
        "children": [
            {"tag": "i", "children": [
                f"Analyse générée automatiquement — Value Bet Agent — {date.today().isoformat()}"
            ]}
        ]
    })

    try:
        resp = requests.post(
            f"{TELEGRAPH_API}/createPage",
            data={
                "access_token": token,
                "title": title[:256],  # Telegraph limite à 256 chars
                "author_name": "Value Bet Agent",
                "content": json.dumps(nodes, ensure_ascii=False),
                "return_content": "false",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            return data["result"]["url"]
        print(f"[Telegraph] createPage KO pour '{title}' : {data}")
    except Exception as e:
        print(f"[Telegraph] Erreur publication '{title}' : {e}")

    return None
