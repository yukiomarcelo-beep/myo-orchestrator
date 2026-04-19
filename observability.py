#!/usr/bin/env python3
"""Módulo de observabilidade — tracker de chamadas LLM e tracer de steps."""
import json, time, uuid
from pathlib import Path

# ── Security Bridge — CostTracker integrado à observabilidade ─────────────────
try:
    from core.security_bridge import record_cost as _record_cost
    _SECURITY_ENABLED = True
except ImportError:
    _SECURITY_ENABLED = False
    def _record_cost(ti, to, m="claude-sonnet"): return {"status": "ok", "cost": 0, "daily_total": 0}
# ───────────────────────────────────────────────────────────────────────────────

_OBS_DIR = Path("outputs/observability")
_OBS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_COSTS = {
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":  {"input": 0.80,  "output": 4.00},
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":       {"input": 0.15,  "output": 0.60},
    "unknown":           {"input": 3.00,  "output": 15.00},
}


def _append(name: str, record: dict):
    path = _OBS_DIR / f"{name}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class _TrackContext:
    def __init__(self, **meta):
        self.meta      = meta
        self.run_id    = uuid.uuid4().hex[:8]
        self._input    = 0
        self._output   = 0
        self._start    = 0.0

    def set_tokens(self, input: int = 0, output: int = 0):
        self._input  = input
        self._output = output

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        model  = self.meta.get("model", "unknown")
        rates  = MODEL_COSTS.get(model, MODEL_COSTS["unknown"])
        cost_usd = round(
            (self._input  / 1_000_000) * rates["input"] +
            (self._output / 1_000_000) * rates["output"],
            8,
        )
        record = {
            **self.meta,
            "run_id":        self.run_id,
            "input_tokens":  self._input,
            "output_tokens": self._output,
            "cost_usd":      cost_usd,
            "elapsed_s":     round(time.time() - self._start, 3),
            "status":        "error" if exc_type else "success",
            "timestamp":     time.strftime("%Y%m%d_%H%M%S"),
        }
        _append("tracker", record)

        # Alimenta CostTracker da security layer
        cost_status = _record_cost(self._input, self._output, model)
        if cost_status["status"] in ("shutdown_non_critical", "emergency_stop"):
            import sys
            print(f"[Security/Observability] ALERTA CUSTO: {cost_status['status']} — "
                  f"${cost_status['daily_total']:.4f} hoje", file=sys.stderr)

        return False  # não suprime exceções


class _Tracker:
    def track(self, **kwargs) -> _TrackContext:
        return _TrackContext(**kwargs)

    def report(self):
        """Soma tokens e custo total de tracker.jsonl"""
        import json
        from pathlib import Path
        log = Path("outputs/observability/tracker.jsonl")
        if not log.exists():
            print("Sem dados ainda."); return
        total_cost, total_tokens, calls, errors = 0, 0, 0, 0
        for line in log.read_text().splitlines():
            try:
                d = json.loads(line)
                total_cost   += d.get("cost_usd", 0)
                total_tokens += d.get("input_tokens", 0) + d.get("output_tokens", 0)
                calls        += 1
                if d.get("status") == "error": errors += 1
            except: continue
        print(f"\n=== COST REPORT ===")
        print(f"  Calls:    {calls}")
        print(f"  Tokens:   {total_tokens:,}")
        print(f"  Custo:    ${round(total_cost, 4)}")
        print(f"  Erros:    {errors}")
        print(f"  Proj/mês: ${round(total_cost * 30, 2)}\n")

    def report_by_engine(self):
        """Agrupa tokens e custo por engine_name"""
        import json
        from pathlib import Path
        log = Path("outputs/observability/tracker.jsonl")
        if not log.exists():
            print("Sem dados ainda."); return
        engines = {}
        for line in log.read_text().splitlines():
            try:
                d = json.loads(line)
                k = d.get("engine_name", "unknown")
                if k not in engines:
                    engines[k] = {"calls": 0, "cost": 0.0, "tokens": 0}
                engines[k]["calls"]  += 1
                engines[k]["cost"]   += d.get("cost_usd", 0)
                engines[k]["tokens"] += d.get("input_tokens", 0) + d.get("output_tokens", 0)
            except: continue
        print(f"\n=== CUSTO POR ENGINE ===")
        for k, v in sorted(engines.items(), key=lambda x: x[1]["cost"], reverse=True):
            print(f"  {k:<30} ${round(v['cost'],4):<10} {v['calls']} calls")
        print()

    def report_by_confidence(self):
        """Agrupa por data_confidence"""
        import json
        from pathlib import Path
        log = Path("outputs/observability/tracker.jsonl")
        if not log.exists():
            print("Sem dados ainda."); return
        conf = {}
        for line in log.read_text().splitlines():
            try:
                d = json.loads(line)
                k = d.get("confidence", d.get("data_confidence", "unknown"))
                conf.setdefault(k, {"calls": 0, "cost": 0.0})
                conf[k]["calls"] += 1
                conf[k]["cost"]  += d.get("cost_usd", 0)
            except: continue
        icons = {"validated": "✅", "observed": "👁 ", "simulated": "🔮"}
        print(f"\n=== CONFIANÇA DOS DADOS ===")
        for k, v in conf.items():
            print(f"  {icons.get(k,'?')} {k:<15} {v['calls']} calls  ${round(v['cost'],4)}")
        print()


