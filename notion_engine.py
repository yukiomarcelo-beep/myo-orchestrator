#!/usr/bin/env python3
"""
notion_engine.py — Orquestrador Notion → AI Factory

Escuta uma database do Notion por itens com status "novo",
roteia pelo modo_execucao e devolve o resultado estruturado.

Modos:
  research_auto  — análise estratégica de oportunidades
  dan_koe        — conteúdo raiz + posts + carrosséis + vídeos
  produto        — estruturação de oferta/produto

Uso:
  python3 notion_engine.py              # roda uma vez
  python3 notion_engine.py --watch      # loop a cada 60s
  python3 notion_engine.py --watch --interval 30
"""

import os, sys, json, time, argparse
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN   = os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY")
NOTION_DB_ID   = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_MODEL      = os.getenv("GPT_MODEL", "gpt-4o")

# ── Cores ──────────────────────────────────────────────────
C  = "\033[0m"; B = "\033[1m"; GR = "\033[92m"; YL = "\033[93m"
RD = "\033[91m"; CY = "\033[96m"; GY = "\033[90m"; PK = "\033[95m"

def log(msg, color=C):   print(f"  {color}{msg}{C}")
def ok(msg):             log(f"✓ {msg}", GR)
def warn(msg):           log(f"⚠ {msg}", YL)
def err(msg):            log(f"✗ {msg}", RD)
def info(msg):           log(f"→ {msg}", CY)
def hdr(msg):            print(f"\n{PK}{B}  {msg}{C}")

# ═══════════════════════════════════════════════════════════
# NOTION CLIENT
# ═══════════════════════════════════════════════════════════

def get_notion():
    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN não encontrado no .env")
    from notion_client import Client
    return Client(auth=NOTION_TOKEN)

def get_prop(props, name, fallback=""):
    """Extrai valor de propriedade Notion de forma segura."""
    p = props.get(name, {})
    t = p.get("type", "")
    if t == "title":
        items = p.get("title", [])
        return "".join(i.get("plain_text", "") for i in items).strip()
    if t == "rich_text":
        items = p.get("rich_text", [])
        return "".join(i.get("plain_text", "") for i in items).strip()
    if t == "select":
        s = p.get("select") or {}
        return s.get("name", fallback)
    if t == "status":
        s = p.get("status") or {}
        return s.get("name", fallback)
    return fallback

def set_prop_text(text):
    return {"rich_text": [{"text": {"content": str(text)[:2000]}}]}

def set_prop_select(name):
    return {"select": {"name": str(name)}}

def set_prop_status(name):
    return {"status": {"name": str(name)}}

# Mapeamento: status interno → nome no Notion
def fetch_novos(notion, db_id):
    """Busca páginas com status = novo."""
    result = notion.databases.query(
        database_id=db_id,
        filter={
            "property": "status",
            "select": {"equals": "novo"}
        }
    )
    return result.get("results", [])

def marcar_processando(notion, page_id):
    try:
        notion.pages.update(page_id=page_id, properties={
            "status": set_prop_select("processando")
        })
    except Exception as e:
        warn(f"Não marcou processando: {e}")

def atualizar_pagina(notion, page_id, status, saida_json, observacoes):
    # status: concluido → concluído, erro → erro
    notion_status = "concluído" if status == "concluido" else status
    props = {"observacoes": set_prop_text(observacoes)}
    if saida_json:
        props["saida_json"] = set_prop_text(saida_json)
    try:
        notion.pages.update(page_id=page_id, properties={
            **props, "status": set_prop_select(notion_status)
        })
    except Exception as e:
        warn(f"Não foi possível atualizar página: {e}")

# ═══════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════

def prompt_research_auto(titulo, descricao):
    return f"""Você é um analista estratégico de negócios digitais com foco em gastronomia, operação, IA e monetização.

TEMA CENTRAL:
{titulo}

CONTEXTO ADICIONAL:
{descricao}

Sua missão:
1. Encontrar 10 oportunidades de conteúdo ou produto
2. Identificar dores de mercado
3. Sugerir ângulos de posicionamento
4. Sugerir quais ideias têm maior potencial de monetização
5. Responder SOMENTE em JSON válido

Formato obrigatório:
{{
  "resumo_estrategico": "",
  "dores": ["", ""],
  "oportunidades": [
    {{
      "titulo": "",
      "tipo": "conteudo|produto|servico",
      "potencial": 1,
      "justificativa": ""
    }}
  ],
  "prioridade_recomendada": {{
    "titulo": "",
    "motivo": ""
  }}
}}"""

def prompt_dan_koe(titulo, descricao):
    return f"""Você é um estrategista de conteúdo no estilo Dan Koe, adaptado para negócios digitais, lucro e operação.

TEMA:
{titulo}

CONTEXTO:
{descricao}

Crie:
1. 1 conteúdo raiz
2. 5 posts curtos para validação
3. 2 ideias de carrossel
4. 2 roteiros curtos de vídeo
5. 1 CTA leve para captar interesse

Responda SOMENTE em JSON válido.

Formato:
{{
  "conteudo_raiz": {{
    "titulo": "",
    "texto": ""
  }},
  "posts_validacao": [
    {{"hook": "", "texto": ""}},
    {{"hook": "", "texto": ""}},
    {{"hook": "", "texto": ""}},
    {{"hook": "", "texto": ""}},
    {{"hook": "", "texto": ""}}
  ],
  "carrosseis": [
    {{"titulo": "", "slides": ["", "", "", "", ""]}},
    {{"titulo": "", "slides": ["", "", "", "", ""]}}
  ],
  "videos_curtos": [
    {{"titulo": "", "roteiro": ""}},
    {{"titulo": "", "roteiro": ""}}
  ],
  "cta": ""
}}"""

