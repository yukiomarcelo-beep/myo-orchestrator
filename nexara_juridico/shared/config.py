"""
Carregador central de configuração.
Resolve: portas e modelos hardcoded espalhados pelos agentes.
"""
import json
from pathlib import Path
from functools import lru_cache
from typing import Any

_POSSIVEIS = [
    Path("nexara_config.json"),
    Path(__file__).parent.parent.parent / "nexara_config.json",
    Path(__file__).parent.parent / "nexara_config.json",
]

@lru_cache(maxsize=1)
def _carregar() -> dict:
    for p in _POSSIVEIS:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}

class _Config:
    def porta(self, servico: str) -> int:
        return _carregar().get("servicos", {}).get(servico, {}).get("porta", 8765)
    def modelo(self, tarefa: str) -> str:
        return _carregar().get("modelos", {}).get(tarefa, "claude-sonnet-4-6")
    def timeout(self, servico: str) -> int:
        return _carregar().get("servicos", {}).get(servico, {}).get("timeout_segundos", 120)
    def get(self, *keys, default=None) -> Any:
        data = _carregar()
        for k in keys:
            if isinstance(data, dict):
                data = data.get(k)
            else:
                return default
        return data if data is not None else default

cfg = _Config()