class _Tracer:
    def start_run(self, run_id: str, **kwargs):
        record = {"run_id": run_id, "event": "start_run",
                  "timestamp": time.strftime("%Y%m%d_%H%M%S"), **kwargs}
        _append("tracer", record)

    def step(self, run_id: str, **kwargs):
        record = {
            "run_id":    run_id,
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            **kwargs,
        }
        record["event"] = "step"
        _append("tracer", record)

    def update_progress(self, run_id: str, progress: float, **kwargs):
        record = {"run_id": run_id, "event": "progress",
                  "progress_pct": round(float(progress), 1),
                  "timestamp": time.strftime("%Y%m%d_%H%M%S"), **kwargs}
        _append("tracer", record)

    def end_run(self, run_id: str, **kwargs):
        record = {"run_id": run_id, "event": "end_run",
                  "timestamp": time.strftime("%Y%m%d_%H%M%S"), **kwargs}
        _append("tracer", record)

    def diagnose_stuck_pipelines(self, stuck_minutes=30):
        """Encontra start_run sem end_run correspondente"""
        import json
        from pathlib import Path
        from datetime import datetime, timedelta
        log = Path("outputs/observability/tracer.jsonl")
        if not log.exists():
            print("Sem dados ainda."); return []
        starts, ends = {}, set()
        for line in log.read_text().splitlines():
            try:
                d = json.loads(line)
                if d.get("event") == "start_run":
                    starts[d["run_id"]] = d
                elif d.get("event") == "end_run":
                    ends.add(d["run_id"])
            except: continue
        cutoff = datetime.now() - timedelta(minutes=stuck_minutes)
        stuck = []
        print(f"\n=== PIPELINES TRAVADOS (>{stuck_minutes}min) ===")
        for run_id, d in starts.items():
            if run_id in ends: continue
            try:
                ts = datetime.strptime(d["timestamp"], "%Y%m%d_%H%M%S")
                mins = int((datetime.now() - ts).total_seconds() / 60)
                if ts < cutoff:
                    stuck.append(d)
                    print(f"  ❌ [{run_id}] {d.get('pipeline','?')} — {mins}min parado")
                    print(f"     Último progresso: {d.get('progress_pct', '?')}%")
            except: continue
        if not stuck: print("  ✅ Nenhum pipeline travado.")
        print()
        return stuck

    def error_hotspots(self):
        """Agrupa steps com status=error por action"""
        import json
        from pathlib import Path
        log = Path("outputs/observability/tracer.jsonl")
        if not log.exists():
            print("Sem dados ainda."); return
        spots = {}
        for line in log.read_text().splitlines():
            try:
                d = json.loads(line)
                if d.get("status") == "error" and d.get("event") == "step":
                    k = d.get("action", "unknown")
                    spots.setdefault(k, {"count": 0, "last": ""})
                    spots[k]["count"] += 1
                    spots[k]["last"]   = d.get("error_message", "")[:80]
            except: continue
        print(f"\n=== HOTSPOTS DE ERRO ===")
        if not spots:
            print("  ✅ Nenhum erro registrado.")
        for k, v in sorted(spots.items(), key=lambda x: x[1]["count"], reverse=True):
            print(f"  {k:<35} {v['count']} erros")
            if v["last"]: print(f"    └─ {v['last']}")
        print()


tracker = _Tracker()
tracer  = _Tracer()
