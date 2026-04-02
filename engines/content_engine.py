#!/usr/bin/env python3
"""
Content Engine — Pipeline AI
Transforma o blueprint do Product Engine em conteúdo pronto para publicar.

Fluxo:
  Product Blueprint
  → Angle Generator   (Claude)  — 10 ângulos de conteúdo
  → Hook Generator    (GPT)     — 20 ganchos virais
  → Content Ideas     (GPT)     — 10 ideias estruturadas
  → Short Posts       (GPT)     — 5 posts prontos
  → Reels Scripts     (Claude)  — 5 roteiros base
  → Script Variations (GPT)     — versões agressivas + elegantes
  → Save + Notion + Dashboard

Uso:
  python content_engine.py                       # pega melhor blueprint automaticamente
  python content_engine.py --title "CFO Digital"
  python content_engine.py --json '{...}'
"""
import asyncio, json, os, sys, time, glob
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
GPT_MODEL         = os.getenv("GPT_MODEL", "gpt-4o")
OUTPUTS_DIR       = "outputs"


# ─── API helpers ──────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict | list:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # tenta extrair objeto
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s != -1 and e > s:
            try: return json.loads(raw[s:e])
            except: pass
        # tenta extrair lista
        s, e = raw.find("["), raw.rfind("]") + 1
        if s != -1 and e > s:
            try: return json.loads(raw[s:e])
            except: pass
        return {"raw": raw}


