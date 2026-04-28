"""
NEXARA — Servidor HTTP e CLI do Orquestrador
Versão: 1.0.0

Servidor: python orquestrador_server.py --server  (porta 8767)
Demo:     python orquestrador_server.py --demo
Demo dry: python orquestrador_server.py --demo --dry-run
"""

import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp.web

# Garante imports locais
sys.path.insert(0, str(Path(__file__).parent))
from orquestrador import OrquestradorNexara
from schemas import EntradaOrquestrador, FormatoOutput, StatusOrquestracao, TipoDemanda
from shared.config import cfg

PORTA = 8767


# ─────────────────────────────────────────────
# Handlers HTTP
# ─────────────────────────────────────────────

orquestrador = OrquestradorNexara()


async def handle_health(request):
    return aiohttp.web.json_response({"status": "ok", "servico": "nexara-orquestrador"})


async def handle_orquestrar(request):
    """
    POST /orquestrar
    Body: {
        "pdf_path": "...",
        "tipo_demanda": "trabalhista|m&a|societario|prestacao_servicos",
        "formato_output": "unificado|separados|sumario",
        "objetivo": "...",         (opcional)
        "dry_run": false           (opcional)
    }
    """
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"erro": "Body JSON inválido"}, status=400)

    # Validação dos campos obrigatórios
    campos = ["pdf_path", "tipo_demanda", "formato_output"]
    faltando = [c for c in campos if c not in body]
    if faltando:
        return aiohttp.web.json_response(
            {"erro": f"Campos obrigatórios faltando: {faltando}"}, status=400
        )

    # Parse dos enums com mensagem clara em caso de valor inválido
    try:
        tipo = TipoDemanda(body["tipo_demanda"])
        formato = FormatoOutput(body["formato_output"])
    except ValueError as e:
        return aiohttp.web.json_response({"erro": f"Valor inválido: {e}"}, status=400)

    entrada = EntradaOrquestrador(
        caminho_pdf=body["pdf_path"],
        tipo_demanda=tipo,
        formato_output=formato,
        objetivo=body.get("objetivo"),
        prazo_urgente=body.get("prazo_urgente", False),
        dry_run=body.get("dry_run", False),
    )

    estado = await orquestrador.executar(entrada)

    return aiohttp.web.json_response(
        {
            "job_id": estado.job_id,
            "status": estado.status.value,
            "outputs": estado.outputs_gerados,
            "score_risco": estado.resultado_analise.score_risco
            if estado.resultado_analise
            else None,
            "riscos_count": len(estado.resultado_analise.riscos) if estado.resultado_analise else 0,
            "pesquisas_count": len(estado.resultados_pesquisa),
            "erros": estado.erros,
            "custo_total_usd": estado.custo_total_usd,
            "duracao": _calcular_duracao(estado),
        }
    )


async def handle_status(request):
    """GET /status — informações do servidor."""
    return aiohttp.web.json_response(
        {
            "servico": "nexara-orquestrador",
            "versao": "1.0.0",
            "porta": PORTA,
            "agentes": {
                "analisador": f"http://localhost:{cfg.porta('analisador')}",
                "pesquisador": f"http://localhost:{cfg.porta('pesquisador')}",
            },
            "endpoints": ["/health", "/orquestrar", "/status"],
        }
    )


def _calcular_duracao(estado) -> str:
    if estado.inicio and estado.fim:
        from datetime import datetime

        ini = datetime.fromisoformat(estado.inicio)
        fim = datetime.fromisoformat(estado.fim)
        seg = (fim - ini).total_seconds()
        return f"{seg:.1f}s"
    return "N/A"


# ─────────────────────────────────────────────
# Demo interativo via CLI
# ─────────────────────────────────────────────


