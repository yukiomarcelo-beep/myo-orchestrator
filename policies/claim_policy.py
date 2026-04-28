"""
Claim Policy — Pipeline AI
Define tópicos, criticidade e palavras-chave para classificação de afirmações.

Criticidade:
 "critical" → número, benchmark, custo, concorrente: exige fonte primária
 "moderate" → demanda, tendência: pode seguir com evidência parcial
 "low" → copy, estratégia: orientação, não decisão de fato

Regra de gate:
 Qualquer claim "critical" com confiança < CRITICAL_CONFIDENCE_THRESHOLD
 ou sem fonte de qualidade suficiente → força VALIDATION_REQUIRED,
 independente do score agregado.
"""

import re
from typing import Optional

# Thresholds

CRITICAL_CONFIDENCE_THRESHOLD = 70  # abaixo disso, claim crítica bloqueia execução
MODERATE_CONFIDENCE_THRESHOLD = 50


# Tópicos e palavras-chave

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "pricing": [
        "preço",
        "ticket",
        "r$",
        "custa",
        "cobra",
        "mensalidade",
        "benchmark",
        "ltv",
        "cac",
        "roi",
        "arpu",
        "arppu",
        "revenue",
        "receita",
        "faturamento",
        "margem",
    ],
    "market_data": [
        "crescimento",
        "expansão",
        "cagr",
        "tam",
        "sam",
        "som",
        "bilhão",
        "milhão",
        "trilhão",
        "mercado vale",
        "projeção",
        "market share",
        "participação",
        "%",
        "porcentagem",
    ],
    "competitor": [
        "concorrente",
        "concorrência",
        "líder",
        "domina",
        "referência",
        "benchmark",
        "player",
        "competidor",
        "maior empresa",
        "pioneiro",
        "market leader",
    ],
    "api_cost": [
        "api",
        "token",
        "requisição",
        "por mensagem",
        "por chamada",
        "por request",
        "custo de integração",
        "custo técnico",
        "openai",
        "anthropic",
        "perplexity",
        "elevenlabs",
        "heygen",
    ],
    "demand": [
        "demanda",
        "urgência",
        "dor recorrente",
        "alta procura",
        "muito pedido",
        "necessidade real",
        "problema crítico",
    ],
    "timing": [
        "momento ideal",
        "janela de oportunidade",
        "tendência emergente",
        "agora é a hora",
        "mercado aquecido",
        "em alta",
        "growing",
    ],
    "headline_copy": [
        "headline",
        "cta",
        "copy",
        "slogan",
        "chamada principal",
        "abertura",
        "gancho",
        "hook",
        "subheadline",
    ],
    "strategy": [
        "recomendo",
        "sugiro",
        "ideal seria",
        "melhor estratégia",
        "deveríamos",
        "proposta de valor",
        "posicionamento",
    ],
}

CRITICALITY: dict[str, str] = {
    "pricing": "critical",
    "market_data": "critical",
    "competitor": "critical",
    "api_cost": "critical",
    "demand": "moderate",
    "timing": "moderate",
    "headline_copy": "low",
    "strategy": "low",
    "general": "moderate",
}

# Tópicos onde dados envelhecem rápido (exigem fonte recente)
VOLATILE_TOPICS: set[str] = {"pricing", "api_cost", "competitor", "timing", "market_data"}

# Tipos numéricos de alto risco (generalização, amostra ruim, fonte indireta)
HIGH_RISK_NUMERIC_TYPES: set[str] = {"benchmark", "forecast", "market_size"}

# Padrões numéricos que indicam afirmação quantitativa (sempre exigem atenção)
NUMERIC_PATTERN = re.compile(
    r"\b(\d[\d.,]*\s*%|\d[\d.,]*\s*(bilh|milh|mil|k\b)|r\$\s*\d|usd\s*\d|\d+x\b)",
    re.IGNORECASE,
)


# Funções públicas


def classify_topic(claim_text: str) -> str:
    """Retorna o tópico mais relevante para a afirmação."""
    text_lower = claim_text.lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return topic
    return "general"


def get_criticality(topic: str) -> str:
    return CRITICALITY.get(topic, "moderate")


def is_critical(topic: str) -> bool:
    return get_criticality(topic) == "critical"


def is_volatile(topic: str) -> bool:
    """Dado instável: preço, API, concorrente, timing."""
    return topic in VOLATILE_TOPICS


def has_numeric_claim(claim_text: str) -> bool:
    """True se a afirmação contém número, percentual ou valor monetário."""
    return bool(NUMERIC_PATTERN.search(claim_text))


# Tipo numérico