async def _claude(prompt: str, max_tokens: int = 2000) -> tuple[dict | list, dict]:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não configurada")
    payload = {"model": CLAUDE_MODEL, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = data.get("content", [{}])[0].get("text", "")
    usage = data.get("usage", {})
    meta = {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((usage.get("input_tokens", 0) * 3e-6) +
                      (usage.get("output_tokens", 0) * 15e-6), 6),
    }
    return _parse_json(raw), meta


async def _gpt(prompt: str) -> tuple[dict | list, dict]:
    if not OPENAI_API_KEY or "sua-chave" in OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY não configurada")
    payload = {"model": GPT_MODEL, "input": prompt}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    items = data.get("output", [])
    raw = "\n".join(i.get("content", [{}])[0].get("text", "")
                    for i in items if i.get("type") == "message")
    usage = data.get("usage", {})
    meta = {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((usage.get("input_tokens", 0) * 2.5e-6) +
                      (usage.get("output_tokens", 0) * 10e-6), 6),
    }
    return _parse_json(raw), meta


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _p_angles(bp: dict) -> str:
    s = bp.get("product_strategy", {})
    o = bp.get("offer_design", {})
    return f"""Você é um estrategista de conteúdo especialista em marketing digital.

Produto: {bp['idea_title']}
Público: {bp['target_audience']}
Transformação prometida: {s.get('transformation', '')}
Mecanismo único: {s.get('unique_mechanism', '')}
Promessa da oferta: {o.get('main_promise', '')}

Crie 10 ângulos de conteúdo, um de cada tipo:
- dor: explora a dor real que o público sente
- erro_comum: erro que o público comete sem perceber
- mito: crença errada que precisa ser quebrada
- insight: verdade contraintuitiva do mercado
- comparacao: antes vs depois, com vs sem o produto
- choque_de_realidade: número, dado ou fato impactante
- oportunidade: o que o público está perdendo agora
- bastidores: como o produto/processo funciona por dentro
- historia: narrativa de transformação real ou hipotética
- autoridade: demonstração de conhecimento profundo

Para cada ângulo:
- tipo (um dos 10 acima)
- titulo (headline do conteúdo, até 12 palavras)
- premissa (a ideia central em 1 frase)
- gancho_sugerido (primeira linha do post/vídeo)

Responda APENAS em JSON válido:

{{
  "angles": [
    {{"tipo": "", "titulo": "", "premissa": "", "gancho_sugerido": ""}}
  ]
}}"""


def _p_hooks(bp: dict, angles: list) -> str:
    titles = [a.get("titulo", "") for a in angles[:10]]
    return f"""Crie 20 ganchos virais para o produto "{bp['idea_title']}" voltado para {bp['target_audience']}.

Ângulos disponíveis:
{json.dumps(titles, ensure_ascii=False)}

Regras:
- Cada gancho deve ter no máximo 15 palavras
- Use linguagem direta, coloquial e impactante
- Varie os formatos: pergunta, afirmação chocante, dado, provocação, história em 1 linha
- Foco total no público: donos de negócio que querem resultado

Responda APENAS em JSON válido:

{{
  "hooks": ["", "", ""]
}}"""


def _p_content_ideas(bp: dict, angles: list, hooks: list) -> str:
    return f"""Crie 10 ideias de conteúdo completas para "{bp['idea_title']}".

Ângulos:
{json.dumps([a.get('titulo','') for a in angles[:10]], ensure_ascii=False)}

Melhores ganchos:
{json.dumps(hooks[:10], ensure_ascii=False)}

Para cada ideia:
- tema (assunto central)
- objetivo (engajamento / autoridade / conversão / educação)
- formato (carrossel / vídeo curto / post texto / stories / thread)
- gancho (primeira linha)
- estrutura (3-4 pontos do desenvolvimento)
- cta (chamada para ação final)

Responda APENAS em JSON válido:

{{
  "content_ideas": [
    {{
      "tema": "",
      "objetivo": "",
      "formato": "",
      "gancho": "",
      "estrutura": [],
      "cta": ""
    }}
  ]
}}"""


def _p_short_posts(bp: dict, ideas: list) -> str:
    top_ideas = json.dumps(ideas[:5], ensure_ascii=False)
    return f"""Escreva 5 posts completos para Instagram/LinkedIn sobre "{bp['idea_title']}".

Baseie em:
{top_ideas}

Cada post deve ter:
- gancho (1 linha impactante para parar o scroll)
- desenvolvimento (3-5 parágrafos curtos, diretos)
- cta (chamada clara para ação)
- hashtags (5 relevantes)

Regras de escrita:
- Parágrafos de 1-2 linhas
- Linguagem direta, sem jargão
- Tom próximo, como se falasse com um amigo do mercado
- Começar com fato, pergunta ou afirmação polêmica

Responda APENAS em JSON válido:

{{
  "posts": [
    {{
      "gancho": "",
      "desenvolvimento": "",
      "cta": "",
      "hashtags": []
    }}
  ]
}}"""


def _p_scripts_base(bp: dict, angles: list) -> str:
    top = [a.get("gancho_sugerido", "") for a in angles[:5]]
    return f"""Crie 5 roteiros de vídeo curto (Reels/TikTok, até 30 segundos) para "{bp['idea_title']}".

Público: {bp['target_audience']}
Ganchos base: {json.dumps(top, ensure_ascii=False)}

Cada roteiro deve ter:
- gancho (primeiros 3 segundos — o que faz parar de scrollar)
- desenvolvimento (o corpo do vídeo — máximo 20 segundos)
- cta (últimos 5 segundos — ação clara)
- duracao_estimada (ex: "25s")
- tom (educativo / provocador / inspiracional / direto)

Responda APENAS em JSON válido:

{{
  "scripts": [
    {{
      "gancho": "",
      "desenvolvimento": "",
      "cta": "",
      "duracao_estimada": "",
      "tom": ""
    }}
  ]
}}"""


def _p_script_variations(scripts: list) -> str:
    return f"""Com base nesses roteiros de vídeo:

{json.dumps(scripts, ensure_ascii=False, indent=2)}

Crie para cada roteiro:
- versao_agressiva: mais direta, provocadora, urgente
- versao_elegante: mais sofisticada, aspiracional, premium

Mantenha a mesma estrutura (gancho + desenvolvimento + cta).

Responda APENAS em JSON válido:

{{
  "variations": [
    {{
      "original_gancho": "",
      "versao_agressiva": {{"gancho": "", "desenvolvimento": "", "cta": ""}},
      "versao_elegante":  {{"gancho": "", "desenvolvimento": "", "cta": ""}}
    }}
  ]
}}"""


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def build_content(bp: dict) -> dict:
    title = bp.get("idea_title", "")
    print(f"\n  Gerando conteúdo: {title[:60]}")
    print("  " + "─" * 56)

    total_cost = 0.0

    # [1] Angle Generator — Claude
    print("  [1/6] Angle Generator via Claude...")
    angles_raw, m1 = await _claude(_p_angles(bp))
    angles = angles_raw.get("angles", []) if isinstance(angles_raw, dict) else []
    total_cost += m1["cost"]
    print(f"        ✓ {len(angles)} ângulos · {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # [2] Hook Generator — GPT
    print("  [2/6] Hook Generator via GPT...")
    hooks_raw, m2 = await _gpt(_p_hooks(bp, angles))
    hooks = hooks_raw.get("hooks", []) if isinstance(hooks_raw, dict) else []
    total_cost += m2["cost"]
    print(f"        ✓ {len(hooks)} ganchos · {m2['latency_ms']}ms · ${m2['cost']:.4f}")

    # [3] Content Ideas — GPT
    print("  [3/6] Content Ideas via GPT...")
    ideas_raw, m3 = await _gpt(_p_content_ideas(bp, angles, hooks))
    ideas = ideas_raw.get("content_ideas", []) if isinstance(ideas_raw, dict) else []
    total_cost += m3["cost"]
    print(f"        ✓ {len(ideas)} ideias · {m3['latency_ms']}ms · ${m3['cost']:.4f}")

    # [4] Short Posts — GPT
    print("  [4/6] Short Posts via GPT...")
    posts_raw, m4 = await _gpt(_p_short_posts(bp, ideas))
    posts = posts_raw.get("posts", []) if isinstance(posts_raw, dict) else []
    total_cost += m4["cost"]
    print(f"        ✓ {len(posts)} posts · {m4['latency_ms']}ms · ${m4['cost']:.4f}")

    # [5] Reels Scripts — Claude
    print("  [5/6] Reels Scripts via Claude...")
    scripts_raw, m5 = await _claude(_p_scripts_base(bp, angles))
    scripts = scripts_raw.get("scripts", []) if isinstance(scripts_raw, dict) else []
    total_cost += m5["cost"]
    print(f"        ✓ {len(scripts)} roteiros · {m5['latency_ms']}ms · ${m5['cost']:.4f}")

    # [6] Script Variations — GPT
    print("  [6/6] Script Variations via GPT...")
    variations_raw, m6 = await _gpt(_p_script_variations(scripts))
    variations = variations_raw.get("variations", []) if isinstance(variations_raw, dict) else []
    total_cost += m6["cost"]
    print(f"        ✓ {len(variations)} variações · {m6['latency_ms']}ms · ${m6['cost']:.4f}")

    result = {
        "idea_title":     title,
        "target_audience": bp.get("target_audience", ""),
        "angles":         angles,
        "hooks":          hooks,
        "content_ideas":  ideas,
        "posts":          posts,
        "scripts":        scripts,
        "script_variations": variations,
        "total_cost":     round(total_cost, 6),
        "timestamp":      time.strftime("%Y%m%d_%H%M%S"),
        "summary": {
            "angles":     len(angles),
            "hooks":      len(hooks),
            "ideas":      len(ideas),
            "posts":      len(posts),
            "scripts":    len(scripts),
            "variations": len(variations),
        },
    }

    _salvar_local(result)
    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Persistência ─────────────────────────────────────────────────────────────

def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug  = result["idea_title"].replace(" ", "_")[:30]
    fname = f"{OUTPUTS_DIR}/content_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  Salvo em: {fname}")
    return fname


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa
        await salvar_tarefa(
            f"Content: {result['idea_title'][:60]}",
            "content",
            json.dumps(result, ensure_ascii=False, indent=2),
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
    s = result["summary"]
    print("\n" + "═" * 62)
    print(f"  CONTENT ENGINE — {result['idea_title'][:40]}")
    print("═" * 62)
    print(f"\n  {s['angles']} ângulos  ·  {s['hooks']} ganchos  ·  {s['ideas']} ideias")
    print(f"  {s['posts']} posts   ·  {s['scripts']} roteiros  ·  {s['variations']} variações")

    angles = result.get("angles", [])
    if angles:
        print("\n  ─── Ângulos ─────────────────────────────────────────────")
        for a in angles:
            print(f"  [{a.get('tipo',''):<18}] {a.get('titulo','')}")

    hooks = result.get("hooks", [])
    if hooks:
        print("\n  ─── Top 5 Ganchos ───────────────────────────────────────")
        for h in hooks[:5]:
            print(f"  → {h}")

    posts = result.get("posts", [])
    if posts:
        print("\n  ─── Post #1 (preview) ───────────────────────────────────")
        p = posts[0]
        print(f"  {p.get('gancho','')}")
        dev = p.get('desenvolvimento','')
        print(f"  {dev[:180]}{'...' if len(dev) > 180 else ''}")
        print(f"  {p.get('cta','')}")

    scripts = result.get("scripts", [])
    if scripts:
        print("\n  ─── Roteiro #1 (preview) ────────────────────────────────")
        sc = scripts[0]
        print(f"  [{sc.get('tom',''):<12}] {sc.get('duracao_estimada','')}")
        print(f"  Gancho: {sc.get('gancho','')}")
        print(f"  CTA   : {sc.get('cta','')}")

    print(f"\n  Custo total : ~${result['total_cost']:.4f}")
    print("═" * 62 + "\n")

    print("  Output (Node 09):")
    print(json.dumps({
        "status":       "success",
        "idea_title":   result["idea_title"],
        "angles":       len(result["angles"]),
        "hooks":        len(result["hooks"]),
        "content":      len(result["content_ideas"]),
        "posts":        len(result["posts"]),
        "scripts":      len(result["scripts"]),
        "total_cost":   result["total_cost"],
    }, ensure_ascii=False, indent=2))
    print()


# ─── Carregar blueprint ───────────────────────────────────────────────────────

def _load_best_blueprint() -> Optional[dict]:
    files = glob.glob(f"{OUTPUTS_DIR}/blueprint_*.json")
    best = None
    best_score = -1
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            bp = data.get("blueprint", {})
            score = bp.get("final_score", 0)
            if score > best_score:
                best_score = score
                best = bp
        except Exception:
            pass
    return best


def _load_blueprint_by_title(title: str) -> Optional[dict]:
    for path in glob.glob(f"{OUTPUTS_DIR}/blueprint_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            bp = data.get("blueprint", {})
            if title.lower() in bp.get("idea_title", "").lower():
                return bp
        except Exception:
            pass
    return None


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]
    bp = None

    if "--json" in args:
        idx = args.index("--json")
        bp = json.loads(args[idx + 1])

    elif "--title" in args:
        idx = args.index("--title")
        title = args[idx + 1] if idx + 1 < len(args) else ""
        bp = _load_blueprint_by_title(title)
        if not bp:
            print(f"  Blueprint não encontrado para: {title}")
            return

    else:
        bp = _load_best_blueprint()
        if bp:
            print(f"\n  Blueprint carregado: {bp.get('idea_title','')} (score {bp.get('final_score',0)})")
        else:
            print("  Nenhum blueprint encontrado. Rode product_engine.py primeiro.")
            return

    if not bp.get("idea_title"):
        print("  idea_title obrigatório.")
        return

    await build_content(bp)


if __name__ == "__main__":
    asyncio.run(main())
