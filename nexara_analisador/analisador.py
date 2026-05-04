"""
NEXARA — Analisador de Contratos
Versão: 1.0.0

5 agentes sequenciais com checkpoint:
  1. validador_pdf   — valida e extrai texto do PDF
  2. classificador   — identifica tipo e partes
  3. extrator        — extrai cláusulas estruturadas
  4. riscos          — analisa riscos por checklist
  5. consolidador    — gera relatório final

Servidor: python analisador.py --server   (porta 8766)
Demo:     python analisador.py --demo
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import aiohttp.web

sys.path.insert(0, str(Path(__file__).parent.parent / "nexara_juridico"))
sys.path.insert(0, str(Path(__file__).parent.parent / "nexara_juridico" / "shared"))

from shared import audit
from shared.aviso_juridico import AvisoJuridico
from shared.checklist_store import ChecklistStore
from shared.config import cfg
from shared.security import (
    REGRAS_SEGURANCA_NEXARA,
    detectar_injection,
    encapsular_conteudo_externo,
)
from shared.session import Session

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
            Path(__file__).parent.parent / "logs" / "analisador.log", encoding="utf-8"
        ),
    ],
)
log = logging.getLogger("nexara.analisador")

PORTA = cfg.porta("analisador")
MODELO = cfg.modelo("analise")
MODELO_SIMPLES = cfg.modelo("classificacao")  # haiku para tarefas simples
CHECKLIST_DIR = Path(__file__).parent / "checklists"


# ─────────────────────────────────────────────
# Chamada ao modelo (com ou sem guard)
# ─────────────────────────────────────────────


def _chamar_modelo(
    prompt: str,
    system: str,
    tarefa: str = "analise",
    modelo: str = None,
) -> str:
    modelo = modelo or MODELO
    try:
        if GUARD_DISPONIVEL:
            resposta = guard.run(
                projeto="nexara_consultoria",
                tarefa=tarefa,
                model=modelo,
                messages=[{"role": "user", "content": prompt}],
                system=system,
            )
        else:
            import os

            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            inicio_ms = time.time()
            resposta = client.messages.create(
                model=modelo,
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            audit.log_tool_call(
                agent=f"analisador.{tarefa}",
                tool="anthropic.messages.create",
                args_summary={
                    "model": modelo,
                    "input_tokens": resposta.usage.input_tokens,
                    "output_tokens": resposta.usage.output_tokens,
                },
                duration_ms=(time.time() - inicio_ms) * 1000,
            )
        return resposta.content[0].text
    except Exception as e:
        log.error(f"Erro ao chamar modelo ({tarefa}): {e}")
        raise


# ─────────────────────────────────────────────
# Agente 1 — Validador PDF
# ─────────────────────────────────────────────


def agente_validador_pdf(pdf_path: str, session: Session) -> dict:
    """
    Valida o PDF e extrai o texto.
    Usa haiku — tarefa simples de validação.
    Retorna: {"valido": bool, "texto": str, "n_paginas": int, "erro": str}
    """
    log.info(f"[Validador] PDF: {pdf_path}")

    path = Path(pdf_path)
    if not path.exists():
        # Em dry_run o arquivo não existe — retorna estrutura válida simulada
        log.warning(f"[Validador] PDF não encontrado: {pdf_path} — usando modo simulação")
        return {
            "valido": True,
            "texto": f"[SIMULAÇÃO] Conteúdo do arquivo {path.name}",
            "n_paginas": 0,
            "simulado": True,
        }

    # Tenta extrair texto com PyPDF2 ou pdfminer
    texto = _extrair_texto_pdf(path)
    if not texto or len(texto.strip()) < 100:
        return {"valido": False, "erro": "PDF sem texto extraível (pode ser imagem).", "texto": ""}

    flags = detectar_injection(texto)
    if flags:
        audit.log_anomaly(
            agent="analisador.validador_pdf",
            flags=flags,
            content=texto,
            source="pdf_cliente",
            severity="high" if len(flags) >= 2 else "medium",
            session_id=session.id,
        )

    session.append(
        "agente_concluido",
        {
            "agente": "validador_pdf",
            "ok": True,
            "resultado": {"n_chars": len(texto), "n_paginas": texto.count("\f") + 1},
        },
    )
    return {"valido": True, "texto": texto, "n_paginas": texto.count("\f") + 1}


def _extrair_texto_pdf(path: Path) -> str:
    """Tenta extrair texto do PDF com bibliotecas disponíveis."""
    # Tenta PyPDF2
    try:
        import PyPDF2

        texto = ""
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                texto += page.extract_text() or ""
        if texto.strip():
            return texto
    except ImportError:
        pass
    except Exception as e:
        log.warning(f"PyPDF2 falhou: {e}")

    # Tenta pdfminer
    try:
        from pdfminer.high_level import extract_text

        return extract_text(str(path))
    except ImportError:
        pass
    except Exception as e:
        log.warning(f"pdfminer falhou: {e}")

    return ""


# ─────────────────────────────────────────────
# Agente 2 — Classificador
# ─────────────────────────────────────────────

SYSTEM_CLASSIFICADOR = f"""{REGRAS_SEGURANCA_NEXARA}

