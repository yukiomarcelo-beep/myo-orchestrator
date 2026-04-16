"""
Checklists versionados com semver.
Resolve: sem versionamento, análises antigas ficam incompatíveis silenciosamente.
"""
import json, re
from pathlib import Path
from typing import Optional
from datetime import datetime

CHECKLISTS_DIR = Path(__file__).parent.parent / "checklists"

class ChecklistStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or CHECKLISTS_DIR

    def vigente(self, tipo: str) -> dict:
        versoes = self._listar_versoes(tipo)
        if not versoes:
            raise FileNotFoundError(f"Nenhum checklist para '{tipo}' em {self.base_dir}")
        versoes.sort(key=lambda v: self._semver(v["versao"]), reverse=True)
        return self._ler(versoes[0]["path"])

    def meta_para_log(self, tipo: str) -> dict:
        c = self.vigente(tipo)
        return {"checklist_tipo": tipo, "checklist_versao": c.get("versao", "1.0.0"),
                "checklist_vigente_desde": c.get("vigente_desde"),
                "total_clausulas": len(c.get("clausulas", []))}

    def migrar_legado(self):
        if not self.base_dir.exists():
            print(f"Diretório {self.base_dir} não encontrado.")
            return
        migrados = 0
        for path in self.base_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if "versao" not in data:
                data.update({"versao": "1.0.0", "tipo": path.stem,
                             "vigente_desde": datetime.now().strftime("%Y-%m-%d"),
                             "migrado_automaticamente": True})
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                migrados += 1
                print(f"  Migrado: {path.name}")
        print(f"Migração concluída: {migrados} arquivo(s).")

    def _listar_versoes(self, tipo: str) -> list:
        if not self.base_dir.exists():
            return []
        versoes = []
        for path in self.base_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("tipo") == tipo or path.stem == tipo:
                    versoes.append({"versao": data.get("versao", "1.0.0"), "path": path})
            except Exception:
                continue
        return versoes

    def _ler(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _semver(v: str) -> tuple:
        partes = re.findall(r"\d+", v)
        return tuple(int(p) for p in partes[:3]) if partes else (0, 0, 0)
