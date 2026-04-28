#!/usr/bin/env python3
"""
benchmark_caching.py
====================
Mede redução de custo do prompt caching do LLMGateway.

Rodada A — cache_system=False: 50 chamadas sem cache
Rodada B — cache_system=True:  50 chamadas com cache

Orçamento máximo: USD 1.50. Aborta se ultrapassar durante execução.

Uso:
    python scripts/benchmark_caching.py
"""

import os
import sys
import time
from pathlib import Path

# Garante que o root do projeto está no path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY or "sk-ant" not in ANTHROPIC_API_KEY:
    print("ERRO: ANTHROPIC_API_KEY ausente ou inválida no .env")
    sys.exit(1)

BUDGET_USD = 1.50
CALLS_PER_ROUND = 50

# ── System prompt longo (>2000 tokens) ────────────────────────────────────────
# Prompt real do papel MYO Critic+Scorer expandido com rubric detalhado.
# Mantido aqui para fins de benchmark — não alterar sem atualizar o teste.

SYSTEM_PROMPT = """
Você é o MYO Evaluator — analista sênior de oportunidades de negócio digital do sistema MYO OS.
Seu papel combina dois papéis críticos: Critic (identifica falhas) e Scorer (pontua dimensões).

════════════════════════════════════════════════════════════
PAPEL 1: CRITIC — Análise Implacável de Propostas
════════════════════════════════════════════════════════════

Sua função como Critic é identificar, sem concessões, os pontos de falha real em qualquer proposta
de negócio digital. Você não valida o que não merece validação. Você é honesto mesmo quando isso
desconforta. Seu trabalho salva o empreendedor de desperdiçar meses em ideias frágeis.

Ao analisar uma proposta, examine obrigatoriamente:

1. HIPÓTESES NÃO VALIDADAS
   - Que suposições sobre o cliente estão sendo feitas sem evidência?
   - O problema descrito foi confirmado com pessoas reais ou é especulação?
   - O modelo de preço foi testado no mercado ou é teórico?
   - A taxa de conversão assumida tem base em dados reais do segmento?

2. RISCOS DE EXECUÇÃO
   - Quão complexo é o produto mínimo viável? Pode ser lançado em 30 dias?
   - Existe dependência de parceiro, plataforma ou API que pode mudar de termos?
   - O fundador tem as competências necessárias para executar ou precisará contratar?
   - Qual é o risco regulatório (LGPD, ANS, CVM, etc.) para este segmento?

3. DINÂMICA DE MERCADO
   - Quantos concorrentes diretos existem? Têm funding? Têm vantagem de rede?
   - Por que o cliente mudaria do que já usa hoje para esta solução?
   - O mercado está crescendo, estagnado ou em declínio?
   - Há sazonalidade que afetaria a receita?

4. MODELO DE NEGÓCIO
   - O CAC (custo de aquisição) é realista para o ticket médio?
   - O LTV (lifetime value) justifica o investimento em aquisição?
   - A margem bruta é sustentável em escala?
   - Existe efeito de rede ou outro moat defensável?

5. PONTOS FATAIS
   Identifique os 2-3 pontos que, se não resolvidos, garantem o fracasso da ideia.
   Seja específico. "Mercado grande" não é um ponto fatal. "O cliente-alvo já tem 3 alternativas
   gratuitas e não há razão clara para pagar" é um ponto fatal.

════════════════════════════════════════════════════════════
PAPEL 2: SCORER — Pontuação por Dimensões
════════════════════════════════════════════════════════════

Após a análise crítica, pontue a oportunidade em 7 dimensões de 0 a 10:

DIMENSÃO 1: DOR DO CLIENTE (peso 2.0)
  0-3: Dor inexistente ou cosmética. Ninguém pagaria para resolver.
  4-6: Dor real mas não urgente. O cliente convive com ela por anos sem resolver.
  7-9: Dor significativa que o cliente tenta resolver ativamente.
  10:  Dor aguda que o cliente PRECISA resolver hoje, custe o que custar.
  Referência: "Minha empresa perde R$50k/mês por causa deste problema" = 9-10.

DIMENSÃO 2: TAMANHO DE MERCADO (peso 1.5)
  0-3: Nicho microscópico (<R$10M TAM Brasil).
  4-6: Mercado pequeno (R$10M-R$100M TAM Brasil).
  7-9: Mercado relevante (R$100M-R$1B TAM Brasil).
  10:  Mercado massivo (>R$1B TAM Brasil, crescendo >15%/ano).

DIMENSÃO 3: DIFERENCIAÇÃO (peso 1.5)
  0-3: Solução idêntica a concorrentes. Zero motivo para trocar.
  4-6: Pequenas diferenças de UX ou preço. Facilmente copiável.
  7-9: Diferenciação técnica ou de distribuição difícil de replicar.
  10:  Vantagem estrutural defensável (dados, rede, regulatório, patente).

DIMENSÃO 4: VELOCIDADE DE VALIDAÇÃO (peso 1.2)
  0-3: Requer 12+ meses e >R$500k para validar hipótese central.
  4-6: Requer 3-6 meses e R$50k-R$200k para validar.
  7-9: Pode validar em 30-90 dias com <R$30k.
  10:  Pode validar em <2 semanas com R$0 (conversas + landing page).

DIMENSÃO 5: POTENCIAL DE RECEITA (peso 1.2)
  0-3: Difícil chegar a R$100k ARR mesmo com execução perfeita.
  4-6: Potencial de R$100k-R$500k ARR em 18 meses.
  7-9: Potencial de R$500k-R$2M ARR em 18 meses.
  10:  Potencial de >R$2M ARR em 18 meses com equipe enxuta.

DIMENSÃO 6: COMPETÊNCIA DO FUNDADOR (peso 1.0)
  Avalie se o perfil descrito tem credibilidade para executar.
  0-3: Sem experiência no segmento e sem competência técnica.
  4-6: Experiência parcial. Precisará contratar papéis críticos rapidamente.
  7-9: Experiência direta no problema. Conhece o cliente de dentro.
  10:  Insider com rede estabelecida e track record comprovado no segmento.

DIMENSÃO 7: TIMING DE MERCADO (peso 0.6)
  0-3: Muito cedo (infraestrutura não existe) ou muito tarde (mercado consolidado).
  4-6: Timing neutro. Pode funcionar mas sem tailwind.
  7-9: Tendência favorável. Regulação, comportamento ou tecnologia criando janela.
  10:  Janela óbvia e urgente. "Se não fizer agora, outro fará em 6 meses."

════════════════════════════════════════════════════════════
INSTRUÇÕES DE RESPOSTA
════════════════════════════════════════════════════════════

Responda SEMPRE em JSON válido, sem markdown. Estrutura obrigatória:

{
  "verdict": "aceito" | "refinar" | "rejeitar",
  "fatal_flaws": ["falha 1", "falha 2"],
  "risks": ["risco 1", "risco 2", "risco 3"],
  "weak_assumptions": ["hipótese fraca 1", "hipótese fraca 2"],
  "strongest_point": "o que é genuinamente forte",
  "critique_summary": "resumo em 2 frases",
  "scores": {
    "dor_cliente": 0.0,
    "tamanho_mercado": 0.0,
    "diferenciacao": 0.0,
    "velocidade_validacao": 0.0,
    "potencial_receita": 0.0,
    "competencia_fundador": 0.0,
    "timing_mercado": 0.0
  },
  "score_total": 0.0,
  "recommendation": "próxima ação concreta em 1 frase"
}

Regras invioláveis:
- Nunca arredonde para cima em dimensões sem evidência explícita.
- "score_total" é a média ponderada com os pesos definidos acima.
- Se "verdict" for "rejeitar", "fatal_flaws" deve ter pelo menos 2 itens específicos.
- Se "verdict" for "aceito", "strongest_point" deve ser uma vantagem real, não genérica.
- Nunca use palavras como "potencial enorme", "mercado gigante" sem dados.
- A "recommendation" deve ser uma ação que pode ser executada em 7 dias.

════════════════════════════════════════════════════════════
EXEMPLOS CALIBRADOS — USE COMO REFERÊNCIA DE PONTUAÇÃO
════════════════════════════════════════════════════════════

EXEMPLO 1: Pontuação alta (score ~7.8)
Oportunidade: SaaS de gestão de ponto e folha para empresas de 10-50 funcionários
Raciocínio:
  dor_cliente=8.5 — multas trabalhistas são reais e frequentes neste segmento
  tamanho_mercado=7.0 — ~5M empresas neste porte no Brasil
  diferenciacao=6.0 — mercado tem players mas nenhum focado neste segmento com UX simples
  velocidade_validacao=8.0 — MVP em 30 dias com Google Sheets + WhatsApp
  potencial_receita=7.5 — R$197/mês × 500 clientes = R$100k MRR em 18 meses
  competencia_fundador=7.0 — fundador com 5 anos em RH de PME
  timing_mercado=7.0 — eSocial aumentou complexidade fiscal recentemente
  score_total = (8.5×2.0 + 7.0×1.5 + 6.0×1.5 + 8.0×1.2 + 7.5×1.2 + 7.0×1.0 + 7.0×0.6) / 9.0 ≈ 7.4
  verdict: aceito

EXEMPLO 2: Pontuação baixa (score ~3.1)
Oportunidade: Marketplace de compra e venda de usados geral (tipo OLX melhorado)
Raciocínio:
  dor_cliente=4.0 — OLX já resolve. Dor é convenção, não urgência.
  tamanho_mercado=9.0 — mercado enorme, mas irrelevante sem diferenciação
  diferenciacao=1.0 — zero diferenciação vs OLX, Enjoei, Mercado Livre
  velocidade_validacao=2.0 — escala é obrigatória para marketplace funcionar
  potencial_receita=2.0 — take rate de marketplace genérico é baixo e CAC é alto
  competencia_fundador=3.0 — sem vantagem de distribuição ou nicho
  timing_mercado=3.0 — sem tailwind específico
  score_total ≈ 3.1
  verdict: rejeitar
  fatal_flaws: ["Efeito de rede impossível de replicar sem R$50M+ de investimento",
                "OLX tem 80M de usuários ativos no Brasil — sem motivo para mudar"]

EXEMPLO 3: Pontuação média (score ~5.6) — caso para refinar
Oportunidade: App de educação financeira para universitários
Raciocínio:
  dor_cliente=6.0 — dor real mas não urgente, universitário não paga facilmente
  tamanho_mercado=6.0 — ~9M universitários no Brasil mas poder de compra baixo
  diferenciacao=4.0 — Nubank, Me Poupe!, GuiaBolso já existem
  velocidade_validacao=7.0 — landing page + conteúdo gratuito para validar
  potencial_receita=5.0 — freemium com conversão < 2% = receita limitada
  competencia_fundador=5.0 — depende do perfil
  timing_mercado=6.0 — PIX e educação financeira em alta
  score_total ≈ 5.4
  verdict: refinar
  suggested_pivots: ["Focar em universitários que já trabalham (renda > R$2k)",
                     "Modelo B2B via universidades em vez de B2C direto"]

════════════════════════════════════════════════════════════
CONTEXTO DE MERCADO BRASIL (2024-2025) — USE COMO CALIBRAÇÃO
════════════════════════════════════════════════════════════

SEGMENTOS QUENTES (tailwind claro):
  - Automação para PMEs: >6M PMEs, apenas 12% usam algum SaaS de gestão
  - Saúde digital: telemedicina cresceu 400% pós-pandemia, regulação favorável
  - Agronegócio: R$2T de PIB, digitalização acelerada, CAC via cooperativas
  - Educação profissional: desemprego técnico alto, FIES e ProUni como canais
  - Compliance fiscal: reforma tributária gerando complexidade temporária (2024-2028)

SEGMENTOS SATURADOS (evitar sem diferenciação clara):
  - E-commerce genérico: Shopify + VTEX + Tray já dominam
  - Marketplace horizontal: OLX + Mercado Livre + GetNinjas já existem
  - App de finanças pessoais: Nubank/Guia Bolso/Me Poupe bloqueiam espaço
  - Delivery de comida: iFood tem 85% do mercado e poder de destruição de preço
  - Redes sociais: custo de aquisição impossível para novo entrante

BENCHMARKS DE MERCADO BRASIL (use para validar scores):
  - CAC B2B médio SaaS: R$800-R$2.500 dependendo do ticket
  - LTV/CAC saudável: > 3x em 12 meses
  - Churn médio SaaS PME Brasil: 3-5%/mês (alto — modelo precisa compensar)
  - Ticket médio SaaS PME: R$97-R$497/mês (R$197 é ponto ideal de adoção)
  - Tempo médio de ciclo de vendas B2B PME: 2-6 semanas
  - NPS médio SaaS Brasil: 32 (abaixo de 50 é sinal de risco de churn)

ERROS COMUNS DE EMPREENDEDORES BRASILEIROS (identifique nas propostas):
  1. "Vou cobrar depois que tiver usuários" — modelo freemium sem path claro para receita
  2. "O mercado é enorme, se pegar 1% já está bom" — TAM não valida unit economics
  3. "Não tenho concorrentes" — geralmente significa que o problema não é real o suficiente
  4. "Vou crescer via indicação" — não é canal, é esperança
  5. "Precisamos de um app" — app sem tração web-first costuma ser desperdício de capital
  6. "O cliente vai adaptar o processo dele para usar nosso produto" — rarely works
  7. "Vamos internacionalizar rapidamente" — foco primeiro em PMF no Brasil

════════════════════════════════════════════════════════════
VALIDAÇÃO DE OUTPUT — CHECKLIST INTERNO
════════════════════════════════════════════════════════════

Antes de emitir a resposta, verifique internamente:
  □ "score_total" calculado com os pesos corretos (soma dos pesos = 9.0)
  □ "verdict" consistente com "score_total": rejeitar <4.5, refinar 4.5-6.5, aceito >6.5
  □ "fatal_flaws" populado com itens específicos e actionáveis, não genéricos
  □ "recommendation" é uma ação de 7 dias, não uma estratégia de 6 meses
  □ Nenhuma dimensão pontuada acima de 8.0 sem justificativa explícita no critique_summary
  □ JSON válido sem trailing commas
""".strip()

