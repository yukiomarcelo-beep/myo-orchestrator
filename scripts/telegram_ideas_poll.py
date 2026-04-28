#!/usr/bin/env python3
"""Poll do Telegram → inbox dos PROJECT_TREE.yaml.

Formato esperado: `ideia <projeto>: <texto>`  (ou `ideia <projeto> <texto>`)

Projetos válidos: forja, kitchen, myo, sofia.

Offset persistido em ~/.claude/telegram_ideas_offset.json pra não reprocessar.
Só aceita mensagens do TELEGRAM_CHAT_ID configurado no .env do MYO.

Chamado periodicamente por launchd (com.marceloyukio.telegram-ideas.plist).
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

HOME = Path.home()
MYO_ENV = HOME / "Documents/orchestrator/.env"
OFFSET_FILE = HOME / ".claude/telegram_ideas_offset.json"
LOG_FILE = Path("/tmp/telegram-ideas-poll.log")

PROJECTS = {
    "forja": HOME / "forja/PROJECT_TREE.yaml",
    "kitchen": HOME / "kitchen/PROJECT_TREE.yaml",
    "myo": HOME / "Documents/orchestrator/PROJECT_TREE.yaml",
    "sofia": HOME / "evolution-api/PROJECT_TREE.yaml",
}

IDEA_RE = re.compile(r"^\s*ideia\s+(\w+)\s*[:\-—]?\s*(.+)$", re.IGNORECASE | re.DOTALL)


def log(msg: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    line = f"[{stamp}] {msg}\n"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="", file=sys.stderr)


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_offset() -> int:
    if not OFFSET_FILE.exists():
        return 0
    try:
        return int(json.loads(OFFSET_FILE.read_text()).get("offset", 0))
    except Exception:
        return 0


def save_offset(offset: int) -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(json.dumps({"offset": offset, "saved_at": datetime.now().isoformat()}))


def telegram_api(token: str, method: str, params: dict, timeout: int = 20) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def send_reply(token: str, chat_id: str, text: str) -> None:
    try:
        telegram_api(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        log(f"falha send_reply: {e}")


def append_to_inbox(project_key: str, idea_text: str, source: dict) -> None:
    path = PROJECTS[project_key]
    if not path.exists():
        raise FileNotFoundError(f"YAML do projeto {project_key} não existe: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    inbox = data.get("inbox") or []
    entry = {
        "text": idea_text.strip(),
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "source": "telegram",
        "from": source.get("from", ""),
    }
    inbox.append(entry)
    data["inbox"] = inbox
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main() -> int:
    env = load_env(MYO_ENV)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    allowed_chat = env.get("TELEGRAM_CHAT_ID", "")
    if not token:
        log("TELEGRAM_BOT_TOKEN não configurado — abortando")
        return 1

    offset = load_offset()
    try:
        res = telegram_api(token, "getUpdates", {"offset": offset, "timeout": 0, "limit": 50})
    except Exception as e:
        log(f"falha getUpdates: {e}")
        return 2

    if not res.get("ok"):
        log(f"resposta Telegram não-ok: {res}")
        return 3

    updates = res.get("result") or []
    if not updates:
        return 0

    last_update_id = offset
    processed = 0
    ignored = 0

    for upd in updates:
        uid = upd.get("update_id", 0)
        last_update_id = max(last_update_id, uid)

        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = msg.get("text") or ""
        sender = msg.get("from") or {}
        sender_name = sender.get("username") or sender.get("first_name") or "?"

        if allowed_chat and chat_id != allowed_chat:
            ignored += 1
            continue

        m = IDEA_RE.match(text)
        if not m:
            continue

        project_key = m.group(1).lower()
        idea_text = m.group(2).strip()

        if project_key not in PROJECTS:
            send_reply(
                token,
                chat_id,
                f"❓ projeto <b>{project_key}</b> não reconhecido.\nDisponíveis: {', '.join(PROJECTS)}",
            )
            continue

        try:
            append_to_inbox(project_key, idea_text, {"from": sender_name})
            send_reply(
                token,
                chat_id,
                f"💡 ideia capturada em <b>{project_key}</b>:\n<i>{idea_text[:200]}</i>",
            )
            processed += 1
            log(f"ideia salva em {project_key}: {idea_text[:80]}")
        except Exception as e:
            log(f"falha ao salvar ideia em {project_key}: {e}")
            send_reply(token, chat_id, f"❌ erro ao salvar em {project_key}: {e}")

    save_offset(last_update_id + 1)
    if processed or ignored:
        log(f"processadas={processed} ignoradas={ignored} novo_offset={last_update_id + 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
