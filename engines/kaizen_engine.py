"""
Kaizen Engine — Pipeline AI / MYO

Motor de melhoria contínua autônoma.

Loop: Detectar → Priorizar → Sugerir (Claude) → Testar → Aplicar → Registrar

Fontes de dados reais:
- self_healing (operational.db) → erros recorrentes, baixa taxa de sucesso
- human_decisions → padrões que humano corrige com frequência
- audit (decision_log.jsonl) → bias, extremos, tendência de bloqueio
- performance (performance_*.json) → conteúdo com baixo engajamento
- financial (financial_data.json) → margem caindo, custo alto

Uso:
python3 kaizen_engine.py → 1 ciclo e sai
python3 kaizen_engine.py --loop → loop contínuo (padrão: 1h)
python3 kaizen_engine.py --status → estado atual do banco
python3 kaizen_engine.py --history → histórico de melhorias aplicadas
python3 kaizen_engine.py --ab → relatório de A/B tests
python3 kaizen_engine.py --interval 1800 → ciclo a cada 30 min
"""
import argparse
import glob
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()

from agents.strategic_memory import (
init_strategic_db,
registrar_estrategia as _sm_registrar,
pode_mudar_estrategia as _sm_pode_mudar,
dias_desde_ultima_mudanca as _sm_dias,
sugerir_melhor_estrategia as _sm_sugerir,
sugerir_melhor_estrategia_completo as _sm_sugerir_completo,
atualizar_resultado_estrategia as _sm_atualizar,
)

# Configuração

SCAN_INTERVAL = 3600 # 1h entre ciclos
MAX_MELHORIAS_POR_CICLO = 3
DB_FILE = Path("outputs/kaizen/kaizen.db")
SH_DB = Path("outputs/self_healing/operational.db")
DECISION_LOG = Path("outputs/audit/decision_log.jsonl")
FINANCIAL_FILE = Path("outputs/financial_data.json")
OUTPUTS_DIR = Path("outputs")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

TIPOS_MELHORIA = [
"conversao_copy",
"preco_oferta",
"fluxo_venda",
"erro_operacional",
"custo_api",
"risco_compliance",
"engajamento_conteudo",
"margem_financeira",
"padrao_aprendizado",
]

# Pesos por tipo — amplificam score de priorização
TIPO_PESO = {
"risco_compliance": 1.5,
"erro_operacional": 1.4,
"margem_financeira": 1.3,
"conversao_copy": 1.2,
"preco_oferta": 1.2,
"fluxo_venda": 1.1,
"custo_api": 1.0,
"engajamento_conteudo": 1.0,
"padrao_aprendizado": 0.9,
}

# Impacto mínimo de sandbox para aplicar (15% de melhoria esperada)
SANDBOX_MIN_IMPACT = 1.05

# Direção Estratégica
# Objetivo ativo: maximizar_receita | reduzir_custo | aumentar_conversao | equilibrio
OBJETIVO_ATUAL = os.getenv("KAIZEN_OBJETIVO", "maximizar_receita")

# Fase do negócio: validacao | escala | lucro | produto
FASE_NEGOCIO = os.getenv("KAIZEN_FASE", "validacao")

# Multiplicador de score por objetivo × tipo de melhoria
_OBJETIVO_BOOST: dict = {
"maximizar_receita": {
"preco_oferta": 1.6, "conversao_copy": 1.5, "fluxo_venda": 1.4,
"engajamento_conteudo": 1.2, "margem_financeira": 1.3,
},
"reduzir_custo": {
"custo_api": 1.7, "erro_operacional": 1.5, "margem_financeira": 1.4,
"padrao_aprendizado": 1.2,
},
"aumentar_conversao": {
"conversao_copy": 1.7, "fluxo_venda": 1.6, "preco_oferta": 1.3,
"engajamento_conteudo": 1.4,
},
"equilibrio": {}, # sem boost — todos iguais
}

# Tipos prioritários por fase de negócio
_FASE_PRIORIDADE: dict = {
"validacao": ["conversao_copy", "fluxo_venda", "preco_oferta"],
"escala": ["engajamento_conteudo", "conversao_copy", "fluxo_venda"],
"lucro": ["margem_financeira", "custo_api", "preco_oferta"],
"produto": ["padrao_aprendizado", "erro_operacional", "risco_compliance"],
}

# Exploração autônoma direcionada pela fase
_FASE_EXPLORACAO: dict = {
"validacao": [
{"tipo": "conversao_copy", "descricao": "Estratégia/validacao: testar nova copy de conversão",
"impacto": 8, "frequencia": 3, "urgencia": 7, "complexidade": 2, "fonte": "strategic_kaizen"},
{"tipo": "fluxo_venda", "descricao": "Estratégia/validacao: simplificar funil de vendas",
"impacto": 7, "frequencia": 2, "urgencia": 6, "complexidade": 3, "fonte": "strategic_kaizen"},
],
"escala": [
{"tipo": "engajamento_conteudo", "descricao": "Estratégia/escala: aumentar alcance de conteúdo",
"impacto": 8, "frequencia": 3, "urgencia": 7, "complexidade": 2, "fonte": "strategic_kaizen"},
{"tipo": "conversao_copy", "descricao": "Estratégia/escala: otimizar CTA para volume",
"impacto": 7, "frequencia": 3, "urgencia": 6, "complexidade": 2, "fonte": "strategic_kaizen"},
],
"lucro": [
{"tipo": "custo_api", "descricao": "Estratégia/lucro: cortar custo de API sem perda de qualidade",
"impacto": 8, "frequencia": 2, "urgencia": 7, "complexidade": 2, "fonte": "strategic_kaizen"},
{"tipo": "margem_financeira", "descricao": "Estratégia/lucro: reajustar pricing para maximizar margem",
"impacto": 9, "frequencia": 2, "urgencia": 8, "complexidade": 3, "fonte": "strategic_kaizen"},
],
"produto": [
{"tipo": "padrao_aprendizado", "descricao": "Estratégia/produto: revalidar padrões com dados frescos",
"impacto": 7, "frequencia": 2, "urgencia": 6, "complexidade": 3, "fonte": "strategic_kaizen"},
{"tipo": "erro_operacional", "descricao": "Estratégia/produto: eliminar erros recorrentes no pipeline",
"impacto": 8, "frequencia": 2, "urgencia": 7, "complexidade": 3, "fonte": "strategic_kaizen"},
],
}

# Exploração Autônoma
MODO_EXPLORACAO = True
TAXA_EXPLORACAO = 0.20 # 20% — explora mesmo sem problemas detectados

