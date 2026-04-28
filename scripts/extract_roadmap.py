#!/usr/bin/env python3
"""Extrai próximas etapas dos CLAUDE.md + checkpoints + STATUS.md de cada projeto.

Fontes escaneadas:
- ~/kitchen/CLAUDE.md + ~/kitchen/STATUS.md (se existir)
- ~/Documents/orchestrator/CLAUDE.md + STATUS.md
- ~/evolution-api/CLAUDE.md
- ~/.claude/projects/-Users-marceloyukio/memory/projetos/*/checkpoint_*.md
- ~/.claude/projects/-Users-marceloyukio/memory/projetos/*/project_*.md

Retorna estrutura:
{
  "kitchen": {
    "project_name": "Kitchen / Nexxor",
    "emoji": "🍳",
    "version": "v0.9.0",  # se detectável
    "freshness": {"latest_source_age_days": 0},
    "items": [
      {
        "text": "Testar cmv_variacao E2E",
        "urgency": "high",  # high | medium | low
        "source_file": "checkpoint_dia10.md",
        "source_section": "Próximo passo candidato (Dia 11)",
      },
      ...
    ],
    "done_recent": [...]  # bullets com [x] ou "feito"
  },
  "myo": {...},
  "sofia": {...}
}
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

HOME = Path.home()
MEMORY_PROJETOS = HOME / ".claude/projects/-Users-marceloyukio/memory/projetos"

PROJECT_CONFIG = {
    "kitchen": {
        "name": "Kitchen / Nexxor",
        "emoji": "🍳",
        "claude_md": HOME / "kitchen/CLAUDE.md",
        "extra_files": [HOME / "kitchen/STATUS.md"],
        "memory_dir": MEMORY_PROJETOS / "kitchen-nexxor",
    },
    "myo": {
        "name": "MYO OS",
        "emoji": "🤖",
        "claude_md": HOME / "Documents/orchestrator/CLAUDE.md",
        "extra_files": [
            HOME / "Documents/orchestrator/STATUS.md",
            HOME / "Documents/orchestrator/README.md",
        ],
        "memory_dir": MEMORY_PROJETOS / "myo-os",
    },
    "sofia": {
        "name": "SOFIA",
        "emoji": "📱",
        "claude_md": HOME / "evolution-api/CLAUDE.md",
        "extra_files": [],
        "memory_dir": MEMORY_PROJETOS / "sofia-whatsapp",
    },
    "forja": {
        "name": "Forja",
        "emoji": "🔥",
        "claude_md": HOME / "forja/CLAUDE.md",
        "extra_files": [HOME / "forja/STATUS.md", HOME / "forja/README.md"],
        "memory_dir": MEMORY_PROJETOS / "forja",
    },
}

# Headings que indicam "próximas etapas" (normalizado — minúsculo + sem acento)
NEXT_STEP_HEADINGS = re.compile(
    r"^(?:#{1,6}\s*)?("
    r"proximos? passos?"
    r"|proxima etapa"
    r"|proxima? acao"
    r"|pendencias?"
    r"|pendencias? ativas"
    r"|debitos? conhecidos?"
    r"|dividas? conhecidas?"
    r"|dividas? tecnicas?"
    r"|todo"
    r"|backlog"
    r"|roadmap"
    r"|o que falta"
    r"|faltando"
    r"|next steps?"
    r"|decisao pendente"
    r"|decisoes pendentes"
    r"|candidato"
    r"|candidato\w*\s*\(dia \d+\)?"
    r").*$",
    re.IGNORECASE,
)

URGENCY_HIGH = re.compile(
    r"\b(critico|urgente|bloqueio|bloqueia|broken|grave|emergencia|decisao pendente|asap)\b"
    r"|🔴|❗|🚨",
    re.IGNORECASE,
)
URGENCY_MED = re.compile(
    r"\b(importante|proxim|high|media prioridade|pendente)\b" r"|🟡|⚠️",
    re.IGNORECASE,
)

VERSION_RE = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")


def normalize(s: str) -> str:
    """Lower + strip accents pra matching case-insensitive sem acento."""
    import unicodedata

    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def classify_urgency(text: str) -> str:
    n = normalize(text)
    if URGENCY_HIGH.search(n):
        return "high"
    if URGENCY_MED.search(n):
        return "medium"
    return "low"


def is_done(line: str) -> bool:
    return bool(re.search(r"\[x\]|^✓|^✅|concluido|concluída|feito", normalize(line)))


def extract_sections(
    content: str,
) -> list[tuple[str, int, list[tuple[str, str]]]]:
    """Retorna [(root_title, start_line, [(sub_title_or_root, bullet), ...])].

    Sub-headings dentro da seção-raiz (ex: "### 🔴 CRÍTICO") são rastreados
    para permitir que urgência seja herdada do sub-heading pelos bullets.
    """
    lines = content.splitlines()
    sections: list[tuple[str, int, list[tuple[str, str]]]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            title = m.group(2).strip()
            title_norm = normalize(title)
            if NEXT_STEP_HEADINGS.match(title_norm):
                level = len(m.group(1))
                current_sub: Optional[str] = None
                bullets_ctx: list[tuple[str, str]] = []
                j = i + 1
                while j < len(lines):
                    raw_j = lines[j]
                    sj = raw_j.strip()
                    mh = re.match(r"^(#{1,6})\s+(.+)$", sj)
                    if mh:
                        if len(mh.group(1)) <= level:
                            break
                        current_sub = mh.group(2).strip()
                        j += 1
                        continue
                    bm = re.match(r"^\s*(?:[-*•▸►]|\d+\.)\s+(.+)$", raw_j)
                    if bm:
                        ctx = current_sub or title
                        bullets_ctx.append((ctx, bm.group(1).strip()))
                    j += 1
                if bullets_ctx:
                    sections.append((title, i + 1, bullets_ctx))
                i = j
                continue
        i += 1
    return sections


def detect_version(content: str) -> Optional[str]:
    """Tenta detectar versão/tag atual do projeto."""
    for line in content.splitlines()[:50]:
        if re.search(r"\bmain @\b|\btag\b|\bversao\b|version", line.lower()):
            m = VERSION_RE.search(line)
            if m:
                return m.group(0)
    m = VERSION_RE.search(content[:2000])
    return m.group(0) if m else None


def extract_bullets_from_sections(
    file_path: Path,
    sections: list[tuple[str, int, list[tuple[str, str]]]],
) -> list[dict]:
    items: list[dict] = []
    order = {"high": 3, "medium": 2, "low": 1}
    for root_title, line_no, bullets_ctx in sections:
        root_urg = classify_urgency(root_title)
        for ctx_title, b in bullets_ctx:
            clean = re.sub(r"\*\*|__|`", "", b)[:200]
            urg = max(
                (classify_urgency(b), classify_urgency(ctx_title), root_urg),
                key=lambda u: order[u],
            )
            items.append(
                {
                    "text": clean,
                    "urgency": urg,
                    "done": is_done(b),
                    "source_file": file_path.name,
                    "source_path": str(file_path),
                    "source_section": ctx_title,
                    "source_line": line_no,
                }
            )
    return items


def age_days(path: Path) -> int:
    return int((datetime.now().timestamp() - path.stat().st_mtime) / 86400)


def scan_project(project_key: str) -> dict:
    cfg = PROJECT_CONFIG[project_key]
    all_items: list[dict] = []
    done_items: list[dict] = []
    sources_used: list[dict] = []
    version: Optional[str] = None
    latest_age = 999

    # Arquivos a escanear (CLAUDE.md + extras + checkpoints da memória)
    files_to_scan: list[Path] = []
    if cfg["claude_md"].exists():
        files_to_scan.append(cfg["claude_md"])
    for extra in cfg["extra_files"]:
        if extra.exists():
            files_to_scan.append(extra)
    mem_dir = cfg["memory_dir"]
    if mem_dir.exists():
        # Prioridade: checkpoint mais recente primeiro
        checkpoints = sorted(
            mem_dir.glob("checkpoint_*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        files_to_scan.extend(checkpoints[:3])  # 3 mais recentes
        # Project files também
        for p in mem_dir.glob("project_*.md"):
            files_to_scan.append(p)

    for f in files_to_scan:
        try:
            content = f.read_text()
        except Exception:
            continue
        age = age_days(f)
        if age < latest_age:
            latest_age = age
        if not version:
            version = detect_version(content)
        sections = extract_sections(content)
        if sections:
            sources_used.append({"file": f.name, "age_days": age, "n_sections": len(sections)})
        items = extract_bullets_from_sections(f, sections)
        for it in items:
            if it["done"]:
                done_items.append(it)
            else:
                all_items.append(it)

    # Dedup por texto (case insensitive)
    seen = set()
    deduped = []
    for it in all_items:
        key = normalize(it["text"])[:80]
        if key not in seen:
            seen.add(key)
            deduped.append(it)

    # Ordena: high → medium → low
    order = {"high": 0, "medium": 1, "low": 2}
    deduped.sort(key=lambda x: order.get(x["urgency"], 3))

    return {
        "key": project_key,
        "name": cfg["name"],
        "emoji": cfg["emoji"],
        "version": version,
        "latest_source_age_days": latest_age if latest_age < 999 else None,
        "items": deduped,
        "done_recent": done_items[:8],
        "sources": sources_used,
    }


def scan_all() -> dict:
    return {key: scan_project(key) for key in PROJECT_CONFIG.keys()}


if __name__ == "__main__":
    import json

    result = scan_all()
    # Print summary
    for key, p in result.items():
        print(f"\n{p['emoji']} {p['name']} — {p['version'] or 'sem versão'}")
        print(f"  {len(p['items'])} próximas etapas · {len(p['sources'])} fontes")
        for it in p["items"][:5]:
            marker = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(it["urgency"], "⚪")
            print(f"  {marker} {it['text'][:70]}  ← {it['source_file']}")
    print("\n---\nJSON output:\n")
    print(json.dumps(result, indent=2, default=str)[:2000], "...")
