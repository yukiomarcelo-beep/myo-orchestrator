"""Smoke test RuntimeGuard (LESSON-003). 12 casos."""

import json
import sys
import tempfile
from pathlib import Path


def run():
    root = Path(__file__).parent.parent
    sys.path.insert(0, str(root))
    from policies.runtime_guard import GuardDecision, RuntimeGuard, build_hook_response

    failures = []

    # Policy de teste escrita em arquivo temporario (nao depende do config real)
    tmp_policy = Path(tempfile.mkdtemp(prefix="guard_")) / "context_policy.json"
    policy_data = {
        "idea": {"api_cost_strict": False},
        "research": {"api_cost_strict": False},
        "mvp": {"api_cost_strict": False},
        "launch_ready": {"api_cost_strict": True},
        "scaling": {"api_cost_strict": True},
    }
    tmp_policy.write_text(json.dumps(policy_data), encoding="utf-8")

    # ========== 1. Hard block em todos contextos ==========
    try:
        for ctx in ["idea", "research", "mvp", "launch_ready", "scaling"]:
            guard = RuntimeGuard(execution_context=ctx, policy_file=tmp_policy)
            d = guard.evaluate_tool_use("Bash", {"command": "rm -rf /"})
            assert not d.allowed, f"{ctx}: rm -rf / deveria ser bloqueado"
            assert d.rule == "hard_block"
        print("  OK   hard_block em todos 5 contextos")
    except Exception as e:
        failures.append(("hard_block", repr(e)))

    # ========== 2. Fork bomb bloqueado ==========
    try:
        g = RuntimeGuard(execution_context="idea", policy_file=tmp_policy)
        d = g.evaluate_tool_use("Bash", {"command": ":(){ :|:& };:"})
        assert not d.allowed and d.rule == "hard_block"
        print("  OK   fork bomb bloqueado")
    except Exception as e:
        failures.append(("fork_bomb", repr(e)))

    # ========== 3. dd if= bloqueado ==========
    try:
        g = RuntimeGuard(execution_context="idea", policy_file=tmp_policy)
        d = g.evaluate_tool_use("Bash", {"command": "dd if=/dev/zero of=/dev/sda"})
        assert not d.allowed and d.rule == "hard_block"
        print("  OK   dd if= bloqueado")
    except Exception as e:
        failures.append(("dd_if", repr(e)))

    # ========== 4. Write em /etc bloqueado em todos contextos ==========
    try:
        for ctx in ["idea", "research", "mvp", "launch_ready", "scaling"]:
            g = RuntimeGuard(execution_context=ctx, policy_file=tmp_policy)
            d = g.evaluate_tool_use("Write", {"file_path": "/etc/passwd", "content": "x"})
            assert not d.allowed and d.rule == "system_path", f"{ctx}: /etc/passwd"
        print("  OK   Write /etc bloqueado em todos contextos")
    except Exception as e:
        failures.append(("sys_etc", repr(e)))

    # ========== 5. Write em /usr/local bloqueado ==========
    try:
        g = RuntimeGuard(execution_context="mvp", policy_file=tmp_policy)
        d = g.evaluate_tool_use("Edit", {"file_path": "/usr/local/bin/script"})
        assert not d.allowed and d.rule == "system_path"
        print("  OK   Edit /usr bloqueado")
    except Exception as e:
        failures.append(("sys_usr", repr(e)))

    # ========== 6. rm -rf <path> bloqueado em scaling ==========
    try:
        g = RuntimeGuard(execution_context="scaling", policy_file=tmp_policy)
        d = g.evaluate_tool_use("Bash", {"command": "rm -rf /tmp/testdir"})
        assert not d.allowed, "scaling deveria bloquear rm -rf com path"
        assert d.rule == "contextual_destructive"
        print("  OK   rm -rf /tmp/testdir bloqueado em scaling")
    except Exception as e:
        failures.append(("rmrf_scaling", repr(e)))

    # ========== 7. rm -rf <path> bloqueado em launch_ready ==========
    try:
        g = RuntimeGuard(execution_context="launch_ready", policy_file=tmp_policy)
        d = g.evaluate_tool_use("Bash", {"command": "rm -rf build/"})
        assert not d.allowed
        print("  OK   rm -rf build/ bloqueado em launch_ready")
    except Exception as e:
        failures.append(("rmrf_launch", repr(e)))

    # ========== 8. rm -rf <path> permitido em idea (warn) ==========
    try:
        g = RuntimeGuard(execution_context="idea", policy_file=tmp_policy)
        d = g.evaluate_tool_use("Bash", {"command": "rm -rf build/"})
        assert d.allowed, "idea deveria permitir rm -rf com warn"
        assert d.severity == "warn"
        print("  OK   rm -rf /build/ permitido em idea com warn")
    except Exception as e:
        failures.append(("rmrf_idea", repr(e)))

    # ========== 9. curl sem auth bloqueado em launch_ready (api_cost_strict) ==========
    try:
        g = RuntimeGuard(execution_context="launch_ready", policy_file=tmp_policy)
        d = g.evaluate_tool_use("Bash", {"command": "curl https://api.openai.com/v1/models"})
        assert not d.allowed, "launch_ready: curl sem auth deveria bloquear"
        assert d.rule == "contextual_api_strict"
        print("  OK   curl sem auth bloqueado em launch_ready (api_strict)")
    except Exception as e:
        failures.append(("curl_strict", repr(e)))

    # ========== 10. curl COM auth permitido em launch_ready ==========
    try:
        g = RuntimeGuard(execution_context="launch_ready", policy_file=tmp_policy)
        d = g.evaluate_tool_use(
            "Bash",
            {"command": 'curl -H "Authorization: Bearer X" https://api.openai.com/v1/models'},
        )
        assert d.allowed, "curl com Authorization deveria passar"
        print("  OK   curl com auth permitido em launch_ready")
    except Exception as e:
        failures.append(("curl_auth_ok", repr(e)))

    # ========== 11. Contexto invalido -> ValueError ==========
    try:
        try:
            RuntimeGuard(execution_context="production", policy_file=tmp_policy)
            failures.append(("invalid_ctx", "nao levantou ValueError"))
        except ValueError:
            print("  OK   contexto invalido rejeitado com ValueError")
    except Exception as e:
        failures.append(("invalid_ctx_exc", repr(e)))

    # ========== 12. Tool safe (Read) sempre allow ==========
    try:
        for ctx in ["idea", "research", "mvp", "launch_ready", "scaling"]:
            g = RuntimeGuard(execution_context=ctx, policy_file=tmp_policy)
            d = g.evaluate_tool_use("Read", {"file_path": "/home/user/x.py"})
            assert d.allowed, f"{ctx}: Read deveria passar"
            assert d.rule == "default_allow"
        # build_hook_response({}): allowed -> {}
        resp_allow = build_hook_response(GuardDecision(allowed=True))
        assert resp_allow == {}
        resp_deny = build_hook_response(GuardDecision(allowed=False, reason="x"))
        assert "hookSpecificOutput" in resp_deny
        assert resp_deny["hookSpecificOutput"]["permissionDecision"] == "deny"
        print("  OK   Read passa em todos contextos + build_hook_response ok")
    except Exception as e:
        failures.append(("read_allow", repr(e)))

    # Cleanup
    import shutil

    shutil.rmtree(tmp_policy.parent, ignore_errors=True)

    print("\n" + "=" * 60)
    if failures:
        print(f"SMOKE TEST FALHOU: {len(failures)}")
        for name, err in failures:
            print(f"  [{name}] {err}")
        return 1
    print("SMOKE TEST PASSOU (12/12)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