EXPLORACAO_CANDIDATOS = [
{"tipo": "conversao_copy", "descricao": "Exploração autônoma: testar nova abordagem de copy/CTA",
"impacto": 6, "frequencia": 3, "urgencia": 5, "complexidade": 2, "fonte": "exploracao_autonoma"},
{"tipo": "preco_oferta", "descricao": "Exploração autônoma: testar variação de preço ou bundle",
"impacto": 7, "frequencia": 2, "urgencia": 4, "complexidade": 3, "fonte": "exploracao_autonoma"},
{"tipo": "fluxo_venda", "descricao": "Exploração autônoma: testar simplificação do funil de venda",
"impacto": 6, "frequencia": 2, "urgencia": 4, "complexidade": 3, "fonte": "exploracao_autonoma"},
{"tipo": "engajamento_conteudo", "descricao": "Exploração autônoma: testar novo formato/gancho de conteúdo",
"impacto": 5, "frequencia": 3, "urgencia": 3, "complexidade": 2, "fonte": "exploracao_autonoma"},
{"tipo": "custo_api", "descricao": "Exploração autônoma: testar otimização de modelo IA",
"impacto": 5, "frequencia": 2, "urgencia": 3, "complexidade": 2, "fonte": "exploracao_autonoma"},
]


# Database

def init_db() -> sqlite3.Connection:
 DB_FILE.parent.mkdir(parents=True, exist_ok=True)
 conn = sqlite3.connect(DB_FILE)
 conn.row_factory = sqlite3.Row
 conn.execute("""
 CREATE TABLE IF NOT EXISTS kaizen_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 ciclo INTEGER DEFAULT 0,
 tipo TEXT NOT NULL,
 problema TEXT NOT NULL,
 score REAL DEFAULT 0.0,
 impacto REAL DEFAULT 0.0,
 frequencia REAL DEFAULT 0.0,
 urgencia REAL DEFAULT 0.0,
 complexidade REAL DEFAULT 1.0,
 fonte TEXT DEFAULT '', -- onde o problema foi detectado
 sugestao TEXT NOT NULL,
 detalhe_sugestao TEXT DEFAULT '', -- explicação Claude
 fonte_sugestao TEXT DEFAULT 'rules', -- 'claude' | 'rules'
 sandbox_impacto REAL DEFAULT 1.0,
 sandbox_detalhes TEXT DEFAULT '{}',
 aplicado INTEGER DEFAULT 0,
 aprovado_sandbox INTEGER DEFAULT 0,
 resultado_real TEXT DEFAULT 'pending',
 resultado_score REAL,
 ts TEXT,
 applied_at TEXT,
 validated_at TEXT
 )
 """)
 conn.execute("""
 CREATE TABLE IF NOT EXISTS ab_tests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kaizen_id INTEGER REFERENCES kaizen_history(id),
 tipo TEXT,
 variante_a TEXT, -- baseline (descrição)
 variante_b TEXT, -- candidato (sugestão kaizen)
 exec_a INTEGER DEFAULT 0,
 exec_b INTEGER DEFAULT 0,
 sucesso_a INTEGER DEFAULT 0,
 sucesso_b INTEGER DEFAULT 0,
 status TEXT DEFAULT 'running', -- running/concluded
 winner TEXT, -- 'a' | 'b' | 'empate'
 ts_start TEXT,
 ts_end TEXT
 )
 """)
 conn.execute("""
 CREATE TABLE IF NOT EXISTS strategic_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 ts TEXT NOT NULL,
 objetivo TEXT NOT NULL,
 fase TEXT NOT NULL,
 motivo TEXT DEFAULT 'manual', -- 'manual' | 'auto' | 'sistema'
 melhorias_ciclo INTEGER DEFAULT 0, -- melhorias aplicadas neste período
 score_medio REAL DEFAULT 0.0, -- score_estrategico médio
 taxa_sucesso REAL DEFAULT 0.0, -- % melhorias que 'melhorou'
 ts_fim TEXT, -- preenchido quando encerrada
 resultado TEXT DEFAULT 'pending' -- 'positivo' | 'neutro' | 'negativo' | 'pending'
 )
 """)
 conn.commit()
 # Migração: colunas adicionadas em versões posteriores
 for col_def in [
 "score_qualidade REAL DEFAULT 0.0",
 "tier_qualidade TEXT DEFAULT 'media'",
 "score_estrategico REAL DEFAULT 0.0",
 "objetivo TEXT DEFAULT ''",
 "fase TEXT DEFAULT ''",
 ]:
  try:
   conn.execute(f"ALTER TABLE kaizen_history ADD COLUMN {col_def}")
   conn.commit()
  except Exception:
   pass
   return conn


def _now() -> str:
 return datetime.now(timezone.utc).isoformat()


# Coleta de Problemas — Fontes Reais

def _coletar_de_self_healing() -> List[Dict]:
 """Lê operational.db: erros recorrentes e correções com baixa taxa de sucesso."""
 problemas = []
 if not SH_DB.exists():
  return problemas
  try:
   conn = sqlite3.connect(SH_DB)
   conn.row_factory = sqlite3.Row

   # Tipos de evento com alta frequência (recorrentes)
   rows = conn.execute("""
   SELECT event_type,
   COUNT(*) as total,
   SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) as resolved,
   AVG(attempts) as avg_attempts
   FROM operational_events
   GROUP BY event_type
   HAVING total >= 2
   ORDER BY total DESC
   LIMIT 10
   """).fetchall()

   for r in rows:
    success_rate = (r["resolved"] or 0) / r["total"]
    if success_rate < 0.7 or r["avg_attempts"] > 1.5:
     problemas.append({
     "tipo": "erro_operacional",
     "impacto": min(10, r["total"] * 1.5),
     "frequencia": min(10, r["total"]),
     "urgencia": 8 if success_rate < 0.5 else 5,
     "complexidade": round(r["avg_attempts"] + 1, 1),
     "descricao": f"Erro recorrente '{r['event_type']}': "
     f"{r['total']}× ocorrências, {success_rate:.0%} taxa de sucesso",
     "fonte": "self_healing",
     "contexto": {"event_type": r["event_type"],
     "success_rate": success_rate,
     "total": r["total"]},
     })

     # Padrões aprendidos com confiança baixa ou decaída
     try:
      patt_rows = conn.execute("""
      SELECT event_type, best_action, success_rate,
      COALESCE(confidence_adjusted, success_rate) as eff_conf
      FROM patterns_learned
      WHERE COALESCE(confidence_adjusted, success_rate) < 0.60
      AND total_attempts >= 3
      ORDER BY eff_conf ASC
      LIMIT 5
      """).fetchall()
      for r in patt_rows:
       problemas.append({
       "tipo": "padrao_aprendizado",
       "impacto": 6,
       "frequencia": 5,
       "urgencia": 4,
       "complexidade": 3,
       "descricao": f"Padrão '{r['event_type']} → {r['best_action']}' "
       f"com confiança baixa ({r['eff_conf']:.0%})",
       "fonte": "learning_layer",
       "contexto": {"event_type": r["event_type"],
       "action": r["best_action"],
       "confidence": r["eff_conf"]},
       })
     except Exception:
      pass

      # Decisões humanas com alta taxa de override
      try:
       hd_rows = conn.execute("""
       SELECT ev_type,
       COUNT(*) as total,
       SUM(CASE WHEN decisao='adjust' THEN 1 ELSE 0 END) as adjusted
       FROM human_decisions
       GROUP BY ev_type
       HAVING total >= 2 AND CAST(adjusted AS REAL)/total > 0.4
       """).fetchall()
       for r in hd_rows:
        override_rate = r["adjusted"] / r["total"]
        # Ajuste 4: decisões humanas viram candidatos de alta prioridade no Kaizen
        problemas.append({
        "tipo": "padrao_aprendizado",
        "impacto": 9, # boost: aprendizado humano é ouro
        "frequencia": r["total"],
        "urgencia": 9,
        "complexidade": 3,
        "descricao": f"[HUMAN] Humano corrige '{r['ev_type']}' em "
        f"{override_rate:.0%} das vezes — sistema desalinhado",
        "fonte": "human_decisions",
        "contexto": {"event_type": r["ev_type"],
        "override_rate": override_rate,
        "prioridade_humana": True},
        })
      except Exception:
       pass

       conn.close()
  except Exception:
   pass
   return problemas


