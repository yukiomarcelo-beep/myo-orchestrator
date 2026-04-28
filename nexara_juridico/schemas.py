"""
NEXARA — Schemas de Handoff entre Agentes
Versão: 1.0.0

Define os contratos de dados entre Analisador → Orquestrador → Pesquisador.
Schema estrito evita queries vagas e garante rastreabilidade.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

# ─────────────────────────────────────────────
# Enums de domínio
# ─────────────────────────────────────────────


class TipoDemanda(str, Enum):
    MA = "m&a"
    SOCIETARIO = "societario"
    TRABALHISTA = "trabalhista"
    PRESTACAO_SVC = "prestacao_servicos"
    GENERICO = "generico"


class NivelRisco(str, Enum):
    CRITICO = "critico"
    ALTO = "alto"
    MEDIO = "medio"
    BAIXO = "baixo"


class FormatoOutput(str, Enum):
    UNIFICADO = "unificado"  # 1 .docx completo
    SEPARADOS = "separados"  # análise + jurisprudência + sumário
    SUMARIO_EXECUTIVO = "sumario"  # só sumário, 1-2 páginas


class StatusOrquestracao(str, Enum):
    INICIADO = "iniciado"
    ANALISANDO = "analisando"
    PESQUISANDO = "pesquisando"
    CONSOLIDANDO = "consolidando"
    CONCLUIDO = "concluido"
    ERRO = "erro"


# ─────────────────────────────────────────────
# Schema de entrada do Orquestrador
# ─────────────────────────────────────────────


@dataclass
class EntradaOrquestrador:
    """Contrato de entrada — o que o advogado fornece."""

    caminho_pdf: str
    tipo_demanda: TipoDemanda
    formato_output: FormatoOutput
    objetivo: Optional[str] = None  # ex: "revisar para assinar", "due diligence"
    prazo_urgente: bool = False
    dry_run: bool = False  # simula sem chamar API

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tipo_demanda"] = self.tipo_demanda.value
        d["formato_output"] = self.formato_output.value
        return d


# ─────────────────────────────────────────────
# Schema de saída do Analisador (handoff)
# ─────────────────────────────────────────────


@dataclass
class RiscoIdentificado:
    """Um risco específico extraído pelo analisador."""

    clausula: str  # ex: "Cláusula 5.2 — Rescisão"
    descricao: str  # descrição do risco em linguagem jurídica
    nivel: NivelRisco
    artigo_ref: Optional[str] = None  # ex: "Art. 473 CLT"
    query_sugerida: Optional[str] = None  # preenchida pelo orquestrador

    def to_dict(self) -> dict:
        d = asdict(self)
        d["nivel"] = self.nivel.value
        return d


@dataclass
class ResultadoAnalisador:
    """Output estruturado do Analisador → entrada para o Pesquisador."""

    tipo_contrato: str
    score_risco: float  # 0.0 a 10.0
    riscos: list[RiscoIdentificado]
    clausulas_ok: list[str]
    resumo_executivo: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_md_path: Optional[str] = None  # caminho do .md gerado
    raw_docx_path: Optional[str] = None  # caminho do .docx gerado

    def riscos_por_nivel(self, nivel: NivelRisco) -> list[RiscoIdentificado]:
        return [r for r in self.riscos if r.nivel == nivel]

    def riscos_prioritarios(self, limite: int = 5) -> list[RiscoIdentificado]:
        """Retorna riscos ordenados por criticidade para o Pesquisador."""
        ordem = [NivelRisco.CRITICO, NivelRisco.ALTO, NivelRisco.MEDIO, NivelRisco.BAIXO]
        ordenados = sorted(self.riscos, key=lambda r: ordem.index(r.nivel))
        return ordenados[:limite]

    def to_dict(self) -> dict:
        return {
            "tipo_contrato": self.tipo_contrato,
            "score_risco": self.score_risco,
            "riscos": [r.to_dict() for r in self.riscos],
            "clausulas_ok": self.clausulas_ok,
            "resumo_executivo": self.resumo_executivo,
            "timestamp": self.timestamp,
            "raw_md_path": self.raw_md_path,
            "raw_docx_path": self.raw_docx_path,
        }


# ─────────────────────────────────────────────
# Schema de queries para o Pesquisador
# ─────────────────────────────────────────────


@dataclass
class QueryPesquisa:
    """Query estruturada enviada ao Pesquisador — gerada pelo Orquestrador."""

    risco_origem: str  # referência ao risco que gerou esta query
    nivel_risco: NivelRisco
    query_jurisprudencia: str  # ex: "rescisão indireta justa causa empregador TST"
    query_legislacao: str  # ex: "Art. 483 CLT rescisão indireta"
    jurisdicao: str = "Brasil"
    tribunais_alvo: list[str] = field(default_factory=lambda: ["STJ", "TST", "STF"])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["nivel_risco"] = self.nivel_risco.value
        return d


@dataclass
class LoteQuerys:
    """Conjunto de queries enviadas ao Pesquisador em uma única chamada."""

    queries: list[QueryPesquisa]
    tipo_demanda: TipoDemanda
    objetivo: Optional[str]

    def to_dict(self) -> dict:
        return {
            "queries": [q.to_dict() for q in self.queries],
            "tipo_demanda": self.tipo_demanda.value,
            "objetivo": self.objetivo,
        }


# ─────────────────────────────────────────────
# Schema de saída do Pesquisador (handoff)
# ─────────────────────────────────────────────


@dataclass
class ResultadoPesquisa:
    """Output estruturado do Pesquisador → entrada para o Consolidador."""

    risco_origem: str
    jurisprudencia: list[dict]  # [{tribunal, numero, ementa, relevancia}]
    legislacao: list[dict]  # [{diploma, artigo, texto, aplicacao}]
    doutrina: list[dict]  # [{autor, obra, trecho, relevancia}]
    recomendacao: str  # orientação prática baseada na pesquisa
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────
# Schema de estado do Orquestrador
# ─────────────────────────────────────────────


@dataclass
class EstadoOrquestracao:
    """Estado completo da orquestração — usado para log e recovery."""

    job_id: str
    status: StatusOrquestracao
    entrada: EntradaOrquestrador
    resultado_analise: Optional[ResultadoAnalisador] = None
    queries_geradas: Optional[LoteQuerys] = None
    resultados_pesquisa: list[ResultadoPesquisa] = field(default_factory=list)
    outputs_gerados: list[str] = field(default_factory=list)  # caminhos
    erros: list[str] = field(default_factory=list)
    inicio: str = field(default_factory=lambda: datetime.now().isoformat())
    fim: Optional[str] = None
    custo_total_usd: float = 0.0

    def marcar_fim(self):
        self.fim = datetime.now().isoformat()
        self.status = StatusOrquestracao.CONCLUIDO

    def registrar_erro(self, msg: str):
        self.erros.append(f"[{datetime.now().isoformat()}] {msg}")
        self.status = StatusOrquestracao.ERRO

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "entrada": self.entrada.to_dict(),
            "resultado_analise": self.resultado_analise.to_dict()
            if self.resultado_analise
            else None,
            "queries_geradas": self.queries_geradas.to_dict() if self.queries_geradas else None,
            "resultados_pesquisa": [r.to_dict() for r in self.resultados_pesquisa],
            "outputs_gerados": self.outputs_gerados,
            "erros": self.erros,
            "inicio": self.inicio,
            "fim": self.fim,
            "custo_total_usd": self.custo_total_usd,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
