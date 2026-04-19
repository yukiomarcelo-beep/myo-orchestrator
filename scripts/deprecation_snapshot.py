"""
Snapshot diario do DeprecationRegistry (FASE 4.3 — wave2).

Uso:
    python scripts/deprecation_snapshot.py [--output /tmp/dep_snapshot.json]

Criterio de remocao (LESSON-013):
    Quando cada shim estiver com contador zerado por 7 dias corridos,
    o cron de monitoramento autoriza execucao da FASE 6.

Integrar como cron ou daemon:
    0 23 * * * /path/to/venv/bin/python /repo/scripts/deprecation_snapshot.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta snapshot do DeprecationRegistry")
    parser.add_argument(
        "--output",
        default="/tmp/dep_snapshot.json",
        help="Arquivo JSON de saida (default: /tmp/dep_snapshot.json)",
    )
    args = parser.parse_args()

    try:
        from orch_core.adapters.deprecation import default_deprecation_registry
    except ImportError as e:
        print(f"[ERROR] Nao foi possivel importar orch_core: {e}", file=sys.stderr)
        sys.exit(1)

    registry = default_deprecation_registry()
    snapshot = registry.snapshot()

    out: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_calls": sum(snapshot.values()),
        "by_shim": {},
    }

    for (shim, module), count in sorted(snapshot.items()):
        out["by_shim"].setdefault(shim, {})[module] = count

    out_path = Path(args.output)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[OK] Snapshot salvo em {out_path} — total_calls={out['total_calls']}")

    # Indicar se esta pronto para LESSON-013
    if out["total_calls"] == 0:
        print("[READY] Todos os contadores zerados. Candidate a LESSON-013.")
    else:
        print(f"[WAIT] {len(out['by_shim'])} shim(s) ainda ativos.")


if __name__ == "__main__":
    main()
