#!/usr/bin/env python3
"""
CRM Engine — Pipeline AI
Organiza e automatiza leads, follow-up e conversão.

Fluxo:
  Lead Input
  → Normalize Lead      (lógica)  — limpa e padroniza dados
  → Lead Scoring        (lógica)  — score por palavras-chave + temperatura
  → Save Lead           (local)   — persiste em crm_leads.json
  → Pipeline Assign     (lógica)  — entrada / interessado / qualificado / proposta / fechamento / cliente
  → Followup Sequence   (GPT)     — 3 mensagens de follow-up personalizadas
  → Update Status       (lógica)  — status = em_contato
  → Output              (terminal + Notion + Dashboard)

Regras de conversão:
  quente (≥60) → abordagem direta: oferta + preço + fechamento
  morno  (≥30) → educação: conteúdo + prova + autoridade
  frio   (<30) → aquecimento: insight + dor + curiosidade

Uso:
  python crm_engine.py --json '{"name":"João","source":"instagram","message":"quero saber mais","product":"CFO Digital"}'
  python crm_engine.py --name "João" --source instagram --message "quero saber mais" --product "CFO Digital"
  python crm_engine.py --pipeline              # view kanban do CRM
  python crm_engine.py --update ID --stage qualificado
  python crm_engine.py --update ID --status cliente
  python crm_engine.py                         # modo interativo
"""
import asyncio, json, os, sys, time, glob
from datetime import datetime
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
GPT_MODEL         = os.getenv("GPT_MODEL", "gpt-4o")
OUTPUTS_DIR       = "outputs"
CRM_FILE          = os.path.join(OUTPUTS_DIR, "crm_leads.json")

PIPELINE_STAGES = ["entrada", "interessado", "qualificado", "proposta", "fechamento", "cliente"]

# Palavras-chave e pesos para lead scoring
SCORE_KEYWORDS = {
    "quero":          40,
    "comprar":        40,
    "fechar":         35,
    "quanto custa":   35,
    "preço":          30,
    "valor":          30,
    "como acesso":    25,
    "como funciona":  20,
    "interesse":      20,
    "me interessa":   25,
    "quero mais":     30,
    "saber mais":     20,
    "informação":     15,
    "tem vaga":       30,
    "disponível":     20,
    "quando abre":    25,
}


# ─── API helpers ──────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict | list:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for a, b in [("{", "}"), ("[", "]")]:
            s, e = raw.find(a), raw.rfind(b) + 1
            if s != -1 and e > s:
                try:
                    return json.loads(raw[s:e])
                except Exception:
                    pass
        return {"raw": raw}


async def _gpt(prompt: str) -> tuple[dict, dict]:
    if not OPENAI_API_KEY or "sua-chave" in OPENAI_API_KEY:
        return _fallback_followup_sequence(), {"latency_ms": 0, "cost": 0.0}
    payload = {"model": GPT_MODEL, "input": prompt}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = "\n".join(
        i.get("content", [{}])[0].get("text", "")
        for i in data.get("output", []) if i.get("type") == "message"
    )
    u = data.get("usage", {})
    return _parse_json(raw), {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((u.get("input_tokens", 0) * 2.5e-6) + (u.get("output_tokens", 0) * 10e-6), 6),
    }


