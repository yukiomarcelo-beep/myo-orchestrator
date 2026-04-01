"""
Strategic Memory — MYO Kaizen Engine

Camada de memória estratégica: registra, avalia e sugere direção de negócio.
Inclui contexto de mercado externo para decisões adaptativas.

Funções principais:
 registrar_estrategia(objetivo, fase, motivo, contexto) → grava nova estratégia ativa
 atualizar_resultado_estrategia(objetivo, r, c, cv, ctx) → feedback loop com impactos reais
 sugerir_melhor_estrategia() → retorna objetivo com melhor score histórico
 sugerir_por_contexto(contexto) → melhor estratégia para o contexto atual
 calcular_fator_mercado(cac_delta, ctr_delta, leads_delta, api_cost_delta) → ajuste contextual
 pode_mudar_estrategia() → respeita mínimo de 3 dias entre mudanças
 status() → resumo completo para CLI / dashboard

score_global = receita×0.5 + conversao×0.3 - custo×0.2 + fator_mercado

Uso standalone:
 python3 strategic_memory.py
 python3 strategic_memory.py --registrar receita validacao --contexto normal
 python3 strategic_memory.py --atualizar receita 1200 300 0.08 --cac-delta 0.1 --ctr-delta -0.05
 python3 strategic_memory.py --sugerir
 python3 strategic_memory.py --sugerir --contexto ads_caro
"""

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, List

# Config 

DB_PATH = Path("outputs/kaizen/kaizen.db")
MUDANCA_MINIMA_DIAS = 3 # mínimo de dias antes de permitir mudança de estratégia

# Pesos do score_global = receita*0.5 + conversao*0.3 - custo*0.2 + fator_mercado
PESO_RECEITA = 0.5
PESO_CONVERSAO = 0.3
PESO_CUSTO = 0.2 # penaliza custo

# Contextos de mercado reconhecidos 
# Contexto = sinal externo que afeta a estratégia ideal
# Exemplos: ads_caro, ads_barato, sazonalidade_alta, sazonalidade_baixa,
# leads_em_queda, organico_crescendo, competicao_alta, normal
CONTEXTOS_VALIDOS = {
 "normal": "Mercado estável, sem sinais externos relevantes",
 "ads_caro": "CAC subiu >10% — paid acquisition menos eficiente",
 "ads_barato": "CAC caiu >10% — oportunidade de escala paga",
 "organico_crescendo": "CTR orgânico subiu — conteúdo ganhando tração",
 "leads_em_queda": "Volume de leads caiu >20% — topo de funil fraco",
 "sazonalidade_alta": "Período de alta demanda sazonal",
 "sazonalidade_baixa": "Período de baixa demanda sazonal",
 "competicao_alta": "Concorrência aumentou — diferenciação prioritária",
 "custo_api_alto": "Custo de APIs IA subiu — otimização necessária",
}


# Fator de Mercado 

def calcular_fator_mercado(
 cac_delta: float = 0.0, # variação % do CAC (positivo = piorou)
 ctr_delta: float = 0.0, # variação % do CTR (positivo = melhorou)
 leads_delta: float = 0.0, # variação % de leads (positivo = melhorou)
 api_cost_delta: float = 0.0, # variação % custo API (positivo = piorou)
) -> float:
 """
 Calcula ajuste contextual para o score_global.
 Range típico: -0.5 a +0.5

 Lógica:
 CAC subiu → penaliza (paid acquisition menos eficiente)
 CTR subiu → bônus (orgânico ganhando tração)
 Leads subiram → bônus (topo de funil saudável)
 Custo API subiu → penaliza (margem comprimida)
 """
 fator = (
 - cac_delta * 0.30 # CAC pior é negativo
 + ctr_delta * 0.25 # CTR melhor é positivo
 + leads_delta * 0.25 # mais leads é positivo
 - api_cost_delta * 0.20 # custo API pior é negativo
 )
 return round(max(-1.0, min(1.0, fator)), 3)


def detectar_contexto(
 cac_delta: float = 0.0,
 ctr_delta: float = 0.0,
 leads_delta: float = 0.0,
) -> str:
 """Classifica o contexto de mercado com base nos deltas dos indicadores."""
 if cac_delta > 0.10:
 return "ads_caro"
 if cac_delta < -0.10:
 return "ads_barato"
 if ctr_delta > 0.10:
 return "organico_crescendo"
 if leads_delta < -0.20:
 return "leads_em_queda"
 return "normal"


