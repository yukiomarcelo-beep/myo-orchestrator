"""
Ciclo final pré-6C — geração de amostra representativa.

Garante:
 - contexts variados: research, idea, mvp, launch_ready
 - engines variados: autonomous_agent, product_engine
 - tópicos críticos: benchmark, api_cost, competitor, market_data
 - casos difíceis (números, comparações, preços)
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.verification_engine import VerificationEngine

engine = VerificationEngine()

# Corpus representativo
# Cada entrada: (texto, context, origin_engine, entity_id)
SAMPLES = [
    # RESEARCH × autonomous_agent (benchmark + market_data)
    (
        """
 O mercado de CFO Digital para MEI cresce 35% ao ano.
 O ticket médio dos concorrentes diretos é de R$ 197 a R$ 397.
 A Conta Azul domina com 40% de market share no segmento de gestão financeira para pequenas empresas.
 Existe uma janela de oportunidade clara antes de 2026 para produtos de ticket alto.
 """,
        "research",
        "autonomous_agent",
        "cfo_digital_research_1",
    ),
    (
        """
 O custo por token da API da Anthropic para Claude Sonnet é de $3 por 1M tokens de input.
 O HeyGen cobra entre $24 e $144/mês dependendo do plano.
 O ElevenLabs tem custo de $0.30 por 1000 caracteres no plano Creator.
 Integrar os 3 eleva o custo variável para aproximadamente R$ 4,50 por usuário/mês.
 """,
        "research",
        "autonomous_agent",
        "api_cost_research_1",
    ),
    (
        """
 O Notion domina o mercado de ferramentas de produtividade com 20 milhões de usuários.
 O Roam Research perdeu tração depois do pico em 2021.
 A Obsidian cresce 60% ao ano em usuários pagantes.
 O mercado de PKM vale aproximadamente USD 1,2 bilhão e deve dobrar até 2028.
 """,
        "research",
        "autonomous_agent",
        "pkm_market_research",
    ),
    (
        """
 Cursos online de Excel para MEI têm ticket médio de R$ 97 a R$ 297.
 A Hotmart representa 70% das vendas de info-produtos no Brasil.
 A taxa de conclusão média de cursos online é de 12%.
 Existe alta demanda por soluções financeiras simples para autônomos.
 """,
        "research",
        "product_engine",
        "excel_mei_research",
    ),
    # IDEA × autonomous_agent (demand + timing)
    (
        """
 Existe uma oportunidade real em automação de follow-up para coaches.
 O mercado de coaching cresce 20% ao ano no Brasil.
 A maioria dos coaches perde leads por falta de follow-up sistemático.
 Um produto de R$ 197/mês resolveria esse problema com boa margem.
 """,
        "idea",
        "autonomous_agent",
        "coach_followup_idea",
    ),
    (
        """
 Ferramentas de geração de conteúdo com IA estão em alta no Brasil.
 O interesse por "IA para Instagram" cresceu 400% no último ano.
 Existe espaço para um produto focado em criadores de conteúdo de nicho.
 O benchmark de engajamento para conteúdo de IA é de 3x acima da média.
 """,
        "idea",
        "autonomous_agent",
        "ai_content_idea",
    ),
    (
        """
 Serviços de assessoria financeira para pessoas físicas têm ticket de R$ 500 a R$ 3.000/mês.
 O mercado de wealth management para classe média brasileira está subatendido.
 Uma solução digital poderia atender 10x mais clientes com o mesmo custo.
 O custo de API para esse produto ficaria em torno de R$ 0,80 por sessão de usuário.
 """,
        "idea",
        "product_engine",
        "wealth_management_idea",
    ),
    (
        """
 O mercado de educação financeira no Brasil vale R$ 2 bilhões.
 Menos de 5% dos brasileiros investem na bolsa.
 Existe oportunidade para cursos de investimento para iniciantes com ticket de R$ 297.
 Os concorrentes cobram entre R$ 197 e R$ 997 por cursos equivalentes.
 """,
        "idea",
        "product_engine",
        "fin_edu_idea",
    ),
    # MVP × product_engine (benchmark + competitor)
    (
        """
 O CFO Digital versão MVP tem custo de API de R$ 2,10 por usuário/mês.
 O ticket de R$ 97/mês gera margem de 78% descontados custos variáveis.
 Concorrentes equivalentes cobram R$ 149 a R$ 249/mês.
 O NPS médio de produtos SaaS para MEI é de 42.
 """,
        "mvp",
        "product_engine",
        "cfo_digital_mvp",
    ),
    (
        """
 O pipeline atual converte 8% dos leads em clientes pagantes.
 O benchmark de conversão para SaaS B2C no Brasil é de 3% a 12%.
 O CAC atual está em R$ 180 e o LTV projetado é de R$ 1.164.
 A razão LTV/CAC de 6,5x está acima do benchmark saudável de 3x.
 """,
        "mvp",
        "product_engine",
        "saas_metrics_mvp",
    ),
    (
        """
 A taxa de churn mensal do produto está em 4,2%.
 O benchmark de churn para SaaS de ticket baixo é de 3% a 7%.
 O custo de retenção por cliente é de R$ 25/mês entre suporte e automações.
 O produto está dentro da faixa aceitável para essa fase.
 """,
        "mvp",
        "autonomous_agent",
        "churn_mvp",
    ),
    (
        """
 O custo de aquisição via Meta Ads está em R$ 12 por lead qualificado.
 O Google Ads tem CPC médio de R$ 3,50 para palavras-chave de gestão financeira.
 O benchmark de CAC para SaaS brasileiro de ticket R$ 97 é de R$ 120 a R$ 200.
 O funil atual está performando dentro do esperado.
 """,
        "mvp",
        "autonomous_agent",
        "ads_mvp",
    ),
    # LAUNCH_READY × product_engine (pricing + market_data)
    (
        """
 O produto está pronto para escalar com ticket de R$ 197/mês.
 O mercado-alvo de MEIs com faturamento acima de R$ 10k/mês tem 1,2 milhões de empresas.
 O benchmark de ticket para ferramentas de gestão financeira para PME é de R$ 149 a R$ 499.
 A margem líquida projetada para 500 usuários é de 62%.
 """,
        "launch_ready",
        "product_engine",
        "cfo_digital_launch",
    ),
    (
        """
 O custo técnico total com IA (Claude + HeyGen + ElevenLabs) é de R$ 8,30 por usuário/mês.
 O plano de R$ 197/mês cobre os custos variáveis com margem de 96%.
 O plano de R$ 97/mês gera margem negativa se o uso médio de API ultrapassar R$ 4,50.
 A estratégia de pricing está correta para lançamento.
 """,
        "launch_ready",
        "product_engine",
        "pricing_launch",
    ),
    (
        """
 O funil de vendas atual tem taxa de conversão de 9,5% de lead para cliente.
 O benchmark de funil de vendas para produtos digitais é de 5% a 15%.
 A taxa de recompra esperada para o segundo mês é de 88%.
 O produto está dentro da faixa saudável para lançamento.
 """,
        "launch_ready",
        "autonomous_agent",
        "funnel_launch",
    ),
    (
        """
 O mercado de SaaS para pequenas empresas no Brasil cresce 28% ao ano.
 Os 3 principais concorrentes têm ticket médio de R$ 230/mês e NPS abaixo de 35.
 O posicionamento de R$ 197 com NPS acima de 60 é diferenciado.
 Existe janela de 12 meses antes da consolidação do segmento.
 """,
        "launch_ready",
        "autonomous_agent",
        "market_position_launch",
    ),
]


async def run():
    print(f"\n{''*64}")
    print(f" CICLO FINAL PRÉ-6C — {len(SAMPLES)} amostras")
    print(f"{''*64}\n")

    for i, (text, ctx, origin, entity) in enumerate(SAMPLES, 1):
        print(f"\n[{i:02d}/{len(SAMPLES)}] engine={origin} | context={ctx} | entity={entity}")
    try:
        await engine.verify(
            text=text.strip(),
            context=f"Análise de {entity} — estágio: {ctx}",
            origin_engine=origin,
            entity_id=entity,
            execution_context=ctx,
        )
    except Exception as e:
        print(f" ERRO: {e}")

    print(f"\n{''*64}")
    print(" Ciclo concluído. Rode agora:")
    print(" python3 trust_aggregator.py && python3 trust_feedback_engine.py")
    print(f"{''*64}\n")


if __name__ == "__main__":
    asyncio.run(run())
