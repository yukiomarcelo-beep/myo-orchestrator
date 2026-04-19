"""
Memória de cliente como arquivo — não como prompt.
Resolve: sem rastreamento de ROI, memória no system prompt.
"""
import json, time, fcntl
from pathlib import Path
from typing import Optional
from datetime import datetime, date

PROFILES_DIR = Path(__file__).parent.parent.parent / "logs" / "nexara_profiles"
RESUMO_MAX = 600
HISTORICO_MAX = 100

class ProfileStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or PROFILES_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def carregar(self, escritorio_id: str) -> dict:
        path = self._path(escritorio_id)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    return json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        return {"escritorio_id": escritorio_id, "nome": escritorio_id,
                "criado_em": datetime.now().isoformat(),
                "areas_foco": [], "valor_hora_advogado": 350,
                "historico": [], "preferencias": {}}

    def contexto_para_prompt(self, escritorio_id: str, n_ultimas: int = 3) -> str:
        perfil = self.carregar(escritorio_id)
        ultimas = perfil.get("historico", [])[-n_ultimas:]
        if not ultimas:
            return f"Escritório: {escritorio_id}. Nenhuma análise anterior."
        linhas = [f"Escritório: {perfil.get('nome', escritorio_id)}"]
        for a in ultimas:
            linhas.append(f"  - {a.get('tipo_contrato', '?')} "
                          f"({a.get('n_riscos', 0)} riscos) — {a.get('data', '?')}")
        return "\n".join(linhas)

    def registrar_analise(self, escritorio_id: str, analise: dict):
        perfil = self.carregar(escritorio_id)
        entrada = {"ts": time.time(), "data": date.today().isoformat(),
                   **{k: v for k, v in analise.items() if k != "relatorio_completo"},
                   "resumo": str(analise.get("resumo", ""))[:RESUMO_MAX]}
        perfil.setdefault("historico", []).append(entrada)
        perfil["historico"] = perfil["historico"][-HISTORICO_MAX:]
        self._salvar(escritorio_id, perfil)

    def relatorio_roi(self, escritorio_id: str) -> dict:
        perfil = self.carregar(escritorio_id)
        historico = perfil.get("historico", [])
        horas = sum(a.get("horas_economizadas", 0) for a in historico)
        valor_hora = perfil.get("valor_hora_advogado", 350)
        from collections import Counter
        por_tipo = {}
        for a in historico:
            tipo = a.get("tipo_contrato", "outros")
            por_tipo.setdefault(tipo, {"analises": 0, "horas": 0.0})
            por_tipo[tipo]["analises"] += 1
            por_tipo[tipo]["horas"] += a.get("horas_economizadas", 0)
        return {
            "escritorio_id": escritorio_id,
            "nome": perfil.get("nome", escritorio_id),
            "total_analises": len(historico),
            "horas_economizadas_total": round(horas, 1),
            "valor_economizado_estimado_brl": round(horas * valor_hora, 2),
            "por_tipo": por_tipo,
            "primeira_analise": historico[0].get("data") if historico else None,
            "ultima_analise": historico[-1].get("data") if historico else None,
        }

    def _path(self, escritorio_id: str) -> Path:
        safe = "".join(c for c in escritorio_id if c.isalnum() or c in "-_")
        return self.base_dir / f"{safe}.json"

    def _salvar(self, escritorio_id: str, perfil: dict):
        with open(self._path(escritorio_id), "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(perfil, f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