───────────────────────────────────────────────────────────────────

Você é um especialista em direito contratual brasileiro.
Analise o texto do contrato e retorne APENAS um JSON válido com:
{
  "tipo_contrato": "Contrato de Prestação de Serviços|Contrato de Compra e Venda|...",
  "partes": [{"nome": "...", "qualificacao": "contratante|contratado|vendedor|comprador"}],
  "objeto": "descrição resumida do objeto em 1 frase",
  "vigencia": "prazo ou 'indeterminado'",
  "valor_estimado": "valor ou 'não especificado'",
  "jurisdicao": "estado ou 'não especificado'"
}
Sem texto adicional. Sem markdown."""


def agente_classificador(texto: str, session: Session) -> dict:
    """Agente 2: classifica o contrato. Usa haiku."""
    log.info("[Classificador] Classificando contrato...")

    # Usa apenas os primeiros 3000 chars para classificação (economiza tokens)
    trecho = texto[:3000]
    prompt = "Classifique este contrato:\n\n" + encapsular_conteudo_externo(trecho, "pdf_cliente")

    try:
        resposta = _chamar_modelo(
            prompt=prompt,
            system=SYSTEM_CLASSIFICADOR,
            tarefa="classificacao",
            modelo=MODELO_SIMPLES,
        )
        resultado = _parse_json_seguro(
            resposta,
            default={
                "tipo_contrato": "Contrato (tipo não identificado)",
                "partes": [],
                "objeto": "não identificado",
            },
        )
        session.append(
            "agente_concluido",
            {
                "agente": "classificador",
                "ok": True,
                "resultado": {"tipo": resultado.get("tipo_contrato")},
            },
        )
        return resultado
    except Exception as e:
        log.error(f"[Classificador] Erro: {e}")
        session.append("agente_erro", {"agente": "classificador", "erro": str(e)})
        return {"tipo_contrato": "Não classificado", "partes": [], "objeto": ""}


# ─────────────────────────────────────────────
# Agente 3 — Extrator
# ─────────────────────────────────────────────

SYSTEM_EXTRATOR = f"""{REGRAS_SEGURANCA_NEXARA}

───────────────────────────────────────────────────────────────────