# ── Mensagens de usuário (50 variações curtas) ────────────────────────────────

USER_MESSAGES = [
    f"Avalie em 1 frase o potencial de negócio #{i+1:02d}: " + msg
    for i, msg in enumerate(
        [
            "SaaS de gestão para clínicas médicas pequenas, R$197/mês",
            "Marketplace de freelancers especializados em e-commerce",
            "App de controle financeiro para MEIs, freemium",
            "Consultoria de IA para RH de médias empresas",
            "Plataforma de cursos online para enfermeiros",
            "Ferramenta de automação para contadores, R$89/mês",
            "Delivery de marmitas fit para academias",
            "CRM simplificado para corretores de imóveis",
            "SaaS de precificação dinâmica para e-commerces",
            "Agência de marketing digital para clínicas odontológicas",
            "App de agendamento para salões de beleza",
            "Plataforma B2B de compras coletivas para restaurantes",
            "Ferramenta de gestão de obras para construtoras pequenas",
            "SaaS de compliance trabalhista para PMEs",
            "Marketplace de pet services (banho, tosa, veterinário)",
            "Plataforma de educação financeira para universitários",
            "App de rastreamento de frotas para pequenas transportadoras",
            "SaaS de laudos médicos com IA para radiologistas",
            "Ferramenta de análise de concorrentes para e-commerces",
            "Plataforma de conexão entre franqueadores e franqueados",
            "App de controle de estoque para bares e restaurantes",
            "SaaS de gestão de contratos para advogados autônomos",
            "Plataforma de cashback B2B para PMEs",
            "Ferramenta de automação de propostas comerciais",
            "App de wellness corporativo para empresas de 50-500 funcionários",
            "SaaS de gestão de manutenção preventiva para indústrias",
            "Plataforma de antecipação de recebíveis para fornecedores",
            "App de controle de gastos para times de vendas",
            "Ferramenta de onboarding digital para RH",
            "SaaS de gestão de fornecedores para redes de varejo",
            "Plataforma de treinamento online para franquias",
            "App de agendamento para clínicas de fisioterapia",
            "Ferramenta de análise de margem para distribuidoras",
            "SaaS de gestão de orçamentos para oficinas mecânicas",
            "Plataforma de comunidade para empreendedores locais",
            "App de controle de ponto para pequenas empresas",
            "Ferramenta de BI simplificado para gerentes de loja",
            "SaaS de gestão de churros e doceiros (Food Service)",
            "Plataforma de captação de doações para ONGs pequenas",
            "App de gestão de academia boutique",
            "Ferramenta de precificação para artesãos e makers",
            "SaaS de gestão de eventos corporativos",
            "Plataforma de marketplace para produtos artesanais",
            "App de controle de produção para confecções pequenas",
            "Ferramenta de gestão de clientes para personal trainers",
            "SaaS de automação fiscal para e-commerces",
            "Plataforma de mentoria entre empreendedores",
            "App de gestão de locação de equipamentos",
            "Ferramenta de análise de rentabilidade para consultores",
            "SaaS de gestão de biblioteca para escolas privadas",
        ]
    )
]

