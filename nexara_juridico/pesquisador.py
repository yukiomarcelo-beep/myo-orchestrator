"""
NEXARA — Pesquisador Jurídico
Versão: 1.0.0

2 agentes paralelos:
  - Agente A: jurisprudência (STJ, TST, STF, TJs)
  - Agente B: legislação + doutrina

Servidor: python pesquisador.py --server   (porta 8765)
Demo:     python pesquisador.py --demo
"""

import asyncio
import sys
import json
import argparse
import logging
import time
from pathlib import Path

import aiohttp.web

sys.path.insert(0, str(Path(__file__).parent))
from shared.config import cfg
from shared.session import Session
from shared.retry import com_retry

try:
    import anthropic
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "nexara_cost_guard"))
    from cost_guard import CostGuard
    guard = CostGuard()
    GUARD_DISPONIVEL = True
except ImportError:
    guard = None
    GUARD_DISPONIVEL = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            Path(__file__).parent.parent / "logs" / "pesquisador.log",
            encoding="utf-8"
        ),
    ]
)
log = logging.getLogger("nexara.pesquisador")

PORTA = cfg.porta("pesquisador")
MODELO = cfg.modelo("pesquisa_juridica")


# ─────────────────────────────────────────────
# Prompts dos agentes
# ─────────────────────────────────────────────

SYSTEM_JURISPRUDENCIA = """Você é um pesquisador jurídico especializado em jurisprudência brasileira.
Pesquise e retorne jurisprudência relevante dos tribunais superiores (STJ, STF, TST) e estaduais.

Para cada resultado retorne JSON com:
{
  "tribunal": "STJ|STF|TST|TRT|TJSP...",
  "numero": "REsp 1.234.567/SP",
  "ementa": "resumo da decisão em 1-2 frases",
  "relevancia": "alta|media|baixa",
  "aplicacao": "como se aplica ao caso"
}

Retorne APENAS um array JSON válido. Sem texto adicional. Sem markdown. Máximo 5 resultados."""

SYSTEM_LEGISLACAO = """Você é um pesquisador jurídico especializado em legislação e doutrina brasileira.
Pesquise dispositivos legais, artigos e doutrina relevante.

Para legislação retorne JSON com:
{
  "tipo": "legislacao",
  "diploma": "Código Civil/2002|CLT|Lei 6.404/76...",
  "artigo": "Art. 413",
  "texto": "resumo do dispositivo",
  "aplicacao": "como se aplica ao caso"
}

Para doutrina retorne JSON com:
{
  "tipo": "doutrina",
  "autor": "Nome do Autor",
  "obra": "Título da Obra",
  "trecho": "resumo da posição doutrinária",
  "relevancia": "alta|media|baixa"
}

Retorne APENAS um array JSON válido. Sem texto adicional. Sem markdown. Máximo 5 resultados."""


# ─────────────────────────────────────────────
# Agentes paralelos
# ─────────────────────────────────────────────

async def agente_jurisprudencia(
    query: str,
    tribunais: list[str],
    session: Session,
) -> list[dict]:
    """Agente A: pesquisa jurisprudência."""
    log.info(f"[Jurisprudência] Query: '{query}' | Tribunais: {tribunais}")
    session.append("agente_iniciado", {"agente": "jurisprudencia", "query": query})

    prompt = (
        f"Pesquise jurisprudência sobre: {query}\n"
        f"Foco nos tribunais: {', '.join(tribunais)}\n"
        f"Retorne os 5 acórdãos mais relevantes e recentes."
    )

    try:
        if GUARD_DISPONIVEL:
            resposta = guard.run(
                projeto="nexara_consultoria",
                tarefa="pesquisa_juridica",
                model=MODELO,
                messages=[{"role": "user", "content": prompt}],
                system=SYSTEM_JURISPRUDENCIA,
            )
            texto = resposta.content[0].text
        else:
            import os
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            resposta = client.messages.create(
                model=MODELO,
                max_tokens=2000,
                system=SYSTEM_JURISPRUDENCIA,
                messages=[{"role": "user", "content": prompt}],
            )
            texto = resposta.content[0].text

        resultado = _parse_json_seguro(texto, default=[])
        session.append("agente_concluido", {
            "agente": "jurisprudencia", "ok": True,
            "resultado": {"n_resultados": len(resultado)}
        })
        log.info(f"[Jurisprudência] {len(resultado)} resultado(s) encontrado(s)")
        return resultado

    except Exception as e:
        log.error(f"[Jurisprudência] Erro: {e}")
        session.append("agente_erro", {"agente": "jurisprudencia", "erro": str(e)})
        return []