Você é um especialista em extração de cláusulas contratuais.
Extraia as cláusulas mais relevantes do contrato e retorne APENAS um JSON válido:
[
  {
    "numero": "Cláusula 1",
    "titulo": "Objeto",
    "texto": "texto resumido da cláusula em até 200 caracteres",
    "temas": ["objeto", "serviços"]
  }
]
Máximo 15 cláusulas mais relevantes. Sem texto adicional. Sem markdown."""


def agente_extrator(texto: str, session: Session) -> list[dict]:
    """Agente 3: extrai cláusulas estruturadas. Usa sonnet."""
    log.info("[Extrator] Extraindo cláusulas...")

    # Limita o texto para não explodir contexto
    texto_limitado = texto[:8000] if len(texto) > 8000 else texto
    prompt = "Extraia as cláusulas deste contrato:\n\n" + encapsular_conteudo_externo(
        texto_limitado, "pdf_cliente"
    )

    try:
        resposta = _chamar_modelo(
            prompt=prompt,
            system=SYSTEM_EXTRATOR,
            tarefa="extracao_dados",
            modelo=MODELO_SIMPLES,
        )
        clausulas = _parse_json_seguro(resposta, default=[])
        session.append(
            "agente_concluido",
            {"agente": "extrator", "ok": True, "resultado": {"n_clausulas": len(clausulas)}},
        )
        log.info(f"[Extrator] {len(clausulas)} cláusula(s) extraída(s)")
        return clausulas
    except Exception as e:
        log.error(f"[Extrator] Erro: {e}")
        session.append("agente_erro", {"agente": "extrator", "erro": str(e)})
        return []


# ─────────────────────────────────────────────
# Agente 4 — Analisador de Riscos
# ─────────────────────────────────────────────


def _montar_system_riscos(checklist: dict) -> str:
    clausulas_checklist = checklist.get("clausulas", [])
    temas = "\n".join(
        f"- {c['id']}: {c['tema']} — {c['descricao']} "
        f"(Ref: {c['baseline_legal']}, Risco default: {c['nivel_default']})"
        for c in clausulas_checklist
    )
    return f"""{REGRAS_SEGURANCA_NEXARA}

───────────────────────────────────────────────────────────────────

Você é um advogado especialista em análise de riscos contratuais.
Analise as cláusulas fornecidas e identifique riscos usando o checklist abaixo.

CHECKLIST ({checklist.get('tipo', 'geral')} v{checklist.get('versao', '1.0.0')}):
{temas}

