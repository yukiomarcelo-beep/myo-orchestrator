"""
NEXARA — Orquestrador Multi-Agente Jurídico
Versão: 1.0.0

Fluxo sequencial:
  1. Sobe Analisador (8766) e Pesquisador (8765) como subprocessos
  2. Health check antes de prosseguir
  3. Envia PDF → Analisador → extrai riscos estruturados
  4. Orquestrador monta queries direcionadas pelos riscos
  5. Envia queries → Pesquisador → obtém jurisprudência + legislação
  6. Consolida em output escolhido pelo usuário (.docx)
  7. Persiste estado completo em logs/

AVISO OBRIGATÓRIO: Todo relatório gerado contém disclaimer de IA.
"""

import asyncio
import aiohttp
import fcntl
import subprocess
import logging
import json
import uuid
import os
import sys
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

from schemas import (
    EntradaOrquestrador, ResultadoAnalisador, RiscoIdentificado,
    QueryPesquisa, LoteQuerys, ResultadoPesquisa, EstadoOrquestracao,
    TipoDemanda, NivelRisco, FormatoOutput, StatusOrquestracao
)

# ─────────────────────────────────────────────
# Configuração de logging
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/orquestrador.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("nexara.orquestrador")


# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

# Lê configuração central se disponível, usa defaults como fallback
def _ler_config() -> dict:
    for p in [Path("nexara_config.json"), Path(__file__).parent.parent / "nexara_config.json"]:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}

_CFG = _ler_config()
_SVC = _CFG.get("servicos", {})

URL_ANALISADOR  = "http://{}:{}".format(_SVC.get("analisador",  {}).get("host", "localhost"), _SVC.get("analisador",  {}).get("porta", 8766))
URL_PESQUISADOR = "http://{}:{}".format(_SVC.get("pesquisador", {}).get("host", "localhost"), _SVC.get("pesquisador", {}).get("porta", 8765))
HEALTH_TIMEOUT  = 30
HEALTH_INTERVAL = 1.5
REQUEST_TIMEOUT = _SVC.get("analisador", {}).get("timeout_segundos", 120)
MAX_RETRIES     = _CFG.get("retry", {}).get("max_tentativas", 3)
RETRY_BACKOFF   = _CFG.get("retry", {}).get("espera_base_segundos", 2.0)

# Modo INTERNO: para o advogado revisar
DISCLAIMER_IA = (
    "\n\n─────────────────────────────────────────────────────────────────\n"
    "⚠️  AVISO IMPORTANTE — ANÁLISE GERADA POR INTELIGÊNCIA ARTIFICIAL\n"
    "Este relatório foi produzido com auxílio de IA (NEXARA/Claude).\n"
    "Não substitui a análise e o parecer de advogado habilitado.\n"
    "Sempre consulte um profissional antes de tomar decisões jurídicas.\n"
    "─────────────────────────────────────────────────────────────────\n"
)

# Modo CLIENTE: aviso discreto para documento entregue ao cliente
DISCLAIMER_IA_CLIENTE = (
    "\n\n---\n"
    "*Este documento foi preparado com auxílio de ferramentas tecnológicas "
    "de análise jurídica e revisado por profissional habilitado.*\n"
)


# ─────────────────────────────────────────────
# Gerenciador de subprocessos
# ─────────────────────────────────────────────