# Database 

def _conn() -> sqlite3.Connection:
 DB_PATH.parent.mkdir(parents=True, exist_ok=True)
 c = sqlite3.connect(str(DB_PATH))
 c.row_factory = sqlite3.Row
 return c


def init_strategic_db():
 """Garante que a tabela existe com todos os campos necessários."""
 conn = _conn()
 conn.execute("""
 CREATE TABLE IF NOT EXISTS strategic_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 timestamp TEXT NOT NULL,
 objetivo TEXT NOT NULL,
 fase TEXT NOT NULL,
 motivo TEXT DEFAULT 'manual',
 contexto_mercado TEXT DEFAULT 'normal',
 fator_mercado REAL DEFAULT 0.0,
 impacto_receita REAL,
 impacto_custo REAL,
 impacto_conversao REAL,
 score_global REAL,
 melhorias_ciclo INTEGER DEFAULT 0,
 taxa_sucesso REAL DEFAULT 0.0,
 resultado TEXT DEFAULT 'pending',
 ts_fim TEXT
 )
 """)
 conn.commit()
 # Migração: adiciona colunas novas se o banco veio de versão anterior
 for col_def in [
 "impacto_receita REAL",
 "impacto_custo REAL",
 "impacto_conversao REAL",
 "score_global REAL",
 "melhorias_ciclo INTEGER DEFAULT 0",
 "taxa_sucesso REAL DEFAULT 0.0",
 "resultado TEXT DEFAULT 'pending'",
 "ts_fim TEXT",
 "fase TEXT DEFAULT 'validacao'",
 "contexto_mercado TEXT DEFAULT 'normal'",
 "fator_mercado REAL DEFAULT 0.0",
 ]:
 try:
 conn.execute(f"ALTER TABLE strategic_history ADD COLUMN {col_def}")
 conn.commit()
 except Exception:
 pass
 conn.close()


# 1. Registrar Estratégia 

def registrar_estrategia(objetivo: str, fase: str,
 motivo: str = "manual",
 contexto: str = "normal") -> int:
 """
 Registra nova estratégia ativa com contexto de mercado.
 Encerra a anterior calculando resultado com base nas melhorias kaizen do período.
 """
 contexto = contexto if contexto in CONTEXTOS_VALIDOS else "normal"
 conn = _conn()
 ts = datetime.now(timezone.utc).isoformat()

 # Encerrar estratégia anterior
 anterior = conn.execute(
 "SELECT id, timestamp FROM strategic_history WHERE ts_fim IS NULL ORDER BY id DESC LIMIT 1"
 ).fetchone()

 if anterior:
 prev_id = anterior["id"]
 prev_ts = anterior["timestamp"]
 rows = conn.execute(
 "SELECT COUNT(*) as total, "
 "SUM(CASE WHEN resultado_real='melhorou' THEN 1 ELSE 0 END) as ok "
 "FROM kaizen_history WHERE aplicado=1 AND applied_at >= ?",
 (prev_ts,)
 ).fetchone()
 total_m = rows["total"] or 0
 ok_m = rows["ok"] or 0
 taxa_s = round(ok_m / max(total_m, 1), 3)
 resultado = "positivo" if taxa_s >= 0.5 else ("neutro" if taxa_s >= 0.25 else "negativo")
 conn.execute(
 "UPDATE strategic_history SET ts_fim=?, melhorias_ciclo=?, taxa_sucesso=?, resultado=? "
 "WHERE id=?",
 (ts, total_m, taxa_s, resultado, prev_id),
 )

 cur = conn.execute(
 "INSERT INTO strategic_history (timestamp, objetivo, fase, motivo, contexto_mercado) "
 "VALUES (?,?,?,?,?)",
 (ts, objetivo, fase, motivo, contexto),
 )
 conn.commit()
 sid = cur.lastrowid
 conn.close()
 print(f" Estratégia registrada (id={sid}): {objetivo} | {fase} "
 f"[{motivo}] ctx={contexto}")
 return sid


# 2. Atualizar Resultado (Feedback Loop) 

