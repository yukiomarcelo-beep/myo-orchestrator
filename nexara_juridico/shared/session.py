"""
Session log append-only com lock thread-safe.
Resolve: race condition com agentes paralelos + checkpoint por agente.
"""

import fcntl
import json
import time
import uuid
from pathlib import Path
from typing import Optional

LOGS_DIR = Path(__file__).parent.parent.parent / "logs" / "nexara_sessions"


class Session:
    def __init__(self, task_id: Optional[str] = None, escritorio_id: Optional[str] = None):
        self.id = task_id or str(uuid.uuid4())[:12]
        self.escritorio_id = escritorio_id
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = LOGS_DIR / f"session_{self.id}.jsonl"

    def append(self, event: str, data: dict):
        entry = {
            "ts": time.time(),
            "session_id": self.id,
            "escritorio_id": self.escritorio_id,
            "event": event,
            **data,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def concluidos(self) -> set:
        return {
            e.get("agente")
            for e in self.replay()
            if e.get("event") == "agente_concluido" and e.get("ok")
        }

    def resultado_de(self, agente: str) -> Optional[dict]:
        for entry in reversed(self.replay()):
            if entry.get("event") == "agente_concluido" and entry.get("agente") == agente:
                return entry.get("resultado")
        return None

    def replay(self) -> list:
        if not self.log_path.exists():
            return []
        entries = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return entries

    def status(self) -> dict:
        entries = self.replay()
        return {
            "session_id": self.id,
            "escritorio_id": self.escritorio_id,
            "total_eventos": len(entries),
            "agentes_concluidos": list(self.concluidos()),
            "ultimo_evento": entries[-1].get("event") if entries else None,
            "tem_erro": any("erro" in e.get("event", "") for e in entries),
        }