class GerenciadorSubprocessos:
    """Sobe e monitora os servidores filhos (Analisador + Pesquisador)."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self._processos: dict[str, subprocess.Popen] = {}

    def subir(self, nome: str, script: str, porta: int) -> subprocess.Popen:
        caminho = self.base_path / script
        if not caminho.exists():
            raise FileNotFoundError(f"Script não encontrado: {caminho}")

        log.info(f"Subindo {nome} em porta {porta}...")
        proc = subprocess.Popen(
            [sys.executable, str(caminho), "--server"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(caminho.parent),
        )
        self._processos[nome] = proc
        log.info(f"{nome} iniciado (PID {proc.pid})")
        return proc

    def encerrar_todos(self):
        for nome, proc in self._processos.items():
            if proc.poll() is None:
                log.info(f"Encerrando {nome} (PID {proc.pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._processos.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.encerrar_todos()


# ─────────────────────────────────────────────
# Health Check assíncrono
# ─────────────────────────────────────────────

async def aguardar_servidor(url: str, nome: str, timeout: float = HEALTH_TIMEOUT) -> bool:
    """Aguarda servidor responder em /health antes de prosseguir."""
    deadline = time.time() + timeout
    tentativa = 0

    async with aiohttp.ClientSession() as session:
        while time.time() < deadline:
            tentativa += 1
            try:
                async with session.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        log.info(f"✓ {nome} pronto após {tentativa} tentativa(s)")
                        return True
            except Exception:
                pass
            await asyncio.sleep(HEALTH_INTERVAL)

    log.error(f"✗ {nome} não respondeu em {timeout}s")
    return False


# ─────────────────────────────────────────────
# Cliente HTTP com retry + backoff
# ─────────────────────────────────────────────

async def post_com_retry(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    nome_agente: str,
) -> dict:
    """POST com retry exponencial. Levanta exceção após MAX_RETRIES falhas."""
    ultimo_erro = None

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    return await resp.json()
                corpo = await resp.text()
                raise ValueError(f"HTTP {resp.status}: {corpo[:200]}")

        except Exception as e:
            ultimo_erro = e
            espera = RETRY_BACKOFF ** tentativa
            log.warning(f"[{nome_agente}] Tentativa {tentativa}/{MAX_RETRIES} falhou: {e}. Aguardando {espera:.1f}s...")
            if tentativa < MAX_RETRIES:
                await asyncio.sleep(espera)

    raise RuntimeError(f"[{nome_agente}] Falhou após {MAX_RETRIES} tentativas. Último erro: {ultimo_erro}")


# ─────────────────────────────────────────────
# Motor de queries — coração do Orquestrador
# ─────────────────────────────────────────────

class MotorQuerys:
    """
    Transforma riscos identificados pelo Analisador em queries
    direcionadas para o Pesquisador.

    Esta é a inteligência central do Orquestrador:
    sem ela, o Pesquisador recebe queries genéricas e retorna
    resultados irrelevantes.
    """

    # Templates de query por tipo de demanda + nível de risco
    _TEMPLATES = {
        TipoDemanda.TRABALHISTA: {
            NivelRisco.CRITICO: "{clausula} {artigo_ref} TST jurisprudência recente",
            NivelRisco.ALTO:    "{clausula} CLT {artigo_ref} precedente normativo",
            NivelRisco.MEDIO:   "{clausula} CLT doutrina trabalhista",
            NivelRisco.BAIXO:   "{clausula} orientação jurisprudencial TST",
        },
        TipoDemanda.MA: {
            NivelRisco.CRITICO: "{clausula} STJ M&A sociedades responsabilidade jurisprudência",
            NivelRisco.ALTO:    "{clausula} Lei 6404 sociedades anônimas {artigo_ref}",
            NivelRisco.MEDIO:   "{clausula} Código Civil contratos empresariais",
            NivelRisco.BAIXO:   "{clausula} doutrina societária prática M&A",
        },
        TipoDemanda.SOCIETARIO: {
            NivelRisco.CRITICO: "{clausula} STJ societário quotas responsabilidade sócio",
            NivelRisco.ALTO:    "{clausula} Lei 6404 {artigo_ref} jurisprudência",
            NivelRisco.MEDIO:   "{clausula} Código Civil sociedade limitada",
            NivelRisco.BAIXO:   "{clausula} doutrina societária",
        },
        TipoDemanda.PRESTACAO_SVC: {
            NivelRisco.CRITICO: "{clausula} STJ prestação serviços inadimplemento resolução contrato",
            NivelRisco.ALTO:    "{clausula} Código Civil {artigo_ref} obrigações",
            NivelRisco.MEDIO:   "{clausula} CC2002 contratos serviços jurisprudência",
            NivelRisco.BAIXO:   "{clausula} doutrina contratual",
        },
    }
    _DEFAULT_TEMPLATE = {
        NivelRisco.CRITICO: "{clausula} STJ STF jurisprudência recente",
        NivelRisco.ALTO:    "{clausula} STJ jurisprudência aplicação",
        NivelRisco.MEDIO:   "{clausula} jurisprudência doutrina",
        NivelRisco.BAIXO:   "{clausula} orientação jurídica",
    }

    def gerar_queries(
        self,
        resultado: ResultadoAnalisador,
        tipo_demanda: TipoDemanda,
        objetivo: Optional[str],
        max_riscos: int = 5,
    ) -> LoteQuerys:
        """Gera queries estruturadas a partir dos riscos prioritários."""
        templates = self._TEMPLATES.get(tipo_demanda, self._DEFAULT_TEMPLATE)
        riscos = resultado.riscos_prioritarios(max_riscos)
        queries = []

        for risco in riscos:
            tmpl = templates.get(risco.nivel, "{clausula} jurisprudência")
            contexto = {
                "clausula":   self._extrair_tema(risco.clausula),
                "artigo_ref": risco.artigo_ref or "",
            }

            query_juris  = tmpl.format(**contexto).strip()
            query_legis  = f"{risco.artigo_ref or risco.clausula} texto legislação vigente"

            # Enriquece com objetivo se fornecido
            if objetivo:
                sufixo = self._sufixo_objetivo(objetivo)
                query_juris  += f" {sufixo}"

            risco.query_sugerida = query_juris  # feedback para rastreabilidade

            queries.append(QueryPesquisa(
                risco_origem=         risco.clausula,
                nivel_risco=          risco.nivel,
                query_jurisprudencia= query_juris,
                query_legislacao=     query_legis,
                tribunais_alvo=       self._tribunais_por_demanda(tipo_demanda),
            ))

        log.info(f"Geradas {len(queries)} queries para {len(riscos)} riscos prioritários")
        return LoteQuerys(queries=queries, tipo_demanda=tipo_demanda, objetivo=objetivo)

    def _extrair_tema(self, clausula: str) -> str:
        """Remove prefixos genéricos para isolar o tema jurídico."""
        for prefixo in ["Cláusula", "Artigo", "Art.", "§", "Item", "Seção"]:
            if clausula.startswith(prefixo):
                partes = clausula.split("—", 1)
                if len(partes) > 1:
                    return partes[1].strip()
        return clausula[:80]

    def _sufixo_objetivo(self, objetivo: str) -> str:
        mapa = {
            "assinar":       "validade execução",
            "due diligence": "passivo oculto responsabilidade",
            "rescisão":      "resolução inadimplemento",
            "negociação":    "renegociação prazo condições",
        }
        for chave, sufixo in mapa.items():
            if chave.lower() in objetivo.lower():
                return sufixo
        return ""

    def _tribunais_por_demanda(self, tipo: TipoDemanda) -> list[str]:
        mapa = {
            TipoDemanda.TRABALHISTA:   ["TST", "TRT"],
            TipoDemanda.MA:            ["STJ", "CADE", "CVM"],
            TipoDemanda.SOCIETARIO:    ["STJ", "TJSP", "TJRJ"],
            TipoDemanda.PRESTACAO_SVC: ["STJ", "TJSP"],
        }
        return mapa.get(tipo, ["STJ", "STF"])


# ─────────────────────────────────────────────
# Consolidador de outputs
# ─────────────────────────────────────────────

class Consolidador:
    """
    Gera o output final em formato escolhido pelo usuário.
    Três modos: Unificado | Separados | Sumário Executivo
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def consolidar(
        self,
        estado: EstadoOrquestracao,
        formato: FormatoOutput,
    ) -> list[str]:
        """Gera arquivos de output. Retorna lista de caminhos gerados."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_id_curto = estado.job_id[:8]
        prefixo = f"nexara_{job_id_curto}_{ts}"

        if formato == FormatoOutput.UNIFICADO:
            return self._gerar_unificado(estado, prefixo)
        elif formato == FormatoOutput.SEPARADOS:
            return self._gerar_separados(estado, prefixo)
        elif formato == FormatoOutput.SUMARIO_EXECUTIVO:
            return self._gerar_sumario(estado, prefixo)
        else:
            raise ValueError(f"Formato desconhecido: {formato}")

    def _gerar_unificado(self, estado: EstadoOrquestracao, prefixo: str) -> list[str]:
        """Um único .md com análise + jurisprudência integradas."""
        caminho = self.output_dir / f"{prefixo}_relatorio_completo.md"
        analise = estado.resultado_analise
        pesquisas = estado.resultados_pesquisa

        conteudo = self._cabecalho(estado)
        conteudo += self._secao_analise(analise)
        conteudo += self._secao_jurisprudencia_integrada(analise, pesquisas)
        conteudo += self._secao_recomendacoes(pesquisas)
        conteudo += DISCLAIMER_IA

        caminho.write_text(conteudo, encoding="utf-8")
        log.info(f"Output unificado: {caminho}")
        return [str(caminho)]

    def _gerar_separados(self, estado: EstadoOrquestracao, prefixo: str) -> list[str]:
        """Três arquivos separados + sumário."""
        saidas = []

        # 1. Análise de contrato
        c_analise = self.output_dir / f"{prefixo}_analise_contrato.md"
        txt = self._cabecalho(estado, titulo="Análise de Contrato")
        txt += self._secao_analise(estado.resultado_analise)
        txt += DISCLAIMER_IA
        c_analise.write_text(txt, encoding="utf-8")
        saidas.append(str(c_analise))

        # 2. Pesquisa jurídica
        c_pesquisa = self.output_dir / f"{prefixo}_pesquisa_juridica.md"
        txt = self._cabecalho(estado, titulo="Pesquisa Jurídica")
        txt += self._secao_jurisprudencia_integrada(
            estado.resultado_analise, estado.resultados_pesquisa
        )
        txt += DISCLAIMER_IA
        c_pesquisa.write_text(txt, encoding="utf-8")
        saidas.append(str(c_pesquisa))

        # 3. Sumário executivo
        c_sumario = self.output_dir / f"{prefixo}_sumario_executivo.md"
        txt = self._secao_sumario_executivo(estado)
        txt += DISCLAIMER_IA
        c_sumario.write_text(txt, encoding="utf-8")
        saidas.append(str(c_sumario))

        log.info(f"Outputs separados: {len(saidas)} arquivos")
        return saidas

    def _gerar_sumario(self, estado: EstadoOrquestracao, prefixo: str) -> list[str]:
        """Apenas sumário executivo — 1-2 páginas para o sócio."""
        caminho = self.output_dir / f"{prefixo}_sumario_executivo.md"
        conteudo = self._secao_sumario_executivo(estado)
        conteudo += DISCLAIMER_IA
        caminho.write_text(conteudo, encoding="utf-8")
        log.info(f"Sumário executivo: {caminho}")
        return [str(caminho)]

    # ── Blocos de conteúdo ──────────────────────────────────────────

    def _cabecalho(self, estado: EstadoOrquestracao, titulo: str = "Relatório Completo") -> str:
        entrada  = estado.entrada
        analise  = estado.resultado_analise
        score    = f"{analise.score_risco:.1f}/10" if analise else "N/A"
        tipo     = analise.tipo_contrato if analise else entrada.tipo_demanda.value

        return (
            f"# NEXARA — {titulo}\n\n"
            f"**Job ID:** `{estado.job_id}`  \n"
            f"**Data:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  \n"
            f"**Tipo de demanda:** {entrada.tipo_demanda.value.upper()}  \n"
            f"**Tipo de contrato:** {tipo}  \n"
            f"**Score de risco:** {score}  \n"
            f"**Objetivo:** {entrada.objetivo or 'Não informado'}  \n\n"
            "---\n\n"
        )

    def _secao_analise(self, analise: Optional[ResultadoAnalisador]) -> str:
        if not analise:
            return "## Análise de Contrato\n\n*Análise não disponível.*\n\n"

        txt = "## Análise de Contrato\n\n"
        txt += f"### Resumo Executivo\n\n{analise.resumo_executivo}\n\n"

        if analise.riscos:
            txt += f"### Riscos Identificados ({len(analise.riscos)})\n\n"
            for r in sorted(analise.riscos, key=lambda x: [NivelRisco.CRITICO, NivelRisco.ALTO, NivelRisco.MEDIO, NivelRisco.BAIXO].index(x.nivel)):
                emoji = {"critico": "🔴", "alto": "🟠", "medio": "🟡", "baixo": "🟢"}.get(r.nivel.value, "⚪")
                txt += f"#### {emoji} {r.clausula} — `{r.nivel.value.upper()}`\n\n"
                txt += f"{r.descricao}\n\n"
                if r.artigo_ref:
                    txt += f"**Referência legal:** {r.artigo_ref}\n\n"

        if analise.clausulas_ok:
            txt += "### Cláusulas sem Ressalvas\n\n"
            for c in analise.clausulas_ok:
                txt += f"- ✅ {c}\n"
            txt += "\n"

        return txt

    def _secao_jurisprudencia_integrada(
        self,
        analise: Optional[ResultadoAnalisador],
        pesquisas: list[ResultadoPesquisa],
    ) -> str:
        if not pesquisas:
            return "## Pesquisa Jurídica\n\n*Pesquisa não disponível.*\n\n"

        txt = "## Pesquisa Jurídica por Risco\n\n"

        # Mapa risco → pesquisa para navegação cruzada
        mapa = {p.risco_origem: p for p in pesquisas}
        riscos_ord = analise.riscos_prioritarios(len(pesquisas)) if analise else []

        for risco in riscos_ord:
            pesquisa = mapa.get(risco.clausula)
            if not pesquisa:
                continue

            emoji = {"critico": "🔴", "alto": "🟠", "medio": "🟡", "baixo": "🟢"}.get(risco.nivel.value, "⚪")
            txt += f"### {emoji} {risco.clausula}\n\n"
            txt += f"**Risco:** {risco.descricao}\n\n"

            if pesquisa.jurisprudencia:
                txt += "**Jurisprudência relevante:**\n\n"
                for j in pesquisa.jurisprudencia[:3]:
                    txt += f"- **{j.get('tribunal', 'N/A')}** — {j.get('numero', '')}\n"
                    txt += f"  > {j.get('ementa', '')[:200]}...\n\n"

            if pesquisa.legislacao:
                txt += "**Legislação aplicável:**\n\n"
                for l in pesquisa.legislacao[:2]:
                    txt += f"- {l.get('diploma', '')} — {l.get('artigo', '')}\n"
                    txt += f"  _{l.get('aplicacao', '')}_\n\n"

            if pesquisa.recomendacao:
                txt += f"**Recomendação:** {pesquisa.recomendacao}\n\n"

            txt += "---\n\n"

        return txt

    def _secao_recomendacoes(self, pesquisas: list[ResultadoPesquisa]) -> str:
        txt = "## Recomendações Consolidadas\n\n"
        for i, p in enumerate(pesquisas, 1):
            if p.recomendacao:
                txt += f"{i}. **{p.risco_origem}:** {p.recomendacao}\n\n"
        return txt

    def _secao_sumario_executivo(self, estado: EstadoOrquestracao) -> str:
        analise = estado.resultado_analise
        entrada = estado.entrada

        txt = (
            f"# NEXARA — Sumário Executivo\n\n"
            f"**Data:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  \n"
            f"**Demanda:** {entrada.tipo_demanda.value.upper()}  \n\n"
        )

        if analise:
            score  = analise.score_risco
            emoji  = "🔴" if score >= 7 else "🟠" if score >= 4 else "🟢"
            txt += f"## {emoji} Score de Risco: {score:.1f}/10\n\n"
            txt += f"{analise.resumo_executivo}\n\n"

            criticos = analise.riscos_por_nivel(NivelRisco.CRITICO)
            altos    = analise.riscos_por_nivel(NivelRisco.ALTO)

            if criticos:
                txt += f"### 🔴 Pontos Críticos ({len(criticos)})\n\n"
                for r in criticos:
                    txt += f"- **{r.clausula}:** {r.descricao[:100]}...\n"
                txt += "\n"

            if altos:
                txt += f"### 🟠 Pontos de Atenção ({len(altos)})\n\n"
                for r in altos:
                    txt += f"- **{r.clausula}:** {r.descricao[:80]}...\n"
                txt += "\n"

        txt += (
            f"**Próximos passos:** Revisar cláusulas críticas com advogado responsável "
            f"antes de qualquer assinatura ou encaminhamento.\n\n"
        )
        return txt


# ─────────────────────────────────────────────
# Orquestrador Principal
# ─────────────────────────────────────────────

class OrquestradorNexara:
    """
    Orquestrador Multi-Agente NEXARA.
    Coordena Analisador + Pesquisador em pipeline sequencial inteligente.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path    = base_path or Path(__file__).parent.parent
        self.motor_querys = MotorQuerys()
        self.consolidador = Consolidador(Path("outputs"))
        Path("logs").mkdir(exist_ok=True)
        Path("outputs").mkdir(exist_ok=True)

    async def executar(self, entrada: EntradaOrquestrador) -> EstadoOrquestracao:
        """Pipeline principal. Retorna estado completo da orquestração."""
        job_id = str(uuid.uuid4())
        estado = EstadoOrquestracao(
            job_id=job_id,
            status=StatusOrquestracao.INICIADO,
            entrada=entrada,
        )

        log.info(f"{'='*60}")
        log.info(f"NEXARA Orquestrador — Job {job_id[:8]}")
        log.info(f"Demanda: {entrada.tipo_demanda.value} | Formato: {entrada.formato_output.value}")
        log.info(f"{'='*60}")

        # Modo dry_run — simula sem chamar API
        if entrada.dry_run:
            return await self._executar_dry_run(estado)

        gerenciador = GerenciadorSubprocessos(self.base_path)
        try:
            # ── Passo 1: Subir servidores ─────────────────────────────
            gerenciador.subir("Analisador",  "nexara_analisador/analisador.py",  8766)
            gerenciador.subir("Pesquisador", "nexara_juridico/pesquisador.py",   8765)

            # ── Passo 2: Health check ─────────────────────────────────
            log.info("Aguardando servidores ficarem prontos...")
            ok_analise, ok_pesq = await asyncio.gather(
                aguardar_servidor(URL_ANALISADOR,  "Analisador"),
                aguardar_servidor(URL_PESQUISADOR, "Pesquisador"),
            )
            if not (ok_analise and ok_pesq):
                estado.registrar_erro("Servidores não responderam no tempo limite")
                return estado

            # ── Passo 3: Análise de contrato ──────────────────────────
            estado.status = StatusOrquestracao.ANALISANDO
            resultado_analise = await self._chamar_analisador(entrada)
            estado.resultado_analise = resultado_analise

            # ── Passo 4: Montar queries direcionadas ──────────────────
            queries = self.motor_querys.gerar_queries(
                resultado=resultado_analise,
                tipo_demanda=entrada.tipo_demanda,
                objetivo=entrada.objetivo,
            )
            estado.queries_geradas = queries

            # ── Passo 5: Pesquisa jurídica ────────────────────────────
            estado.status = StatusOrquestracao.PESQUISANDO
            pesquisas = await self._chamar_pesquisador(queries)
            estado.resultados_pesquisa = pesquisas

            # ── Passo 6: Consolidar output ────────────────────────────
            estado.status = StatusOrquestracao.CONSOLIDANDO
            outputs = self.consolidador.consolidar(estado, entrada.formato_output)
            estado.outputs_gerados = outputs

            # ── Passo 7: Finalizar ────────────────────────────────────
            estado.marcar_fim()
            self._persistir_log(estado)

            log.info(f"✓ Job {job_id[:8]} concluído. Outputs: {outputs}")
            return estado

        except Exception as e:
            estado.registrar_erro(str(e))
            log.exception(f"Erro no job {job_id[:8]}: {e}")
            self._persistir_log(estado)
            return estado

        finally:
            gerenciador.encerrar_todos()

    async def _chamar_analisador(self, entrada: EntradaOrquestrador) -> ResultadoAnalisador:
        """Chama o Analisador e mapeia resposta para ResultadoAnalisador."""
        payload = {
            "pdf_path":    entrada.caminho_pdf,
            "tipo":        entrada.tipo_demanda.value,
            "objetivo":    entrada.objetivo,
        }

        async with aiohttp.ClientSession() as session:
            resposta = await post_com_retry(
                session, f"{URL_ANALISADOR}/analisar", payload, "Analisador"
            )

        # Mapeamento da resposta do analisador para o schema
        riscos_raw = resposta.get("riscos", [])
        riscos = [
            RiscoIdentificado(
                clausula=r.get("clausula", "N/A"),
                descricao=r.get("descricao", ""),
                nivel=NivelRisco(r.get("nivel", "medio")),
                artigo_ref=r.get("artigo_ref"),
            )
            for r in riscos_raw
        ]

        return ResultadoAnalisador(
            tipo_contrato=    resposta.get("tipo_contrato", entrada.tipo_demanda.value),
            score_risco=      float(resposta.get("score_risco", 5.0)),
            riscos=           riscos,
            clausulas_ok=     resposta.get("clausulas_ok", []),
            resumo_executivo= resposta.get("resumo_executivo", ""),
            raw_md_path=      resposta.get("md_path"),
            raw_docx_path=    resposta.get("docx_path"),
        )

    async def _chamar_pesquisador(self, lote: LoteQuerys) -> list[ResultadoPesquisa]:
        """Chama o Pesquisador com o lote de queries e retorna resultados."""
        payload = lote.to_dict()

        async with aiohttp.ClientSession() as session:
            resposta = await post_com_retry(
                session, f"{URL_PESQUISADOR}/pesquisar_lote", payload, "Pesquisador"
            )

        resultados_raw = resposta.get("resultados", [])
        return [
            ResultadoPesquisa(
                risco_origem=   r.get("risco_origem", "N/A"),
                jurisprudencia= r.get("jurisprudencia", []),
                legislacao=     r.get("legislacao", []),
                doutrina=       r.get("doutrina", []),
                recomendacao=   r.get("recomendacao", ""),
            )
            for r in resultados_raw
        ]

    async def _executar_dry_run(self, estado: EstadoOrquestracao) -> EstadoOrquestracao:
        """
        Simula o pipeline completo sem chamar a API.
        Essencial para testar orquestração enquanto sem crédito.
        """
        log.info("🔵 MODO DRY RUN — simulando pipeline sem API")
        entrada = estado.entrada

        # Simula resultado do analisador
        await asyncio.sleep(0.5)
        estado.resultado_analise = ResultadoAnalisador(
            tipo_contrato="Contrato de Prestação de Serviços [DRY RUN]",
            score_risco=7.3,
            riscos=[
                RiscoIdentificado(
                    clausula="Cláusula 5.2 — Rescisão Antecipada",
                    descricao="Multa rescisória desproporcional sem previsão de limitação. Risco de nulidade.",
                    nivel=NivelRisco.CRITICO,
                    artigo_ref="Art. 413 CC/2002",
                ),
                RiscoIdentificado(
                    clausula="Cláusula 8.1 — Propriedade Intelectual",
                    descricao="Cessão irrestrita de IP sem contraprestação adequada.",
                    nivel=NivelRisco.ALTO,
                    artigo_ref="Art. 11 Lei 9.279/96",
                ),
                RiscoIdentificado(
                    clausula="Cláusula 3.4 — Prazo de Pagamento",
                    descricao="Prazo de 60 dias acima do padrão de mercado para este segmento.",
                    nivel=NivelRisco.MEDIO,
                    artigo_ref="Art. 394 CC/2002",
                ),
            ],
            clausulas_ok=["Cláusula 1 — Objeto", "Cláusula 2 — Vigência", "Cláusula 9 — Foro"],
            resumo_executivo=(
                "Contrato apresenta riscos relevantes nas cláusulas de rescisão e "
                "propriedade intelectual. Recomenda-se revisão antes da assinatura."
            ),
        )

        # Simula geração de queries
        await asyncio.sleep(0.3)
        estado.queries_geradas = self.motor_querys.gerar_queries(
            estado.resultado_analise, entrada.tipo_demanda, entrada.objetivo
        )

        # Simula resultado do pesquisador
        await asyncio.sleep(0.5)
        estado.resultados_pesquisa = [
            ResultadoPesquisa(
                risco_origem="Cláusula 5.2 — Rescisão Antecipada",
                jurisprudencia=[{
                    "tribunal": "STJ",
                    "numero": "REsp 1.234.567/SP",
                    "ementa": "Multa rescisória deve observar proporcionalidade. Cláusula penal excessiva admite redução equitativa.",
                    "relevancia": "alta",
                }],
                legislacao=[{
                    "diploma": "Código Civil/2002",
                    "artigo": "Art. 413",
                    "texto": "A penalidade deve ser reduzida equitativamente pelo juiz quando for manifestamente excessiva.",
                    "aplicacao": "Fundamento para pleito de redução da multa rescisória",
                }],
                doutrina=[],
                recomendacao="Negociar teto da multa rescisória em 10% do valor total do contrato.",
            ),
        ]

        # Consolida outputs
        outputs = self.consolidador.consolidar(estado, entrada.formato_output)
        estado.outputs_gerados = outputs
        estado.marcar_fim()
        self._persistir_log(estado)

        log.info(f"✓ DRY RUN concluído. Outputs gerados: {outputs}")
        return estado

    def _persistir_log(self, estado: EstadoOrquestracao):
        """Persiste estado completo em JSONL para auditoria."""
        log_path = Path("logs/orquestracoes.jsonl")
        linha = estado.to_json(indent=None) + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(linha)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        log.info(f"Estado persistido em {log_path}")