def atualizar_resultado_estrategia(objetivo: str,
 impacto_receita: float,
 impacto_custo: float,
 impacto_conversao: float,
 fator_mercado: float = 0.0) -> float:
 """
 Grava impactos reais medidos e calcula score_global context-aware.
 score_global = receita*0.5 + conversao*0.3 - custo*0.2 + fator_mercado
 """
 score_global = (
 impacto_receita * PESO_RECEITA +
 impacto_conversao * PESO_CONVERSAO -
 impacto_custo * PESO_CUSTO +
 fator_mercado
 )
 score_global = round(score_global, 3)

 conn = _conn()
 classificar = ("positivo" if score_global >= 5 else
 "neutro" if score_global >= 2 else "negativo")
 conn.execute(
 """UPDATE strategic_history
 SET impacto_receita=?, impacto_custo=?, impacto_conversao=?,
 fator_mercado=?, score_global=?, resultado=?
 WHERE objetivo=? AND ts_fim IS NULL
 """,
 (impacto_receita, impacto_custo, impacto_conversao,
 fator_mercado, score_global, classificar, objetivo),
 )
 if conn.execute("SELECT changes()").fetchone()[0] == 0:
 conn.execute(
 """UPDATE strategic_history
 SET impacto_receita=?, impacto_custo=?, impacto_conversao=?,
 fator_mercado=?, score_global=?, resultado=?
 WHERE id=(SELECT id FROM strategic_history WHERE objetivo=? ORDER BY id DESC LIMIT 1)
 """,
 (impacto_receita, impacto_custo, impacto_conversao,
 fator_mercado, score_global, classificar, objetivo),
 )
 conn.commit()
 conn.close()
 print(f" Resultado atualizado — '{objetivo}' score={score_global} "
 f"fator_mercado={fator_mercado:+.3f} → {classificar}")
 return score_global


# 3. Sugerir Melhor Estratégia 

def sugerir_melhor_estrategia() -> Optional[str]:
 """
 Analisa histórico e retorna o objetivo com maior score_global médio.
 Considera também taxa_sucesso das melhorias kaizen quando score_global é null.
 """
 conn = _conn()
 # Prioridade: score_global (dados reais de negócio) > taxa_sucesso (dados kaizen)
 row = conn.execute(
 """SELECT objetivo, fase,
 AVG(COALESCE(score_global, taxa_sucesso * 10)) as avg_score,
 COUNT(*) as n_periodos,
 SUM(melhorias_ciclo) as total_melhorias
 FROM strategic_history
 WHERE resultado != 'pending'
 GROUP BY objetivo
 ORDER BY avg_score DESC, total_melhorias DESC
 LIMIT 1"""
 ).fetchone()
 conn.close()
 if row:
 obj = row["objetivo"]
 score = round(row["avg_score"] or 0, 2)
 print(f" Melhor estratégia histórica: {obj} (score médio: {score})")
 return obj
 return None


def sugerir_por_contexto(contexto: str) -> Optional[Dict]:
 """
 Retorna a estratégia com melhor score_global para um contexto específico de mercado.
 Fallback: usa histórico geral se não há dados suficientes para o contexto.
 """
 conn = _conn()
 # Busca específica por contexto
 row = conn.execute(
 """SELECT objetivo, fase,
 AVG(COALESCE(score_global, taxa_sucesso*10)) as avg_score,
 COUNT(*) as n
 FROM strategic_history
 WHERE contexto_mercado=? AND resultado != 'pending'
 GROUP BY objetivo, fase
 ORDER BY avg_score DESC LIMIT 1""",
 (contexto,)
 ).fetchone()
 conn.close()

 if row and row["n"] >= 1:
 return {
 "objetivo": row["objetivo"],
 "fase": row["fase"],
 "score_medio": round(row["avg_score"] or 0, 2),
 "contexto": contexto,
 "n_periodos": row["n"],
 "fonte": "contexto_especifico",
 }
 # Fallback para histórico geral
 geral = sugerir_melhor_estrategia_completo()
 if geral:
 geral["contexto"] = contexto
 geral["fonte"] = "historico_geral"
 return geral