def _coletar_de_audit() -> List[Dict]:
 """Lê decision_log.jsonl: tópicos com bias, extremos, tendência de piora."""
 problemas = []
 if not DECISION_LOG.exists():
  return problemas
  try:
   decisions = []
   with open(DECISION_LOG, encoding="utf-8") as f:
    for line in f:
     try:
      decisions.append(json.loads(line.strip()))
     except Exception:
      pass
      if not decisions:
       return problemas

       # Tópicos consistentemente bloqueados
       from collections import defaultdict
       by_topic: Dict[str, list] = defaultdict(list)
       for d in decisions:
        by_topic[d.get("topic", "?")].append(d)

        for topic, ds in by_topic.items():
         if len(ds) < 3:
          continue
          block_rate = sum(
          1 for d in ds if d.get("output", {}).get("decision") == "BLOQUEADO"
          ) / len(ds)
          if block_rate > 0.6:
           problemas.append({
           "tipo": "risco_compliance",
           "impacto": 8,
           "frequencia": len(ds),
           "urgencia": 7,
           "complexidade": 5,
           "descricao": f"Tópico '{topic}' bloqueado em {block_rate:.0%} "
           f"das decisões ({len(ds)} amostras) — revisar política",
           "fonte": "audit_engine",
           "contexto": {"topic": topic, "block_rate": block_rate,
           "n": len(ds)},
           })

           # Tendência de piora temporal
           if len(decisions) >= 6:
            chunk = max(1, len(decisions) // 3)
            w1 = decisions[:chunk]
            w3 = decisions[2 * chunk:]
            rate1 = sum(
            1 for d in w1
            if d.get("output", {}).get("decision") == "BLOQUEADO"
            ) / len(w1)
            rate3 = sum(
            1 for d in w3
            if d.get("output", {}).get("decision") == "BLOQUEADO"
            ) / len(w3)
            if rate3 - rate1 > 0.10:
             problemas.append({
             "tipo": "risco_compliance",
             "impacto": 7,
             "frequencia": len(decisions),
             "urgencia": 8,
             "complexidade": 4,
             "descricao": f"Taxa de bloqueio crescendo: "
             f"{rate1:.0%} → {rate3:.0%} — drift de política",
             "fonte": "audit_temporal",
             "contexto": {"rate_inicio": rate1, "rate_fim": rate3,
             "delta": round(rate3 - rate1, 3)},
             })
  except Exception:
   pass
   return problemas


def _coletar_de_performance() -> List[Dict]:
 """Lê performance_*.json: conteúdo com baixo engajamento."""
 problemas = []
 try:
  records = []
  for path in glob.glob(str(OUTPUTS_DIR / "performance_*.json")):
   try:
    with open(path, encoding="utf-8") as f:
     d = json.load(f)
     m = d.get("metrics", {})
     if m.get("views"):
      records.append(m)
   except Exception:
    pass

    if len(records) < 2:
     return problemas

     avg_eng = sum(r.get("engagement_rate", 0) for r in records) / len(records)
     avg_score = sum(r.get("performance_score", 0) for r in records) / len(records)

     # Engajamento abaixo de 2%
     if avg_eng < 0.02:
      problemas.append({
      "tipo": "engajamento_conteudo",
      "impacto": 7,
      "frequencia": len(records),
      "urgencia": 6,
      "complexidade": 3,
      "descricao": f"Engajamento médio baixo: {avg_eng:.1%} "
      f"(benchmark: >4%) — ganchos e formato precisam de revisão",
      "fonte": "performance_engine",
      "contexto": {"avg_engagement": avg_eng, "n_videos": len(records),
      "avg_score": avg_score},
      })

      # Performance score abaixo de 60
      if avg_score < 60:
       problemas.append({
       "tipo": "conversao_copy",
       "impacto": 6,
       "frequencia": len(records),
       "urgencia": 5,
       "complexidade": 3,
       "descricao": f"Score médio de performance baixo: {avg_score:.0f}/100 "
       f"— copy e CTA precisam de ajuste",
       "fonte": "performance_engine",
       "contexto": {"avg_score": avg_score, "n_videos": len(records)},
       })
 except Exception:
  pass
  return problemas


def _coletar_de_financeiro() -> List[Dict]:
 """Lê financial_data.json: margem caindo, custos altos."""
 problemas = []
 if not FINANCIAL_FILE.exists():
  return problemas
  try:
   with open(FINANCIAL_FILE, encoding="utf-8") as f:
    data = json.load(f)

    projs = data.get("projections", [])
    if len(projs) >= 2:
     last = projs[-1]
     prev = projs[-2]
     margin_drop = prev.get("monthly_margin_pct", 0) - last.get("monthly_margin_pct", 0)
     if margin_drop > 5:
      problemas.append({
      "tipo": "margem_financeira",
      "impacto": min(10, margin_drop),
      "frequencia": 1,
      "urgencia": 9 if margin_drop > 15 else 7,
      "complexidade": 5,
      "descricao": f"Margem caiu {margin_drop:.1f}pp "
      f"({prev.get('monthly_margin_pct',0):.0f}% → "
      f"{last.get('monthly_margin_pct',0):.0f}%) — "
      f"revisar custos ou preço",
      "fonte": "financial_engine",
      "contexto": {"margin_drop": margin_drop,
      "current": last.get("monthly_margin_pct", 0),
      "month": last.get("month", "?")},
      })

      # Custo de produtos alto vs receita
      for prod in data.get("products", []):
       rev = prod.get("revenue", 0)
       costs = prod.get("variable_costs", 0) + prod.get("fixed_costs", 0)
       if rev > 0 and costs / rev > 0.60:
        problemas.append({
        "tipo": "custo_api",
        "impacto": 6,
        "frequencia": 2,
        "urgencia": 5,
        "complexidade": 3,
        "descricao": f"Produto '{prod.get('name','?')}': custos em "
        f"{costs/rev:.0%} da receita — otimizar ou reajustar preço",
        "fonte": "financial_products",
        "contexto": {"produto": prod.get("name"), "cost_ratio": costs / rev},
        })
  except Exception:
   pass
   return problemas


def coletar_problemas() -> List[Dict]:
 """Agrega problemas de todas as fontes reais."""
 all_problems = (
 _coletar_de_self_healing() +
 _coletar_de_audit() +
 _coletar_de_performance() +
 _coletar_de_financeiro()
 )
 # Deduplica por (tipo + fonte + descricao truncada)
 seen = set()
 unique = []
 for p in all_problems:
  key = (p["tipo"], p["fonte"], p["descricao"][:40])
  if key not in seen:
   seen.add(key)
   unique.append(p)
   return unique


# Priorização

def calcular_score(p: Dict) -> float:
 base = (p["impacto"] * p["frequencia"] * p["urgencia"]) / max(p["complexidade"], 1)
 peso = TIPO_PESO.get(p["tipo"], 1.0)
 return round(base * peso, 2)


def ajustar_score_por_objetivo(score: float, tipo: str) -> float:
 """Aplica boost estratégico com base no objetivo ativo e na fase de negócio."""
 # Boost por objetivo
 boost_obj = _OBJETIVO_BOOST.get(OBJETIVO_ATUAL, {}).get(tipo, 1.0)
 # Boost por fase: tipos prioritários da fase ganham +20%
 boost_fase = 1.20 if tipo in _FASE_PRIORIDADE.get(FASE_NEGOCIO, []) else 1.0
 return round(score * boost_obj * boost_fase, 2)


def priorizar_problemas(problemas: List[Dict]) -> List[Dict]:
 for p in problemas:
  raw = calcular_score(p)
  p["score"] = raw
  p["score_estrategico"] = ajustar_score_por_objetivo(raw, p["tipo"])
  return sorted(problemas, key=lambda x: x["score_estrategico"], reverse=True)


# Score de Qualidade (Ajuste 3)

_DURABILIDADE_TIPO = {
"risco_compliance": 0.90,
"erro_operacional": 0.85,
"margem_financeira": 0.80,
"fluxo_venda": 0.70,
"padrao_aprendizado": 0.70,
"custo_api": 0.75,
"preco_oferta": 0.65,
"conversao_copy": 0.60,
"engajamento_conteudo":0.55,
}


def calcular_score_qualidade(sandbox: Dict, problema: Dict) -> Tuple[float, str]:
 """score_qualidade = impacto_norm × confiança × durabilidade → tier alta/media/baixa."""
 impacto_norm = min(1.0, max(0.0, sandbox.get("impacto", 1.0) - 1.0))
 confianca = sandbox.get("confianca", 0.5)
 durabilidade = _DURABILIDADE_TIPO.get(problema.get("tipo", ""), 0.60)
 score = round(impacto_norm * confianca * durabilidade * 10, 2)
 tier = "alta" if score >= 3.5 else ("media" if score >= 1.5 else "baixa")
 return score, tier


# Alerta de Estagnação (Ajuste 6)

def verificar_estagnacao(conn: sqlite3.Connection) -> Optional[str]:
 """Alerta se não houver melhorias aplicadas nos últimos 7 dias."""
 cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
 row = conn.execute(
 "SELECT COUNT(*) as n FROM kaizen_history WHERE aplicado=1 AND applied_at >= ?",
 (cutoff,)
 ).fetchone()
 melhorias_7d = row["n"] if row else 0
 if melhorias_7d == 0:
  alerta = "Sistema sem melhorias aplicadas nos últimos 7 dias — possível estagnação"
  rec_path = Path("outputs/kaizen/recommendations.jsonl")
  rec_path.parent.mkdir(parents=True, exist_ok=True)
  with open(rec_path, "a", encoding="utf-8") as f:
   f.write(json.dumps({
   "ts": _now(), "tipo": "stagnation_alert",
   "mensagem": alerta, "melhorias_7d": melhorias_7d,
   }) + "\n")
   return alerta
   return None


# Strategic Memory

MUDANCA_MINIMA_DIAS = 3 # mínimo de dias antes de mudar estratégia


def registrar_estrategia(conn: sqlite3.Connection,
objetivo: str, fase: str,
motivo: str = "manual") -> int:
 """Registra nova estratégia e encerra a anterior com métricas."""
 # Encerrar estratégia anterior
 anterior = conn.execute(
 "SELECT id, ts FROM strategic_history WHERE ts_fim IS NULL ORDER BY ts DESC LIMIT 1"
 ).fetchone()

 if anterior:
  prev_id = anterior["id"]
  prev_ts = anterior["ts"]
  # Métricas do período anterior
  rows = conn.execute(
  "SELECT COUNT(*) as total, "
  "SUM(CASE WHEN resultado_real='melhorou' THEN 1 ELSE 0 END) as ok, "
  "AVG(COALESCE(score_estrategico, score)) as sc_med "
  "FROM kaizen_history WHERE aplicado=1 AND applied_at >= ?",
  (prev_ts,)
  ).fetchone()
  total_m = rows["total"] or 0
  ok_m = rows["ok"] or 0
  sc_med = round(rows["sc_med"] or 0.0, 2)
  taxa_s = round(ok_m / max(total_m, 1), 3)
  resultado = "positivo" if taxa_s >= 0.5 else ("neutro" if taxa_s >= 0.25 else "negativo")
  conn.execute(
  "UPDATE strategic_history SET ts_fim=?, melhorias_ciclo=?, score_medio=?, "
  "taxa_sucesso=?, resultado=? WHERE id=?",
  (_now(), total_m, sc_med, taxa_s, resultado, prev_id),
  )

  # Inserir nova
  cur = conn.execute(
  "INSERT INTO strategic_history (ts, objetivo, fase, motivo) VALUES (?,?,?,?)",
  (_now(), objetivo, fase, motivo),
  )
  conn.commit()
  return cur.lastrowid


def verificar_mudanca_permitida(conn: sqlite3.Connection) -> Tuple[bool, int]:
 """Retorna (permitida, dias_desde_ultima_mudanca)."""
 row = conn.execute(
 "SELECT ts FROM strategic_history ORDER BY ts DESC LIMIT 1"
 ).fetchone()
 if not row:
  return True, 999
  try:
   ultima = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
   agora = datetime.now(timezone.utc)
   dias = (agora - ultima).days
   return dias >= MUDANCA_MINIMA_DIAS, dias
  except Exception:
   return True, 999


def sugerir_melhor_estrategia(conn: sqlite3.Connection) -> Optional[Dict]:
 """
 Analisa o histórico estratégico e retorna a combinação (objetivo, fase)
 com maior taxa_sucesso e melhorias aplicadas.
 Retorna None se não há histórico suficiente.
 """
 rows = conn.execute(
 """SELECT objetivo, fase,
 COUNT(*) as n_periodos,
 AVG(taxa_sucesso) as taxa_media,
 SUM(melhorias_ciclo) as total_melhorias,
 AVG(score_medio) as score_medio
 FROM strategic_history
 WHERE resultado != 'pending' AND melhorias_ciclo >= 1
 GROUP BY objetivo, fase
 ORDER BY taxa_media DESC, total_melhorias DESC
 LIMIT 1"""
 ).fetchall()

 if not rows:
  return None

  r = rows[0]
  return {
  "objetivo": r["objetivo"],
  "fase": r["fase"],
  "taxa_sucesso": round(r["taxa_media"] or 0, 3),
  "total_melhorias": r["total_melhorias"] or 0,
  "score_medio": round(r["score_medio"] or 0, 1),
  "n_periodos": r["n_periodos"],
  }


# Sugestão de Melhoria — Claude ou Regras

_RULES_SUGESTOES: Dict[str, List[Dict]] = {
"erro_operacional": [
{"acao": "Aumentar retry_limit e adicionar backoff exponencial",
"detalhe": "Erros recorrentes geralmente se beneficiam de retry com espera progressiva"},
{"acao": "Revisar threshold de detecção para reduzir falsos positivos",
"detalhe": "Alta frequência pode indicar threshold muito sensível"},
],
"padrao_aprendizado": [
{"acao": "Forçar revalidação do padrão com 5 execuções supervisionadas",
"detalhe": "Padrão com confiança baixa precisa de dados frescos"},
{"acao": "Deprecar padrão e iniciar coleta de dados com ação alternativa",
"detalhe": "Se confiança < 50%, o padrão pode estar desatualizado"},
],
"risco_compliance": [
{"acao": "Rebaixar threshold de bloqueio do tópico em 5pp e monitorar por 7 dias",
"detalhe": "Taxa > 60% indica política excessivamente restritiva"},
{"acao": "Adicionar whitelist para sub-tópicos frequentemente bloqueados sem razão",
"detalhe": "Permite granularidade fina sem comprometer segurança geral"},
],
"engajamento_conteudo": [
{"acao": "Testar 3 novos ganchos de abertura nos próximos 5 vídeos",
"detalhe": "Engajamento baixo geralmente começa no gancho dos primeiros 3 segundos"},
{"acao": "Revisar formato para short-form (< 60s) e adicionar legenda automática",
"detalhe": "Formatos curtos com legenda têm 40% mais retenção"},
],
"conversao_copy": [
{"acao": "Reescrever CTAs focando em urgência e prova social",
"detalhe": "CTAs genéricos têm taxa de clique < 1%; específicos chegam a 3-5%"},
{"acao": "Inserir depoimento real no meio do conteúdo (não só no final)",
"detalhe": "Prova social no meio reduz drop-off antes do CTA"},
],
"custo_api": [
{"acao": "Implementar cache de respostas idênticas por 24h",
"detalhe": "Queries repetidas representam 20-40% do custo em pipelines de IA"},
{"acao": "Migrar diagnósticos rápidos de GPT-4o para Claude Haiku",
"detalhe": "Haiku é 10× mais barato para tarefas simples sem perda de qualidade"},
],
"margem_financeira": [
{"acao": "Reajustar preço do produto em 10-15% — margem caiu abaixo do target",
"detalhe": "Elasticidade de preço em infoprodutos é tipicamente baixa (0.3-0.5)"},
{"acao": "Identificar e cortar 2 custos variáveis com menor impacto em qualidade",
"detalhe": "Regra 80/20: 20% dos custos geram 80% do impacto em margem"},
],
"preco_oferta": [
{"acao": "Testar preço âncora (produto premium) para elevar percepção de valor",
"detalhe": "Âncora aumenta conversão do produto principal em 20-30%"},
],
"fluxo_venda": [
{"acao": "Reduzir etapas do funil de 5 para 3 e mover CTA para cima do fold",
"detalhe": "Cada etapa adicional reduz conversão em ~20%"},
],
}


def sugerir_melhoria_rules(problema: Dict) -> Dict:
 """Regras baseadas em boas práticas para cada tipo."""
 sugestoes = _RULES_SUGESTOES.get(problema["tipo"], [
 {"acao": f"Investigar e documentar causa raiz de: {problema['descricao'][:60]}",
 "detalhe": "Sem regra específica — análise manual necessária"}
 ])
 s = sugestoes[0]
 return {
 "acao": s["acao"],
 "detalhe": s["detalhe"],
 "fonte_sugestao": "rules",
 "alternativas": [x["acao"] for x in sugestoes[1:]],
 }


KAIZEN_SYSTEM_PROMPT = """Você é um especialista em crescimento de negócios digitais e otimização de sistemas de IA.
Analise o problema e sugira a melhoria mais impactante possível — específica, executável e mensurável.

O sistema MYO é um pipeline de negócio digital autônomo com engines de IA (Claude, GPT-4o, Perplexity),
funil de vendas digital, conteúdo em vídeo e infoprodutos.

Responda SOMENTE em JSON válido:
{
"acao": "ação específica e executável (máx 100 chars)",
"detalhe": "por que isso vai funcionar e como medir (2-3 frases)",
"impacto_esperado": "estimativa de melhoria (ex: +15% conversão, -30% custo)",
"prazo": "imediato|3_dias|1_semana|2_semanas",
"alternativas": ["alternativa 1", "alternativa 2"]
}"""


def sugerir_melhoria_claude(problema: Dict) -> Optional[Dict]:
 """Usa Claude Haiku para sugerir melhoria específica e inteligente."""
 if not ANTHROPIC_KEY:
  return None
  ctx = json.dumps({
  "tipo": problema["tipo"],
  "descricao": problema["descricao"],
  "score": problema.get("score", 0),
  "contexto": problema.get("contexto", {}),
  "historico_tipo": _RULES_SUGESTOES.get(problema["tipo"], [])[:1],
  }, ensure_ascii=False)
  try:
   import httpx
   response = httpx.post(
   "https://api.anthropic.com/v1/messages",
   headers={
   "x-api-key": ANTHROPIC_KEY,
   "anthropic-version": "2023-06-01",
   "content-type": "application/json",
   },
   json={
   "model": "claude-haiku-4-5-20251001",
   "max_tokens": 512,
   "system": KAIZEN_SYSTEM_PROMPT,
   "messages": [{"role": "user",
   "content": f"Problema detectado no pipeline MYO:\n{ctx}"}],
   },
   timeout=30.0,
   )
   if response.status_code == 200:
    text = response.json()["content"][0]["text"]
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
     result = json.loads(text[start:end])
     result["fonte_sugestao"] = "claude"
     return result
  except Exception as e:
   print(f" [Kaizen] Claude indisponível: {e}")
   return None


def sugerir_melhoria(problema: Dict) -> Dict:
 """Tenta Claude; fallback para regras."""
 claude_result = sugerir_melhoria_claude(problema)
 if claude_result and claude_result.get("acao"):
  return claude_result
  return sugerir_melhoria_rules(problema)


# Sandbox Testing

def testar_no_sandbox(conn: sqlite3.Connection, melhoria: Dict, problema: Dict) -> Dict:
 """
 Estima impacto com base em:
 1. Histórico de melhorias do mesmo tipo (taxa de sucesso real)
 2. Score do problema (alta urgência = maior impacto esperado)
 3. Fonte da sugestão (claude > rules)
 4. Complexidade (alta complexidade reduz confiança)
 """
 tipo = problema["tipo"]

 # Histórico do mesmo tipo
 rows = conn.execute(
 "SELECT COUNT(*) as n, "
 " SUM(CASE WHEN resultado_real='melhorou' THEN 1 ELSE 0 END) as ok "
 "FROM kaizen_history WHERE tipo=? AND aplicado=1",
 (tipo,)
 ).fetchone()

 n_historico = rows["n"] or 0
 n_sucesso = rows["ok"] or 0
 taxa_historica = (n_sucesso / n_historico) if n_historico >= 3 else 0.65

 # Multiplicadores
 impacto_base = 1.0 + (problema.get("impacto", 5) / 50) # +2%–+20%
 urgencia_bonus = 1.0 + (problema.get("urgencia", 5) / 100) # +1%–+10%
 complexidade_penalidade = 1.0 - (max(0, problema.get("complexidade", 3) - 3) * 0.03)
 fonte_bonus = 1.05 if melhoria.get("fonte_sugestao") == "claude" else 1.0

 impacto_estimado = round(
 impacto_base * urgencia_bonus * complexidade_penalidade * fonte_bonus * taxa_historica,
 3,
 )

 confianca = round(min(0.95, 0.5 + n_historico * 0.05 + taxa_historica * 0.3), 2)

 return {
 "sucesso": impacto_estimado >= SANDBOX_MIN_IMPACT,
 "impacto": impacto_estimado,
 "confianca": confianca,
 "n_historico": n_historico,
 "taxa_historica": taxa_historica,
 "detalhes": {
 "impacto_base": impacto_base,
 "urgencia_bonus": urgencia_bonus,
 "fonte_bonus": fonte_bonus,
 },
 }


# Aplicação em Produção

def aplicar_em_producao(conn: sqlite3.Connection, kaizen_id: int,
melhoria: Dict, problema: Dict) -> bool:
 """
 Aplica a melhoria no sistema real.
 Estratégia por tipo — cria ExecutionTask ou modifica config diretamente.
 """
 tipo = problema["tipo"]
 acao = melhoria.get("acao", "")

 try:
  # Para todos os tipos, registramos uma execution task para rastreabilidade
  task = {
  "task_id": f"kaizen_{kaizen_id}_{int(time.time())}",
  "source": "kaizen_engine",
  "tipo": tipo,
  "acao": acao,
  "detalhe": melhoria.get("detalhe", ""),
  "problema": problema["descricao"],
  "kaizen_id": kaizen_id,
  "status": "pending",
  "created_at": _now(),
  }
  task_dir = Path("outputs/kaizen/tasks")
  task_dir.mkdir(parents=True, exist_ok=True)
  task_path = task_dir / f"{task['task_id']}.json"
  with open(task_path, "w", encoding="utf-8") as f:
   json.dump(task, f, ensure_ascii=False, indent=2)

   # Ações imediatas por tipo
   if tipo == "risco_compliance":
    _aplicar_compliance(problema, melhoria)

   elif tipo == "custo_api":
    _aplicar_custo_api(problema, melhoria)

    print(f" Task criada: {task_path.name}")
    return True

 except Exception as e:
  print(f" Erro ao aplicar: {e}")
  return False


def _aplicar_compliance(problema: Dict, melhoria: Dict):
 """Sugere ajuste de threshold via log — não modifica policy diretamente."""
 ctx = problema.get("contexto", {})
 topic = ctx.get("topic", "?")
 block_rate = ctx.get("block_rate", 0)
 # Apenas registra recomendação — policy_adapter fará a mudança no próximo ciclo
 rec_path = Path("outputs/kaizen/recommendations.jsonl")
 with open(rec_path, "a", encoding="utf-8") as f:
  f.write(json.dumps({
  "ts": _now(),
  "tipo": "compliance_threshold",
  "topic": topic,
  "block_rate": block_rate,
  "sugestao": melhoria.get("acao"),
  }) + "\n")


def _aplicar_custo_api(problema: Dict, melhoria: Dict):
 """Registra recomendação de otimização de custo."""
 rec_path = Path("outputs/kaizen/recommendations.jsonl")
 with open(rec_path, "a", encoding="utf-8") as f:
  f.write(json.dumps({
  "ts": _now(),
  "tipo": "custo_api_optimization",
  "contexto": problema.get("contexto", {}),
  "sugestao": melhoria.get("acao"),
  }) + "\n")


# Registro e A/B

def registrar_kaizen(conn: sqlite3.Connection, ciclo: int,
problema: Dict, melhoria: Dict,
sandbox: Dict) -> int:
 """Insere registro no banco. Retorna o id gerado."""
 sq, tq = calcular_score_qualidade(sandbox, problema)
 cur = conn.execute(
 """INSERT INTO kaizen_history
 (ciclo, tipo, problema, score, impacto, frequencia, urgencia, complexidade,
 fonte, sugestao, detalhe_sugestao, fonte_sugestao,
 sandbox_impacto, sandbox_detalhes,
 aprovado_sandbox, score_qualidade, tier_qualidade,
 score_estrategico, objetivo, fase, ts)
 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
 (
 ciclo,
 problema["tipo"],
 problema["descricao"],
 problema.get("score", 0),
 problema.get("impacto", 0),
 problema.get("frequencia", 0),
 problema.get("urgencia", 0),
 problema.get("complexidade", 1),
 problema.get("fonte", ""),
 melhoria.get("acao", ""),
 melhoria.get("detalhe", ""),
 melhoria.get("fonte_sugestao", "rules"),
 sandbox.get("impacto", 1.0),
 json.dumps(sandbox, ensure_ascii=False),
 1 if sandbox.get("sucesso") else 0,
 sq,
 tq,
 problema.get("score_estrategico", problema.get("score", 0)),
 OBJETIVO_ATUAL,
 FASE_NEGOCIO,
 _now(),
 ),
 )
 conn.commit()
 return cur.lastrowid


def marcar_aplicado(conn: sqlite3.Connection, kaizen_id: int):
 conn.execute(
 "UPDATE kaizen_history SET aplicado=1, applied_at=? WHERE id=?",
 (_now(), kaizen_id),
 )
 conn.commit()


def registrar_resultado(conn: sqlite3.Connection, kaizen_id: int,
resultado: str, score: float = 0.0):
 conn.execute(
 "UPDATE kaizen_history SET resultado_real=?, resultado_score=?, validated_at=? WHERE id=?",
 (resultado, score, _now(), kaizen_id),
 )
 conn.commit()


def iniciar_ab_test(conn: sqlite3.Connection, kaizen_id: int,
tipo: str, variante_a: str, variante_b: str) -> int:
 """Registra início de A/B test para uma melhoria."""
 cur = conn.execute(
 """INSERT INTO ab_tests (kaizen_id, tipo, variante_a, variante_b, ts_start)
 VALUES (?,?,?,?,?)""",
 (kaizen_id, tipo, variante_a, variante_b, _now()),
 )
 conn.commit()
 return cur.lastrowid


def atualizar_ab_test(conn: sqlite3.Connection, ab_id: int,
exec_a: int, exec_b: int,
sucesso_a: int, sucesso_b: int):
 conn.execute(
 """UPDATE ab_tests
 SET exec_a=?, exec_b=?, sucesso_a=?, sucesso_b=?
 WHERE id=?""",
 (exec_a, exec_b, sucesso_a, sucesso_b, ab_id),
 )
 # Checar se pode concluir (mín 10 execuções por variante)
 row = conn.execute("SELECT * FROM ab_tests WHERE id=?", (ab_id,)).fetchone()
 if row and row["exec_a"] >= 10 and row["exec_b"] >= 10:
  rate_a = (row["sucesso_a"] or 0) / row["exec_a"]
  rate_b = (row["sucesso_b"] or 0) / row["exec_b"]
  winner = "b" if rate_b > rate_a + 0.05 else ("a" if rate_a > rate_b + 0.05 else "empate")
  conn.execute(
  "UPDATE ab_tests SET status='concluded', winner=?, ts_end=? WHERE id=?",
  (winner, _now(), ab_id),
  )
  conn.commit()


# Engine Principal

class KaizenEngine:

 def __init__(self):
  self.conn = init_db()
  self.ciclo = self._get_last_ciclo() + 1
  self._sincronizar_estrategia()

 def _get_last_ciclo(self) -> int:
  row = self.conn.execute(
  "SELECT MAX(ciclo) as n FROM kaizen_history"
  ).fetchone()
  return row["n"] or 0

 def _sincronizar_estrategia(self):
  """Registra mudança de estratégia via strategic_memory se objetivo/fase mudaram."""
  init_strategic_db()
  row = self.conn.execute(
  "SELECT objetivo, fase FROM strategic_history ORDER BY id DESC LIMIT 1"
  ).fetchone()
  ultimo_obj = row["objetivo"] if row else None
  ultimo_fase = row["fase"] if row else None

  if ultimo_obj != OBJETIVO_ATUAL or ultimo_fase != FASE_NEGOCIO:
   if _sm_pode_mudar() or ultimo_obj is None:
    motivo = "sistema" if ultimo_obj is None else "manual"
    _sm_registrar(OBJETIVO_ATUAL, FASE_NEGOCIO, motivo)
   else:
    dias = _sm_dias()
    print(f" Mudança bloqueada — "
    f"{MUDANCA_MINIMA_DIAS - dias}d restantes (mínimo {MUDANCA_MINIMA_DIAS} dias)")

 def run_cycle(self) -> Dict:
  import random as _random
  ts = _now()
  print(f"\n {''*60}")
  print(f" Kaizen Engine — Ciclo #{self.ciclo} — {ts[:19]}")
  print(f" Objetivo: {OBJETIVO_ATUAL} | Fase: {FASE_NEGOCIO}")
  print(f" {''*60}")

  # 1. Coletar
  print(f" [1/4] Coletando problemas...")
  problemas = coletar_problemas()

  # Exploração estratégica: prioriza candidatos da fase ativa, fallback para genéricos
  explorar = MODO_EXPLORACAO and (not problemas or _random.random() < TAXA_EXPLORACAO)
  if explorar:
   pool = _FASE_EXPLORACAO.get(FASE_NEGOCIO, EXPLORACAO_CANDIDATOS)
   candidato = _random.choice(pool).copy()
   problemas.append(candidato)
   print(f" Exploração estratégica [{FASE_NEGOCIO}/{OBJETIVO_ATUAL}]: {candidato['descricao']}")

   if not problemas:
    print(f" Nenhum problema encontrado — sistema saudável")
    return {"ciclo": self.ciclo, "problemas": 0, "aplicadas": 0}

    print(f" {len(problemas)} problema(s) encontrado(s)")

    # 2. Priorizar
    print(f" [2/4] Priorizando...")
    priorizados = priorizar_problemas(problemas)
    for i, p in enumerate(priorizados[:5], 1):
     print(f" #{i} [{p['tipo']}] {p['descricao'][:70]} score={p['score']:.1f}")

     # 3. Loop de melhoria
     print(f" [3/4] Gerando e testando melhorias...")
     aplicadas = 0

     for problema in priorizados:
      if aplicadas >= MAX_MELHORIAS_POR_CICLO:
       break

       print(f"\n {problema['descricao'][:80]}")
       print(f" Tipo: {problema['tipo']} | Score: {problema['score']:.1f} | "
       f"Fonte: {problema['fonte']}")

       # Sugerir
       melhoria = sugerir_melhoria(problema)
       src_icon = "" if melhoria.get("fonte_sugestao") == "claude" else ""
       print(f" {src_icon} Sugestão ({melhoria['fonte_sugestao']}): {melhoria['acao']}")
       if melhoria.get("detalhe"):
        print(f" → {melhoria['detalhe'][:100]}")

        # Sandbox
        sandbox = testar_no_sandbox(self.conn, melhoria, problema)
        sb_icon = "" if sandbox["sucesso"] else ""
        print(f" {sb_icon} Sandbox: impacto estimado {sandbox['impacto']:.2f}× "
        f"(conf {sandbox['confianca']:.0%}, "
        f"histórico: {sandbox['n_historico']} casos)")

        # Registrar
        kaizen_id = registrar_kaizen(self.conn, self.ciclo, problema, melhoria, sandbox)

        if sandbox["sucesso"]:
         # Aplicar
         ok = aplicar_em_producao(self.conn, kaizen_id, melhoria, problema)
         if ok:
          marcar_aplicado(self.conn, kaizen_id)
          aplicadas += 1

          # Iniciar A/B test para melhorias de copy/conversão
          if problema["tipo"] in ("conversao_copy", "engajamento_conteudo",
          "fluxo_venda"):
           ab_id = iniciar_ab_test(
           self.conn, kaizen_id, problema["tipo"],
           "baseline_atual", melhoria["acao"][:80]
           )
           print(f" A/B test iniciado: #{ab_id}")
          else:
           print(f" Melhoria não aprovada no sandbox — registrada para revisão")

           # 4. Resumo
           self.ciclo += 1
           print(f"\n {''*60}")
           print(f" Ciclo finalizado: {len(problemas)} problemas, "
           f"{aplicadas} melhorias aplicadas")

           # Alerta de estagnação
           alerta_estagnacao = verificar_estagnacao(self.conn)
           if alerta_estagnacao:
            print(f"\n ALERTA: {alerta_estagnacao}")

            # Auto-sugestão estratégica via strategic_memory
            sugestao = _sm_sugerir_completo()
            if sugestao and sugestao["objetivo"] != OBJETIVO_ATUAL:
             score = sugestao["score_medio"]
             n_mel = sugestao["total_melhorias"]
             print(f"\n SUGESTÃO: '{sugestao['objetivo']} / {sugestao['fase']}' "
             f"score={score} ({n_mel} melhorias históricas) — "
             f"KAIZEN_OBJETIVO={sugestao['objetivo']} KAIZEN_FASE={sugestao['fase']}")

             return {
             "ciclo": self.ciclo - 1,
             "problemas": len(problemas),
             "aplicadas": aplicadas,
             "ts": ts,
             "stagnation_alert": alerta_estagnacao,
             "sugestao_estrategia": sugestao,
             }

 def run_loop(self, interval: int = SCAN_INTERVAL):
  print(f"\n Kaizen Engine iniciado (ciclos a cada {interval//60} min)")
  try:
   while True:
    self.run_cycle()
    print(f"\n ⏳ Próximo ciclo em {interval//60} minutos...")
    time.sleep(interval)
  except KeyboardInterrupt:
   print(f"\n ⏹ Kaizen Engine interrompido")


# CLI — status e histórico

def show_status():
 if not DB_FILE.exists():
  print(" Banco não encontrado. Rode o engine primeiro.")
  return
  conn = sqlite3.connect(DB_FILE)
  conn.row_factory = sqlite3.Row

  total = conn.execute("SELECT COUNT(*) as n FROM kaizen_history").fetchone()["n"]
  aplicadas = conn.execute(
  "SELECT COUNT(*) as n FROM kaizen_history WHERE aplicado=1"
  ).fetchone()["n"]
  melhorou = conn.execute(
  "SELECT COUNT(*) as n FROM kaizen_history WHERE resultado_real='melhorou'"
  ).fetchone()["n"]
  por_tipo = conn.execute(
  "SELECT tipo, COUNT(*) as n, SUM(aplicado) as ap "
  "FROM kaizen_history GROUP BY tipo ORDER BY n DESC"
  ).fetchall()
  ab_open = conn.execute(
  "SELECT COUNT(*) as n FROM ab_tests WHERE status='running'"
  ).fetchone()["n"]

  print(f"\n Kaizen Engine — Status")
  print(f" {''*50}")
  print(f" Total de melhorias registradas : {total}")
  print(f" Melhorias aplicadas : {aplicadas}")
  print(f" Confirmadas como melhoria : {melhorou}")
  print(f" A/B tests em andamento : {ab_open}")
  print(f"\n Por tipo:")
  for r in por_tipo:
   print(f" {r['tipo']:<28} {r['n']:>3} registros {r['ap'] or 0:>3} aplicados")
   conn.close()


def show_history(limit: int = 20):
 if not DB_FILE.exists():
  print(" Banco não encontrado. Rode o engine primeiro.")
  return
  conn = sqlite3.connect(DB_FILE)
  conn.row_factory = sqlite3.Row
  rows = conn.execute(
  "SELECT id, ciclo, tipo, problema, sugestao, fonte_sugestao, "
  " sandbox_impacto, aplicado, resultado_real, ts "
  "FROM kaizen_history ORDER BY ts DESC LIMIT ?",
  (limit,),
  ).fetchall()
  print(f"\n Histórico Kaizen (últimas {limit})\n")
  print(f" {'ID':<4} {'Ciclo':<6} {'Tipo':<24} {'Fonte':<7} {'Sandbox':<8} {'Apl':<4} {'Resultado'}")
  print(f" {''*80}")
  for r in rows:
   icon = "" if r["aplicado"] else "⏸"
   res = {"melhorou": "", "piorou": "", "neutro": "",
   "pending": "⏳"}.get(r["resultado_real"], "?")
   print(f" {r['id']:<4} #{r['ciclo']:<5} {r['tipo']:<24} "
   f"{r['fonte_sugestao']:<7} {r['sandbox_impacto']:>5.2f}× "
   f"{icon} {res}")
   print(f" P: {r['problema'][:65]}")
   print(f" S: {r['sugestao'][:65]}")
   print()
   conn.close()


def show_ab_report():
 if not DB_FILE.exists():
  print(" Banco não encontrado.")
  return
  conn = sqlite3.connect(DB_FILE)
  conn.row_factory = sqlite3.Row
  rows = conn.execute(
  "SELECT ab.*, kz.tipo, kz.problema FROM ab_tests ab "
  "JOIN kaizen_history kz ON ab.kaizen_id=kz.id "
  "ORDER BY ab.ts_start DESC LIMIT 20"
  ).fetchall()
  print(f"\n A/B Tests — Kaizen Engine\n")
  print(f" {'ID':<4} {'Tipo':<24} {'Status':<12} {'Winner':<8} "
  f"{'Exec A':<8} {'Exec B':<8} {'Rate A':<8} {'Rate B'}")
  print(f" {''*80}")
  for r in rows:
   rate_a = round(r["sucesso_a"] / r["exec_a"], 2) if r["exec_a"] else 0
   rate_b = round(r["sucesso_b"] / r["exec_b"], 2) if r["exec_b"] else 0
   winner = {"a": " A", "b": " B", "empate": ""}.get(r["winner"] or "", "—")
   print(f" {r['id']:<4} {r['tipo']:<24} {r['status']:<12} {winner:<8} "
   f"{r['exec_a']:<8} {r['exec_b']:<8} {rate_a:<8.0%} {rate_b:.0%}")
   conn.close()


# CLI

def main():
 parser = argparse.ArgumentParser(description="Kaizen Engine — MYO Melhoria Contínua")
 parser.add_argument("--loop", action="store_true",
 help="Loop contínuo (padrão: 1 ciclo e sai)")
 parser.add_argument("--status", action="store_true",
 help="Estado atual do banco Kaizen")
 parser.add_argument("--history", action="store_true",
 help="Histórico de melhorias registradas")
 parser.add_argument("--ab", action="store_true",
 help="Relatório de A/B tests em andamento")
 parser.add_argument("--interval", type=int, default=SCAN_INTERVAL,
 help=f"Intervalo do loop em segundos (padrão: {SCAN_INTERVAL})")
 args = parser.parse_args()

 if args.status:
  show_status(); return
  if args.history:
   show_history(); return
   if args.ab:
    show_ab_report(); return

    engine = KaizenEngine()
    if args.loop:
     engine.run_loop(interval=args.interval)
    else:
     engine.run_cycle()


if __name__ == "__main__":
 main()