assert len(USER_MESSAGES) == CALLS_PER_ROUND, f"Esperado {CALLS_PER_ROUND} mensagens"

# ── Execução ──────────────────────────────────────────────────────────────────

from core.llm_gateway import LLMGateway  # noqa: E402


def run_round(label: str, cache_system: bool) -> dict:
    """Executa CALLS_PER_ROUND chamadas e retorna métricas agregadas."""
    gw = LLMGateway(
        api_key=ANTHROPIC_API_KEY,
        model="claude-haiku-4-5-20251001",  # haiku: mais barato, suficiente para benchmark
        failure_threshold=3,
        cooldown_secs=30.0,
    )

    total_input = 0
    total_output = 0
    total_cache_write = 0
    total_cache_read = 0
    total_cost = 0.0
    latencies = []
    accumulated_cost = 0.0

    print(f"\n{'─'*50}")
    print(f"Rodada {label} (cache_system={cache_system}) — {CALLS_PER_ROUND} chamadas")
    print(f"{'─'*50}")

    for i, msg in enumerate(USER_MESSAGES):
        resp = gw.chat(
            SYSTEM_PROMPT,
            msg,
            max_tokens=80,
            temperature=0.0,
            cache_system=cache_system,
        )
        accumulated_cost += resp.cost_usd
        total_input += resp.input_tokens
        total_output += resp.output_tokens
        total_cache_write += 0 if not hasattr(resp, "_raw_cache_write") else resp._raw_cache_write
        total_cache_read += 0  # será preenchido abaixo via recalculo
        total_cost += resp.cost_usd
        latencies.append(resp.latency_ms)

        if (i + 1) % 10 == 0:
            print(
                f"  {i+1}/{CALLS_PER_ROUND} — custo acumulado: ${accumulated_cost:.4f} | cached={resp.cached}"
            )

        if accumulated_cost > BUDGET_USD:
            print(
                f"\nABORTANDO: custo acumulado ${accumulated_cost:.4f} ultrapassou orçamento ${BUDGET_USD}"
            )
            sys.exit(1)

    latencies_sorted = sorted(latencies)
    p95_idx = int(len(latencies_sorted) * 0.95)
    p95 = latencies_sorted[p95_idx]
    avg = sum(latencies) / len(latencies)

    return {
        "label": label,
        "cache_system": cache_system,
        "total_input": total_input,
        "total_output": total_output,
        "total_cost": total_cost,
        "lat_avg": avg,
        "lat_p95": p95,
        "cached_calls": sum(1 for r in latencies if r > 0),  # proxy — veremos abaixo
    }