async def _claude(prompt: str, max_tokens: int = 1200) -> tuple[dict, dict]:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        return _fallback_followup_sequence(), {"latency_ms": 0, "cost": 0.0}
    payload = {
        "model": CLAUDE_MODEL, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = data.get("content", [{}])[0].get("text", "")
    u = data.get("usage", {})
    return _parse_json(raw), {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((u.get("input_tokens", 0) * 3e-6) + (u.get("output_tokens", 0) * 15e-6), 6),
    }


def _fallback_followup_sequence() -> dict:
    return {
        "followup_sequence": [
            {"dia": 0, "tipo": "resposta_inicial", "mensagem": "Olá! Vi sua mensagem. Posso te contar mais sobre o produto?", "objetivo": "abertura"},
            {"dia": 1, "tipo": "followup",         "mensagem": "Oi! Só passando para ver se ficou alguma dúvida. Estou aqui para ajudar.", "objetivo": "reengajamento"},
            {"dia": 3, "tipo": "reforco",           "mensagem": "Oi novamente! Caso ainda tenha interesse, posso compartilhar mais detalhes.", "objetivo": "reativação"},
        ]
    }


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _p_followup(lead: dict) -> str:
    temp_ctx = {
        "quente": "Lead quente — use abordagem direta: apresente oferta, preço e facilite o fechamento.",
        "morno":  "Lead morno — use educação: envie conteúdo de valor, prova social e demonstre autoridade.",
        "frio":   "Lead frio — use aquecimento: desperte curiosidade com um insight, amplifique a dor, gere interesse.",
    }
    return f"""Crie 3 mensagens de follow-up para esse lead no WhatsApp/Instagram DM.

Produto: {lead.get('product', '')}
Mensagem inicial do lead: "{lead.get('message', '')}"
Temperatura: {lead.get('temperature', 'frio')}
Estágio no pipeline: {lead.get('pipeline_stage', 'entrada')}

Contexto: {temp_ctx.get(lead.get('temperature','frio'), '')}

Sequência:
- Mensagem 1 (dia 0): resposta imediata após o contato
- Mensagem 2 (dia 1): primeiro follow-up
- Mensagem 3 (dia 3): reforço ou última tentativa

Para cada mensagem:
- dia (0, 1 ou 3)
- tipo (resposta_inicial / followup / reforco)
- mensagem (texto pronto para enviar, máximo 3 linhas, tom humano e direto)
- objetivo (abertura / reengajamento / conversão / aquecimento)

Responda APENAS em JSON válido:

{{
  "followup_sequence": [
    {{"dia": 0, "tipo": "resposta_inicial", "mensagem": "", "objetivo": ""}}
  ]
}}"""


# ─── Etapas do pipeline ───────────────────────────────────────────────────────

def _normalize(raw: dict) -> dict:
    """Node 02 — normaliza dados do lead."""
    return {
        **raw,
        "name":       raw.get("name", "Desconhecido").strip().title(),
        "source":     raw.get("source", "direto").strip().lower(),
        "message":    (raw.get("message", "")).strip().lower(),
        "product":    raw.get("product", "").strip(),
        "created_at": raw.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _lead_scoring(lead: dict) -> dict:
    """Node 03 — score por palavras-chave + temperatura."""
    msg   = lead.get("message", "")
    score = sum(pts for kw, pts in SCORE_KEYWORDS.items() if kw in msg)
    score = min(score, 100)

    if score >= 60:
        temperature = "quente"
    elif score >= 30:
        temperature = "morno"
    else:
        temperature = "frio"

    return {**lead, "lead_score": score, "temperature": temperature}


def _pipeline_assign(lead: dict) -> dict:
    """Node 05 — atribui estágio no pipeline."""
    temp = lead.get("temperature", "frio")
    if temp == "quente":
        stage = "qualificado"
    elif temp == "morno":
        stage = "interessado"
    else:
        stage = "entrada"

    return {**lead, "pipeline_stage": stage, "status": "novo"}


# ─── CRM store ────────────────────────────────────────────────────────────────

def _load_crm() -> list:
    if not os.path.exists(CRM_FILE):
        return []
    try:
        with open(CRM_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_crm(leads: list):
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    with open(CRM_FILE, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)


def _next_id(leads: list) -> int:
    return max((l.get("id", 0) for l in leads), default=0) + 1


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def add_lead(raw_input: dict) -> dict:
    print(f"\n  Novo lead: {raw_input.get('name','?')} via {raw_input.get('source','?')}")
    print(f"  Produto: {raw_input.get('product','?')}")
    print("  " + "─" * 56)

    # [1] Normalize
    print("  [1/5] Normalizing lead...")
    lead = _normalize(raw_input)

    # [2] Lead Scoring
    print("  [2/5] Lead Scoring...")
    lead = _lead_scoring(lead)
    TEMP_ICON = {"quente": "🔥", "morno": "🟡", "frio": "❄️"}
    print(f"        ✓ score {lead['lead_score']} → {TEMP_ICON.get(lead['temperature'],'')} {lead['temperature'].upper()}")

    # [3] Save Lead
    print("  [3/5] Saving lead...")
    leads = _load_crm()
    lead["id"]        = _next_id(leads)
    lead["timestamp"] = time.strftime("%Y%m%d_%H%M%S")
    leads.append(lead)
    _save_crm(leads)
    print(f"        ✓ Lead #{lead['id']} salvo (total: {len(leads)})")

    # [4] Pipeline Assign
    print("  [4/5] Pipeline Assign...")
    lead = _pipeline_assign(lead)
    leads[-1] = lead
    _save_crm(leads)
    print(f"        ✓ Estágio: {lead['pipeline_stage'].upper()}")

    # [5] Followup Sequence
    print("  [5/5] Generating Followup Sequence via GPT...")
    if OPENAI_API_KEY and "sua-chave" not in OPENAI_API_KEY:
        seq_raw, meta = await _gpt(_p_followup(lead))
    else:
        seq_raw, meta = await _claude(_p_followup(lead))

    sequence = seq_raw.get("followup_sequence", []) if isinstance(seq_raw, dict) else []
    if not sequence:
        sequence = _fallback_followup_sequence().get("followup_sequence", [])

    lead["followup_sequence"] = sequence
    lead["status"]            = "em_contato"
    leads[-1] = lead
    _save_crm(leads)
    print(f"        ✓ {len(sequence)} mensagens geradas · ${meta.get('cost',0):.4f}")

    result = {
        "lead":     lead,
        "cost":     meta.get("cost", 0),
        "response": {
            "status":         "success",
            "lead_id":        lead["id"],
            "name":           lead["name"],
            "temperature":    lead["temperature"],
            "lead_score":     lead["lead_score"],
            "pipeline_stage": lead["pipeline_stage"],
            "followups":      len(sequence),
        },
    }

    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Update de lead ───────────────────────────────────────────────────────────

def update_lead(lead_id: int, stage: Optional[str] = None, status: Optional[str] = None):
    leads  = _load_crm()
    target = next((l for l in leads if l.get("id") == lead_id), None)
    if not target:
        print(f"  Lead #{lead_id} não encontrado.")
        return

    changed = []
    if stage and stage in PIPELINE_STAGES:
        target["pipeline_stage"] = stage
        changed.append(f"estágio → {stage}")
    if status:
        target["status"] = status
        changed.append(f"status → {status}")

    _save_crm(leads)
    print(f"\n  Lead #{lead_id} ({target.get('name','?')}) atualizado: {', '.join(changed)}")
    _atualizar_dashboard()


# ─── Pipeline view ────────────────────────────────────────────────────────────

def show_pipeline():
    leads = _load_crm()
    if not leads:
        print("  Nenhum lead encontrado.")
        print("  Rode: python crm_engine.py --json '{...}'")
        return

    TEMP_ICON  = {"quente": "🔥", "morno": "🟡", "frio": "❄️"}
    STAGE_ORDER = {s: i for i, s in enumerate(PIPELINE_STAGES)}

    print("\n" + "═" * 72)
    print("  CRM ENGINE — Pipeline de Leads")
    print("═" * 72)

    # Estatísticas
    total   = len(leads)
    quentes = sum(1 for l in leads if l.get("temperature") == "quente")
    clientes = sum(1 for l in leads if l.get("pipeline_stage") == "cliente")
    conv_rate = round(clientes / total * 100, 1) if total > 0 else 0

    print(f"\n  Total: {total}  |  🔥 Quentes: {quentes}  |  ✅ Clientes: {clientes}  |  Conv: {conv_rate}%\n")

    # Agrupa por estágio
    for stage in PIPELINE_STAGES:
        stage_leads = [l for l in leads if l.get("pipeline_stage") == stage]
        if not stage_leads:
            continue
        print(f"  ┌─ {stage.upper()} ({len(stage_leads)}) {'─'*(46-len(stage))}")
        for l in sorted(stage_leads, key=lambda x: -x.get("lead_score", 0)):
            icon = TEMP_ICON.get(l.get("temperature","frio"), "")
            print(f"  │  #{l.get('id','?'):<4} {icon} {l.get('name','?'):<18} "
                  f"[{l.get('source','?'):<12}] "
                  f"score:{l.get('lead_score',0):<4} "
                  f"status:{l.get('status','?')}")
            msg = l.get("message", "")
            if msg:
                print(f"  │       \"{msg[:55]}{'...' if len(msg)>55 else ''}\"")
        print(f"  └{'─'*50}")

    # Sequências pendentes
    pendentes = [l for l in leads if l.get("followup_sequence") and l.get("status") != "cliente"]
    if pendentes:
        print(f"\n  ─── Follow-ups pendentes ({len(pendentes)} leads) ───────────────")
        for l in pendentes[:5]:
            seq = l.get("followup_sequence", [])
            print(f"\n  {TEMP_ICON.get(l.get('temperature',''),'?')} {l.get('name','')} — {l.get('product','')} (#{l.get('id','')})")
            for msg in seq:
                print(f"     Dia {msg.get('dia',0)} [{msg.get('tipo','')}]: {msg.get('mensagem','')[:65]}")

    print()


# ─── Persistência ─────────────────────────────────────────────────────────────

async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa
        l    = result["lead"]
        body = (
            f"Lead #{l.get('id','')} — {l.get('name','')} via {l.get('source','')}\n"
            f"Produto: {l.get('product','')}\n"
            f"Score: {l.get('lead_score',0)} ({l.get('temperature','')})\n"
            f"Pipeline: {l.get('pipeline_stage','')}\n"
            f"Mensagem: {l.get('message','')}\n\n"
            f"Follow-up:\n" +
            "\n".join(
                f"  Dia {m.get('dia',0)}: {m.get('mensagem','')}"
                for m in l.get("followup_sequence", [])
            )
        )
        await salvar_tarefa(
            f"CRM: {l.get('name','')} → {l.get('temperature','').upper()} · {l.get('pipeline_stage','')}",
            "crm_engine",
            body,
        )
    except Exception:
        pass


def _atualizar_dashboard():
    import subprocess, sys as _sys
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_dashboard.py")
    if not os.path.exists(script):
        return
    try:
        subprocess.run([_sys.executable, script], check=True, capture_output=True)
        dashboard = os.path.join(os.path.dirname(script), "dashboard.html")
        subprocess.Popen(["open", dashboard])
        print("  Dashboard atualizado.")
    except Exception as e:
        print(f"  Dashboard: {e}")


# ─── Display terminal ─────────────────────────────────────────────────────────

def _imprimir(result: dict):
    l   = result["lead"]
    seq = l.get("followup_sequence", [])

    TEMP_LABEL = {
        "quente": "🔥 QUENTE — abordagem direta: oferta + preço + fechamento",
        "morno":  "🟡 MORNO  — educação: conteúdo + prova + autoridade",
        "frio":   "❄️  FRIO   — aquecimento: insight + dor + curiosidade",
    }

    print("\n" + "═" * 62)
    print(f"  CRM ENGINE — Lead #{l.get('id','')} · {l.get('name','')}")
    print("═" * 62)

    print(f"\n  Fonte        : {l.get('source','')}")
    print(f"  Produto      : {l.get('product','')}")
    print(f"  Mensagem     : \"{l.get('message','')[:70]}\"")
    print(f"\n  Score        : {l.get('lead_score',0)}/100")
    print(f"  Temperatura  : {TEMP_LABEL.get(l.get('temperature','frio'), l.get('temperature',''))}")
    print(f"  Estágio      : {l.get('pipeline_stage','').upper()}")
    print(f"  Status       : {l.get('status','')}")

    if seq:
        print(f"\n  ─── Follow-up Sequence ({len(seq)} mensagens) ─────────────────")
        for msg in seq:
            print(f"\n  [Dia {msg.get('dia',0)} · {msg.get('tipo','')}]  → {msg.get('objetivo','')}")
            lines = msg.get("mensagem","")
            for line in lines.split("\n"):
                print(f"  {line}")

    print(f"\n  Custo        : ~${result.get('cost',0):.4f}")
    print("═" * 62 + "\n")

    print("  Response (Node 08):")
    print(json.dumps(result["response"], ensure_ascii=False, indent=2))
    print()


# ─── Modo interativo ──────────────────────────────────────────────────────────

def _interactive_input() -> dict:
    print("\n  ─── CRM Engine — Novo Lead ──────────────────────────────")
    name    = input("  Nome             : ").strip()
    source  = input("  Fonte (instagram): ").strip() or "instagram"
    message = input("  Mensagem do lead : ").strip()
    product = input("  Produto          : ").strip()
    return {"name": name, "source": source, "message": message, "product": product}


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]

    # --pipeline: view kanban
    if "--pipeline" in args:
        show_pipeline()
        return

    # --update ID --stage X --status Y
    if "--update" in args:
        idx      = args.index("--update")
        lead_id  = int(args[idx + 1]) if idx + 1 < len(args) else None
        stage    = None
        status   = None
        if "--stage" in args:
            i = args.index("--stage")
            stage = args[i + 1] if i + 1 < len(args) else None
        if "--status" in args:
            i = args.index("--status")
            status = args[i + 1] if i + 1 < len(args) else None
        if lead_id:
            update_lead(lead_id, stage, status)
        return

    raw_input: Optional[dict] = None

    # --json
    if "--json" in args:
        idx       = args.index("--json")
        raw_input = json.loads(args[idx + 1])

    # --name --source --message --product
    elif "--name" in args:
        def _arg(flag: str, default=""):
            if flag in args:
                i = args.index(flag)
                return args[i + 1] if i + 1 < len(args) else default
            return default

        raw_input = {
            "name":    _arg("--name"),
            "source":  _arg("--source", "instagram"),
            "message": _arg("--message"),
            "product": _arg("--product"),
        }

    else:
        raw_input = _interactive_input()

    if not raw_input or not raw_input.get("name"):
        print("  name obrigatório.")
        return

    await add_lead(raw_input)


if __name__ == "__main__":
    asyncio.run(main())
