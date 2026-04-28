"""
Feedback do advogado sobre análises.
Resolve: sem feedback, produto estático. Base para evoluir checklists.
"""

import fcntl
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

FEEDBACK_DIR = Path(__file__).parent.parent.parent / "logs" / "nexara_feedback"
AvaliacaoTipo = Literal["correto", "incorreto", "impreciso", "faltou_item"]


class FeedbackStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or FEEDBACK_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def registrar(
        self,
        session_id: str,
        escritorio_id: str,
        avaliacao: AvaliacaoTipo,
        agente: str = "consolidador",
        comentario: str = "",
        clausula_ref: str = "",
        tipo_contrato: str = "",
        risco_original: str = "",
    ) -> str:
        fid = str(uuid.uuid4())[:8]
        entry = {
            "id": fid,
            "ts": time.time(),
            "data": datetime.now().strftime("%Y-%m-%d"),
            "session_id": session_id,
            "escritorio_id": escritorio_id,
            "agente": agente,
            "avaliacao": avaliacao,
            "comentario": comentario[:1000],
            "clausula_ref": clausula_ref,
            "tipo_contrato": tipo_contrato,
            "risco_original": risco_original[:500],
        }
        path = self.base_dir / f"feedback_{tipo_contrato or 'geral'}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return fid

    def relatorio_por_tipo(self, tipo_contrato: str = "") -> dict:
        entries = self._carregar(tipo_contrato)
        if not entries:
            return {"tipo_contrato": tipo_contrato, "total": 0}
        from collections import Counter

        avaliacoes = Counter(e.get("avaliacao") for e in entries)
        taxa_acerto = avaliacoes.get("correto", 0) / len(entries) * 100
        clausulas = Counter(
            e.get("clausula_ref")
            for e in entries
            if e.get("avaliacao") in ("incorreto", "impreciso") and e.get("clausula_ref")
        )
        return {
            "tipo_contrato": tipo_contrato or "todos",
            "total_feedbacks": len(entries),
            "taxa_acerto_pct": round(taxa_acerto, 1),
            "avaliacoes": dict(avaliacoes),
            "clausulas_mais_problematicas": dict(clausulas.most_common(5)),
        }

    def _carregar(self, tipo: str) -> list:
        path = self.base_dir / f"feedback_{tipo or 'geral'}.jsonl"
        if not path.exists():
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
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
