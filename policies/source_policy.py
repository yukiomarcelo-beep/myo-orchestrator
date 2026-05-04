"""
Source Policy — Pipeline AI
Converte tipo de fonte em score de qualidade (1–10) e define mínimos por criticidade.

Escala de qualidade:
 9–10 fonte primária: dados oficiais, pesquisa própria, documentação oficial
 7–8 relatório setorial reconhecido, publicação acadêmica ou de imprensa confiável
 5–6 agregador com metodologia clara, site especializado
 3–4 blog, newsletter, conteúdo editorial sem dados primários
 1–2 rede social, fórum, conteúdo sem autor claro, AI-generated sem referência

Regras de frescor (staleness):
 Para tópicos voláteis (pricing, api_cost, competitor, timing),
 fontes com mais de 6 meses reduzem 2 pontos no score.
 Fontes sem data explícita reduzem 1 ponto.
"""

from datetime import datetime, timezone
from typing import Optional

# Fontes confiáveis para tópicos de custo técnico/API
# "oficial" foi estreito demais — expandido para cobrir casos reais válidos

TRUSTED_API_SOURCES: set[str] = {
    "primary",  # dado direto da própria fonte
    "official_docs",  # documentação oficial do provedor
    "vendor_pricing",  # pricing page oficial
    "trusted_partner_docs",  # documentação de parceiro com link verificável
    "industry_report",  # relatório setorial com metodologia clara
}

# Score base por tipo de fonte (usa strings para evitar import circular)

BASE_QUALITY: dict[str, int] = {
    "primary": 9,  # dado oficial, pesquisa própria
    "industry_report": 8,  # relatório setorial (Gartner, Forrester, etc.)
    "recognized_publication": 7,  # G1, Valor, TechCrunch, Harvard BR
    "aggregator": 5,  # SimilarWeb, Statista sem primária clara
    "blog": 4,  # blog, newsletter editorial
    "social": 2,  # Twitter, LinkedIn, Reddit
    "ai_generated": 3,  # output de IA sem referência de fonte
    "unknown": 2,  # sem identificação de origem
}

# Qualidade mínima exigida por criticidade

MIN_QUALITY: dict[str, int] = {
    "critical": 7,  # pricing, market_data, competitor, api_cost
    "moderate": 5,  # demand, timing
    "low": 3,  # headline_copy, strategy
}

# Funções públicas


def base_score(source_type: str) -> int:
    """Score base para o tipo de fonte."""
    return BASE_QUALITY.get(source_type, 2)


def adjusted_score(
    source_type: str,
    date_str: Optional[str] = None,
    is_volatile_topic: bool = False,
) -> int:
    """
    Score ajustado por frescor da fonte.
    Penalidades:
    - fonte sem data: -1
    - fonte com mais de 6 meses em tópico volátil: -2
    - fonte com mais de 18 meses em qualquer tópico: -1
    """
    score = base_score(source_type)
    penalty = 0

    if date_str is None:
        penalty += 1  # sem data declarada
    else:
        try:
            pub = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            age_months = (datetime.now(timezone.utc) - pub).days / 30
            if is_volatile_topic and age_months > 6:
                penalty += 3  # tópico volátil + fonte velha = penalidade forte
            elif age_months > 18:
                penalty += 1
        except ValueError:
            penalty += 1  # data malformada

    return max(1, score - penalty)


def meets_minimum(score: int, criticality: str) -> bool:
    """True se o score da fonte atende ao mínimo para a criticidade."""
    return score >= MIN_QUALITY.get(criticality, 5)


def score_from_label(label: str) -> int:
    """
    Converte rótulo textual (ex: "blog", "primary") em score.
    Útil quando a fonte vem como string livre do Claude.
    """
    label = label.lower().strip()
    if label in BASE_QUALITY:
        return BASE_QUALITY[label]

    # Heurística por palavras-chave no label
    if any(k in label for k in ["official", "oficial", "gov", "primary", "primary"]):
        return 9
    if any(k in label for k in ["report", "relatório", "research", "study", "gartner"]):
        return 8
    if any(k in label for k in ["techcrunch", "valor econômico", "reuters", "forbes"]):
        return 7
    if any(k in label for k in ["statista", "similarweb", "aggregate"]):
        return 5
    if any(k in label for k in ["blog", "medium", "substack", "newsletter"]):
        return 4
    if any(k in label for k in ["twitter", "linkedin", "reddit", "social"]):
        return 2
    if any(k in label for k in ["ai", "gpt", "claude", "generated"]):
        return 3

    return 2  # desconhecido


def aggregate_quality(scores: list[int]) -> float:
    """Média simples dos scores de fonte. Retorna 4.0 se lista vazia."""
    if not scores:
        return 4.0
    return round(sum(scores) / len(scores), 1)
