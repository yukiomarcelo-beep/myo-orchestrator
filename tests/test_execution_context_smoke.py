"""Smoke test: validacao runtime de execution_context (LESSON-002)."""
import sys
from pathlib import Path

src = Path(__file__).parent.parent / "utils" / "verification_engine.py"
text = src.read_text(encoding="utf-8")
start = text.index("VALID_EXECUTION_CONTEXTS = frozenset")
end = text.index("# =========================\n# ENUMS", start)
ns = {}
exec(text[start:end], ns)

normalize = ns["normalize_execution_context"]
VALID = ns["VALID_EXECUTION_CONTEXTS"]
DEFAULT = ns["DEFAULT_EXECUTION_CONTEXT"]

def run():
    failures = []
    for v in ["idea", "research", "mvp", "launch_ready", "scaling"]:
        try:
            got = normalize(v)
            assert got == v
            print(f"  OK   valido: {v!r} -> {got!r}")
        except Exception as e:
            failures.append((v, repr(e)))
    for inp, exp in [("  MVP  ", "mvp"), ("Launch_Ready", "launch_ready"), ("SCALING", "scaling")]:
        try:
            got = normalize(inp)
            assert got == exp
            print(f"  OK   norm: {inp!r} -> {got!r}")
        except Exception as e:
            failures.append((inp, repr(e)))
    for empty in ["", None]:
        try:
            got = normalize(empty)
            assert got == DEFAULT
            print(f"  OK   default: {empty!r} -> {got!r}")
        except Exception as e:
            failures.append((empty, repr(e)))
    for bad in ["production", "launch", "lauch_ready", "xyz", "discovery"]:
        try:
            got = normalize(bad)
            failures.append((bad, f"nao levantou erro, retornou {got!r}"))
            print(f"  FAIL invalido nao rejeitado: {bad!r} -> {got!r}")
        except ValueError:
            print(f"  OK   invalido rejeitado: {bad!r}")
    print()
    if failures:
        print(f"SMOKE TEST FALHOU: {len(failures)}")
        for inp, err in failures:
            print(f"  {inp!r}: {err}")
        return 1
    print("SMOKE TEST PASSOU (13/13)")
    return 0

if __name__ == "__main__":
    sys.exit(run())