def prompt_produto(titulo, descricao):
    return f"""Você é um estrategista de produtos digitais.

IDEIA VALIDADA:
{titulo}

CONTEXTO:
{descricao}

Crie uma oferta simples e vendável.

Responda SOMENTE em JSON válido.

Formato:
{{
  "nome_produto": "",
  "promessa": "",
  "publico": "",
  "entregaveis": ["", "", ""],
  "estrutura_interna": ["", "", ""],
  "preco_sugerido": {{
    "entrada": "",
    "premium": ""
  }},
  "oferta_curta": "",
  "proximo_passo": ""
}}"""

PROMPT_MAP = {
    "research_auto": prompt_research_auto,
    "dan_koe":       prompt_dan_koe,
    "produto":       prompt_produto,
}

# ═══════════════════════════════════════════════════════════
# OPENAI
# ═══════════════════════════════════════════════════════════

def chamar_openai(prompt):
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY não encontrada no .env")
    import urllib.request
    body = json.dumps({
        "model": GPT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"]

def parse_resposta(text):
    try:
        return json.loads(text)
    except Exception:
        import re
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return json.loads(m.group(0))
        raise ValueError("Não foi possível converter a resposta em JSON")

# ═══════════════════════════════════════════════════════════
# NORMALIZAR ENTRADA
# ═══════════════════════════════════════════════════════════

def normalizar(page):
    props = page.get("properties", {})
    titulo    = get_prop(props, "titulo")   or get_prop(props, "Nome") or get_prop(props, "Name")
    descricao = get_prop(props, "descricao") or get_prop(props, "description") or ""
    modo      = get_prop(props, "modo_execucao") or "research_auto"
    return {
        "page_id":       page["id"],
        "titulo":        titulo.strip(),
        "descricao":     descricao.strip(),
        "modo_execucao": modo.strip().lower(),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }

# ═══════════════════════════════════════════════════════════
# PROCESSAR ITEM
# ═══════════════════════════════════════════════════════════

def processar(notion, item):
    page_id = item["page_id"]
    titulo  = item["titulo"]
    modo    = item["modo_execucao"]

    hdr(f'Processando: "{titulo}"')
    info(f"Modo: {modo}")

    marcar_processando(notion, page_id)

    fn_prompt = PROMPT_MAP.get(modo)
    if not fn_prompt:
        warn(f"Modo desconhecido: {modo} — usando research_auto")
        fn_prompt = prompt_research_auto
        modo = "research_auto"

    prompt = fn_prompt(titulo, item["descricao"])
    info("Chamando OpenAI...")
    raw = chamar_openai(prompt)

    info("Parseando resposta...")
    resultado = parse_resposta(raw)

    saida = json.dumps({"modo_execucao": modo, "resultado": resultado}, ensure_ascii=False, indent=2)
    obs   = f"Execução concluída no modo: {modo} em {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    atualizar_pagina(notion, page_id, "concluido", saida, obs)
    ok(f'Concluído: "{titulo}"')

    # Salva localmente também
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"notion_{modo}_{ts}.json"
    fpath = os.path.join(os.path.dirname(__file__), "outputs", fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump({"item": item, "resultado": resultado}, f, ensure_ascii=False, indent=2)
    info(f"Salvo em outputs/{fname}")
    return resultado

# ═══════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════════

def rodar_uma_vez(notion, db_id):
    paginas = fetch_novos(notion, db_id)
    if not paginas:
        log("Nenhum item novo encontrado.", GY)
        return 0

    log(f"{len(paginas)} item(s) novo(s) encontrado(s).", CY)
    erros = 0
    for page in paginas:
        item = normalizar(page)
        if not item["titulo"]:
            warn(f"Página {page['id']} sem título — pulando")
            continue
        try:
            processar(notion, item)
        except Exception as e:
            err(f"Erro em '{item['titulo']}': {e}")
            atualizar_pagina(notion, item["page_id"], "erro", "",
                             f"Erro: {str(e)[:500]}")
            erros += 1
    return erros

def main():
    parser = argparse.ArgumentParser(description="Notion Engine — AI Factory")
    parser.add_argument("--watch",    action="store_true", help="Loop contínuo")
    parser.add_argument("--interval", type=int, default=60, help="Intervalo em segundos (padrão: 60)")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        err("NOTION_TOKEN não encontrado no .env")
        err("Adicione: NOTION_TOKEN=secret_xxx")
        sys.exit(1)
    if not NOTION_DB_ID:
        err("NOTION_DATABASE_ID não encontrado no .env")
        err("Adicione: NOTION_DATABASE_ID=xxx")
        sys.exit(1)
    if not OPENAI_API_KEY:
        err("OPENAI_API_KEY não encontrada no .env")
        sys.exit(1)

    hdr("MYO — Notion Engine")
    print(f"  {'─' * 44}")
    info(f"Database: {NOTION_DB_ID[:8]}...")
    info(f"Modelo:   {GPT_MODEL}")

    notion = get_notion()

    if args.watch:
        info(f"Watch mode: verificando a cada {args.interval}s\n")
        while True:
            try:
                rodar_uma_vez(notion, NOTION_DB_ID)
            except Exception as e:
                err(f"Erro no loop: {e}")
            print(f"\n{GY}  Aguardando {args.interval}s...{C}")
            time.sleep(args.interval)
    else:
        rodar_uma_vez(notion, NOTION_DB_ID)

if __name__ == "__main__":
    main()