async def agente_legislacao(
    query: str,
    artigos_ref: list[str],
    session: Session,
) -> list[dict]:
    """Agente B: pesquisa legislação e doutrina."""
    log.info(f"[Legislação] Query: '{query}' | Refs: {artigos_ref}")
    session.append("agente_iniciado", {"agente": "legislacao", "query": query})

    refs_str = ", ".join(artigos_ref) if artigos_ref else "não especificado"
    prompt = (
        f"Pesquise legislação e doutrina sobre: {query}\n"
        f"Referências legais específicas: {refs_str}\n"
        f"Inclua o texto dos dispositivos e posições doutrinárias relevantes."
    )

    try:
        if GUARD_DISPONIVEL:
            resposta = guard.run(
                projeto="nexara_consultoria",
                tarefa="pesquisa_juridica",
                model=MODELO,
                messages=[{"role": "user", "content": prompt}],
                system=SYSTEM_LEGISLACAO,
            )
            texto = resposta.content[0].text
        else:
            import os
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            resposta = client.messages.create(
                model=MODELO,
                max_tokens=2000,
                system=SYSTEM_LEGISLACAO,
                messages=[{"role": "user", "content": prompt}],
            )
            texto = resposta.content[0].text

        resultado = _parse_json_seguro(texto, default=[])
        session.append("agente_concluido", {
            "agente": "legislacao", "ok": True,
            "resultado": {"n_resultados": len(resultado)}
        })
        log.info(f"[Legislação] {len(resultado)} resultado(s) encontrado(s)")
        return resultado

    except Exception as e:
        log.error(f"[Legislação] Erro: {e}")
        session.append("agente_erro", {"agente": "legislacao", "erro": str(e)})
        return []


# ─────────────────────────────────────────────
# Consolidador
# ─────────────────────────────────────────────

def consolidar_pesquisa(
    risco_origem: str,
    jurisprudencia: list[dict],
    legislacao_doutrina: list[dict],
) -> dict:
    """Consolida resultados dos 2 agentes em um único ResultadoPesquisa."""
    legislacao = [i for i in legislacao_doutrina if i.get("tipo") == "legislacao"]
    doutrina   = [i for i in legislacao_doutrina if i.get("tipo") == "doutrina"]

    # Gera recomendação baseada nos resultados
    recomendacao = _gerar_recomendacao(risco_origem, jurisprudencia, legislacao)

    return {
        "risco_origem":   risco_origem,
        "jurisprudencia": jurisprudencia,
        "legislacao":     legislacao,
        "doutrina":       doutrina,
        "recomendacao":   recomendacao,
    }


def _gerar_recomendacao(
    risco: str,
    jurisprudencia: list[dict],
    legislacao: list[dict],
) -> str:
    if not jurisprudencia and not legislacao:
        return f"Consultar jurisprudência atualizada sobre '{risco}' antes de prosseguir."
    partes = []
    alta = [j for j in jurisprudencia if j.get("relevancia") == "alta"]
    if alta:
        partes.append(f"Jurisprudência dominante no {alta[0].get('tribunal', 'STJ')} favorece atenção a este ponto.")
    if legislacao:
        partes.append(f"Fundamento legal: {legislacao[0].get('diploma', 'legislação aplicável')}, {legislacao[0].get('artigo', '')}.")
    partes.append("Recomenda-se revisão da cláusula antes da assinatura.")
    return " ".join(partes)


# ─────────────────────────────────────────────
# Pipeline principal — lote de queries
# ─────────────────────────────────────────────