def sugerir_melhor_estrategia_completo() -> Optional[Dict]:
 """Retorna dict completo com objetivo, fase, score, períodos."""
 conn = _conn()
 rows = conn.execute(
 """SELECT objetivo, fase,
 AVG(COALESCE(score_global, taxa_sucesso * 10)) as avg_score,
 COUNT(*) as n_periodos,
 SUM(melhorias_ciclo) as total_melhorias,
 MAX(resultado) as ultimo_resultado
 FROM strategic_history
 WHERE resultado != 'pending'
 GROUP BY objetivo, fase
 ORDER BY avg_score DESC, total_melhorias DESC"""
 ).fetchall()
 conn.close()
 if not rows:
 return None
 r = rows[0]
 return {
 "objetivo": r["objetivo"],
 "fase": r["fase"],
 "score_medio": round(r["avg_score"] or 0, 2),
 "n_periodos": r["n_periodos"],
 "total_melhorias": r["total_melhorias"] or 0,
 "ranking": [dict(rw) for rw in rows],
 }


# 4. Controle de Frequência 

def pode_mudar_estrategia() -> bool:
 """Retorna True se passaram >= MUDANCA_MINIMA_DIAS desde a última mudança."""
 conn = _conn()
 row = conn.execute(
 "SELECT timestamp FROM strategic_history ORDER BY id DESC LIMIT 1"
 ).fetchone()
 conn.close()
 if not row:
 return True
 try:
 last = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
 return datetime.now(timezone.utc) - last >= timedelta(days=MUDANCA_MINIMA_DIAS)
 except Exception:
 return True


def dias_desde_ultima_mudanca() -> int:
 """Retorna quantos dias desde a última mudança de estratégia."""
 conn = _conn()
 row = conn.execute(
 "SELECT timestamp FROM strategic_history ORDER BY id DESC LIMIT 1"
 ).fetchone()
 conn.close()
 if not row:
 return 999
 try:
 last = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
 return (datetime.now(timezone.utc) - last).days
 except Exception:
 return 999


# 5. Status Completo 

def status() -> Dict:
 """Retorna estado completo da Strategic Memory para dashboard e CLI."""
 conn = _conn()

 # Estratégia ativa
 ativa = conn.execute(
 "SELECT * FROM strategic_history WHERE ts_fim IS NULL ORDER BY id DESC LIMIT 1"
 ).fetchone()

 # Histórico (últimas 10)
 historico = conn.execute(
 "SELECT * FROM strategic_history ORDER BY id DESC LIMIT 10"
 ).fetchall()

 # Ranking por score médio
 ranking = conn.execute(
 """SELECT objetivo, fase,
 ROUND(AVG(COALESCE(score_global, taxa_sucesso*10)), 2) as score_medio,
 COUNT(*) as n_periodos, SUM(melhorias_ciclo) as total_melhorias,
 GROUP_CONCAT(DISTINCT contexto_mercado) as contextos
 FROM strategic_history
 WHERE resultado != 'pending'
 GROUP BY objetivo, fase
 ORDER BY score_medio DESC"""
 ).fetchall()

 # Breakdown por contexto de mercado
 por_contexto = conn.execute(
 """SELECT contexto_mercado, objetivo, fase,
 ROUND(AVG(COALESCE(score_global, taxa_sucesso*10)), 2) as score_medio,
 COUNT(*) as n
 FROM strategic_history
 WHERE resultado != 'pending' AND contexto_mercado IS NOT NULL
 GROUP BY contexto_mercado, objetivo, fase
 ORDER BY contexto_mercado, score_medio DESC"""
 ).fetchall()

 conn.close()

 dias = dias_desde_ultima_mudanca()
 return {
 "ativa": dict(ativa) if ativa else None,
 "pode_mudar": dias >= MUDANCA_MINIMA_DIAS,
 "dias_desde_mudanca": dias,
 "historico": [dict(r) for r in historico],
 "ranking": [dict(r) for r in ranking],
 "melhor": dict(ranking[0]) if ranking else None,
 "por_contexto": [dict(r) for r in por_contexto],
 }


# CLI 