def run_round_v2(label: str, cache_system: bool, global_budget_tracker: list) -> dict:
    """Versão melhorada que rastreia cache_write/read corretamente via resposta completa."""
    import httpx as _httpx

    # Usa httpx diretamente para capturar os campos de usage completos
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "anthropic-beta": "prompt-caching-2024-07-31",
    }

    use_cache = cache_system and len(SYSTEM_PROMPT) >= 4096
    system_payload = (
        [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
        if use_cache
        else SYSTEM_PROMPT
    )

    total_input = 0
    total_output = 0
    total_cache_write = 0
    total_cache_read = 0
    total_cost = 0.0
    latencies = []

    print(f"\n{'─'*50}")
    print(f"Rodada {label} (cache_system={cache_system}) — {CALLS_PER_ROUND} chamadas")
    print(f"{'─'*50}")

    for i, msg in enumerate(USER_MESSAGES):
        payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 80,
            "temperature": 0.0,
            "system": system_payload,
            "messages": [{"role": "user", "content": msg}],
        }
        t0 = time.time()
        for attempt in range(5):
            with _httpx.Client(timeout=90) as c:
                resp = c.post(
                    "https://api.anthropic.com/v1/messages", json=payload, headers=headers
                )
            if resp.status_code == 429:
                wait = 2**attempt * 5  # 5, 10, 20, 40, 80s
                print(f"    [429] tentativa {attempt+1}/5 — aguardando {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        else:
            print(f"\nERRO: 429 persistente após 5 tentativas na chamada {i+1}")
            sys.exit(1)
        lat = int((time.time() - t0) * 1000)
        time.sleep(0.3)  # inter-call throttle

        u = data.get("usage", {})
        inp = u.get("input_tokens", 0)
        out = u.get("output_tokens", 0)
        cw = u.get("cache_creation_input_tokens", 0)
        cr = u.get("cache_read_input_tokens", 0)

        cost = round(inp * 3e-6 + out * 15e-6 + cw * 3.75e-6 + cr * 0.3e-6, 6)
        # haiku pricing (claude-haiku-4-5): $0.80/$4 per M tokens
        cost = round(inp * 0.8e-6 + out * 4e-6 + cw * 1.0e-6 + cr * 0.08e-6, 6)

        total_input += inp
        total_output += out
        total_cache_write += cw
        total_cache_read += cr
        total_cost += cost
        latencies.append(lat)
        global_budget_tracker[0] += cost

        if (i + 1) % 10 == 0:
            cached = cr > 0
            print(
                f"  {i+1}/{CALLS_PER_ROUND} — custo acum: ${global_budget_tracker[0]:.4f} | "
                f"inp={inp} cw={cw} cr={cr} cached={cached} lat={lat}ms"
            )

        if global_budget_tracker[0] > BUDGET_USD:
            print(
                f"\nABORTANDO: custo acumulado ${global_budget_tracker[0]:.4f} > orçamento ${BUDGET_USD}"
            )
            sys.exit(1)

    latencies_sorted = sorted(latencies)
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]
    avg = sum(latencies) / len(latencies)

    return {
        "label": label,
        "total_input": total_input,
        "total_output": total_output,
        "total_cache_write": total_cache_write,
        "total_cache_read": total_cache_read,
        "total_cost": total_cost,
        "lat_avg": round(avg),
        "lat_p95": p95,
    }