async def pesquisar_lote(payload: dict) -> dict:
    """
    Recebe lote de queries do orquestrador e retorna resultados consolidados.
    Cada query roda 2 agentes em paralelo (jurisprudência + legislação).
    """
    queries = payload.get("queries", [])
    session = Session(escritorio_id=payload.get("escritorio_id", "nexara"))

    session.append("pesquisa_iniciada", {
        "n_queries": len(queries),
        "tipo_demanda": payload.get("tipo_demanda"),
    })

    log.info(f"Iniciando pesquisa: {len(queries)} queries")
    inicio = time.time()

    resultados = []
    for q in queries:
        risco_origem          = q.get("risco_origem", "N/A")
        query_jurisprudencia  = q.get("query_jurisprudencia", "")
        query_legislacao      = q.get("query_legislacao", "")
        tribunais             = q.get("tribunais_alvo", ["STJ", "TST", "STF"])
        artigos_ref           = [q.get("artigo_ref")] if q.get("artigo_ref") else []

        # 2 agentes em paralelo
        juris, legis = await asyncio.gather(
            agente_jurisprudencia(query_jurisprudencia, tribunais, session),
            agente_legislacao(query_legislacao, artigos_ref, session),
            return_exceptions=True,
        )

        # Tolerância a falha — se um agente falhar, usa resultado vazio
        if isinstance(juris, Exception):
            log.warning(f"Agente jurisprudência falhou: {juris}")
            juris = []
        if isinstance(legis, Exception):
            log.warning(f"Agente legislação falhou: {legis}")
            legis = []

        resultado = consolidar_pesquisa(risco_origem, juris, legis)
        resultados.append(resultado)

    duracao = round(time.time() - inicio, 2)
    session.append("pesquisa_concluida", {
        "n_resultados": len(resultados),
        "duracao_s": duracao,
    })

    log.info(f"Pesquisa concluída: {len(resultados)} resultado(s) em {duracao}s")
    return {"resultados": resultados, "duracao_s": duracao}


# ─────────────────────────────────────────────
# Servidor HTTP
# ─────────────────────────────────────────────

async def handle_health(request):
    return aiohttp.web.json_response({
        "status": "ok",
        "servico": "nexara-pesquisador",
        "guard_disponivel": GUARD_DISPONIVEL,
    })


async def handle_pesquisar_lote(request):
    """POST /pesquisar_lote — recebe lote de queries do orquestrador."""
    try:
        payload = await request.json()
    except Exception:
        return aiohttp.web.json_response({"erro": "Body JSON inválido"}, status=400)

    if "queries" not in payload:
        return aiohttp.web.json_response({"erro": "Campo 'queries' obrigatório"}, status=400)

    try:
        resultado = await pesquisar_lote(payload)
        return aiohttp.web.json_response(resultado)
    except Exception as e:
        log.exception(f"Erro no pesquisar_lote: {e}")
        return aiohttp.web.json_response({"erro": str(e)}, status=500)


async def handle_pesquisar(request):
    """POST /pesquisar — pesquisa simples, query única."""
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"erro": "Body JSON inválido"}, status=400)

    query = body.get("query", "")
    if not query:
        return aiohttp.web.json_response({"erro": "Campo 'query' obrigatório"}, status=400)

    # Monta payload no formato de lote com 1 query
    payload = {
        "queries": [{
            "risco_origem": query,
            "query_jurisprudencia": query,
            "query_legislacao": query,
            "tribunais_alvo": body.get("tribunais", ["STJ", "TST", "STF"]),
        }],
        "escritorio_id": body.get("escritorio_id", "nexara"),
    }

    resultado = await pesquisar_lote(payload)
    resultados = resultado.get("resultados", [])
    r = resultados[0] if resultados else {}

    return aiohttp.web.json_response({
        "query": query,
        "jurisprudencia": r.get("jurisprudencia", []),
        "legislacao":     r.get("legislacao", []),
        "doutrina":       r.get("doutrina", []),
        "recomendacao":   r.get("recomendacao", ""),
        "resumo":         f"{len(r.get('jurisprudencia', []))} julgados + "
                          f"{len(r.get('legislacao', []))} dispositivos",
        "n_fontes":       len(r.get("jurisprudencia", [])) + len(r.get("legislacao", [])),
    })