_NUMERIC_TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("price", ["r\\$", "usd", "eur", "€", "ticket", "mensalidade", "cobr", "pric"]),
    ("percentage", ["%", "porcentagem", "cagr", "crescimento", "expansão", "taxa de"]),
    ("forecast", ["projeção", "estimativa", "vai chegar", "deve atingir", "previsto"]),
    ("benchmark", ["benchmark", "média do setor", "média de mercado", "média industria"]),
    ("cost_estimate", ["custo", "investimento", "gasto", "despesa", "budget"]),
    ("market_size", ["tam", "sam", "som", "bilhão", "milhão", "trilhão", "mercado vale"]),
    ("internal_target", ["meta", "objetivo", "goal", "ods", "kpi", "target"]),
]


def numeric_claim_type(claim_text: str) -> Optional[str]:
    """
    Retorna o tipo de afirmação numérica detectada, ou None se não houver número.
    Tipos: price | percentage | forecast | benchmark | cost_estimate | market_size | internal_target | numeric
    """
    if not has_numeric_claim(claim_text):
        return None
    text_lower = claim_text.lower()
    for ntype, patterns in _NUMERIC_TYPE_PATTERNS:
        if any(re.search(p, text_lower) for p in patterns):
            return ntype
    return "numeric"  # número presente mas tipo não classificado


def confidence_threshold(topic: str) -> int:
    """Threshold mínimo de confiança aceitável para o tópico (estático, sem contexto)."""
    crit = get_criticality(topic)
    if crit == "critical":
        return CRITICAL_CONFIDENCE_THRESHOLD
    if crit == "moderate":
        return MODERATE_CONFIDENCE_THRESHOLD
    return 30


def confidence_threshold_for_context(topic: str, execution_context: str = "") -> int:
    """
    Threshold mínimo de confiança para o tópico, ajustado por contexto (6C).
    Lê config/context_policy.json se disponível.
    Fallback: comportamento estático de confidence_threshold().
    """
    if not execution_context:
        return confidence_threshold(topic)
    try:
        import json
        from pathlib import Path

        policy_file = Path(__file__).parent / "config" / "context_policy.json"
        if not policy_file.exists():
            return confidence_threshold(topic)
        with open(policy_file, encoding="utf-8") as f:
            policy = json.load(f)
        ctx_policy = policy.get(execution_context)
        if not ctx_policy:
            return confidence_threshold(topic)
        topic_thresholds = ctx_policy.get("topic_thresholds", {})
        if topic in topic_thresholds:
            return int(topic_thresholds[topic])
    except Exception:
        pass
    return confidence_threshold(topic)


def gate_thresholds_for_context(execution_context: str = "") -> dict:
    """
    Retorna os thresholds do gate de execução para o contexto (6C).
    Fallback: valores estáticos padrão.
    """
    defaults = {
        "confidence_normal": 80,
        "confidence_experiment": 60,
        "source_quality": 7.0,
        "unverified_limit": 2,
        "api_cost_strict": False,
    }
    if not execution_context:
        return defaults
    try:
        import json
        from pathlib import Path

        policy_file = Path(__file__).parent / "config" / "context_policy.json"
        if not policy_file.exists():
            return defaults
        with open(policy_file, encoding="utf-8") as f:
            policy = json.load(f)
        ctx = policy.get(execution_context)
        if not ctx:
            return defaults
        return {
            "confidence_normal": ctx.get("gate_confidence_normal", defaults["confidence_normal"]),
            "confidence_experiment": ctx.get(
                "gate_confidence_experiment", defaults["confidence_experiment"]
            ),
            "source_quality": ctx.get("gate_source_quality", defaults["source_quality"]),
            "unverified_limit": ctx.get("gate_unverified_limit", defaults["unverified_limit"]),
            "api_cost_strict": ctx.get("api_cost_strict", defaults["api_cost_strict"]),
        }
    except Exception:
        return defaults


def is_high_risk_numeric_claim(numeric_claim_type: Optional[str]) -> bool:
    """True para tipos numéricos que historicamente falham por generalização ou fonte indireta."""
    return (numeric_claim_type or "") in HIGH_RISK_NUMERIC_TYPES


def group_label(topic: str) -> str:
    """Label legível para agrupamento de validation tasks."""
    labels = {
        "pricing": "Validação de benchmark de preço",
        "market_data": "Validação de dados de mercado",
        "competitor": "Validação de concorrência",
        "api_cost": "Validação de custo técnico/API",
        "demand": "Validação de demanda real",
        "timing": "Validação de timing de mercado",
        "headline_copy": "Revisão de copy e CTA",
        "strategy": "Revisão de estratégia",
        "general": "Validação geral",
    }
    return labels.get(topic, f"Validação: {topic}")