def print_table(a: dict, b: dict) -> None:
    def delta_pct(va, vb):
        if va == 0:
            return f"+{vb}" if vb > 0 else "—"
        pct = (vb - va) / va * 100
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct:.0f}%"

    def delta_abs(va, vb):
        diff = vb - va
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff}"

    rows = [
        (
            "Input tokens cobrados",
            a["total_input"],
            b["total_input"],
            delta_pct(a["total_input"], b["total_input"]),
        ),
        (
            "Cache creation tokens",
            a["total_cache_write"],
            b["total_cache_write"],
            delta_abs(a["total_cache_write"], b["total_cache_write"]),
        ),
        (
            "Cache read tokens",
            a["total_cache_read"],
            b["total_cache_read"],
            delta_abs(a["total_cache_read"], b["total_cache_read"]),
        ),
        (
            "Output tokens",
            a["total_output"],
            b["total_output"],
            delta_pct(a["total_output"], b["total_output"]),
        ),
        (
            "Custo total (USD)",
            f"${a['total_cost']:.4f}",
            f"${b['total_cost']:.4f}",
            delta_pct(a["total_cost"], b["total_cost"]),
        ),
        ("Latência média (ms)", a["lat_avg"], b["lat_avg"], delta_pct(a["lat_avg"], b["lat_avg"])),
        ("Latência p95 (ms)", a["lat_p95"], b["lat_p95"], delta_pct(a["lat_p95"], b["lat_p95"])),
    ]

    print("\n\n═══ BENCHMARK DE PROMPT CACHING ═══")
    print(f"{'Métrica':<33}| {'Sem cache':<11}| {'Com cache':<11}| Δ")
    print(f"{'-'*33}|{'-'*13}|{'-'*13}|{'-'*10}")
    for name, va, vb, d in rows:
        print(f"{name:<33}| {str(va):<11} | {str(vb):<11} | {d}")

    total = a["total_cost"] + b["total_cost"]
    print(f"\nCusto total das duas rodadas: ${total:.4f} USD")

    # Critérios de done
    cost_reduction = (
        (a["total_cost"] - b["total_cost"]) / a["total_cost"] * 100 if a["total_cost"] > 0 else 0
    )
    print("\n─── Critérios de Done ───")
    ok = "✓"
    fail = "✗"
    print(
        f"  {ok if cost_reduction >= 60 else fail} Redução de custo >= 60%:   {cost_reduction:.1f}%"
    )
    print(
        f"  {ok if b['total_cache_read'] > 0 else fail} Cache read tokens > 0:    {b['total_cache_read']}"
    )
    print(f"  {ok if total < 1.50 else fail} Custo total < USD 1.50:   ${total:.4f}")

    return a["total_cost"], b["total_cost"], total, cost_reduction


def main():
    print("═══ MYO OS — Benchmark de Prompt Caching ═══")
    print(f"System prompt: {len(SYSTEM_PROMPT)} chars / ~{len(SYSTEM_PROMPT)//4} tokens")
    print(f"Chamadas por rodada: {CALLS_PER_ROUND}")
    print(f"Orçamento máximo: ${BUDGET_USD:.2f}")

    budget = [0.0]  # mutable tracker compartilhado

    result_a = run_round_v2("A (sem cache)", cache_system=False, global_budget_tracker=budget)
    result_b = run_round_v2("B (com cache)", cache_system=True, global_budget_tracker=budget)

    cost_a, cost_b, total, reduction = print_table(result_a, result_b)
    return result_a, result_b, total


if __name__ == "__main__":
    main()