async def handle_status(request):
    return aiohttp.web.json_response({
        "servico":  "nexara-pesquisador",
        "versao":   "1.0.0",
        "porta":    PORTA,
        "modelo":   MODELO,
        "guard":    GUARD_DISPONIVEL,
        "endpoints": ["/health", "/pesquisar", "/pesquisar_lote", "/status"],
    })


# ─────────────────────────────────────────────
# Demo e CLI
# ─────────────────────────────────────────────

async def rodar_demo():
    print("\n" + "="*60)
    print("  NEXARA — Pesquisador Jurídico")
    print("  Demo (dry run — sem chamada de API)")
    print("="*60 + "\n")

    payload = {
        "queries": [
            {
                "risco_origem": "Cláusula 5.2 — Rescisão Antecipada",
                "query_jurisprudencia": "rescisão antecipada multa desproporcional STJ",
                "query_legislacao": "Art. 413 CC/2002 cláusula penal redução",
                "tribunais_alvo": ["STJ", "TJSP"],
            },
            {
                "risco_origem": "Cláusula 8.1 — Propriedade Intelectual",
                "query_jurisprudencia": "cessão direitos autorais software STJ",
                "query_legislacao": "Art. 11 Lei 9.279/96 cessão PI",
                "tribunais_alvo": ["STJ"],
            },
        ],
        "tipo_demanda": "prestacao_servicos",
        "escritorio_id": "demo",
    }

    print(f"Simulando pesquisa com {len(payload['queries'])} queries...")
    print("(Sem API — mostrando estrutura do resultado)\n")

    # Simula resultado sem chamar API
    for q in payload["queries"]:
        print(f"  Risco: {q['risco_origem']}")
        print(f"  Query jurisprudência: {q['query_jurisprudencia']}")
        print(f"  Query legislação:     {q['query_legislacao']}")
        print()

    print("Para testar com API real: recarregue o crédito e rode --demo novamente")
    print("Para subir o servidor:    python pesquisador.py --server\n")


def main():
    # Garante que o diretório de logs existe
    (Path(__file__).parent.parent / "logs").mkdir(exist_ok=True)

    parser = argparse.ArgumentParser(description="NEXARA Pesquisador Jurídico")
    parser.add_argument("--server",  action="store_true", help=f"Sobe servidor HTTP na porta {PORTA}")
    parser.add_argument("--demo",    action="store_true", help="Roda demo")
    args = parser.parse_args()

    if args.server:
        app = aiohttp.web.Application()
        app.router.add_get("/health",             handle_health)
        app.router.add_post("/pesquisar",          handle_pesquisar)
        app.router.add_post("/pesquisar_lote",     handle_pesquisar_lote)
        app.router.add_get("/status",             handle_status)
        print(f"\n🔍 NEXARA Pesquisador rodando em http://localhost:{PORTA}")
        print(f"   POST /pesquisar       — query única")
        print(f"   POST /pesquisar_lote  — lote de queries (orquestrador)")
        print(f"   GET  /health          — health check")
        print(f"   Guard: {'✓ ativo' if GUARD_DISPONIVEL else '✗ não disponível'}\n")
        aiohttp.web.run_app(app, host="0.0.0.0", port=PORTA, print=None)

    elif args.demo:
        asyncio.run(rodar_demo())

    else:
        parser.print_help()
        print(f"\nExemplos:")
        print(f"  python pesquisador.py --demo     # visualiza estrutura")
        print(f"  python pesquisador.py --server   # sobe na porta {PORTA}")


# ─────────────────────────────────────────────
# Utilitários
# ─────────────────────────────────────────────

def _parse_json_seguro(texto: str, default=None):
    """Parse JSON com tolerância a markdown fences."""
    if default is None:
        default = []
    texto = texto.strip()
    # Remove markdown fences se existirem
    if texto.startswith("```"):
        linhas = texto.split("\n")
        texto = "\n".join(linhas[1:-1] if linhas[-1].strip() == "```" else linhas[1:])
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.warning(f"JSON inválido retornado pelo modelo. Usando default.")
        return default


if __name__ == "__main__":
    main()
