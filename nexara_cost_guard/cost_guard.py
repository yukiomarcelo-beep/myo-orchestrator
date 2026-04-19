import asyncio
import fcntl
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import anthropic
except ImportError:
    print("Instale: pip install anthropic")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CONFIG_PATH = Path(__file__).parent / "cost_guard_config.json"
LOG_PATH = Path(__file__).parent / "logs" / "execucoes.jsonl"
LOG_PATH.parent.mkdir(exist_ok=True)

PRECOS_MODELO = {
    "claude-opus-4-6":    {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":  {"input":  3.00, "output": 15.00},
    "claude-sonnet-4-5":  {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5":   {"input":  0.80, "output":  4.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
}

REGRAS_MODELO = {
    "validacao":            "claude-haiku-4-5",
    "formatacao":           "claude-haiku-4-5",
    "estruturacao":         "claude-haiku-4-5",
    "traducao":             "claude-haiku-4-5",
    "resumo_simples":       "claude-haiku-4-5",
    "classificacao":        "claude-haiku-4-5",
    "extracao_dados":       "claude-haiku-4-5",
    "pesquisa":             "claude-sonnet-4-6",
    "analise":              "claude-sonnet-4-6",
    "redacao":              "claude-sonnet-4-6",
    "consolidacao":         "claude-sonnet-4-6",
    "raciocinio":           "claude-sonnet-4-6",
    "raciocinio_juridico":  "claude-sonnet-4-6",
    "pesquisa_juridica":    "claude-sonnet-4-6",
    "codigo":               "claude-sonnet-4-6",
    "agente":               "claude-sonnet-4-6",
    "raciocinio_critico":   "claude-opus-4-6",
    "analise_juridica":     "claude-opus-4-6",
    "estrategia":           "claude-opus-4-6",
    "revisao_final":        "claude-opus-4-6",
}

PROJETOS_VALIDOS = {
    "pesquisador_juridico", "bellaflow", "luxai", "signal",
    "whatsapp_central", "nexara_consultoria", "oquefazersp",
    "interno", "outro",
}

USD_BRL = 5.70


def carregar_config() -> dict:
    defaults = {
        "versao": "1.0",
        "precos_atualizados_em": "2026-04-10",
        "usd_brl": USD_BRL,
        "alerta_anomalia_fator": 2.0,
        "alerta_execucao_brl": 5.00,
        "projetos": {
            p: {"budget_diario_brl": 50.0, "budget_mensal_brl": 500.0}
            for p in PROJETOS_VALIDOS
        },
    }
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(defaults, indent=2, ensure_ascii=False))
        return defaults
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        dt = datetime.strptime(cfg.get("precos_atualizados_em", "2000-01-01"), "%Y-%m-%d")
        if (datetime.now() - dt).days > 30:
            print(f"⚠  [CostGuard] Preços com {(datetime.now()-dt).days} dias. Verifique anthropic.com/pricing")
        return cfg
    except Exception:
        return defaults


CONFIG = carregar_config()


def _log_escrever(registro: dict) -> None:
    linha = json.dumps(registro, ensure_ascii=False) + "\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(linha)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _log_ler(dias: int = 30) -> list:
    if not LOG_PATH.exists():
        return []
    cutoff = datetime.now() - timedelta(days=dias)
    registros = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
              for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    r = json.loads(linha)
                    dt = datetime.fromisoformat(r.get("timestamp", "2000-01-01"))
                    if dt >= cutoff:
                        registros.append(r)
                except Exception:
                        continue
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass
    return registros


def calcular_custo_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    model_base = model
    for key in PRECOS_MODELO:
        if model.startswith(key) or key.startswith(model):
            model_base = key
            break
    preco = PRECOS_MODELO.get(model_base, {"input": 3.00, "output": 15.00})
    return round((input_tokens / 1_000_000 * preco["input"]) +
                 (output_tokens / 1_000_000 * preco["output"]), 6)


def custo_brl(usd: float) -> float:
    return round(usd * CONFIG.get("usd_brl", USD_BRL), 4)


def recomendar_modelo(tarefa: str, modelo_solicitado: str):
    recomendado = REGRAS_MODELO.get(tarefa.lower())
    if not recomendado:
        return modelo_solicitado, None
    hierarquia = ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"]
    def nivel(m):
        for i, h in enumerate(hierarquia):
            if h in m or m in h:
                return i
        return 1
    nv_sol = nivel(modelo_solicitado)
    nv_rec = nivel(recomendado)
    if nv_sol != nv_rec:
        if nv_sol > nv_rec:
            economia = round((1 - PRECOS_MODELO.get(recomendado, {}).get("output", 15) /
                              max(PRECOS_MODELO.get(modelo_solicitado, {}).get("output", 15), 1)) * 100)
            aviso = f"Para '{tarefa}', {recomendado} é suficiente (~{economia}% mais barato)"
        else:
            aviso = f"Para '{tarefa}', recomenda-se {recomendado} (mais adequado)"
        return recomendado, aviso
    return modelo_solicitado, None


def verificar_anomalia(projeto: str, custo_brl_atual: float):
    registros = _log_ler(dias=30)
    historico = [r["custo_brl"] for r in registros
                 if r.get("projeto") == projeto and r.get("custo_brl", 0) > 0 and not r.get("tipo")]
    if len(historico) < 5:
        return None
    media = sum(historico) / len(historico)
    fator = CONFIG.get("alerta_anomalia_fator", 2.0)
    limite = CONFIG.get("alerta_execucao_brl", 5.0)
    if custo_brl_atual > media * fator:
        return f"Anomalia em '{projeto}': R$ {custo_brl_atual:.4f} vs média R$ {media:.4f} ({custo_brl_atual/media:.1f}x)"
    if custo_brl_atual > limite:
        return f"Execução cara em '{projeto}': R$ {custo_brl_atual:.4f} (limite: R$ {limite:.2f})"
    return None


def verificar_budget_diario(projeto: str):
    hoje = datetime.now().date().isoformat()
    registros = _log_ler(dias=1)
    gasto = sum(r.get("custo_brl", 0) for r in registros
                if r.get("projeto") == projeto and
                r.get("timestamp", "")[:10] == hoje and not r.get("tipo"))
    cfg_p = CONFIG.get("projetos", {}).get(projeto, {})
    budget = cfg_p.get("budget_diario_brl", 50.0)
    if gasto >= budget:
        return f"Budget diário de '{projeto}' esgotado: R$ {gasto:.2f} / R$ {budget:.2f}"
    if gasto >= budget * 0.8:
        return f"Alerta: '{projeto}' em {gasto/budget*100:.0f}% do budget diário"
    return None


class CostGuard:
    def __init__(self):
        self.client = None

    def _get_client(self):
        if self.client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY não configurada")
            self.client = anthropic.Anthropic(api_key=api_key)
        return self.client

    def run(self, projeto="outro", tarefa="agente", model="claude-sonnet-4-6",
            messages=None, max_tokens=2048, system=None,
            valor_contexto="interno", forcar_modelo=False, **kwargs):
        if projeto not in PROJETOS_VALIDOS:
            projeto = "outro"
        alerta_budget = verificar_budget_diario(projeto)
        if alerta_budget and "esgotado" in alerta_budget:
            raise RuntimeError(f"[CostGuard] {alerta_budget}")
        elif alerta_budget:
            print(f"⚠  [CostGuard] {alerta_budget}")
        modelo_final = model
        if not forcar_modelo:
            modelo_rec, aviso = recomendar_modelo(tarefa, model)
            if aviso:
                print(f"💡 [CostGuard] {aviso}")
            modelo_final = modelo_rec
        call_kwargs = {"model": modelo_final, "max_tokens": max_tokens,
                       "messages": messages or [], **kwargs}
        if system:
            call_kwargs["system"] = system
        inicio = time.time()
        client = self._get_client()
        resposta = client.messages.create(**call_kwargs)
        duracao_ms = round((time.time() - inicio) * 1000)
        import threading
        threading.Thread(
            target=self._registrar,
            kwargs=dict(projeto=projeto, tarefa=tarefa, model=modelo_final,
                        model_solicitado=model, resposta=resposta,
                        duracao_ms=duracao_ms, valor_contexto=valor_contexto),
            daemon=True
        ).start()
        return resposta

    def _registrar(self, projeto, tarefa, model, model_solicitado,
                   resposta, duracao_ms, valor_contexto):
        try:
            inp = resposta.usage.input_tokens
            out = resposta.usage.output_tokens
            custo_usd = calcular_custo_usd(model, inp, out)
            custo_brl_val = custo_brl(custo_usd)
            registro = {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat(),
                "projeto": projeto, "tarefa": tarefa,
                "model": model, "model_solicitado": model_solicitado,
                "model_trocado": model != model_solicitado,
                "input_tokens": inp, "output_tokens": out,
                "total_tokens": inp + out,
                "custo_usd": custo_usd, "custo_brl": custo_brl_val,
                "duracao_ms": duracao_ms, "valor_contexto": valor_contexto,
                "stop_reason": resposta.stop_reason,
            }
            _log_escrever(registro)
            alerta = verificar_anomalia(projeto, custo_brl_val)
            if alerta:
                print(f"\n🚨 [CostGuard] {alerta}")
                _log_escrever({"tipo": "alerta", "timestamp": datetime.now().isoformat(),
                               "projeto": projeto, "mensagem": alerta, "execucao_id": registro["id"]})
        except Exception as e:
            try:
                _log_escrever({"tipo": "erro_registro", "timestamp": datetime.now().isoformat(),
                               "erro": str(e), "projeto": projeto})
            except Exception:
                pass


guard = CostGuard()


def cmd_status():
    registros = _log_ler(dias=1)
    hoje = datetime.now().date().isoformat()
    registros_hoje = [r for r in registros
                      if r.get("timestamp", "")[:10] == hoje and not r.get("tipo")]
    print(f"\n{'━'*52}")
    print(f"  NEXARA Cost Guard — {datetime.now().strftime('%d/%m %H:%M')}")
    print(f"{'━'*52}")
    if not registros_hoje:
        print("  Nenhuma execução hoje.\n")
        return
    projetos = {}
    for r in registros_hoje:
        p = r.get("projeto", "outro")
        if p not in projetos:
            projetos[p] = {"custo_brl": 0, "execucoes": 0, "tokens": 0, "trocas": 0}
        projetos[p]["custo_brl"] += r.get("custo_brl", 0)
        projetos[p]["execucoes"] += 1
        projetos[p]["tokens"] += r.get("total_tokens", 0)
        if r.get("model_trocado"):
            projetos[p]["trocas"] += 1
    registros_30d = _log_ler(dias=30)
    medias = {}
    for p in projetos:
        dias_d = {}
        for r in registros_30d:
            if r.get("projeto") == p and not r.get("tipo"):
                dia = r.get("timestamp", "")[:10]
                dias_d[dia] = dias_d.get(dia, 0) + r.get("custo_brl", 0)
        if dias_d:
            medias[p] = sum(dias_d.values()) / len(dias_d)
    total = 0
    for p, d in sorted(projetos.items(), key=lambda x: x[1]["custo_brl"], reverse=True):
        media = medias.get(p, 0)
        comp = f"({'+' if d['custo_brl']>=media else ''}{((d['custo_brl']-media)/media*100) if media else 0:.0f}% vs média)" if media else "(sem histórico)"
        cfg_p = CONFIG.get("projetos", {}).get(p, {})
        budget = cfg_p.get("budget_diario_brl", 50.0)
        flag = " 🚨 BUDGET ESGOTADO" if d["custo_brl"] >= budget else (" ⚠  80% do budget" if d["custo_brl"] >= budget * 0.8 else "")
        print(f"\n  {p}")
        print(f"    R$ {d['custo_brl']:.4f}  {comp}{flag}")
        print(f"    {d['execucoes']} execuções · {d['tokens']:,} tokens" +
              (f" · {d['trocas']} trocas (economia)" if d["trocas"] else ""))
        total += d["custo_brl"]
    print(f"\n  {'─'*46}")
    print(f"  Total hoje: R$ {total:.4f}")
    print(f"{'━'*52}\n")


def cmd_report(dias=7):
    registros = _log_ler(dias=dias)
    hoje = datetime.now().date().isoformat()
    ontem = (datetime.now() - timedelta(days=1)).date().isoformat()
    def soma(dia):
        return sum(r.get("custo_brl", 0) for r in registros
                   if r.get("timestamp", "")[:10] == dia and not r.get("tipo"))
    c_hoje = soma(hoje)
    c_ontem = soma(ontem)
    c_7d = sum(r.get("custo_brl", 0) for r in registros if not r.get("tipo"))
    por_projeto = {}
    por_modelo = {}
    trocas = 0
    for r in registros:
        if r.get("tipo"):
            continue
        p = r.get("projeto", "outro")
        por_projeto[p] = por_projeto.get(p, 0) + r.get("custo_brl", 0)
        m = r.get("model", "?").replace("claude-", "")
        por_modelo[m] = por_modelo.get(m, 0) + 1
        if r.get("model_trocado"):
            trocas += 1
    var = f" ({'↑' if c_hoje > c_ontem else '↓'}{abs((c_hoje-c_ontem)/c_ontem*100):.0f}% vs ontem)" if c_ontem else ""
    linhas = [
        "━━ COST GUARD — CONSUMO DE TOKENS ━━",
        f"Hoje: R$ {c_hoje:.4f}{var}",
        f"Ontem: R$ {c_ontem:.4f}",
        f"7 dias: R$ {c_7d:.4f}",
        "", "Por projeto (7d):",
    ]
    for p, c in sorted(por_projeto.items(), key=lambda x: x[1], reverse=True):
        linhas.append(f"  {p}: R$ {c:.4f} ({c/c_7d*100 if c_7d else 0:.0f}%)")
    linhas += ["", "Por modelo (7d):"]
    for m, n in sorted(por_modelo.items(), key=lambda x: x[1], reverse=True):
        linhas.append(f"  {m}: {n}x")
    if trocas:
        linhas.append(f"\n✓ {trocas} trocas de modelo pelo advisor")
    alertas = [r for r in registros if r.get("tipo") == "alerta"][-3:]
    if alertas:
        linhas.append(f"\n⚠ {len(alertas)} alertas recentes:")
        for a in alertas:
            linhas.append(f"  {a.get('timestamp','')[:16]} — {a.get('mensagem','')[:60]}")
    relatorio = "\n".join(linhas)
    print(relatorio)
    return relatorio


def cmd_audit():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY não configurada")
        return
    print("\n  Verificando usage na Anthropic API...")
    try:
        import urllib.request
        hoje = datetime.now().date().isoformat()
        req = urllib.request.Request(
            f"https://api.anthropic.com/v1/usage?date={hoje}",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        c_anthropic = data.get("total_cost_usd", 0) * USD_BRL
        c_local = sum(r.get("custo_brl", 0) for r in _log_ler(dias=1)
                      if r.get("timestamp", "")[:10] == hoje and not r.get("tipo"))
        diff = c_anthropic - c_local
        print(f"\n  Auditoria {hoje}")
        print(f"  Anthropic: R$ {c_anthropic:.4f}")
        print(f"  Local:     R$ {c_local:.4f}")
        print(f"  Diferença: R$ {diff:.4f}")
        if diff > 0.10:
            print(f"\n  ⚠  R$ {diff:.4f} em chamadas não rastreadas.")
            print(f"  Verifique se todos os projetos usam guard.run()\n")
        else:
            print(f"\n  ✓ Cobertura completa\n")
    except Exception as e:
        print(f"  ⚠  Não foi possível buscar da Anthropic: {e}")
        print(f"  Verifique: console.anthropic.com/settings/usage\n")


def cmd_config():
    print(f"\n  Config: {CONFIG_PATH}")
    print(f"  Log:    {LOG_PATH}")
    print(f"  Preços atualizados em: {CONFIG.get('precos_atualizados_em')}")
    print(f"  USD/BRL: {CONFIG.get('usd_brl', USD_BRL)}")
    print(f"\n  Advisor — modelo por tarefa:")
    for t, m in REGRAS_MODELO.items():
        print(f"    {t:<25} → {m.replace('claude-','')}")
    print(f"\n  Budgets diários:")
    for p, c in CONFIG.get("projetos", {}).items():
        print(f"    {p:<25} R$ {c.get('budget_diario_brl',0):.2f}/dia")
    print()


if __name__ == "__main__":
    cmds = {"status": cmd_status, "report": lambda: cmd_report(7),
            "audit": cmd_audit, "config": cmd_config}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("\nNexara Cost Guard v1.0\n\nUso:\n"
              "  python cost_guard.py status\n"
              "  python cost_guard.py report\n"
              "  python cost_guard.py audit\n"
              "  python cost_guard.py config\n")
    else:
        cmds[sys.argv[1]]()