async def rodar_demo(dry_run: bool = False):
    """Demo interativo — mostra o pipeline completo no terminal."""

    print("\n" + "=" * 60)
    print("  NEXARA — Orquestrador Multi-Agente Jurídico")
    print("  Demo Interativo")
    print("=" * 60 + "\n")

    # ── Seleção do tipo de demanda ────────────────────────────────
    tipos = {
        "1": TipoDemanda.PRESTACAO_SVC,
        "2": TipoDemanda.MA,
        "3": TipoDemanda.SOCIETARIO,
        "4": TipoDemanda.TRABALHISTA,
    }
    print("Tipo de demanda:")
    print("  1. Prestação de Serviços")
    print("  2. M&A / Due Diligence")
    print("  3. Societário")
    print("  4. Trabalhista")
    escolha_tipo = input("\nEscolha [1-4]: ").strip() or "1"
    tipo = tipos.get(escolha_tipo, TipoDemanda.PRESTACAO_SVC)

    # ── Caminho do PDF ────────────────────────────────────────────
    if dry_run:
        pdf_path = "contrato_demo.pdf"
        print(f"\nDRY RUN: usando '{pdf_path}' (fictício)")
    else:
        pdf_path = input("\nCaminho do PDF: ").strip()
        if not pdf_path:
            print("❌ Caminho obrigatório.")
            return

    # ── Objetivo (opcional) ───────────────────────────────────────
    print("\nObjetivo da análise (opcional):")
    print("  Ex: revisar para assinar | due diligence | identificar passivo")
    objetivo = input("Objetivo: ").strip() or None

    # ── Formato de output ─────────────────────────────────────────
    formatos = {
        "1": FormatoOutput.UNIFICADO,
        "2": FormatoOutput.SEPARADOS,
        "3": FormatoOutput.SUMARIO_EXECUTIVO,
    }
    print("\nFormato do relatório:")
    print("  1. Relatório Unificado    — análise + jurisprudência em 1 documento")
    print("  2. Documentos Separados   — análise + pesquisa + sumário executivo")
    print("  3. Sumário Executivo      — apenas pontos críticos (1-2 páginas)")
    escolha_fmt = input("\nEscolha [1-3]: ").strip() or "1"
    formato = formatos.get(escolha_fmt, FormatoOutput.UNIFICADO)

    # ── Executar ──────────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("Iniciando orquestração...")
    print(f"  Tipo:      {tipo.value}")
    print(f"  Objetivo:  {objetivo or 'não informado'}")
    print(f"  Formato:   {formato.value}")
    print(f"  Dry run:   {dry_run}")
    print("─" * 60 + "\n")

    entrada = EntradaOrquestrador(
        caminho_pdf=pdf_path,
        tipo_demanda=tipo,
        formato_output=formato,
        objetivo=objetivo,
        dry_run=dry_run,
    )

    orch = OrquestradorNexara()
    estado = await orch.executar(entrada)

    # ── Resultado ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if estado.status == StatusOrquestracao.CONCLUIDO:
        print("  ✅ ORQUESTRAÇÃO CONCLUÍDA COM SUCESSO")
    else:
        print("  ❌ ORQUESTRAÇÃO FINALIZADA COM ERROS")
    print("=" * 60)

    print(f"\nJob ID:   {estado.job_id[:8]}")
    print(f"Duração:  {_calcular_duracao(estado)}")

    if estado.resultado_analise:
        a = estado.resultado_analise
        print(f"Contrato: {a.tipo_contrato}")
        print(f"Score:    {a.score_risco:.1f}/10")
        print(f"Riscos:   {len(a.riscos)} identificados")

    print("\nOutputs gerados:")
    for path in estado.outputs_gerados:
        print(f"  → {path}")

    if estado.erros:
        print("\nErros:")
        for e in estado.erros:
            print(f"  ⚠️  {e}")

    print()


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="NEXARA Orquestrador Multi-Agente")
    parser.add_argument("--server", action="store_true", help="Sobe servidor HTTP na porta 8767")
    parser.add_argument("--demo", action="store_true", help="Roda demo interativo")
    parser.add_argument("--dry-run", action="store_true", help="Executa sem chamar API (simulação)")
    args = parser.parse_args()

    if args.server:
        app = aiohttp.web.Application()
        app.router.add_get("/health", handle_health)
        app.router.add_post("/orquestrar", handle_orquestrar)
        app.router.add_get("/status", handle_status)
        print(f"\n🚀 NEXARA Orquestrador rodando em http://localhost:{PORTA}")
        print("   POST /orquestrar — executa pipeline completo")
        print("   GET  /health     — health check\n")
        aiohttp.web.run_app(app, host="0.0.0.0", port=PORTA, print=None)

    elif args.demo:
        asyncio.run(rodar_demo(dry_run=args.dry_run))

    else:
        parser.print_help()
        print("\nExemplos:")
        print("  python orquestrador_server.py --demo --dry-run   # testa sem API")
        print("  python orquestrador_server.py --demo             # demo com API real")
        print("  python orquestrador_server.py --server           # sobe servidor HTTP")


if __name__ == "__main__":
    main()