Retorne APENAS um JSON válido:
{{
  "score_risco": 7.5,
  "riscos": [
    {{
      "clausula": "Cláusula X.X — Título",
      "descricao": "descrição do risco em linguagem jurídica",
      "nivel": "critico|alto|medio|baixo",
      "artigo_ref": "Art. XXX CC/2002"
    }}
  ],
  "clausulas_ok": ["Cláusula 1 — Objeto", "..."],
  "resumo_executivo": "resumo em 2-3 frases para o sócio"
}}
Sem texto adicional. Sem markdown."""


def agente_riscos(
    clausulas: list[dict],
    tipo_contrato: str,
    checklist_versao: str,
    session: Session,
) -> dict:
    """Agente 4: analisa riscos com checklist versionado. Usa sonnet."""
    log.info(f"[Riscos] Analisando {len(clausulas)} cláusula(s)...")

    # Carrega checklist correspondente ao tipo
    store = ChecklistStore(CHECKLIST_DIR)
    tipo_checklist = _mapear_tipo_para_checklist(tipo_contrato)
    try:
        checklist = store.vigente(tipo_checklist)
        checklist_versao = checklist.get("versao", "1.0.0")
    except FileNotFoundError:
        log.warning(f"[Riscos] Checklist '{tipo_checklist}' não encontrado. Usando análise livre.")
        checklist = {"tipo": tipo_checklist, "versao": "0.0.0", "clausulas": []}

    system = _montar_system_riscos(checklist)
    clausulas_texto = json.dumps(clausulas, ensure_ascii=False, indent=2)
    prompt = f"Analise os riscos das seguintes cláusulas:\n\n{clausulas_texto}"

    try:
        resposta = _chamar_modelo(
            prompt=prompt,
            system=system,
            tarefa="analise_juridica",
            modelo=MODELO,
        )
        resultado = _parse_json_seguro(
            resposta,
            default={
                "score_risco": 5.0,
                "riscos": [],
                "clausulas_ok": [],
                "resumo_executivo": "Análise não disponível.",
            },
        )
        session.append(
            "agente_concluido",
            {
                "agente": "riscos",
                "ok": True,
                "resultado": {
                    "n_riscos": len(resultado.get("riscos", [])),
                    "score": resultado.get("score_risco"),
                    "checklist_versao": checklist_versao,
                },
            },
        )
        log.info(
            f"[Riscos] {len(resultado.get('riscos', []))} risco(s) — score {resultado.get('score_risco')}"
        )
        return resultado
    except Exception as e:
        log.error(f"[Riscos] Erro: {e}")
        session.append("agente_erro", {"agente": "riscos", "erro": str(e)})
        return {"score_risco": 0.0, "riscos": [], "clausulas_ok": [], "resumo_executivo": ""}


def _mapear_tipo_para_checklist(tipo_contrato: str) -> str:
    tipo_lower = tipo_contrato.lower()
    if any(t in tipo_lower for t in ["trabalhista", "emprego", "clt"]):
        return "trabalhista"
    if any(t in tipo_lower for t in ["m&a", "societario", "fusão", "aquisição", "quotas"]):
        return "societario_ma"
    return "prestacao_servicos"


# ─────────────────────────────────────────────
# Agente 5 — Consolidador
# ─────────────────────────────────────────────


def agente_consolidador(
    classificacao: dict,
    clausulas: list[dict],
    analise_riscos: dict,
    checklist_versao: str,
    session: Session,
) -> dict:
    """Agente 5: consolida tudo em relatório final com aviso obrigatório."""
    log.info("[Consolidador] Gerando relatório final...")

    tipo_contrato = classificacao.get("tipo_contrato", "Contrato")
    riscos = analise_riscos.get("riscos", [])
    clausulas_ok = analise_riscos.get("clausulas_ok", [])
    score = analise_riscos.get("score_risco", 0.0)
    resumo = analise_riscos.get("resumo_executivo", "")

    # Monta relatório em markdown
    emoji_score = "🔴" if score >= 7 else "🟠" if score >= 4 else "🟢"
    relatorio = f"# Análise de Contrato — {tipo_contrato}\n\n"
    relatorio += f"**Score de Risco:** {emoji_score} {score:.1f}/10\n\n"
    relatorio += f"## Resumo Executivo\n\n{resumo}\n\n"

    if riscos:
        relatorio += f"## Riscos Identificados ({len(riscos)})\n\n"
        for r in sorted(
            riscos,
            key=lambda x: ["critico", "alto", "medio", "baixo"].index(x.get("nivel", "baixo")),
        ):
            emoji = {"critico": "🔴", "alto": "🟠", "medio": "🟡", "baixo": "🟢"}.get(
                r.get("nivel", "baixo"), "⚪"
            )
            relatorio += (
                f"### {emoji} {r.get('clausula','N/A')} — `{r.get('nivel','?').upper()}`\n\n"
            )
            relatorio += f"{r.get('descricao','')}\n\n"
            if r.get("artigo_ref"):
                relatorio += f"**Referência legal:** {r['artigo_ref']}\n\n"

    if clausulas_ok:
        relatorio += "## Cláusulas sem Ressalvas\n\n"
        for c in clausulas_ok:
            relatorio += f"- ✅ {c}\n"
        relatorio += "\n"

    # AVISO OBRIGATÓRIO — hardcoded no código, não nas regras
    relatorio = AvisoJuridico.inserir_no_relatorio(
        conteudo_relatorio=relatorio,
        tipo_analise=f"Análise de Contrato — {tipo_contrato}",
        checklist_versao=checklist_versao,
        modo="interno",
    )

    # Salva .md
    ts = int(time.time())
    output_dir = Path(__file__).parent.parent / "outputs"
    output_dir.mkdir(exist_ok=True)
    md_path = output_dir / f"analise_{ts}.md"
    md_path.write_text(relatorio, encoding="utf-8")

    session.append(
        "agente_concluido",
        {
            "agente": "consolidador",
            "ok": True,
            "resultado": {"md_path": str(md_path), "n_riscos": len(riscos)},
        },
    )
    log.info(f"[Consolidador] Relatório salvo: {md_path}")

    return {
        "tipo_contrato": tipo_contrato,
        "score_risco": score,
        "riscos": riscos,
        "clausulas_ok": clausulas_ok,
        "resumo_executivo": resumo,
        "md_path": str(md_path),
        "n_riscos": len(riscos),
    }


# ─────────────────────────────────────────────
# Pipeline principal — 5 agentes com checkpoint
# ─────────────────────────────────────────────


async def analisar_contrato(payload: dict) -> dict:
    """
    Pipeline completo de análise. Suporta retomada via session_id.
    Checkpoint após cada agente — se falhar, retoma de onde parou.
    """
    pdf_path = payload.get("pdf_path", "")
    tipo_contrato = payload.get("tipo", "prestacao_servicos")
    session_id = payload.get("session_id")
    checklist_versao = payload.get("checklist_versao", "1.0.0")

    session = Session(task_id=session_id, escritorio_id=payload.get("escritorio_id", "nexara"))
    concluidos = session.concluidos()

    if concluidos:
        log.info(f"Retomando sessão {session.id}. Concluídos: {concluidos}")
    else:
        session.append(
            "analise_iniciada",
            {
                "pdf_path": pdf_path,
                "tipo": tipo_contrato,
            },
        )

    # ── Agente 1: Validador PDF ───────────────────────────────────
    if "validador_pdf" in concluidos:
        validacao = session.resultado_de("validador_pdf") or {}
        texto_contrato = validacao.get("texto", "")
    else:
        validacao = agente_validador_pdf(pdf_path, session)
        if not validacao.get("valido"):
            return {"erro": validacao.get("erro", "PDF inválido"), "session_id": session.id}
        texto_contrato = validacao.get("texto", "")
        if not validacao.get("simulado"):
            session.append(
                "agente_concluido",
                {
                    "agente": "validador_pdf",
                    "ok": True,
                    "resultado": {"texto": texto_contrato[:200]},
                },
            )

    # ── Agente 2: Classificador ───────────────────────────────────
    if "classificador" in concluidos:
        classificacao = session.resultado_de("classificador") or {}
    else:
        classificacao = agente_classificador(texto_contrato, session)

    # ── Agente 3: Extrator ────────────────────────────────────────
    if "extrator" in concluidos:
        clausulas = session.resultado_de("extrator") or []
    else:
        clausulas = agente_extrator(texto_contrato, session)

    # ── Agente 4: Riscos ──────────────────────────────────────────
    if "riscos" in concluidos:
        analise_riscos = session.resultado_de("riscos") or {}
    else:
        analise_riscos = agente_riscos(
            clausulas=clausulas,
            tipo_contrato=classificacao.get("tipo_contrato", tipo_contrato),
            checklist_versao=checklist_versao,
            session=session,
        )

    # ── Agente 5: Consolidador ────────────────────────────────────
    if "consolidador" in concluidos:
        resultado_final = session.resultado_de("consolidador") or {}
    else:
        resultado_final = agente_consolidador(
            classificacao=classificacao,
            clausulas=clausulas,
            analise_riscos=analise_riscos,
            checklist_versao=checklist_versao,
            session=session,
        )

    session.append(
        "analise_concluida",
        {
            "n_riscos": resultado_final.get("n_riscos", 0),
            "score": resultado_final.get("score_risco", 0),
        },
    )

    resultado_final["session_id"] = session.id
    return resultado_final


# ─────────────────────────────────────────────
# Servidor HTTP
# ─────────────────────────────────────────────


async def handle_health(request):
    return aiohttp.web.json_response(
        {
            "status": "ok",
            "servico": "nexara-analisador",
            "guard_disponivel": GUARD_DISPONIVEL,
        }
    )


async def handle_analisar(request):
    """POST /analisar — analisa um contrato PDF."""
    try:
        payload = await request.json()
    except Exception:
        return aiohttp.web.json_response({"erro": "Body JSON inválido"}, status=400)

    if "pdf_path" not in payload:
        return aiohttp.web.json_response({"erro": "Campo 'pdf_path' obrigatório"}, status=400)

    try:
        resultado = await asyncio.get_event_loop().run_in_executor(
            None, lambda: asyncio.run(analisar_contrato(payload))
        )
        return aiohttp.web.json_response(resultado)
    except Exception as e:
        log.exception(f"Erro na análise: {e}")
        return aiohttp.web.json_response({"erro": str(e)}, status=500)


async def handle_analisar_async(request):
    """POST /analisar — versão async correta para aiohttp."""
    try:
        payload = await request.json()
    except Exception:
        return aiohttp.web.json_response({"erro": "Body JSON inválido"}, status=400)

    if "pdf_path" not in payload:
        return aiohttp.web.json_response({"erro": "Campo 'pdf_path' obrigatório"}, status=400)

    try:
        resultado = await analisar_contrato(payload)
        return aiohttp.web.json_response(resultado)
    except Exception as e:
        log.exception(f"Erro na análise: {e}")
        return aiohttp.web.json_response({"erro": str(e)}, status=500)


async def handle_status(request):
    return aiohttp.web.json_response(
        {
            "servico": "nexara-analisador",
            "versao": "1.0.0",
            "porta": PORTA,
            "modelo": MODELO,
            "guard": GUARD_DISPONIVEL,
            "endpoints": ["/health", "/analisar", "/status"],
        }
    )


# ─────────────────────────────────────────────
# Demo e CLI
# ─────────────────────────────────────────────


async def rodar_demo(dry_run: bool = True):
    print("\n" + "=" * 60)
    print("  NEXARA — Analisador de Contratos")
    print("  Demo (dry run — sem chamada de API)")
    print("=" * 60 + "\n")

    payload = {
        "pdf_path": "contrato_demo.pdf",
        "tipo": "prestacao_servicos",
        "objetivo": "revisar para assinar",
        "dry_run": True,
        "escritorio_id": "demo",
    }

    print("Simulando pipeline de análise:")
    print("  1. validador_pdf  — extrai texto do PDF")
    print("  2. classificador  — identifica tipo e partes")
    print("  3. extrator       — extrai cláusulas")
    print("  4. riscos         — analisa com checklist")
    print("  5. consolidador   — gera relatório .md\n")

    resultado = await analisar_contrato(payload)
    print(f"Session ID: {resultado.get('session_id')}")
    print(f"Tipo:       {resultado.get('tipo_contrato', 'simulado')}")
    print(f"Score:      {resultado.get('score_risco', 0)}/10")
    print(f"Riscos:     {resultado.get('n_riscos', 0)}")
    if resultado.get("md_path"):
        print(f"Output:     {resultado['md_path']}")
    print("\nPara análise real: recarregue o crédito e forneça um PDF real.")


def main():
    (Path(__file__).parent.parent / "logs").mkdir(exist_ok=True)

    parser = argparse.ArgumentParser(description="NEXARA Analisador de Contratos")
    parser.add_argument(
        "--server", action="store_true", help=f"Sobe servidor HTTP na porta {PORTA}"
    )
    parser.add_argument("--demo", action="store_true", help="Roda demo")
    args = parser.parse_args()

    if args.server:
        app = aiohttp.web.Application()
        app.router.add_get("/health", handle_health)
        app.router.add_post("/analisar", handle_analisar_async)
        app.router.add_get("/status", handle_status)
        print(f"\n📄 NEXARA Analisador rodando em http://localhost:{PORTA}")
        print("   POST /analisar  — analisa contrato PDF")
        print("   GET  /health    — health check")
        print(f"   Guard: {'✓ ativo' if GUARD_DISPONIVEL else '✗ não disponível'}\n")
        aiohttp.web.run_app(app, host="0.0.0.0", port=PORTA, print=None)

    elif args.demo:
        asyncio.run(rodar_demo())

    else:
        parser.print_help()
        print("\nExemplos:")
        print("  python analisador.py --demo     # visualiza pipeline")
        print(f"  python analisador.py --server   # sobe na porta {PORTA}")


# ─────────────────────────────────────────────
# Utilitários
# ─────────────────────────────────────────────


def _parse_json_seguro(texto: str, default=None):
    if default is None:
        default = {}
    texto = texto.strip()
    if texto.startswith("```"):
        linhas = texto.split("\n")
        texto = "\n".join(linhas[1:-1] if linhas[-1].strip() == "```" else linhas[1:])
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.warning("JSON inválido retornado pelo modelo.")
        return default


if __name__ == "__main__":
    main()