def _print_status():
 init_strategic_db()
 s = status()

 print(f"\n Strategic Memory — Status")
 print(f" {''*55}")

 ativa = s["ativa"]
 if ativa:
 dias = s["dias_desde_mudanca"]
 lock = f" bloqueada ({MUDANCA_MINIMA_DIAS - dias}d restantes)" if not s["pode_mudar"] else " mudança permitida"
 print(f" Estratégia ativa : {ativa['objetivo']} / {ativa['fase']}")
 print(f" Desde : {(ativa.get('timestamp') or '')[:10]} ({dias} dias) {lock}")
 print(f" Motivo : {ativa.get('motivo','—')}")
 else:
 print(f" Nenhuma estratégia ativa — rode: python3 strategic_memory.py --registrar <obj> <fase>")

 melhor = s["melhor"]
 if melhor:
 print(f"\n Melhor histórica : {melhor['objetivo']} / {melhor['fase']}"
 f" (score={melhor['score_medio']}, {melhor['n_periodos']} período(s))")

 if s["ranking"]:
 print(f"\n Ranking estratégias:")
 for i, r in enumerate(s["ranking"], 1):
 print(f" {i}. {r['objetivo']:<22} fase={r['fase']:<12} "
 f"score={r['score_medio']:<6} períodos={r['n_periodos']}")

 print(f"\n Histórico recente:")
 _RES = {"positivo": "", "neutro": "", "negativo": "", "pending": "⏳"}
 for h in s["historico"]:
 res = _RES.get(h.get("resultado","pending"), "⏳")
 ts = (h.get("timestamp") or "")[:10]
 ativo = " ← ativo" if not h.get("ts_fim") else ""
 score = f"score={h['score_global']:.1f}" if h.get("score_global") else f"taxa={h.get('taxa_sucesso',0):.0%}"
 print(f" {res} {ts} {h['objetivo']:<22} {h['fase']:<12} {score}{ativo}")
 print()


def main():
 parser = argparse.ArgumentParser(description="Strategic Memory — MYO Kaizen")
 parser.add_argument("--registrar", nargs=2, metavar=("OBJETIVO", "FASE"),
 help="Registrar nova estratégia")
 parser.add_argument("--motivo", default="manual")
 parser.add_argument("--contexto", default="normal",
 help=f"Contexto de mercado: {', '.join(CONTEXTOS_VALIDOS)}")
 parser.add_argument("--atualizar", nargs=4,
 metavar=("OBJETIVO", "RECEITA", "CUSTO", "CONVERSAO"),
 help="Atualizar resultados reais")
 # Indicadores para calcular fator_mercado automaticamente
 parser.add_argument("--cac-delta", type=float, default=0.0,
 help="Variação %% do CAC (ex: 0.10 = subiu 10%%)")
 parser.add_argument("--ctr-delta", type=float, default=0.0,
 help="Variação %% do CTR (ex: 0.05 = subiu 5%%)")
 parser.add_argument("--leads-delta", type=float, default=0.0,
 help="Variação %% de leads")
 parser.add_argument("--api-cost-delta", type=float, default=0.0,
 help="Variação %% do custo de API")
 parser.add_argument("--sugerir", action="store_true",
 help="Sugerir melhor estratégia (use --contexto para contexto específico)")
 args = parser.parse_args()

 init_strategic_db()

 if args.registrar:
 obj, fase = args.registrar
 if not pode_mudar_estrategia():
 dias = dias_desde_ultima_mudanca()
 print(f" Mudança bloqueada — {MUDANCA_MINIMA_DIAS - dias}d restantes")
 else:
 registrar_estrategia(obj, fase, args.motivo, args.contexto)

 elif args.atualizar:
 obj, rec, cus, cvs = args.atualizar
 fm = calcular_fator_mercado(
 cac_delta=args.cac_delta,
 ctr_delta=args.ctr_delta,
 leads_delta=args.leads_delta,
 api_cost_delta=args.api_cost_delta,
 )
 if fm != 0:
 ctx = detectar_contexto(args.cac_delta, args.ctr_delta, args.leads_delta)
 print(f" Contexto detectado: {ctx} fator_mercado={fm:+.3f}")
 atualizar_resultado_estrategia(obj, float(rec), float(cus), float(cvs), fm)

 elif args.sugerir:
 ctx = args.contexto
 if ctx != "normal":
 r = sugerir_por_contexto(ctx)
 prefix = f"[contexto={ctx}]"
 else:
 r = sugerir_melhor_estrategia_completo()
 prefix = "[histórico geral]"
 if r:
 print(f" Recomendação {prefix}: {r['objetivo']} / {r['fase']} "
 f"score={r.get('score_medio',0)} ({r.get('n_periodos',0)} período(s))")
 else:
 print(" Histórico insuficiente — rode mais ciclos antes de sugerir.")

 else:
 _print_status()


if __name__ == "__main__":
 main()
