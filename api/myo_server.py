#!/usr/bin/env python3
"""
MYO Server — Control Layer v3

Rotas:
GET / → home executiva
GET /dashboard → dashboard operacional
GET /executive → dashboard executivo
GET /api/state → estado multi-produto
GET /api/log → log de execução
GET /api/kaizen → status kaizen
GET /api/autonomous → nível de autonomia (0/1/2)
POST /api/autonomous → muda nível
POST /api/run-kaizen → roda 1 ciclo kaizen
POST /api/estrategia → muda objetivo/fase
POST /api/sugerir → sugestão de estratégia
POST /api/pipeline/start → inicia master_controller
GET /api/pipeline/status → estado pipeline
POST /api/regenerar → regenera dashboards HTML
GET /api/home-data → dados da home (KPIs ao vivo)

Uso:
python3 myo_server.py
python3 myo_server.py --port 8080
"""

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# Config

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / "outputs" / "system_state.json"
LOG_FILE = BASE_DIR / "outputs" / "execution_log.jsonl"
AUTO_FILE = BASE_DIR / "outputs" / "autonomous_mode.json"
DASHBOARD_HTML = BASE_DIR / "dashboard.html"
EXEC_DASH_HTML = BASE_DIR / "executive_dashboard.html"
LOG_MAX_LINES = 200

OBJETIVOS_VALIDOS = [
    "maximizar_receita",
    "reduzir_custo",
    "aumentar_conversao",
    "equilibrio",
]
FASES_VALIDAS = ["validacao", "escala", "lucro", "produto"]

OBJ_LABEL = {
    "maximizar_receita": " Maximizar Receita",
    "reduzir_custo": " Reduzir Custo",
    "aumentar_conversao": " Aumentar Conversão",
    "equilibrio": " Equilíbrio",
}
FASE_LABEL = {
    "validacao": " Validação",
    "escala": " Escala",
    "lucro": " Lucro",
    "produto": " Produto",
}
PIPELINE_STAGES = [
    ("opportunity", "01", "Análise"),
    ("product", "02", "Produto"),
    ("content", "03", "Conteúdo"),
    ("video", "04", "Vídeo"),
    ("sales", "05", "Vendas"),
    ("performance", "06", "Performance"),
]

# Auth
# Defina MYO_PASSWORD no .env para ativar auth. Deixe em branco para desabilitar.
MYO_PASSWORD = os.getenv("MYO_PASSWORD", "")
_SESSION_TOKENS: set[str] = set()  # tokens válidos em memória


def _make_session_token() -> str:
    return secrets.token_urlsafe(32)


def _is_authenticated(request: Request) -> bool:
    if not MYO_PASSWORD:
        return True  # auth desabilitada
    token = request.cookies.get("myo_session")
    return token in _SESSION_TOKENS


# Telegram
_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")


def _send_telegram(msg: str) -> None:
    """Envia mensagem via Telegram usando urllib (sem dependência extra)."""
    if not _TG_TOKEN or not _TG_CHAT:
        return
    try:
        url = f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode(
            {
                "chat_id": _TG_CHAT,
                "text": msg,
                "parse_mode": "HTML",
            }
        ).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


# Stripe
STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WH_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PNL_HISTORY_FILE = BASE_DIR / "outputs" / "pnl_history.json"
_pnl_lock = threading.Lock()


def _read_pnl_history() -> dict:
    if PNL_HISTORY_FILE.exists():
        try:
            return json.loads(PNL_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_pnl_history(data: dict):
    with _pnl_lock:
        PNL_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        PNL_HISTORY_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# Nível de autonomia: 0=Manual, 1=Assistido, 2=Autônomo
AUTO_LEVELS = {
    0: {
        "label": "⏸ Manual",
        "color": "#475569",
        "bg": "#1a2d4533",
        "border": "#1a2d45",
    },
    1: {
        "label": " Assistido",
        "color": "#38bdf8",
        "bg": "#38bdf822",
        "border": "#38bdf855",
    },
    2: {
        "label": " Autônomo",
        "color": "#f59e0b",
        "bg": "#f59e0b22",
        "border": "#f59e0b55",
    },
}

# App

app = FastAPI(title="MYO Control Server", version="3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware
from starlette.middleware.base import BaseHTTPMiddleware

_AUTH_PUBLIC = {"/login", "/api/login", "/static", "/favicon.ico"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not MYO_PASSWORD:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(p) for p in _AUTH_PUBLIC):
            return await call_next(request)
        if not _is_authenticated(request):
            return RedirectResponse(url="/login")
        return await call_next(request)


app.add_middleware(AuthMiddleware)

# Security middleware — DLP + prompt injection em endpoints POST
try:
    import sys as _sys

    _sys.path.insert(0, str(BASE_DIR.parent))
    from core.security_bridge import guard_input as _guard_input

    _SECURITY_MW = True
except ImportError:
    _SECURITY_MW = False

    def _guard_input(x):
        return True, "OK"


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _SECURITY_MW and request.method == "POST":
            try:
                body = await request.body()
                if body:
                    import json as _json

                    data = _json.loads(body)
                    input_text = (
                        data.get("input", "")
                        or data.get("text", "")
                        or data.get("task", "")
                    )
                    if input_text:
                        ok, reason = _guard_input(str(input_text))
                        if not ok:
                            return JSONResponse(
                                {"error": "blocked", "reason": reason}, status_code=400
                            )
            except Exception:
                pass  # body não é JSON ou já consumido — ignora
        return await call_next(request)


app.add_middleware(SecurityMiddleware)
#

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_pipeline_proc: subprocess.Popen | None = None
_pipeline_lock = threading.Lock()

# State helpers

_state_lock = threading.Lock()


def _read_state() -> dict:
    if STATE_FILE.exists():
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "produtos" not in raw:
                raw = {"produtos": [raw], "autonomous": False}
            return raw
        except Exception:
            pass
    return {"produtos": [], "autonomous": False}


def _write_state(state: dict):
    with _state_lock:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _read_autonomous_level() -> int:
    if AUTO_FILE.exists():
        try:
            d = json.loads(AUTO_FILE.read_text())
            return int(d.get("level", 2 if d.get("enabled") else 0))
        except Exception:
            pass
    return 0


def _write_autonomous_level(level: int):
    AUTO_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_FILE.write_text(json.dumps({"level": level, "enabled": level >= 2}))


def _read_autonomous() -> bool:
    return _read_autonomous_level() >= 2


def _ts_to_epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def log_evento(produto: str, evento: str, fase: str = "", status: str = "info"):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "produto": produto,
        "evento": evento,
        "fase": fase,
        "status": status,
    }
    with _state_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            try:
                lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
                if len(lines) > LOG_MAX_LINES:
                    LOG_FILE.write_text(
                        "\n".join(lines[-LOG_MAX_LINES:]) + "\n", encoding="utf-8"
                    )
            except Exception:
                pass


def atualizar_fase(
    fase: str, status: str = "rodando", produto: str = "", progresso: int = 0
):
    if not produto:
        produto = "Sistema"
        state = _read_state()
        produtos = state.get("produtos", [])
        entry = next((p for p in produtos if p.get("produto") == produto), None)
        if entry:
            entry.update(
                {
                    "fase_atual": fase,
                    "status": status,
                    "progresso": progresso,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        else:
            produtos.append(
                {
                    "produto": produto,
                    "fase_atual": fase,
                    "status": status,
                    "progresso": progresso,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            cutoff = datetime.now(timezone.utc).timestamp() - 3600
            produtos = [
                p
                for p in produtos
                if p.get("status") != "idle"
                or _ts_to_epoch(p.get("timestamp", "")) > cutoff
            ]
            if not produtos:
                produtos = [
                    {
                        "produto": produto,
                        "fase_atual": fase,
                        "status": status,
                        "progresso": progresso,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ]
                state["produtos"] = produtos
                _write_state(state)


# Live Stats


def _load_live_stats() -> dict:
    stats = {
        "receita_protegida": 0.0,
        "pct_automatizado": 0,
        "melhoria_semanal": 0,
        "melhoria_semana_ant": 0,
        "tendencia_semanal": 0,  # % vs semana anterior
        "kaizen_aplicados": 0,
        "taxa_sucesso": 0,
        "stagnation": False,
        "objetivo_atual": "equilibrio",
        "fase_negocio": "validacao",
        "produtos": [],
        "autonomous_level": 0,
        "alertas": [],
    }
    try:
        db_path = BASE_DIR / "kaizen.db"
        if db_path.exists():
            con = sqlite3.connect(str(db_path))
            cur = con.cursor()

            cur.execute("SELECT COUNT(*) FROM kaizen_history WHERE status='aplicado'")
            row = cur.fetchone()
            stats["kaizen_aplicados"] = row[0] if row else 0

            cur.execute(
                "SELECT status FROM kaizen_history ORDER BY timestamp DESC LIMIT 20"
            )
            rows = cur.fetchall()
            if rows:
                ok = sum(1 for r in rows if r[0] == "aplicado")
                stats["taxa_sucesso"] = round(ok / len(rows) * 100)
                stats["pct_automatizado"] = stats["taxa_sucesso"]

                try:
                    cur.execute(
                        "SELECT SUM(impacto_receita) FROM kaizen_history WHERE status='aplicado'"
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        stats["receita_protegida"] = round(float(row[0]), 2)
                except Exception:
                    pass

                    # Esta semana vs semana anterior → tendência
                    try:
                        cur.execute(
                            """SELECT COUNT(*) FROM kaizen_history
      WHERE status='aplicado'
      AND timestamp >= date('now', '-7 days')"""
                        )
                        row = cur.fetchone()
                        stats["melhoria_semanal"] = row[0] if row else 0

                        cur.execute(
                            """SELECT COUNT(*) FROM kaizen_history
      WHERE status='aplicado'
      AND timestamp >= date('now', '-14 days')
      AND timestamp < date('now', '-7 days')"""
                        )
                        row = cur.fetchone()
                        stats["melhoria_semana_ant"] = row[0] if row else 0

                        ant = stats["melhoria_semana_ant"]
                        atu = stats["melhoria_semanal"]
                        if ant > 0:
                            stats["tendencia_semanal"] = round((atu - ant) / ant * 100)
                        elif atu > 0:
                            stats["tendencia_semanal"] = 100
                    except Exception:
                        pass

                        try:
                            cur.execute(
                                """SELECT objetivo, fase FROM strategic_history
       ORDER BY timestamp DESC LIMIT 1"""
                            )
                            row = cur.fetchone()
                            if row:
                                stats["objetivo_atual"] = row[0] or "equilibrio"
                                stats["fase_negocio"] = row[1] or "validacao"
                        except Exception:
                            pass

                            try:
                                cur.execute(
                                    """SELECT COUNT(*) FROM kaizen_history
        WHERE timestamp >= date('now', '-3 days')"""
                                )
                                row = cur.fetchone()
                                stats["stagnation"] = (
                                    row[0] if row else 0
                                ) == 0 and stats["kaizen_aplicados"] > 0
                            except Exception:
                                pass

                                con.close()
    except Exception:
        pass

    state = _read_state()
    stats["produtos"] = state.get("produtos", [])
    stats["autonomous_level"] = _read_autonomous_level()
    stats["alertas"] = _gerar_alertas(stats)
    stats["proxima_acao"] = _computar_proxima_acao(stats)
    return stats


def _fmt_brl(valor: float) -> str:
    return f"R$ {valor:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _gerar_alertas(stats: dict) -> list:
    alertas = []
    receita = stats.get("receita_protegida", 0)
    kaizens = max(stats.get("kaizen_aplicados", 1), 1)
    valor_por_ciclo = receita / kaizens if receita > 0 else 0

    if stats.get("stagnation"):
        impacto = _fmt_brl(valor_por_ciclo * 4)
        alertas.append(
            {
                "nivel": "critico",
                "icon": "",
                "titulo": "Estagnação detectada",
                "descricao": "Sistema sem novas melhorias há 3+ dias",
                "impacto": f"Oportunidade em risco: {impacto}/mês",
                "sugestao": "Ativar modo de exploração no Kaizen para forçar novas tentativas",
                "acao_label": "Rodar Kaizen de Exploração",
                "acao_js": "runKaizen()",
            }
        )

    taxa = stats.get("taxa_sucesso", 100)
    if taxa < 50 and kaizens > 5:
        perda = _fmt_brl(receita * (0.5 - taxa / 100) * 0.5)
        alertas.append(
            {
                "nivel": "aviso",
                "icon": "",
                "titulo": f"Taxa de sucesso baixa — {taxa}% de efetividade",
                "descricao": "Menos da metade dos Kaizens recentes foram aplicados com sucesso",
                "impacto": f"Impacto estimado: -{perda}/mês em otimizações perdidas",
                "sugestao": "Mudar para estratégia de redução de custo ou aumentar conversão",
                "acao_label": "Descobrir melhor estratégia",
                "acao_js": "sugerirEstrategia()",
            }
        )

    tend = stats.get("tendencia_semanal", 0)
    if tend < -20 and stats.get("melhoria_semanal", 0) < stats.get(
        "melhoria_semana_ant", 0
    ):
        alertas.append(
            {
                "nivel": "aviso",
                "icon": "",
                "titulo": f"Queda de {abs(tend)}% nas melhorias semanais",
                "descricao": f"Esta semana: {stats['melhoria_semanal']} melhorias vs {stats['melhoria_semana_ant']} na anterior",
                "impacto": "Ritmo de otimização desacelerando",
                "sugestao": "Rodar um ciclo Kaizen para retomar o momentum",
                "acao_label": "Melhorar sistema agora",
                "acao_js": "runKaizen()",
            }
        )

    return alertas


def _computar_proxima_acao(stats: dict) -> dict:
    if stats.get("stagnation"):
        return {
            "icon": "",
            "impacto": "alto",
            "cor": "#ef4444",
            "titulo": "Estagnação — sistema parado há 3+ dias",
            "descricao": "Nenhuma melhoria registrada — risco de perda de eficiência",
            "acao": "Rodar Kaizen agora",
            "acao_js": "runKaizen()",
        }
    if stats.get("taxa_sucesso", 100) < 50 and stats.get("kaizen_aplicados", 0) > 5:
        return {
            "icon": "",
            "impacto": "alto",
            "cor": "#f59e0b",
            "titulo": "Taxa de sucesso abaixo do esperado",
            "descricao": f"{stats['taxa_sucesso']}% de efetividade — sistema pode estar mal calibrado",
            "acao": "Descobrir melhor estratégia",
            "acao_js": "sugerirEstrategia()",
        }
    if stats.get("kaizen_aplicados", 0) == 0:
        return {
            "icon": "",
            "impacto": "alto",
            "cor": "#10b981",
            "titulo": "Sistema pronto — zero melhorias aplicadas ainda",
            "descricao": "Rode o primeiro ciclo Kaizen para iniciar a otimização contínua",
            "acao": "Melhorar sistema agora",
            "acao_js": "runKaizen()",
        }
    tend = stats.get("tendencia_semanal", 0)
    tend_str = f"{'↑' if tend >= 0 else '↓'} {abs(tend)}% vs semana anterior"
    return {
        "icon": "",
        "impacto": "médio",
        "cor": "#3b82f6",
        "titulo": "Sistema operando — manutenção contínua recomendada",
        "descricao": (
            f"{stats['kaizen_aplicados']} melhorias aplicadas · "
            f"{stats['taxa_sucesso']}% sucesso · {tend_str}"
        ),
        "acao": "Melhorar sistema agora",
        "acao_js": "runKaizen()",
    }


# Dashboard helpers


def _regenerar_dashboard():
    subprocess.run(
        [sys.executable, "scripts/generate_dashboard.py"],
        cwd=str(BASE_DIR),
        capture_output=True,
        timeout=60,
    )


def _regenerar_executive():
    subprocess.run(
        [sys.executable, "dashboard_engine.py", "--print"],
        cwd=str(BASE_DIR),
        capture_output=True,
        timeout=60,
    )


# HTML — Controls (top bar)


def _build_controls_html(dashboard_type: str = "main") -> str:
    return r"""
<div id="myo-controls" style="
position:fixed;top:0;left:0;right:0;z-index:9999;
background:linear-gradient(90deg,#020609,#060d17,#020609);
border-bottom:1px solid #0d1a2a;
padding:0 20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
font-family:Inter,system-ui,sans-serif;font-size:12px;min-height:48px;">

<!-- Logo -->
<a href="/" style="text-decoration:none;display:flex;align-items:center;gap:6px;margin-right:8px">
<span style="color:#3b82f6;font-weight:800;font-size:15px"> MYO</span>
</a>

<!-- Ação primária -->
<button onclick="runKaizen()" id="btn-kaizen"
style="background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none;
border-radius:8px;padding:7px 16px;cursor:pointer;font-weight:700;font-size:11px;
box-shadow:0 0 14px #10b98144;transition:all .3s;white-space:nowrap">
Melhorar sistema agora
</button>

<span style="color:#0d1f35;font-size:16px"></span>

<!-- Sugestão label -->
<span id="myo-sugestao-label"
style="color:#2d4a6b;font-size:10px;white-space:nowrap;max-width:200px;overflow:hidden;
text-overflow:ellipsis">
carregando sugestão…
</span>

<!-- Analisar estratégia -->
<button id="btn-sugerir" onclick="sugerirEstrategia()"
style="background:#8b5cf622;color:#a78bfa;border:1px solid #8b5cf644;border-radius:6px;
padding:5px 12px;cursor:pointer;font-size:10px;font-weight:600;transition:all .3s">
Analisar estratégia
</button>

<!-- Dropdowns -->
<select id="objetivo-select"
style="background:#060d17;color:#64748b;border:1px solid #0d1f35;
border-radius:6px;padding:5px 8px;font-size:10px;max-width:155px">
<option value="maximizar_receita"> Maximizar Receita</option>
<option value="reduzir_custo"> Reduzir Custo</option>
<option value="aumentar_conversao"> Aumentar Conversão</option>
<option value="equilibrio"> Equilíbrio</option>
</select>
<select id="fase-select"
style="background:#060d17;color:#64748b;border:1px solid #0d1f35;
border-radius:6px;padding:5px 8px;font-size:10px;max-width:125px">
<option value="validacao"> Validação</option>
<option value="escala"> Escala</option>
<option value="lucro"> Lucro</option>
<option value="produto"> Produto</option>
</select>
<button onclick="trocarEstrategia()"
style="background:#f59e0b11;color:#f59e0b;border:1px solid #f59e0b33;border-radius:6px;
padding:5px 12px;cursor:pointer;font-size:10px;font-weight:600">
Aplicar
</button>

<span style="color:#0d1f35;font-size:16px"></span>

<!-- Pipeline -->
<button onclick="iniciarPipeline()"
style="background:#06b6d411;color:#06b6d4;border:1px solid #06b6d433;border-radius:6px;
padding:5px 12px;cursor:pointer;font-size:10px;font-weight:600">
Pipeline
</button>

<!-- Regenerar -->
<button onclick="regenerar()" title="Atualizar dashboards"
style="background:transparent;color:#1e3a5f;border:1px solid #0d1f35;border-radius:6px;
padding:5px 10px;cursor:pointer;font-size:10px">

</button>

<!-- Nível de autonomia (3 níveis) -->
<button id="btn-autonomo" onclick="cycleAutonomia()"
style="border-radius:6px;padding:5px 12px;cursor:pointer;font-size:10px;font-weight:700;
transition:all .4s;white-space:nowrap;border:1px solid">
⏸ Manual
</button>

<!-- Toast -->
<span id="myo-toast" style="color:#475569;font-size:10px;transition:opacity .3s;margin-left:2px"></span>

<!-- Uptime + nav -->
<div style="margin-left:auto;display:flex;align-items:center;gap:6px">
<span id="myo-uptime" style="color:#1e3a5f;font-size:9px;margin-right:4px">⏱ 0s</span>
<span style="color:#0d1f35;font-size:14px"></span>
<a href="/" title="Demo" style="color:#1e3a5f;text-decoration:none;font-size:9px;
padding:3px 7px;border:1px solid transparent;border-radius:4px;transition:all .2s"
onmouseover="this.style.borderColor='#0d1f35';this.style.color='#3b82f6'"
onmouseout="this.style.borderColor='transparent';this.style.color='#1e3a5f'"> Demo</a>
<a href="/ops" title="Operação" style="color:#10b981;text-decoration:none;font-size:9px;
padding:3px 7px;border:1px solid #10b98133;border-radius:4px;
background:#10b98111;font-weight:700;transition:all .2s"
onmouseover="this.style.background='#10b98122'" onmouseout="this.style.background='#10b98111'"> Ops</a>
<a href="/orch" title="ORCH Engine" style="color:#8b5cf6;text-decoration:none;font-size:9px;
padding:3px 7px;border:1px solid #8b5cf633;border-radius:4px;
background:#8b5cf611;font-weight:700;transition:all .2s"
onmouseover="this.style.background='#8b5cf622'" onmouseout="this.style.background='#8b5cf611'"> ORCH</a>
<a href="/dashboard" title="Operacional completo" style="color:#1e3a5f;text-decoration:none;font-size:9px;
padding:3px 6px;border:1px solid transparent;border-radius:4px;transition:all .2s"
onmouseover="this.style.borderColor='#0d1f35'" onmouseout="this.style.borderColor='transparent'"></a>
<a href="/executive" title="Executivo completo" style="color:#1e3a5f;text-decoration:none;font-size:9px;
padding:3px 6px;border:1px solid transparent;border-radius:4px;transition:all .2s"
onmouseover="this.style.borderColor='#0d1f35'" onmouseout="this.style.borderColor='transparent'"></a>
</div>
</div>
<div style="height:52px"></div>
"""


# HTML — Pipeline Visual (bottom bar)


def _build_pipeline_html() -> str:
    nodes_html = ""
    for i, (fase_id, num, label) in enumerate(PIPELINE_STAGES):
        arrow = (
            ""
            if i == len(PIPELINE_STAGES) - 1
            else (
                '<span style="color:#0d1f35;font-size:12px;margin:0 1px;flex-shrink:0">→</span>'
            )
        )
        nodes_html += f"""
<div class="myo-node" data-fase="{fase_id}" style="position:relative;display:inline-flex;align-items:center">
<div class="myo-node-box" data-fase="{fase_id}"
style="display:flex;flex-direction:column;align-items:center;justify-content:center;
width:68px;height:42px;border-radius:8px;border:1px solid #0d1f35;
background:#030810;transition:all .5s;cursor:default;flex-shrink:0">
<span style="color:#0d2a40;font-size:8px;font-weight:800;line-height:1">{num}</span>
<span class="myo-node-lbl" style="color:#1e3a5f;font-size:9px;font-weight:700;
white-space:nowrap;line-height:1.2;margin-top:1px">{label}</span>
<span class="myo-node-proc" style="display:none;color:currentColor;font-size:8px">processando</span>
</div>
<!-- Tooltip hover -->
<div class="myo-tip" style="display:none;position:absolute;bottom:52px;left:50%;
transform:translateX(-50%);background:#0a1828;border:1px solid #1a2d45;
border-radius:10px;padding:10px 14px;font-size:10px;color:#e2e8f0;
white-space:nowrap;z-index:9999;box-shadow:0 8px 32px #00000099;pointer-events:none">
<div style="color:#1e3a5f;font-size:9px;font-weight:800;margin-bottom:6px;text-transform:uppercase;
letter-spacing:.5px">{label}</div>
<div id="tip-{fase_id}-produto" style="font-weight:700;color:#e2e8f0">—</div>
<div id="tip-{fase_id}-status" style="color:#475569;margin-top:3px;font-size:9px">aguardando</div>
<div style="position:absolute;bottom:-5px;left:50%;transform:translateX(-50%);
width:8px;height:8px;background:#0a1828;border-right:1px solid #1a2d45;
border-bottom:1px solid #1a2d45;transform:translateX(-50%) rotate(45deg)"></div>
</div>
</div>{arrow}"""

    return (
        """
<!-- BOTTOM BAR -->
<div id="myo-bottom-bar" style="
position:fixed;bottom:0;left:0;right:0;z-index:9998;
background:#020609;border-top:1px solid #0a1520;
font-family:Inter,system-ui,sans-serif;">

<!-- Pipeline flow -->
<div style="display:flex;align-items:center;justify-content:center;
gap:3px;padding:7px 20px 5px;position:relative;flex-wrap:nowrap;overflow-x:auto">
"""
        + nodes_html
        + """
<!-- Badge autônomo -->
<div id="myo-auto-badge" style="display:none;position:absolute;right:14px;
background:#f59e0b18;border:1px solid #f59e0b44;border-radius:6px;
color:#f59e0b;padding:2px 10px;font-size:9px;font-weight:800">
AUTÔNOMO
</div>
</div>

<!-- Produtos + Log -->
<div style="display:flex;align-items:center;gap:10px;padding:3px 16px 6px;
border-top:1px solid #080f18;overflow:hidden;min-height:24px">
<span style="color:#0d1f35;font-size:8px;font-weight:800;white-space:nowrap;flex-shrink:0">PRODUTOS</span>
<div id="myo-produtos-list" style="display:flex;gap:5px;flex-shrink:0;overflow:hidden;max-width:45%"></div>
<span style="color:#080f18;font-size:12px;flex-shrink:0"></span>
<span style="color:#0d1f35;font-size:8px;font-weight:800;white-space:nowrap;flex-shrink:0">LOG</span>
<div id="myo-log-entries" style="display:flex;gap:12px;overflow:hidden;flex:1;min-width:0"></div>
</div>
</div>
<div style="height:76px"></div>

<style>
/* Pipeline */
.myo-node:hover .myo-tip { display:block !important; }
.myo-node-box.rodando {
border-color:#f59e0b !important; background:#f59e0b08 !important;
animation:myo-pulse 1.4s infinite;
}
.myo-node-box.rodando .myo-node-lbl { color:#f59e0b !important; }
.myo-node-box.rodando .myo-node-proc { display:block !important; }
.myo-node-box.done {
border-color:#10b981 !important; background:#10b98108 !important;
box-shadow:0 0 14px #10b98133;
}
.myo-node-box.done .myo-node-lbl { color:#10b981 !important; }
.myo-node-box.error {
border-color:#ef4444 !important; background:#ef444408 !important;
animation:myo-blink 0.9s infinite;
}
.myo-node-box.error .myo-node-lbl { color:#ef4444 !important; }
/* Chips */
.myo-chip {
display:inline-flex;align-items:center;gap:3px;padding:2px 7px;
border-radius:20px;font-size:9px;font-weight:700;border:1px solid;
white-space:nowrap;transition:all .4s;
}
.myo-chip.rodando { background:#f59e0b0a;border-color:#f59e0b44;color:#f59e0b;animation:myo-pulse 1.4s infinite; }
.myo-chip.done { background:#10b9810a;border-color:#10b98144;color:#10b981; }
.myo-chip.error { background:#ef44440a;border-color:#ef444444;color:#ef4444;animation:myo-blink .9s infinite; }
.myo-chip.idle { background:#0d1f350a;border-color:#0d1f3544;color:#1e3a5f; }
/* Log */
.myo-log { font-size:9px;white-space:nowrap;animation:myo-fadein .5s ease; }
.myo-log.ok { color:#10b981; }
.myo-log.warn { color:#f59e0b; }
.myo-log.error { color:#ef4444; }
.myo-log.info { color:#1e3a5f; }
/* Keyframes */
@keyframes myo-blink { 0%,100%{opacity:1} 50%{opacity:.2} }
@keyframes myo-pulse { 0%,100%{box-shadow:none} 60%{box-shadow:0 0 12px currentColor} }
@keyframes myo-fadein { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }
</style>
"""
    )


# JS — Polling + Actions


def _build_polling_js() -> str:
    return r"""
<script>
// MYO System v3
const API = '';

/* Toast */
function toast(msg, color='#475569') {
const t = document.getElementById('myo-toast');
if (!t) return;
t.textContent = msg; t.style.color = color; t.style.opacity = '1';
setTimeout(() => { t.style.opacity='0'; setTimeout(()=>{ t.textContent=''; },300); }, 5000);
}
function btnLoad(id, on) {
const b = document.getElementById(id);
if (b) { b.disabled = on; b.style.opacity = on ? '0.45' : '1'; }
}

/* Ações */
function runKaizen() {
btnLoad('btn-kaizen', true);
toast('⏳ Iniciando melhoria contínua…', '#10b981');
fetch(API + '/api/run-kaizen', { method:'POST' })
.then(r => r.json())
.then(d => toast(' ' + (d.message||'Kaizen rodando'), '#10b981'))
.catch(() => toast(' Erro ao iniciar Kaizen', '#ef4444'))
.finally(() => btnLoad('btn-kaizen', false));
}

function sugerirEstrategia() {
btnLoad('btn-sugerir', true);
toast(' Analisando histórico…', '#8b5cf6');
fetch(API + '/api/sugerir', { method:'POST' })
.then(r => r.json())
.then(d => {
if (d.sugestao) {
const s = d.sugestao;
const lbl = document.getElementById('myo-sugestao-label');
if (lbl) lbl.innerHTML = ` <b style="color:#a78bfa">${s.objetivo}</b> / ${s.fase} (score ${s.score_medio||'—'})`;
const os = document.getElementById('objetivo-select');
const fs = document.getElementById('fase-select');
if (os) os.value = s.objetivo;
if (fs) fs.value = s.fase;
toast(` Melhor: ${s.objetivo} / ${s.fase}`, '#10b981');
} else {
toast(' ' + (d.message||'Histórico insuficiente'), '#f59e0b');
}
})
.catch(() => toast(' Erro na análise', '#ef4444'))
.finally(() => btnLoad('btn-sugerir', false));
}

function trocarEstrategia() {
const objetivo = document.getElementById('objetivo-select')?.value;
const fase = document.getElementById('fase-select')?.value;
if (!objetivo || !fase) return;
toast(`⏳ Aplicando: ${objetivo} / ${fase}…`, '#f59e0b');
fetch(API + '/api/estrategia', {
method:'POST', headers:{'Content-Type':'application/json'},
body: JSON.stringify({objetivo, fase}),
})
.then(r => r.json())
.then(d => toast((d.status==='bloqueado'?' ':' ')+(d.message||'ok'),
d.status==='bloqueado'?'#f59e0b':'#10b981'))
.catch(() => toast(' Erro ao trocar estratégia','#ef4444'));
}

function iniciarPipeline() {
const obj = prompt('Objetivo do produto (ex: CFO Digital):', 'CFO Digital');
if (!obj) return;
toast(' Iniciando pipeline…', '#06b6d4');
fetch(API + '/api/pipeline/start', {
method:'POST', headers:{'Content-Type':'application/json'},
body: JSON.stringify({objetivo: obj, mode: 'auto'}),
})
.then(r => r.json())
.then(d => toast(' '+(d.message||'Pipeline iniciado'), '#06b6d4'))
.catch(() => toast(' Erro ao iniciar pipeline','#ef4444'));
}

function regenerar() {
toast(' Regenerando…', '#475569');
fetch(API + '/api/regenerar', {method:'POST'})
.then(r => r.json())
.then(() => { toast(' Pronto — recarregando…','#10b981'); setTimeout(()=>location.reload(),1800); })
.catch(() => toast(' Erro ao regenerar','#ef4444'));
}

/* Autonomia 3 níveis */
const _AUTO_CFG = {
0: { label:'⏸ Manual', color:'#475569', bg:'#1a2d4533', border:'#1a2d45' },
1: { label:' Assistido', color:'#38bdf8', bg:'#38bdf818', border:'#38bdf855' },
2: { label:' Autônomo', color:'#f59e0b', bg:'#f59e0b18', border:'#f59e0b55' },
};
let _autoLevel = 0;

function _applyAutoStyle(level) {
_autoLevel = level;
const btn = document.getElementById('btn-autonomo');
const badge = document.getElementById('myo-auto-badge');
const cfg = _AUTO_CFG[level] || _AUTO_CFG[0];
if (btn) {
btn.textContent = cfg.label;
btn.style.color = cfg.color;
btn.style.background = cfg.bg;
btn.style.borderColor = cfg.border;
}
if (badge) badge.style.display = level >= 2 ? 'block' : 'none';
}

function cycleAutonomia() {
const next = (_autoLevel + 1) % 3;
fetch(API + '/api/autonomous', {
method:'POST', headers:{'Content-Type':'application/json'},
body: JSON.stringify({level: next}),
})
.then(r => r.json())
.then(d => {
_applyAutoStyle(d.level ?? next);
const msgs = ['⏸ Modo manual ativado',' Modo assistido — sugestões automáticas',' Modo autônomo — sistema age sozinho'];
toast(msgs[d.level ?? next] || 'Modo alterado', _AUTO_CFG[d.level??next]?.color||'#475569');
})
.catch(() => toast(' Erro ao alternar modo','#ef4444'));
}

/* Polling */
const _ICON = { rodando:'', done:'', error:'', idle:'' };
const _CLS = { rodando:'rodando', done:'done', error:'error', idle:'idle' };

function _syncState() {
fetch(API + '/api/state')
.then(r => r.json())
.then(data => {
const produtos = data.produtos || [];

// Pipeline nodes
document.querySelectorAll('.myo-node-box').forEach(b => b.classList.remove('rodando','done','error'));
produtos.forEach(p => {
const box = document.querySelector(`.myo-node-box[data-fase="${p.fase_atual||''}"]`);
const st = p.status || 'idle';
if (box && st !== 'idle') {
box.classList.add(_CLS[st]||'rodando');
const tp = document.getElementById(`tip-${p.fase_atual}-produto`);
const ts_el = document.getElementById(`tip-${p.fase_atual}-status`);
if (tp) tp.textContent = p.produto || '?';
if (ts_el) ts_el.textContent = `${st} ${p.progresso||0}% ${(p.timestamp||'').slice(11,16)} UTC`;
}
});

// Produto chips
const lista = document.getElementById('myo-produtos-list');
if (lista) {
lista.innerHTML = produtos.length === 0
? '<span style="color:#0d1f35;font-size:8px">nenhum ativo</span>'
: produtos.map(p => {
const st = p.status||'idle';
const prog = p.progresso ? ` ${p.progresso}%` : '';
return `<span class="myo-chip ${_CLS[st]||'idle'}">${_ICON[st]||''} ${p.produto||'?'}`
+ `<span style="font-weight:400;opacity:.55"> ${p.fase_atual||''}${prog}</span></span>`;
}).join('');
}

// Nível de autonomia
const lvl = typeof data.autonomous_level === 'number'
? data.autonomous_level
: (data.autonomous ? 2 : 0);
if (lvl !== _autoLevel) _applyAutoStyle(lvl);
})
.catch(()=>{});
}

function _syncLog() {
fetch(API + '/api/log?n=10')
.then(r => r.json())
.then(entries => {
const c = document.getElementById('myo-log-entries');
if (!c) return;
c.innerHTML = !entries?.length
? '<span style="color:#0a1520;font-size:8px">sem eventos</span>'
: entries.map(e => {
const f = e.fase ? ` [${e.fase}]` : '';
return `<span class="myo-log ${e.status||'info'}">${e.ts} <b>${e.produto}</b>${f} ${e.evento}</span>`;
}).join('');
})
.catch(()=>{});
}

/* Uptime counter */
const _t0 = Date.now();
function _syncUptime() {
const s = Math.floor((Date.now() - _t0) / 1000);
const h = Math.floor(s / 3600);
const m = Math.floor((s % 3600) / 60);
const sec = s % 60;
const el = document.getElementById('myo-uptime');
if (el) el.textContent = h > 0 ? `⏱ ${h}h ${m}m` : m > 0 ? `⏱ ${m}m ${sec}s` : `⏱ ${sec}s`;
}

/* Processing dots animation */
let _dots = 0;
function _animDots() {
_dots = (_dots + 1) % 4;
document.querySelectorAll('.myo-node-proc').forEach(el => {
el.textContent = 'proc' + '.'.repeat(_dots);
});
}

/* Sugestão inicial na barra */
function _loadSugestao() {
fetch(API + '/api/sugerir', {method:'POST'})
.then(r => r.json())
.then(d => {
const lbl = document.getElementById('myo-sugestao-label');
if (!lbl) return;
if (d.sugestao) {
const s = d.sugestao;
lbl.innerHTML = ` <b style="color:#a78bfa">${s.objetivo}</b> / ${s.fase}`;
} else {
lbl.textContent = ' Rode ciclos para obter sugestões';
}
})
.catch(()=>{});
}

/* Init */
// Carrega nível de autonomia inicial
fetch(API + '/api/autonomous').then(r=>r.json()).then(d=>{
_applyAutoStyle(d.level ?? (d.enabled ? 2 : 0));
}).catch(()=>{});

setInterval(_syncState, 2000);
setInterval(_syncLog, 2500);
setInterval(_syncUptime, 1000);
setInterval(_animDots, 400);

_syncState();
_syncLog();
_syncUptime();
setTimeout(_loadSugestao, 2000);
</script>
"""


# HTML — Home Executiva


def _build_home_html() -> str:
    s = _load_live_stats()

    # Formatação KPIs
    receita = (
        f"R$ {s['receita_protegida']:,.0f}".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )
    auto_str = s["taxa_sucesso"]
    semanal = s["melhoria_semanal"]
    total = s["kaizen_aplicados"]
    obj_lbl = OBJ_LABEL.get(s["objetivo_atual"], s["objetivo_atual"])
    fase_lbl = FASE_LABEL.get(s["fase_negocio"], s["fase_negocio"])
    lvl = s["autonomous_level"]

    # Tendência semanal
    tend = s.get("tendencia_semanal", 0)
    tend_icon = "↑" if tend > 0 else ("↓" if tend < 0 else "→")
    tend_color = "#10b981" if tend > 0 else ("#ef4444" if tend < 0 else "#475569")
    tend_label = f"{tend_icon} {abs(tend)}% vs semana anterior"

    # Status geral
    n_crit = sum(1 for a in s["alertas"] if a["nivel"] == "critico")
    n_warn = sum(1 for a in s["alertas"] if a["nivel"] == "aviso")
    if n_crit:
        st_icon, st_label, st_color, st_bg = (
            "",
            f"{n_crit} alerta(s) crítico(s) — ação necessária",
            "#ef4444",
            "#ef444410",
        )
    elif n_warn:
        st_icon, st_label, st_color, st_bg = (
            "",
            f"{n_warn} aviso(s) — monitorar",
            "#f59e0b",
            "#f59e0b10",
        )
    else:
        st_icon, st_label, st_color, st_bg = (
            "",
            "Sistema saudável — operando normalmente",
            "#10b981",
            "#10b98110",
        )

        # Próxima ação
        px = s.get("proxima_acao", {})

        # Alertas HTML
        alertas_html = ""
        for al in s["alertas"]:
            lc = "#ef4444" if al["nivel"] == "critico" else "#f59e0b"
            alertas_html += f"""
<div style="background:{lc}0a;border:1px solid {lc}33;border-radius:12px;padding:18px 22px;
display:flex;align-items:flex-start;gap:16px">
<span style="font-size:22px;flex-shrink:0">{al['icon']}</span>
<div style="flex:1;min-width:0">
<div style="color:{lc};font-weight:800;font-size:14px;margin-bottom:2px">{al['titulo']}</div>
<div style="color:#64748b;font-size:11px;margin-bottom:6px">{al['descricao']}</div>
<div style="color:{lc}cc;font-size:12px;font-weight:700;margin-bottom:8px;
background:{lc}11;border-radius:6px;padding:6px 12px;display:inline-block">
{al.get('impacto', '')}
</div>
<div style="color:#475569;font-size:11px;margin-bottom:12px">
<em>{al['sugestao']}</em>
</div>
<button onclick="{al['acao_js']}"
style="background:{lc};color:#fff;border:none;border-radius:8px;
padding:8px 18px;cursor:pointer;font-size:11px;font-weight:800;
box-shadow:0 0 16px {lc}44">
{al['acao_label']} →
</button>
</div>
</div>"""

    # Produtos HTML
    produtos_html = ""
    for p in s["produtos"]:
        st = p.get("status", "idle")
        icon = {"rodando": "", "done": "", "error": "", "idle": ""}.get(st, "")
        color = {
            "rodando": "#f59e0b",
            "done": "#10b981",
            "error": "#ef4444",
            "idle": "#1e3a5f",
        }.get(st, "#1e3a5f")
        ts = (p.get("timestamp") or "")[:16].replace("T", " ")
        prog = p.get("progresso", 0)
        fase = p.get("fase_atual", "")
        produtos_html += f"""
<div style="background:#060d17;border:1px solid #0d1f35;border-radius:10px;
padding:12px 18px;display:flex;align-items:center;gap:14px;transition:all .3s"
onmouseover="this.style.borderColor='{color}44'"
onmouseout="this.style.borderColor='#0d1f35'">
<span style="font-size:22px">{icon}</span>
<div style="flex:1">
<div style="color:{color};font-weight:800;font-size:14px">{p.get('produto','?')}</div>
<div style="color:#1e3a5f;font-size:11px;margin-top:2px">
{fase} · {prog}% · {ts}
</div>
</div>
<div style="background:{color}18;border:1px solid {color}44;border-radius:6px;
padding:3px 10px;color:{color};font-size:10px;font-weight:700">
{st}
</div>
</div>"""

    if not produtos_html:
        produtos_html = '<div style="color:#0d1f35;font-size:12px;padding:8px 0">Nenhum produto em execução — clique em Pipeline para iniciar.</div>'

    # Nível autonomia label
    auto_labels = {0: "⏸ Manual", 1: " Assistido", 2: " Autônomo"}
    auto_label = auto_labels.get(lvl, "⏸ Manual")

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MYO System</title>
<style>
*, *::before, *::after {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#020609; color:#e2e8f0; font-family:Inter,system-ui,sans-serif; min-height:100vh; }}
.card {{ background:#060d17; border:1px solid #0d1f35; border-radius:12px; padding:20px 24px; }}
.section-lbl {{
color:#0d2a40; font-size:9px; font-weight:800; text-transform:uppercase;
letter-spacing:1px; margin-bottom:12px; display:flex; align-items:center; gap:6px;
}}
details summary {{ list-style:none; cursor:pointer; }}
details summary::-webkit-details-marker {{ display:none; }}
</style>
</head>
<body>
<div style="max-width:1080px;margin:0 auto;padding:24px 18px;display:flex;flex-direction:column;gap:18px">

<!-- HERO -->
<div style="text-align:center;padding:16px 0 4px">
<div style="color:#1e3a5f;font-size:9px;font-weight:800;text-transform:uppercase;
letter-spacing:3px;margin-bottom:10px">MYO SYSTEM · OPERADOR DIGITAL</div>
<h1 style="color:#e2e8f0;font-size:26px;font-weight:800;line-height:1.25;
max-width:640px;margin:0 auto">
Seu negócio está sendo operado por IA<br>
<span style="background:linear-gradient(90deg,#3b82f6,#8b5cf6);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;
background-clip:text">
com decisões otimizadas continuamente
</span>
</h1>
<div style="color:#0d2a40;font-size:11px;margin-top:10px;display:flex;
align-items:center;justify-content:center;gap:14px">
<span id="myo-hero-uptime">⏱ calculando…</span>
<span>·</span>
<span style="color:{st_color}">{st_icon} {st_label}</span>
<span>·</span>
<span style="color:#1e3a5f">{auto_label}</span>
</div>
</div>

<!-- KPIs -->
<section>
<div class="section-lbl"> visão executiva — agora</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px">

<div class="card">
<div style="font-size:28px;font-weight:800;color:#10b981;letter-spacing:-1px">{receita}</div>
<div style="color:#1e3a5f;font-size:10px;font-weight:600;margin-top:3px"> impacto em receita</div>
</div>

<div class="card">
<div style="font-size:28px;font-weight:800;color:#3b82f6;letter-spacing:-1px">{auto_str}%</div>
<div style="color:#1e3a5f;font-size:10px;font-weight:600;margin-top:3px"> resolvido automaticamente</div>
</div>

<div class="card">
<div style="display:flex;align-items:baseline;gap:8px">
<span style="font-size:28px;font-weight:800;color:#8b5cf6;letter-spacing:-1px">+{semanal}</span>
<span style="font-size:11px;font-weight:700;color:{tend_color}">{tend_label}</span>
</div>
<div style="color:#1e3a5f;font-size:10px;font-weight:600;margin-top:3px"> melhorias esta semana</div>
</div>

<div class="card">
<div style="font-size:28px;font-weight:800;color:#f59e0b;letter-spacing:-1px">{total}</div>
<div style="color:#1e3a5f;font-size:10px;font-weight:600;margin-top:3px"> kaizens aplicados total</div>
</div>
</div>
</section>

<!-- STATUS + DIREÇÃO -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
<div class="card" style="background:{st_bg};border-color:{st_color}33">
<div class="section-lbl" style="color:{st_color}88"> status do sistema</div>
<div style="display:flex;align-items:center;gap:12px">
<span style="font-size:26px">{st_icon}</span>
<div>
<div style="color:{st_color};font-weight:800;font-size:13px">{st_label}</div>
<div style="color:#1e3a5f;font-size:10px;margin-top:3px">{auto_label}</div>
</div>
</div>
</div>
<div class="card">
<div class="section-lbl"> direção estratégica</div>
<div style="display:flex;flex-direction:column;gap:8px">
<div style="display:flex;justify-content:space-between;align-items:center">
<span style="color:#1e3a5f;font-size:10px">Estratégia</span>
<span style="color:#a78bfa;font-weight:800;font-size:12px">{obj_lbl}</span>
</div>
<div style="display:flex;justify-content:space-between;align-items:center">
<span style="color:#1e3a5f;font-size:10px">Fase</span>
<span style="color:#38bdf8;font-weight:800;font-size:12px">{fase_lbl}</span>
</div>
</div>
</div>
</div>

<!-- PRÓXIMA AÇÃO -->
<div class="card" style="border-color:{px.get('cor','#3b82f6')}44;background:{px.get('cor','#3b82f6')}08">
<div class="section-lbl"> próxima ação recomendada</div>
<div style="display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap">
<div style="display:flex;align-items:flex-start;gap:14px">
<span style="font-size:22px;flex-shrink:0">{px.get('icon','')}</span>
<div>
<div style="color:{px.get('cor','#3b82f6')};font-weight:800;font-size:14px">
{px.get('titulo','—')}
</div>
<div style="color:#1e3a5f;font-size:11px;margin-top:4px">{px.get('descricao','—')}</div>
</div>
</div>
<button onclick="{px.get('acao_js','runKaizen()')}"
style="background:{px.get('cor','#3b82f6')};color:#fff;border:none;border-radius:10px;
padding:11px 24px;cursor:pointer;font-weight:800;font-size:12px;flex-shrink:0;
box-shadow:0 0 20px {px.get('cor','#3b82f6')}55;transition:all .3s"
onmouseover="this.style.transform='scale(1.04)'"
onmouseout="this.style.transform='scale(1)'">
→ {px.get('acao','Agir')}
</button>
</div>
<div style="margin-top:10px">
<span style="background:{px.get('cor','#3b82f6')}18;color:{px.get('cor','#3b82f6')};
border:1px solid {px.get('cor','#3b82f6')}33;border-radius:4px;
padding:2px 8px;font-size:9px;font-weight:800">{px.get('impacto','—').upper()}</span>
</div>
</div>

<!-- ALERTAS -->
{"" if not alertas_html else f'<section><div class="section-lbl"> alertas com ação decisiva</div><div style="display:flex;flex-direction:column;gap:10px">' + alertas_html + '</div></section>'}

<!-- MULTI-PRODUTO -->
<details open>
<summary>
<div class="section-lbl" style="cursor:pointer">
produtos em execução
<span style="color:#0a1828;font-weight:400;margin-left:4px"></span>
</div>
</summary>
<div style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
{produtos_html}
</div>
</details>

<!-- DASHBOARDS -->
<details>
<summary>
<div class="section-lbl" style="cursor:pointer">
dashboards detalhados
<span style="color:#0a1828;font-weight:400;margin-left:4px"></span>
</div>
</summary>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:4px">
<a href="/dashboard" style="text-decoration:none">
<div class="card" style="cursor:pointer;transition:all .3s"
onmouseover="this.style.borderColor='#3b82f655';this.style.background='#0d1f3522'"
onmouseout="this.style.borderColor='#0d1f35';this.style.background='#060d17'">
<div style="color:#3b82f6;font-size:22px;margin-bottom:8px"></div>
<div style="color:#e2e8f0;font-weight:700;font-size:13px">Dashboard Operacional</div>
<div style="color:#1e3a5f;font-size:10px;margin-top:4px">Kaizen · Logs · Histórico · Testes A/B</div>
</div>
</a>
<a href="/executive" style="text-decoration:none">
<div class="card" style="cursor:pointer;transition:all .3s"
onmouseover="this.style.borderColor='#8b5cf655';this.style.background='#0d1f3522'"
onmouseout="this.style.borderColor='#0d1f35';this.style.background='#060d17'">
<div style="color:#8b5cf6;font-size:22px;margin-bottom:8px"></div>
<div style="color:#e2e8f0;font-weight:700;font-size:13px">Dashboard Executivo</div>
<div style="color:#1e3a5f;font-size:10px;margin-top:4px">KPIs · Estratégia · ROI · Visão C-Level</div>
</div>
</a>
</div>
</details>

</div>

<script>
// Uptime do hero (independente do bar de cima)
const _hero_t0 = Date.now();
function _heroUptime() {{
const s = Math.floor((Date.now()-_hero_t0)/1000);
const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
const el = document.getElementById('myo-hero-uptime');
if (el) el.textContent = h>0?`⏱ ${{h}}h ${{m}}m`:m>0?`⏱ ${{m}}m ${{sec}}s`:`⏱ ${{sec}}s`;
}}
setInterval(_heroUptime, 1000);
</script>
</body>
</html>"""


# HTML — Ops Mode


def _build_ops_html() -> str:
    """Ops mode — pipeline central, inline styles, zero dependências externas."""
    s = _load_live_stats()
    px = s.get("proxima_acao", {})

    receita = (
        f"R${s['receita_protegida']:,.0f}".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )
    tend = s.get("tendencia_semanal", 0)
    tend_sym = "↑" if tend > 0 else ("↓" if tend < 0 else "→")
    tend_col = "#4ade80" if tend > 0 else ("#f87171" if tend < 0 else "#6b7280")

    n_crit = sum(1 for a in s["alertas"] if a["nivel"] == "critico")
    n_warn = sum(1 for a in s["alertas"] if a["nivel"] == "aviso")
    sys_icon = "" if n_crit else ("" if n_warn else "")
    sys_txt = (
        f"{n_crit} ALERTA CRÍTICO"
        if n_crit
        else (f"{n_warn} aviso" if n_warn else "OK")
    )
    sys_col = "#f87171" if n_crit else ("#facc15" if n_warn else "#4ade80")

    lvl = s["autonomous_level"]
    auto_lbl = {0: "⏸ Manual", 1: " Assistido", 2: " Autônomo"}.get(lvl, "⏸ Manual")
    auto_col = {0: "#6b7280", 1: "#38bdf8", 2: "#facc15"}.get(lvl, "#6b7280")

    obj_lbl = OBJ_LABEL.get(s["objetivo_atual"], s["objetivo_atual"]).split(" ", 1)[-1]
    fase_lbl = FASE_LABEL.get(s["fase_negocio"], s["fase_negocio"]).split(" ", 1)[-1]

    px_cor = px.get("cor", "#3b82f6")
    px_js = px.get("acao_js", "run()")
    px_acao = px.get("acao", "Executar")
    px_title = px.get("titulo", "Melhorar sistema")
    px_desc = px.get("descricao", "")
    px_icon = px.get("icon", "")

    # Pipeline nodes — JS atualiza as classes/estilos
    nodes_html = ""
    for i, (fase_id, num, label) in enumerate(PIPELINE_STAGES):
        arrow = (
            ""
            if i == len(PIPELINE_STAGES) - 1
            else '<div style="color:#1e293b;font-size:22px;padding:0 8px;flex-shrink:0">→</div>'
        )
        nodes_html += f"""
<div id="node-{fase_id}" style="text-align:center;flex-shrink:0;transition:all .5s">
<div id="node-label-{fase_id}"
style="font-weight:700;color:#1e293b;transition:all .5s">{num} {label}</div>
<div id="node-prod-{fase_id}"
style="font-size:12px;color:#f59e0b;margin-top:6px;display:none"></div>
</div>{arrow}"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MYO · Ops</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
html, body {{ height:100%; overflow:hidden; background:#0f172a; color:#e5e7eb;
font-family:Inter,system-ui,sans-serif; }}
button {{ font-family:inherit; cursor:pointer; transition:all .2s; }}
button:hover {{ opacity:.85; }}
@keyframes glow {{ 0%,100%{{text-shadow:none}} 60%{{text-shadow:0 0 20px currentColor}} }}
@keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:.15}} }}
.node-active {{ animation:glow 1.5s infinite; }}
.node-error {{ animation:blink .9s infinite; }}
</style>
</head>
<body>

<!-- TOP BAR -->
<div style="height:44px;display:flex;justify-content:space-between;align-items:center;
padding:0 20px;background:#020617;border-bottom:1px solid #1e293b;
position:fixed;top:0;left:0;right:0;z-index:100">

<div style="display:flex;align-items:center;gap:10px;font-size:12px;font-weight:600">
<span id="sys-icon" style="color:{sys_col}">{sys_icon}</span>
<span id="sys-label" style="color:{sys_col}">{sys_txt}</span>
<span style="color:#1e293b">·</span>
<span id="sys-strat" style="color:#475569;font-size:11px">{obj_lbl} / {fase_lbl}</span>
<span style="color:#1e293b">·</span>
<span id="sys-uptime" style="color:#1e293b;font-size:10px">⏱ 0s</span>
</div>

<div style="display:flex;align-items:center;gap:8px">
<button id="btn-run" onclick="run()"
style="background:#10b981;color:#fff;border:none;border-radius:7px;
padding:7px 18px;font-weight:700;font-size:12px;box-shadow:0 0 12px #10b98133">
Rodar
</button>
<button id="btn-suggest" onclick="applySuggestion()"
style="background:#1e1b4b;color:#a78bfa;border:1px solid #4c1d95;
border-radius:7px;padding:7px 16px;font-weight:700;font-size:12px">
Sugestão
</button>
<button id="btn-mode" onclick="toggleMode()"
style="background:#111827;color:{auto_col};border:1px solid {auto_col}55;
border-radius:7px;padding:7px 14px;font-weight:700;font-size:12px">
{auto_lbl}
</button>
<button onclick="toggleConfig()"
style="background:#111827;color:#6b7280;border:1px solid #374151;
border-radius:7px;padding:7px 12px;font-size:13px">

</button>
<a href="/"
style="background:#111827;color:#475569;border:1px solid #1e293b;border-radius:7px;
padding:7px 12px;font-size:11px;text-decoration:none;font-weight:600">

</a>
</div>
</div>

<!-- Config panel -->
<div id="config-panel"
style="display:none;position:fixed;top:52px;right:16px;z-index:500;
background:#0c1120;border:1px solid #1e293b;border-radius:10px;
padding:14px;min-width:200px;box-shadow:0 8px 32px #00000099">
<div style="color:#334155;font-size:9px;font-weight:800;text-transform:uppercase;
letter-spacing:1px;margin-bottom:8px">Estratégia</div>
<select id="cfg-obj" style="width:100%;background:#0f172a;color:#9ca3af;
border:1px solid #1e293b;border-radius:5px;padding:6px 8px;font-size:10px;margin-bottom:6px">
<option value="maximizar_receita"> Maximizar Receita</option>
<option value="reduzir_custo"> Reduzir Custo</option>
<option value="aumentar_conversao"> Aumentar Conversão</option>
<option value="equilibrio" selected> Equilíbrio</option>
</select>
<select id="cfg-fase" style="width:100%;background:#0f172a;color:#9ca3af;
border:1px solid #1e293b;border-radius:5px;padding:6px 8px;font-size:10px;margin-bottom:8px">
<option value="validacao" selected> Validação</option>
<option value="escala"> Escala</option>
<option value="lucro"> Lucro</option>
<option value="produto"> Produto</option>
</select>
<button onclick="applyStrategy()"
style="width:100%;background:#f59e0b18;color:#f59e0b;border:1px solid #f59e0b44;
border-radius:5px;padding:6px;font-size:10px;font-weight:700;margin-bottom:4px">
Aplicar estratégia
</button>
<button onclick="startPipeline()"
style="width:100%;background:#06b6d411;color:#06b6d4;border:1px solid #06b6d433;
border-radius:5px;padding:6px;font-size:10px;font-weight:700">
Novo pipeline
</button>
</div>

<!-- PIPELINE CENTRAL -->
<div style="position:fixed;top:44px;bottom:100px;left:0;right:0;
display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px">

<div style="display:flex;align-items:center;justify-content:center">
{nodes_html}
</div>

<!-- Produtos ativos -->
<div id="produtos-chips" style="display:flex;flex-wrap:wrap;justify-content:center;gap:8px"></div>
</div>

<!-- AÇÃO RECOMENDADA -->
<div style="position:fixed;bottom:44px;left:50%;transform:translateX(-50%);
display:flex;align-items:center;gap:16px;
background:#0c1a2e;border:1px solid #1e293b;border-radius:10px;
padding:12px 20px;min-width:300px;max-width:500px">
<span style="font-size:18px;flex-shrink:0" id="action-icon">{px_icon}</span>
<div style="flex:1;min-width:0">
<div style="color:{px_cor};font-weight:700;font-size:12px" id="action-title">{px_title}</div>
<div style="color:#475569;font-size:10px;margin-top:2px;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis" id="action-desc">{px_desc}</div>
</div>
<button id="btn-execute" onclick="{px_js}"
style="background:{px_cor};color:#fff;border:none;border-radius:8px;
padding:9px 20px;font-weight:700;font-size:12px;flex-shrink:0;
box-shadow:0 0 16px {px_cor}44">
→ {px_acao}
</button>
</div>

<!-- STRIP BASE -->
<div style="position:fixed;bottom:0;left:0;right:0;height:44px;
background:#020617;border-top:1px solid #1e293b;
display:flex;align-items:center;justify-content:center;
gap:18px;font-size:11px;font-weight:700">
<span>{receita}</span>
<span style="color:#1e293b">·</span>
<span style="color:{tend_col}">{tend_sym}{abs(tend)}%</span>
<span style="color:#1e293b">·</span>
<span> {s['taxa_sucesso']}%</span>
<span style="color:#1e293b">·</span>
<span style="color:{'#f87171' if n_crit else '#facc15' if n_warn else '#374151'}">
{n_crit+n_warn}
</span>
</div>

<!-- Toast -->
<div id="toast" style="position:fixed;top:52px;left:50%;transform:translateX(-50%);
background:#0c1120;border:1px solid #1e293b;border-radius:8px;padding:8px 18px;
font-size:11px;pointer-events:none;opacity:0;transition:opacity .3s;z-index:9999;
white-space:nowrap"></div>

<script>
//
const STEPS = ['opportunity','product','content','video','sales','performance'];
const ICONS = {{ rodando:'', done:'', error:'', idle:'' }};

// Toast
let _tt;
function toast(msg, color='#9ca3af') {{
const el = document.getElementById('toast');
el.textContent = msg; el.style.color = color;
el.style.borderColor = color + '55'; el.style.opacity = '1';
clearTimeout(_tt);
_tt = setTimeout(() => el.style.opacity='0', 4000);
}}

// Ações
async function run() {{
const b = document.getElementById('btn-run');
if (b) {{ b.disabled=true; b.style.opacity='.5'; }}
toast('⏳ Iniciando…', '#4ade80');
const r = await fetch('/api/run-kaizen', {{method:'POST'}}).catch(()=>null);
const d = r ? await r.json().catch(()=>{{}}) : {{}};
toast(' ' + (d.message||'Kaizen rodando'), '#4ade80');
if (b) {{ b.disabled=false; b.style.opacity='1'; }}
}}

async function applySuggestion() {{
const b = document.getElementById('btn-suggest');
if (b) {{ b.disabled=true; b.style.opacity='.5'; }}
toast(' Consultando…', '#a78bfa');
const r = await fetch('/api/sugerir', {{method:'POST'}}).catch(()=>null);
const d = r ? await r.json().catch(()=>{{}}) : {{}};
if (d.sugestao) {{
const s = d.sugestao;
toast(' Melhor: ' + s.objetivo + ' / ' + s.fase, '#4ade80');
const co = document.getElementById('cfg-obj');
const cf = document.getElementById('cfg-fase');
if (co) co.value = s.objetivo;
if (cf) cf.value = s.fase;
}} else {{
toast(' ' + (d.message||'Histórico insuficiente'), '#facc15');
}}
if (b) {{ b.disabled=false; b.style.opacity='1'; }}
}}

async function toggleMode() {{
const r = await fetch('/api/autonomous').catch(()=>null);
const d = r ? await r.json().catch(()=>{{}}) : {{}};
const next = ((d.level??0) + 1) % 3;
const r2 = await fetch('/api/autonomous', {{
method:'POST', headers:{{'Content-Type':'application/json'}},
body: JSON.stringify({{level: next}})
}}).catch(()=>null);
const d2 = r2 ? await r2.json().catch(()=>{{}}) : {{level:next}};
const lvl = d2.level ?? next;
const labels = {{0:'⏸ Manual', 1:' Assistido', 2:' Autônomo'}};
const colors = {{0:'#6b7280', 1:'#38bdf8', 2:'#facc15'}};
const btn = document.getElementById('btn-mode');
if (btn) {{
btn.textContent = labels[lvl];
btn.style.color = colors[lvl];
btn.style.borderColor = colors[lvl] + '55';
}}
toast(d2.message||'Modo alterado', colors[lvl]);
}}

function toggleConfig() {{
const p = document.getElementById('config-panel');
p.style.display = p.style.display === 'none' ? 'block' : 'none';
}}
document.addEventListener('click', e => {{
const p = document.getElementById('config-panel');
if (p?.style.display !== 'none' && !p?.contains(e.target) &&
!e.target.closest('[onclick="toggleConfig()"]')) {{
if (p) p.style.display = 'none';
}}
}});

async function applyStrategy() {{
const obj = document.getElementById('cfg-obj')?.value;
const fase = document.getElementById('cfg-fase')?.value;
if (!obj || !fase) return;
toast('⏳ Aplicando…', '#facc15');
const r = await fetch('/api/estrategia', {{
method:'POST', headers:{{'Content-Type':'application/json'}},
body: JSON.stringify({{objetivo:obj, fase}})
}}).catch(()=>null);
const d = r ? await r.json().catch(()=>{{}}) : {{}};
toast((d.status==='bloqueado'?' ':' ')+(d.message||'ok'),
d.status==='bloqueado'?'#facc15':'#4ade80');
toggleConfig();
}}

async function startPipeline() {{
const obj = prompt('Objetivo do produto:', 'CFO Digital');
if (!obj) return;
await fetch('/api/pipeline/start', {{
method:'POST', headers:{{'Content-Type':'application/json'}},
body: JSON.stringify({{objetivo:obj, mode:'auto'}})
}}).catch(()=>null);
toast(' Pipeline iniciado: ' + obj, '#38bdf8');
toggleConfig();
}}

// Pipeline live update
function _resetNodes() {{
STEPS.forEach(id => {{
const n = document.getElementById('node-' + id);
const l = document.getElementById('node-label-' + id);
const p = document.getElementById('node-prod-' + id);
if (n) n.className = '';
if (l) {{ l.style.color = '#1e293b'; l.style.fontSize = '14px'; l.style.fontWeight = '700'; }}
if (p) {{ p.style.display = 'none'; p.textContent = ''; }}
}});
}}

async function syncPipeline() {{
const r = await fetch('/api/state').catch(()=>null);
if (!r) return;
const data = await r.json().catch(()=>{{}});
const produtos = data.produtos || [];

_resetNodes();

// Produto principal (primeiro ativo)
const ativo = produtos.find(p=>p.status==='rodando')
|| produtos.find(p=>p.status==='error')
|| null;

if (ativo) {{
const faseIdx = STEPS.indexOf(ativo.fase_atual || '');

STEPS.forEach((id, i) => {{
const lbl = document.getElementById('node-label-' + id);
const prod = document.getElementById('node-prod-' + id);
if (!lbl) return;

if (i < faseIdx) {{
// Concluído
lbl.style.color = '#4ade80';
lbl.style.fontSize = '13px';
}} else if (i === faseIdx) {{
// Ativo — GRANDE
lbl.style.color = '#facc15';
lbl.style.fontSize = '28px';
lbl.style.fontWeight = '800';
const node = document.getElementById('node-' + id);
if (node) node.className = ativo.status === 'error' ? 'node-error' : 'node-active';
if (prod) {{
prod.style.display = 'block';
prod.innerHTML = (ativo.produto||'?') + '<br><span style="color:#d97706">' + (ativo.progresso||0) + '%</span>';
}}
}}
// Próximos: ficam escuros (padrão #1e293b)
}});
}}

// Chips multi-produto
const chips = document.getElementById('produtos-chips');
if (chips) {{
chips.innerHTML = produtos.length === 0 ? '' :
produtos.map(p => {{
const st = p.status||'idle';
const col = {{rodando:'#facc15',done:'#4ade80',error:'#f87171',idle:'#334155'}}[st]||'#334155';
return `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;
border-radius:20px;font-size:10px;font-weight:700;border:1px solid ${{col}}44;
background:${{col}}0a;color:${{col}}">${{ICONS[st]||''}} ${{p.produto||'?'}} — ${{p.fase_atual||''}} ${{p.progresso||0}}%</span>`;
}}).join('');
}}

// Botão modo autônomo
const lvl = data.autonomous_level ?? (data.autonomous ? 2 : 0);
const bm = document.getElementById('btn-mode');
if (bm) {{
const ls = {{0:'⏸ Manual',1:' Assistido',2:' Autônomo'}};
const cs = {{0:'#6b7280',1:'#38bdf8',2:'#facc15'}};
bm.textContent = ls[lvl]; bm.style.color = cs[lvl];
bm.style.borderColor = cs[lvl] + '55';
}}
}}

// Uptime
const _t0 = Date.now();
function _uptime() {{
const s = Math.floor((Date.now()-_t0)/1000);
const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60;
const el = document.getElementById('sys-uptime');
if (el) el.textContent = h>0?`⏱ ${{h}}h ${{m}}m`:m>0?`⏱ ${{m}}m ${{sec}}s`:`⏱ ${{sec}}s`;
}}

setInterval(syncPipeline, 2000);
setInterval(_uptime, 1000);
syncPipeline();
_uptime();
</script>
</body>
</html>"""


# Inject controls


def _inject_controls(html: str, dashboard_type: str = "main") -> str:
    controls = _build_controls_html(dashboard_type)
    pipeline = _build_pipeline_html()
    polling = _build_polling_js()
    if "<body" in html:
        idx = html.index("<body")
        idx = html.index(">", idx) + 1
        html = html[:idx] + controls + pipeline + html[idx:]
    else:
        html = html.replace("</body>", controls + pipeline + "</body>")
    html = html.replace("</body>", polling + "</body>")
    return html


# Routes


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(_inject_controls(_build_home_html(), "home"))


@app.get("/ops", response_class=HTMLResponse)
async def ops_mode():
    """Interface operacional — pipeline central, zero distração."""
    return HTMLResponse(_build_ops_html())


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_main():
    _regenerar_dashboard()
    html = (
        DASHBOARD_HTML.read_text(encoding="utf-8")
        if DASHBOARD_HTML.exists()
        else (
            "<html><body><p>Dashboard não gerado. Rode generate_dashboard.py</p></body></html>"
        )
    )
    return HTMLResponse(_inject_controls(html, "main"))


@app.get("/executive", response_class=HTMLResponse)
async def dashboard_executive():
    _regenerar_executive()
    html = (
        EXEC_DASH_HTML.read_text(encoding="utf-8")
        if EXEC_DASH_HTML.exists()
        else ("<html><body><p>Dashboard executivo não gerado.</p></body></html>")
    )
    return HTMLResponse(_inject_controls(html, "executive"))


# API


@app.get("/api/home-data")
async def home_data():
    return JSONResponse(_load_live_stats())


@app.get("/api/state")
async def get_state():
    state = _read_state()
    state["autonomous"] = _read_autonomous()
    state["autonomous_level"] = _read_autonomous_level()
    return JSONResponse(state)


@app.get("/api/log")
async def get_log(n: int = 50):
    if not LOG_FILE.exists():
        return JSONResponse([])
        try:
            lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            entries = []
            for line in lines[-n:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
                return JSONResponse(list(reversed(entries)))
        except Exception:
            return JSONResponse([])


@app.get("/api/autonomous")
async def get_autonomous():
    lvl = _read_autonomous_level()
    return {"level": lvl, "enabled": lvl >= 2}


@app.post("/api/autonomous")
async def set_autonomous(body: dict):
    # Aceita level (0/1/2) ou enabled (bool)
    if "level" in body:
        lvl = max(0, min(2, int(body["level"])))
    else:
        lvl = 2 if body.get("enabled") else 0
        _write_autonomous_level(lvl)
        labels = {0: "Manual", 1: "Assistido", 2: "Autônomo"}
        log_evento(
            "Sistema",
            f"Modo {labels[lvl]} ativado",
            status="warn" if lvl == 2 else "info",
        )
        return {
            "level": lvl,
            "enabled": lvl >= 2,
            "message": f"Modo {labels[lvl]} ativado",
        }


@app.get("/api/kaizen")
async def get_kaizen():
    try:
        from scripts.generate_dashboard import load_kaizen_data

        os.chdir(str(BASE_DIR))
        return JSONResponse(load_kaizen_data())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


class EstrategiaBody(BaseModel):
    objetivo: str
    fase: str
    contexto: str = "normal"


class PipelineBody(BaseModel):
    objetivo: str = "CFO Digital"
    mode: str = "auto"


@app.post("/api/run-kaizen")
async def run_kaizen():
    def _run():
        atualizar_fase("kaizen", "rodando", produto="Kaizen Engine")
        log_evento("Kaizen Engine", "Ciclo iniciado", fase="kaizen", status="info")
        result = subprocess.run(
            [sys.executable, "kaizen_engine.py"],
            cwd=str(BASE_DIR),
            capture_output=True,
            timeout=120,
        )
        ok = result.returncode == 0
        log_evento(
            "Kaizen Engine",
            "Ciclo concluído" if ok else "Erro no ciclo",
            fase="kaizen",
            status="ok" if ok else "error",
        )
        atualizar_fase("idle", "done", produto="Kaizen Engine")
        if _read_autonomous() and ok:
            import time

            time.sleep(3600)
            _run()

            threading.Thread(target=_run, daemon=True).start()
            log_evento("Kaizen Engine", "Kaizen iniciado via dashboard", status="info")
            return {"status": "ok", "message": "Kaizen iniciado em background"}


@app.post("/api/sugerir")
async def sugerir_estrategia():
    try:
        os.chdir(str(BASE_DIR))
        from agents.strategic_memory import (
            sugerir_melhor_estrategia_completo,
            init_strategic_db,
        )

        init_strategic_db()
        sugestao = sugerir_melhor_estrategia_completo()
        return (
            {"sugestao": sugestao}
            if sugestao
            else {
                "sugestao": None,
                "message": "Histórico insuficiente — rode mais ciclos Kaizen",
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/estrategia")
async def trocar_estrategia(body: EstrategiaBody):
    if body.objetivo not in OBJETIVOS_VALIDOS:
        raise HTTPException(400, f"Objetivo inválido. Válidos: {OBJETIVOS_VALIDOS}")
        if body.fase not in FASES_VALIDAS:
            raise HTTPException(400, f"Fase inválida. Válidas: {FASES_VALIDAS}")
            try:
                os.chdir(str(BASE_DIR))
                from agents.strategic_memory import (
                    registrar_estrategia,
                    pode_mudar_estrategia,
                    dias_desde_ultima_mudanca,
                    init_strategic_db,
                    MUDANCA_MINIMA_DIAS,
                )

                init_strategic_db()
                if not pode_mudar_estrategia():
                    restam = MUDANCA_MINIMA_DIAS - dias_desde_ultima_mudanca()
                    return JSONResponse(
                        {
                            "status": "bloqueado",
                            "message": f"Mudança bloqueada — {restam} dia(s) restantes",
                        }
                    )
                    registrar_estrategia(
                        body.objetivo,
                        body.fase,
                        motivo="manual",
                        contexto=body.contexto,
                    )
                    return {
                        "status": "ok",
                        "message": f"Estratégia aplicada: {body.objetivo} / {body.fase}",
                    }
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/pipeline/start")
async def pipeline_start(body: PipelineBody):
    def _run():
        atualizar_fase("opportunity", "rodando", produto=body.objetivo)
        log_evento(
            body.objetivo, "Pipeline iniciado", fase="opportunity", status="info"
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "master_controller.py",
                "--mode",
                body.mode,
                "--objective",
                body.objetivo,
            ],
            cwd=str(BASE_DIR),
        )
        proc.wait()
        ok = proc.returncode == 0
        log_evento(
            body.objetivo,
            "Pipeline concluído" if ok else "Pipeline com erro",
            fase="idle",
            status="ok" if ok else "error",
        )
        atualizar_fase("idle", "done", produto=body.objetivo, progresso=100)
        if _read_autonomous() and ok:
            import time

            time.sleep(300)
            atualizar_fase("opportunity", "rodando", produto=body.objetivo)
            log_evento(body.objetivo, "Modo autônomo: reiniciando", status="warn")
            _run()

            threading.Thread(target=_run, daemon=True).start()
            log_evento(
                body.objetivo, f"Pipeline agendado [mode={body.mode}]", status="info"
            )
            return {"status": "ok", "message": f"Pipeline iniciado: {body.objetivo}"}


@app.get("/api/pipeline/status")
async def pipeline_status():
    return JSONResponse(_read_state())


@app.post("/api/regenerar")
async def regenerar():
    threading.Thread(
        target=lambda: (_regenerar_dashboard(), _regenerar_executive()), daemon=True
    ).start()
    return {"status": "ok", "message": "Dashboards sendo regenerados"}


# API KPIs, Pipeline & Status (dados reais)

_STAGE_LABEL_FULL = {
    "opportunity": "Análise de Oportunidade",
    "product": "Criação de Produto",
    "content": "Geração de Conteúdo",
    "video": "Produção de Vídeo",
    "sales": "Motor de Vendas",
    "performance": "Performance & Memória",
    "kaizen": "Kaizen Engine",
    "idle": "Aguardando",
}
_STAGE_NEXT = {
    "opportunity": "product",
    "product": "content",
    "content": "video",
    "video": "sales",
    "sales": "performance",
    "performance": None,
}


@app.get("/api/kpis")
async def kpis():
    receita, lucro, conversao, leads = 0.0, 0.0, 0.0, 0
    margem, receita_prox, conversao_prox = 0.0, 0.0, 0.0
    leads_quentes = 0

    fin_file = BASE_DIR / "outputs" / "financial_data.json"
    if fin_file.exists():
        try:
            fin = json.loads(fin_file.read_text(encoding="utf-8"))
            for p in fin.get("products", []):
                receita += float(p.get("revenue", 0))
                lucro += float(p.get("profit", 0))
            if receita > 0:
                margem = round(lucro / receita * 100, 1)
            projs = fin.get("projections", [])
            if projs:
                conversao = float(projs[0].get("conversion_rate", 0))
                receita_prox = float(projs[0].get("monthly_revenue", 0))
                if len(projs) > 1:
                    conversao_prox = float(projs[1].get("conversion_rate", conversao))
        except Exception:
            pass

    crm_file = BASE_DIR / "outputs" / "crm_leads.json"
    if crm_file.exists():
        try:
            crm_data = json.loads(crm_file.read_text(encoding="utf-8"))
            leads = len(crm_data)
            leads_quentes = sum(1 for l in crm_data if l.get("temperature") == "quente")
        except Exception:
            pass

    if receita == 0:
        receita = _load_live_stats().get("receita_protegida", 0)

    # Delta receita: real vs projeção do mês
    receita_delta = 0.0
    if receita_prox > 0:
        receita_delta = round((receita - receita_prox) / receita_prox * 100, 1)

    # Delta conversão: mês atual vs próximo (tendência)
    conv_delta = round(conversao_prox - conversao, 1) if conversao_prox else 0.0

    # Alertas inteligentes
    alertas = []
    if 0 < conversao < 15:
        impacto = round(leads * max(0, (15 - conversao)) / 100 * 297)
        alertas.append(
            {
                "tipo": "warn",
                "titulo": f"Conversão em {conversao}% (meta: 15%)",
                "detalhe": f"Impacto estimado: -R$ {impacto:,.0f}",
                "acao": "Revisar funil",
            }
        )
    if leads_quentes == 0 and leads > 0:
        alertas.append(
            {
                "tipo": "info",
                "titulo": "Nenhum lead quente no momento",
                "detalhe": f"{leads} leads em qualificação",
                "acao": "Ver CRM",
            }
        )

    return {
        "receita": round(receita, 2),
        "lucro": round(lucro, 2),
        "conversao": round(conversao, 1),
        "leads": leads,
        "leads_quentes": leads_quentes,
        "margem": margem,
        "receita_delta": receita_delta,
        "conv_delta": conv_delta,
        "alertas": alertas,
    }


@app.get("/api/pipeline")
async def pipeline_atual():
    state = _read_state()
    produtos = state.get("produtos", [])

    # Produto em execução ou o mais recente
    em_execucao = [p for p in produtos if p.get("status") == "rodando"]
    ativo = (
        em_execucao[0]
        if em_execucao
        else (
            max(produtos, key=lambda p: _ts_to_epoch(p.get("timestamp", "")))
            if produtos
            else None
        )
    )

    # Tempo na fase
    def _tempo_na_fase(ts: str) -> str:
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            d = int((datetime.now(timezone.utc) - t).total_seconds())
            m, s = divmod(d, 60)
            return f"{m}min {s:02d}s"
        except Exception:
            return ""

            # Última ação do log
            def _ultima_acao() -> str:
                if not LOG_FILE.exists():
                    return ""
                    try:
                        for line in reversed(
                            LOG_FILE.read_text(encoding="utf-8").splitlines()
                        ):
                            try:
                                e = json.loads(line)
                                if e.get("evento"):
                                    return e["evento"]
                            except Exception:
                                pass
                    except Exception:
                        pass
                        return ""

                        # Todos os produtos com estado
                        todos = [
                            {
                                "produto": p.get("produto", "—"),
                                "fase": p.get("fase_atual", "idle"),
                                "fase_label": _STAGE_LABEL_FULL.get(
                                    p.get("fase_atual", "idle"), p.get("fase_atual", "")
                                ),
                                "status": p.get("status", "idle"),
                                "progresso": p.get("progresso", 0),
                            }
                            for p in produtos
                            if p.get("produto")
                        ]

                        if ativo:
                            fase = ativo.get("fase_atual", "idle")
                            next_stage = _STAGE_NEXT.get(fase)
                            return {
                                "fase": fase,
                                "fase_label": _STAGE_LABEL_FULL.get(fase, fase),
                                "produto": ativo.get("produto", "—"),
                                "progresso": ativo.get("progresso", 0),
                                "status": ativo.get("status", "idle"),
                                "tempo_fase": _tempo_na_fase(
                                    ativo.get("timestamp", "")
                                ),
                                "ultima_acao": _ultima_acao(),
                                "proximo_passo": (
                                    _STAGE_LABEL_FULL.get(next_stage, "Concluído")
                                    if next_stage
                                    else "Concluído"
                                ),
                                "todos_produtos": todos,
                            }

                            # Fallback: detecta pelo último output gerado
                            for s in reversed(
                                [
                                    "opportunity",
                                    "product",
                                    "content",
                                    "video",
                                    "sales",
                                    "performance",
                                ]
                            ):
                                if list((BASE_DIR / "outputs").glob(f"{s}_*.json")):
                                    next_stage = _STAGE_NEXT.get(s)
                                    return {
                                        "fase": s,
                                        "fase_label": _STAGE_LABEL_FULL.get(s, s),
                                        "produto": "CFO Digital",
                                        "progresso": 100,
                                        "status": "done",
                                        "tempo_fase": "",
                                        "ultima_acao": _ultima_acao(),
                                        "proximo_passo": (
                                            _STAGE_LABEL_FULL.get(
                                                next_stage, "Concluído"
                                            )
                                            if next_stage
                                            else "Concluído"
                                        ),
                                        "todos_produtos": todos,
                                    }

                                    return {
                                        "fase": "idle",
                                        "fase_label": "Aguardando",
                                        "produto": "—",
                                        "progresso": 0,
                                        "status": "idle",
                                        "tempo_fase": "",
                                        "ultima_acao": "",
                                        "proximo_passo": "—",
                                        "todos_produtos": [],
                                    }


@app.get("/api/status")
async def system_status():
    """Saúde geral do sistema."""
    problemas = []

    # Atividade recente no log
    if LOG_FILE.exists():
        try:
            age = (datetime.now().timestamp() - LOG_FILE.stat().st_mtime) / 60
            if age > 120:
                problemas.append("Sistema inativo há mais de 2 horas")
        except Exception:
            pass
        else:
            problemas.append("Log de execução não encontrado")

            # Chave OpenAI
            env_file = BASE_DIR / ".env"
            if env_file.exists():
                try:
                    content = env_file.read_text(encoding="utf-8")
                    openai_line = next(
                        (
                            l
                            for l in content.splitlines()
                            if l.startswith("OPENAI_API_KEY")
                        ),
                        "",
                    )
                    val = openai_line.split("=", 1)[-1].strip().strip('"').strip("'")
                    if not val or val in ("", "sua_chave_aqui", "COLOQUE_AQUI"):
                        problemas.append("OpenAI API key não configurada")
                except Exception:
                    pass
                else:
                    problemas.append("Arquivo .env não encontrado")

                    # Outputs esperados existem?
                    if not (BASE_DIR / "outputs" / "financial_data.json").exists():
                        problemas.append(
                            "financial_data.json ausente — rode Financial Engine"
                        )

                        auto_level = _read_autonomous_level()
                        nivel_label = {0: "Manual", 1: "Assistido", 2: "Autônomo"}.get(
                            auto_level, "Manual"
                        )

                        return {
                            "ok": len(problemas) == 0,
                            "problemas": problemas,
                            "total_problemas": len(problemas),
                            "auto_level": auto_level,
                            "auto_label": nivel_label,
                        }


@app.get("/api/crm")
async def get_crm():
    crm_file = BASE_DIR / "outputs" / "crm_leads.json"
    if crm_file.exists():
        try:
            return JSONResponse(json.loads(crm_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return JSONResponse([])


@app.get("/api/mapa")
async def get_mapa():
    """Pontos do mapa de demanda — lidos de crm_leads + ads."""
    pontos = [
        {"cidade": "São Paulo", "lat": -23.55, "lng": -46.63, "leads": 0, "vendas": 0},
        {
            "cidade": "Rio de Janeiro",
            "lat": -22.90,
            "lng": -43.17,
            "leads": 0,
            "vendas": 0,
        },
        {
            "cidade": "Belo Horizonte",
            "lat": -19.92,
            "lng": -43.94,
            "leads": 0,
            "vendas": 0,
        },
        {"cidade": "Curitiba", "lat": -25.43, "lng": -49.27, "leads": 0, "vendas": 0},
        {
            "cidade": "Porto Alegre",
            "lat": -30.03,
            "lng": -51.23,
            "leads": 0,
            "vendas": 0,
        },
    ]
    # Distribui leads reais proporcionalmente
    crm_file = BASE_DIR / "outputs" / "crm_leads.json"
    total_leads = 0
    if crm_file.exists():
        try:
            total_leads = len(json.loads(crm_file.read_text(encoding="utf-8")))
        except Exception:
            pass
            dist = [0.40, 0.25, 0.15, 0.12, 0.08]
            for i, p in enumerate(pontos):
                p["leads"] = max(1, round(total_leads * dist[i]))
                # Vendas reais de financial_data
                fin_file = BASE_DIR / "outputs" / "financial_data.json"
                total_vendas = 0
                if fin_file.exists():
                    try:
                        fin = json.loads(fin_file.read_text(encoding="utf-8"))
                        for prod in fin.get("products", []):
                            total_vendas += int(prod.get("units_sold", 0))
                    except Exception:
                        pass
                        vdist = [0.45, 0.30, 0.10, 0.10, 0.05]
                        for i, p in enumerate(pontos):
                            p["vendas"] = max(0, round(total_vendas * vdist[i]))
                            return JSONResponse(pontos)


# API Centro de Controle


class RunPipelineBody(BaseModel):
    objetivo: str = "CFO Digital"
    modo: str = "auto"


class NewIdeaBody(BaseModel):
    ideia: str
    nicho: str = ""
    publico: str = ""


class AddLeadBody(BaseModel):
    nome: str
    email: str = ""
    score: int = 50
    temperatura: str = "morno"


@app.post("/api/run-pipeline")
async def api_run_pipeline(body: RunPipelineBody):
    """Inicia o pipeline completo para um produto."""
    global _pipeline_proc

    def _run():
        atualizar_fase("opportunity", "rodando", produto=body.objetivo)
        log_evento(
            body.objetivo,
            "Pipeline iniciado via Centro de Controle",
            fase="opportunity",
            status="info",
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "master_controller.py",
                "--mode",
                body.modo,
                "--objective",
                body.objetivo,
            ],
            cwd=str(BASE_DIR),
        )
        with _pipeline_lock:
            pass  # só registra
            proc.wait()
            ok = proc.returncode == 0
            log_evento(
                body.objetivo,
                "Pipeline concluído " if ok else "Pipeline com erro",
                fase="idle",
                status="ok" if ok else "error",
            )
            atualizar_fase(
                "idle", "done" if ok else "error", produto=body.objetivo, progresso=100
            )

            threading.Thread(target=_run, daemon=True).start()
            log_evento(
                body.objetivo, f"Pipeline agendado: {body.objetivo}", status="info"
            )
            return {
                "status": "ok",
                "message": f"Pipeline iniciado: {body.objetivo}",
                "produto": body.objetivo,
                "modo": body.modo,
            }


@app.post("/api/new-idea")
async def api_new_idea(body: NewIdeaBody):
    """Registra nova ideia de produto e inicia análise de oportunidade."""
    ideias_file = BASE_DIR / "outputs" / "ideias.json"
    ideias_file.parent.mkdir(parents=True, exist_ok=True)

    ideias = []
    if ideias_file.exists():
        try:
            ideias = json.loads(ideias_file.read_text(encoding="utf-8"))
        except Exception:
            ideias = []

            nova = {
                "id": len(ideias) + 1,
                "ideia": body.ideia,
                "nicho": body.nicho,
                "publico": body.publico,
                "status": "nova",
                "criado_em": datetime.now(timezone.utc).isoformat(),
            }
            ideias.append(nova)
            ideias_file.write_text(
                json.dumps(ideias, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            log_evento(
                "Idea Engine",
                f"Nova ideia registrada: {body.ideia[:50]}",
                fase="opportunity",
                status="info",
            )

            # Se master_controller existir, inicia análise em background
            mc = BASE_DIR / "master_controller.py"
            if mc.exists():

                def _analisar():
                    atualizar_fase("opportunity", "rodando", produto=body.ideia[:30])
                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            "master_controller.py",
                            "--mode",
                            "auto",
                            "--objective",
                            body.ideia,
                        ],
                        cwd=str(BASE_DIR),
                    )
                    proc.wait()
                    ok = proc.returncode == 0
                    log_evento(
                        body.ideia[:30],
                        "Análise concluída " if ok else "Análise com erro",
                        fase="idle",
                        status="ok" if ok else "error",
                    )
                    atualizar_fase(
                        "idle",
                        "done" if ok else "error",
                        produto=body.ideia[:30],
                        progresso=100,
                    )
                    threading.Thread(target=_analisar, daemon=True).start()
                    msg = (
                        f"Ideia registrada — análise iniciada para '{body.ideia[:40]}'"
                    )

            else:
                msg = f"Ideia registrada: '{body.ideia[:40]}'"

                return {"status": "ok", "message": msg, "ideia": nova}


@app.post("/api/add-lead")
async def api_add_lead(body: AddLeadBody):
    """Adiciona novo lead ao CRM."""
    crm_file = BASE_DIR / "outputs" / "crm_leads.json"
    crm_file.parent.mkdir(parents=True, exist_ok=True)

    leads = []
    if crm_file.exists():
        try:
            leads = json.loads(crm_file.read_text(encoding="utf-8"))
        except Exception:
            leads = []

            novo = {
                "id": len(leads) + 1,
                "nome": body.nome,
                "email": body.email,
                "score": max(0, min(100, body.score)),
                "temperature": body.temperatura,
                "status": "Entrada",
                "data": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "origem": "Centro de Controle",
            }
            leads.append(novo)
            crm_file.write_text(
                json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            log_evento(
                "CRM",
                f"Lead adicionado: {body.nome} (score {body.score})",
                fase="sales",
                status="ok",
            )

            return {
                "status": "ok",
                "message": f"Lead '{body.nome}' adicionado ao CRM (score {body.score})",
                "lead": novo,
                "total_leads": len(leads),
            }


@app.get("/api/suggest-actions")
async def suggest_actions():
    """IA analisa o estado atual e retorna ações priorizadas."""
    sugestoes = []

    state = _read_state()
    produtos = state.get("produtos", [])
    rodando = [p for p in produtos if p.get("status") == "rodando"]

    receita = 0.0
    conversao = 0.0
    leads = 0
    fin_file = BASE_DIR / "outputs" / "financial_data.json"
    if fin_file.exists():
        try:
            fin = json.loads(fin_file.read_text(encoding="utf-8"))
            for p in fin.get("products", []):
                receita += float(p.get("revenue", 0))
                projs = fin.get("projections", [])
                if projs:
                    conversao = float(projs[0].get("conversion_rate", 0))
        except Exception:
            pass

            crm_file = BASE_DIR / "outputs" / "crm_leads.json"
            if crm_file.exists():
                try:
                    leads = len(json.loads(crm_file.read_text(encoding="utf-8")))
                except Exception:
                    pass

                    if not rodando:
                        sugestoes.append(
                            {
                                "prioridade": 1,
                                "icon": "",
                                "cor": "#7c3aed",
                                "titulo": "Rodar Pipeline Completo",
                                "motivo": "Nenhum produto em execução — sistema ocioso",
                                "endpoint": "run-pipeline",
                                "params": {"objetivo": "CFO Digital", "modo": "auto"},
                            }
                        )

                        if 0 < conversao < 15:
                            sugestoes.append(
                                {
                                    "prioridade": 2,
                                    "icon": "",
                                    "cor": "#3b82f6",
                                    "titulo": "Validar Mercado",
                                    "motivo": f"Conversão em {conversao:.1f}% — meta é 15%",
                                    "endpoint": "run-pipeline",
                                    "params": {
                                        "objetivo": "Validação de Mercado",
                                        "modo": "auto",
                                    },
                                }
                            )

                            if leads < 5:
                                sugestoes.append(
                                    {
                                        "prioridade": 2,
                                        "icon": "",
                                        "cor": "#10b981",
                                        "titulo": "Expandir Base de Leads",
                                        "motivo": f"Apenas {leads} lead(s) no CRM — funil fraco",
                                        "endpoint": None,
                                        "params": {},
                                        "acao_js": "openModal('lead')",
                                    }
                                )

                                inativo = True
                                if LOG_FILE.exists():
                                    try:
                                        inativo = (
                                            datetime.now().timestamp()
                                            - LOG_FILE.stat().st_mtime
                                        ) / 60 > 60
                                    except Exception:
                                        pass

                                        if inativo and not sugestoes:
                                            sugestoes.append(
                                                {
                                                    "prioridade": 3,
                                                    "icon": "",
                                                    "cor": "#f59e0b",
                                                    "titulo": "Simular Ciclo de Validação",
                                                    "motivo": "Sistema sem atividade recente — verifique o pipeline",
                                                    "endpoint": "simulate",
                                                    "params": {},
                                                }
                                            )

                                            if not sugestoes:
                                                rec = (
                                                    f"R$ {receita:,.0f}".replace(
                                                        ",", "X"
                                                    )
                                                    .replace(".", ",")
                                                    .replace("X", ".")
                                                )
                                                sugestoes.append(
                                                    {
                                                        "prioridade": 0,
                                                        "icon": "",
                                                        "cor": "#4ade80",
                                                        "titulo": "Sistema operando bem",
                                                        "motivo": f"{leads} leads · {rec} · {len(produtos)} produto(s)",
                                                        "endpoint": "simulate",
                                                        "params": {},
                                                    }
                                                )

                                                return {"sugestoes": sugestoes[:3]}


class LogPerfBody(BaseModel):
    platform: str
    metric: str
    value: float
    obs: str = ""


@app.post("/api/log-performance")
async def api_log_performance(body: LogPerfBody):
    """Registra uma métrica de performance de conteúdo no log e em arquivo."""
    perf_file = BASE_DIR / "outputs" / "content_performance.json"
    perf_file.parent.mkdir(parents=True, exist_ok=True)

    records = []
    if perf_file.exists():
        try:
            records = json.loads(perf_file.read_text(encoding="utf-8"))
        except Exception:
            records = []

            entry = {
                "platform": body.platform,
                "metric": body.metric,
                "value": body.value,
                "obs": body.obs,
                "data": datetime.now(timezone.utc).isoformat(),
            }
            records.append(entry)
            perf_file.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            log_evento(
                "Content Engine",
                f"{body.platform} · {body.metric}: {body.value}",
                fase="content",
                status="ok",
            )

            return {
                "status": "ok",
                "message": f"Performance registrada: {body.platform} · {body.metric} = {body.value}",
            }


@app.post("/api/simulate")
async def api_simulate():
    """Simula um ciclo completo do pipeline com eventos reais no log."""
    produto = f"Produto-Demo-{datetime.now().strftime('%H%M%S')}"

    import time as _time

    def _sim():
        stages = [
            ("opportunity", "Oportunidade identificada no mercado", 15),
            ("product", "Produto estruturado com IA", 20),
            ("content", "Conteúdo gerado para 3 plataformas", 25),
            ("video", "Roteiro de vídeo criado", 20),
            ("sales", "Funil de vendas configurado", 15),
            ("performance", "Dashboard de performance ativo", 5),
        ]
        for fase, msg, prog in stages:
            atualizar_fase(fase, "rodando", produto=produto, progresso=prog)
            log_evento(produto, msg, fase=fase, status="ok")
            _time.sleep(1.5)

            atualizar_fase("idle", "done", produto=produto, progresso=100)
            log_evento(produto, "Simulação concluída ", fase="idle", status="ok")

            threading.Thread(target=_sim, daemon=True).start()
            log_evento(
                produto, "Simulação iniciada via Centro de Controle", status="info"
            )
            return {
                "status": "ok",
                "message": f"Simulação iniciada — produto: {produto}",
                "produto": produto,
            }


# Stripe Webhook + P&L History


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Webhook Stripe — captura pagamentos em tempo real, sem polling."""
    import hmac as _hmac, hashlib as _hl

    payload = await request.body()

    if STRIPE_WH_SECRET:
        sig_header = request.headers.get("stripe-signature", "")
        try:
            parts = {
                p.split("=", 1)[0]: p.split("=", 1)[1]
                for p in sig_header.split(",")
                if "=" in p
            }
            ts = parts.get("t", "0")
            sig = parts.get("v1", "")
            expected = _hmac.new(
                STRIPE_WH_SECRET.encode(),
                f"{ts}.{payload.decode()}".encode(),
                _hl.sha256,
            ).hexdigest()
            if not _hmac.compare_digest(expected, sig):
                raise HTTPException(400, "Invalid Stripe signature")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Signature verification failed")

            try:
                event = json.loads(payload)
            except Exception:
                raise HTTPException(400, "Invalid JSON")

                etype = event.get("type", "")
                if etype in (
                    "charge.succeeded",
                    "payment_intent.succeeded",
                    "checkout.session.completed",
                ):
                    obj = event.get("data", {}).get("object", {})
                    amount = round(
                        obj.get("amount_total", obj.get("amount", 0)) / 100, 2
                    )
                    currency = obj.get("currency", "brl").upper()
                    desc = obj.get("description") or obj.get(
                        "customer_email", "Pagamento"
                    )
                    now = datetime.now(timezone.utc)
                    month_key = now.strftime("%Y-%m")

                    history = _read_pnl_history()
                    if month_key not in history:
                        history[month_key] = {
                            "receita": 0.0,
                            "custo": 0.0,
                            "eventos": [],
                        }
                        history[month_key]["receita"] = round(
                            history[month_key]["receita"] + amount, 2
                        )
                        history[month_key]["custo"] = round(
                            history[month_key]["receita"] * 0.38, 2
                        )
                        history[month_key]["eventos"].append(
                            {
                                "ts": now.isoformat(),
                                "amount": amount,
                                "currency": currency,
                                "description": str(desc)[:80],
                                "type": etype,
                            }
                        )
                        _write_pnl_history(history)
                        log_evento(
                            "Stripe",
                            f"Pagamento: {currency} {amount:.2f} — {str(desc)[:40]}",
                            fase="sales",
                            status="ok",
                        )
                        threading.Thread(
                            target=_send_telegram,
                            args=(
                                f" <b>Pagamento Stripe</b>\n{currency} {amount:.2f} — {str(desc)[:60]}",
                            ),
                            daemon=True,
                        ).start()

                        return {"received": True}


@app.get("/api/custos")
async def get_custos():
    """Custos operacionais mensais — lidos de financial_data.json."""
    fin_file = BASE_DIR / "outputs" / "financial_data.json"
    if fin_file.exists():
        try:
            fin = json.loads(fin_file.read_text(encoding="utf-8"))
            costs = fin.get("monthly_costs", [])
            total = sum(c.get("amount", 0) for c in costs)
            return JSONResponse({"costs": costs, "total": total})
        except Exception:
            pass
    return JSONResponse({"costs": [], "total": 0})


@app.get("/api/pnl-history")
async def get_pnl_history():
    """P&L mensal — dados reais + estimativa baseada em PNL atual."""
    history = _read_pnl_history()
    now = datetime.now(timezone.utc)

    pnl_resp = await get_pnl()
    pnl_data = json.loads(pnl_resp.body) if pnl_resp else []
    total_rec = sum(b.get("receita", 0) for b in pnl_data)
    total_cos = sum(b.get("custo", 0) for b in pnl_data)

    result = []
    for i in range(5, -1, -1):
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        key = f"{year}-{month:02d}"
        mes_label = [
            "Jan",
            "Fev",
            "Mar",
            "Abr",
            "Mai",
            "Jun",
            "Jul",
            "Ago",
            "Set",
            "Out",
            "Nov",
            "Dez",
        ][month - 1]
        if key in history:
            rec = history[key]["receita"]
            cos = history[key].get("custo", round(rec * 0.38, 2))
        else:
            factor = 0.6 + 0.08 * (5 - i)
            rec = round(total_rec * factor, 2)
            cos = round(total_cos * factor, 2)
        luc = round(rec - cos, 2)
        result.append(
            {
                "mes": mes_label,
                "ano": year,
                "chave": key,
                "receita": rec,
                "custo": cos,
                "lucro": luc,
                "real": key in history,
            }
        )

    insights = []
    if result:
        ultimo = result[-1]
        if ultimo["lucro"] < 0:
            insights.append(
                {
                    "tipo": "negativo",
                    "nivel": "critico",
                    "mensagem": f"P&L negativo em {ultimo['mes']}/{ultimo['ano']}: R${abs(ultimo['lucro']):.0f} de prejuízo",
                }
            )
        if len(result) >= 3:
            u = result[-3:]
            if u[2]["lucro"] < u[1]["lucro"] < u[0]["lucro"]:
                insights.append(
                    {
                        "tipo": "tendencia_queda",
                        "nivel": "atencao",
                        "mensagem": "Lucro em queda nos últimos 3 meses",
                    }
                )

    return JSONResponse({"historico": result, "insights": insights})


# API Multi-Negócio

BUSINESSES_FILE = BASE_DIR / "outputs" / "businesses.json"
_biz_lock = threading.Lock()

_DEFAULT_BUSINESSES = [
    {
        "id": 1,
        "nome": "CFO Digital",
        "status": "ativo",
        "receita": 0.0,
        "fase": "performance",
        "cor": "#7c3aed",
    },
    {
        "id": 2,
        "nome": "Produto X",
        "status": "idle",
        "receita": 0.0,
        "fase": "opportunity",
        "cor": "#3b82f6",
    },
    {
        "id": 3,
        "nome": "Agência MYO",
        "status": "idle",
        "receita": 0.0,
        "fase": "opportunity",
        "cor": "#10b981",
    },
]


def _read_businesses() -> list:
    if BUSINESSES_FILE.exists():
        try:
            return json.loads(BUSINESSES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Primeira vez: salva o padrão
    _write_businesses(_DEFAULT_BUSINESSES.copy())
    return _DEFAULT_BUSINESSES.copy()


def _write_businesses(biz: list):
    with _biz_lock:
        BUSINESSES_FILE.parent.mkdir(parents=True, exist_ok=True)
        BUSINESSES_FILE.write_text(
            json.dumps(biz, ensure_ascii=False, indent=2), encoding="utf-8"
        )


@app.get("/api/businesses")
async def get_businesses():
    biz = _read_businesses()

    # Injeta receita real do financial_data
    fin_file = BASE_DIR / "outputs" / "financial_data.json"
    if fin_file.exists():
        try:
            fin = json.loads(fin_file.read_text(encoding="utf-8"))
            prods = fin.get("products", [])
            if prods and biz:
                total = sum(float(p.get("revenue", 0)) for p in prods)
                dist = [0.6, 0.3, 0.1]
                for i, b in enumerate(biz):
                    b["receita"] = round(total * (dist[i] if i < len(dist) else 0.1), 2)
        except Exception:
            pass

    # Injeta status do pipeline ao vivo
    state = _read_state()
    for p in state.get("produtos", []):
        for b in biz:
            if b["nome"] == p.get("produto"):
                b["status"] = p.get("status", b["status"])
                b["fase"] = p.get("fase_atual", b.get("fase", ""))

    return JSONResponse(biz)


@app.post("/api/businesses")
async def create_business(body: dict):
    biz = _read_businesses()
    new_id = max((b["id"] for b in biz), default=0) + 1
    cores = ["#7c3aed", "#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#06b6d4"]
    novo = {
        "id": new_id,
        "nome": body.get("nome", f"Negócio {new_id}"),
        "status": "idle",
        "receita": 0.0,
        "fase": "opportunity",
        "cor": cores[new_id % len(cores)],
        "criado_em": datetime.now(timezone.utc).isoformat(),
    }
    biz.append(novo)
    _write_businesses(biz)
    log_evento(novo["nome"], "Negócio criado", status="ok")
    return {"status": "ok", "business": novo}


# API Aprovação Humana

APPROVALS_FILE = BASE_DIR / "outputs" / "pending_approvals.json"
_approval_lock = threading.Lock()


def _read_approvals() -> list:
    if APPROVALS_FILE.exists():
        try:
            return json.loads(APPROVALS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _write_approvals(approvals: list):
    with _approval_lock:
        APPROVALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        APPROVALS_FILE.write_text(
            json.dumps(approvals, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _avaliar_acao(custo: float, lucro_estimado: float) -> dict:
    """Classifica impacto pelo custo e calcula ROI."""
    roi = lucro_estimado - custo
    if custo < 200:
        impacto = "baixo"
    elif custo < 1000:
        impacto = "medio"
    else:
        impacto = "alto"
        return {
            "impacto": impacto,
            "roi": round(roi, 2),
            "custo": round(custo, 2),
            "lucro_estimado": round(lucro_estimado, 2),
            "roi_pct": round((roi / custo * 100) if custo > 0 else 0, 1),
        }


@app.post("/api/request-approval")
async def request_approval(body: dict):
    approvals = _read_approvals()
    action_id = max((a["id"] for a in approvals), default=0) + 1

    # Se passou custo+lucro_estimado, calcula impacto automaticamente
    custo = float(body.get("custo", 0))
    lucro_estimado = float(body.get("lucro_estimado", 0))
    financeiro = None
    if custo > 0:
        financeiro = _avaliar_acao(custo, lucro_estimado)
        impacto = financeiro["impacto"]
    else:
        impacto = body.get("impacto", "medio")  # baixo | medio | alto

        novo = {
            "id": action_id,
            "acao": body.get("acao", "Ação não especificada"),
            "descricao": body.get("descricao", ""),
            "impacto": impacto,
            "produto": body.get("produto", "Sistema"),
            "financeiro": financeiro,
            "status": "pending",
            "criado_em": datetime.now(timezone.utc).isoformat(),
        }

        if impacto == "baixo":
            novo["status"] = "aprovado"
            log_evento(
                novo["produto"],
                f"Auto-aprovado (baixo impacto): {novo['acao']}",
                status="ok",
            )
            approvals.append(novo)
            _write_approvals(approvals)
            return {
                "status": "auto_aprovado",
                "id": action_id,
                "message": f"Executado automaticamente: {novo['acao']}",
                "financeiro": financeiro,
            }

            if impacto == "medio":
                novo["status"] = "aprovado"
                log_evento(
                    novo["produto"],
                    f"Executado com aviso (médio impacto): {novo['acao']}",
                    status="warn",
                )
                approvals.append(novo)
                _write_approvals(approvals)
                return {
                    "status": "executado_com_aviso",
                    "id": action_id,
                    "message": f"Executado (verifique o log): {novo['acao']}",
                    "financeiro": financeiro,
                }

                # Alto → aguarda aprovação humana
                log_evento(
                    novo["produto"],
                    f"Aguardando aprovação (alto impacto): {novo['acao']}",
                    status="warn",
                )
                approvals.append(novo)
                _write_approvals(approvals)

                # Notifica via Telegram
                roi_txt = ""
                if financeiro:
                    roi_txt = (
                        f"\n Custo: R$ {financeiro['custo']:,.0f}"
                        f" | Lucro est.: R$ {financeiro['lucro_estimado']:,.0f}"
                        f" | ROI: {financeiro['roi_pct']}%"
                    )
                    threading.Thread(
                        target=_send_telegram,
                        args=(
                            f" <b>MYO — Aprovação necessária #{action_id}</b>\n"
                            f"<b>{novo['acao']}</b>\n"
                            f"Negócio: {novo['produto']}{roi_txt}\n"
                            f"Acesse: http://localhost:8000/operacao"
                        ),
                        daemon=True,
                    ).start()

                    return {
                        "status": "aguardando_aprovacao",
                        "id": action_id,
                        "message": f"Aguardando aprovação: {novo['acao']}",
                        "financeiro": financeiro,
                    }


@app.get("/api/pending")
async def get_pending():
    approvals = _read_approvals()
    return JSONResponse([a for a in approvals if a["status"] == "pending"])


@app.post("/api/approve/{action_id}")
async def approve_action(action_id: int):
    approvals = _read_approvals()
    approved_action = None
    for a in approvals:
        if a["id"] == action_id and a["status"] == "pending":
            a["status"] = "aprovado"
            a["aprovado_em"] = datetime.now(timezone.utc).isoformat()
            approved_action = a
            log_evento(
                a.get("produto", "Sistema"),
                f"Aprovado por humano: {a['acao']}",
                status="ok",
            )
            break
            _write_approvals(approvals)

            # Auto-trigger: se a aprovação vem do ORCH Engine, inicia master_controller
            auto_triggered = False
            if approved_action and (
                approved_action.get("fonte") == "ORCH Engine"
                or "lançar produto" in approved_action.get("acao", "").lower()
            ):
                produto = approved_action.get("produto", "Produto ORCH")
                auto_triggered = True

                # Block 5 — Metadata do auto-trigger
                _trigger_meta = {
                    "motivo": f"Aprovação humana da oportunidade ORCH: {produto}",
                    "prioridade": (
                        "alta" if approved_action.get("impacto") == "alto" else "media"
                    ),
                    "impacto_esperado": (
                        f"ROI {approved_action.get('financeiro', {}).get('roi_pct', '?')}% "
                        f"| Lucro est. R${approved_action.get('financeiro', {}).get('lucro_estimado', 0):.0f}"
                    ),
                    "ativado_em": datetime.now(timezone.utc).isoformat(),
                }

                def _auto_run():
                    import time as _t

                    _t.sleep(1)
                    atualizar_fase("opportunity", "rodando", produto=produto)
                    log_evento(
                        produto,
                        f"Auto-trigger iniciado | motivo: {_trigger_meta['motivo']} | "
                        f"prioridade: {_trigger_meta['prioridade']} | "
                        f"impacto: {_trigger_meta['impacto_esperado']}",
                        fase="opportunity",
                        status="info",
                    )
                    mc = BASE_DIR / "master_controller.py"
                    cmd = (
                        [
                            sys.executable,
                            "master_controller.py",
                            "--mode",
                            "auto",
                            "--objective",
                            produto,
                        ]
                        if mc.exists()
                        else [sys.executable, "main.py", "--mode", "demo"]
                    )
                    proc = subprocess.Popen(cmd, cwd=str(BASE_DIR))
                    proc.wait()
                    ok = proc.returncode == 0
                    log_evento(
                        produto,
                        (
                            "Pipeline auto-trigger concluído "
                            if ok
                            else "Erro no auto-trigger"
                        ),
                        fase="idle",
                        status="ok" if ok else "error",
                    )
                    atualizar_fase(
                        "idle",
                        "done" if ok else "error",
                        produto=produto,
                        progresso=100,
                    )

                    threading.Thread(target=_auto_run, daemon=True).start()
                    threading.Thread(
                        target=_send_telegram,
                        args=(
                            f" <b>Auto-trigger ativado</b>\n"
                            f"Produto: {produto}\n"
                            f"Prioridade: {_trigger_meta['prioridade']}\n"
                            f"Impacto: {_trigger_meta['impacto_esperado']}",
                        ),
                        daemon=True,
                    ).start()
                    log_evento(
                        produto,
                        f"Auto-trigger agendado | prioridade {_trigger_meta['prioridade']}",
                        status="info",
                    )

                    return {
                        "status": "aprovado",
                        "id": action_id,
                        "auto_triggered": auto_triggered,
                    }


@app.post("/api/reject/{action_id}")
async def reject_action(action_id: int):
    approvals = _read_approvals()
    for a in approvals:
        if a["id"] == action_id and a["status"] == "pending":
            a["status"] = "rejeitado"
            a["rejeitado_em"] = datetime.now(timezone.utc).isoformat()
            log_evento(
                a.get("produto", "Sistema"),
                f"Rejeitado por humano: {a['acao']}",
                status="error",
            )
            break
            _write_approvals(approvals)
            return {"status": "rejeitado", "id": action_id}


# Rotas SaaS (render manual — sem cache Jinja2, compatível Python 3.14)

import jinja2 as _jinja2


def _render(name: str) -> HTMLResponse:
    """Renderiza template sem LRU cache (workaround Python 3.14 + Jinja2 bug)."""
    loader = _jinja2.FileSystemLoader(str(BASE_DIR / "templates"))
    env = _jinja2.Environment(loader=loader, cache_size=0, auto_reload=True)
    html = env.get_template(name).render()
    return HTMLResponse(html)


@app.get("/novo-dashboard", response_class=HTMLResponse)
async def novo_dashboard():
    return _render("dashboard.html")


@app.get("/kit-demo", response_class=HTMLResponse)
async def kit_demo():
    return _render("kit-demo.html")


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    return _render("demo.html")


@app.get("/demo-completo", response_class=HTMLResponse)
async def demo_completo():
    return _render("demo_completa.html")


@app.get("/operacao", response_class=HTMLResponse)
async def operacao():
    return _render("operacao.html")


@app.get("/organograma", response_class=HTMLResponse)
async def organograma():
    return _render("organograma.html")


@app.get("/relatorios", response_class=HTMLResponse)
async def relatorios():
    return _render("relatorios.html")


@app.get("/crm", response_class=HTMLResponse)
async def crm():
    return _render("crm.html")


@app.get("/vendas", response_class=HTMLResponse)
async def vendas():
    return _render("vendas.html")


@app.get("/produtos", response_class=HTMLResponse)
async def produtos():
    return _render("produtos.html")


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio():
    return _render("portfolio.html")


# API P&L


@app.get("/api/pnl")
async def get_pnl():
    """P&L por negócio — receita, custo estimado, lucro, margem."""
    biz_list = _read_businesses()

    # Receita real do financial_data
    total_receita = 0.0
    fin_file = BASE_DIR / "outputs" / "financial_data.json"
    if fin_file.exists():
        try:
            fin = json.loads(fin_file.read_text(encoding="utf-8"))
            for p in fin.get("products", []):
                total_receita += float(p.get("revenue", 0))
        except Exception:
            pass

    # Distribui receita proporcionalmente entre negócios
    dist_rec = [0.55, 0.30, 0.15]
    dist_cost = [0.35, 0.40, 0.50]

    result = []
    for i, b in enumerate(biz_list):
        rec = round(total_receita * (dist_rec[i] if i < len(dist_rec) else 0.1), 2)
        pct = dist_cost[i] if i < len(dist_cost) else 0.45
        cost = round(rec * pct, 2)
        luc = round(rec - cost, 2)
        mar = round((luc / rec * 100) if rec > 0 else 0, 1)

        # Alocação recomendada da IA
        if mar > 50:
            ai_rec = "Escalar — alta margem, baixo risco"
            ai_cor = "#4ade80"
        elif mar > 25:
            ai_rec = "Manter — crescimento estável"
            ai_cor = "#38bdf8"
        else:
            ai_rec = "Otimizar custos antes de escalar"
            ai_cor = "#f59e0b"

        result.append(
            {
                "id": b["id"],
                "nome": b["nome"],
                "cor": b.get("cor", "#7c3aed"),
                "status": b.get("status", "idle"),
                "receita": rec,
                "custo": cost,
                "lucro": luc,
                "margem": mar,
                "ai_rec": ai_rec,
                "ai_cor": ai_cor,
            }
        )

    result.sort(key=lambda x: x["lucro"], reverse=True)
    return JSONResponse(result)


# API ROI Histórico


@app.get("/api/roi-history")
async def get_roi_history():
    """Retorna histórico completo de aprovações com dados de ROI."""
    return JSONResponse(_read_approvals())


@app.get("/roi", response_class=HTMLResponse)
async def roi_dashboard():
    return _render("roi.html")


# Auth — Login / Logout


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_authenticated(request):
        return RedirectResponse(url="/novo-dashboard")
        return _render("login.html")


@app.post("/api/login")
async def api_login(body: dict, response: Response):
    senha = body.get("senha", "")
    if (
        not MYO_PASSWORD
        or hashlib.sha256(senha.encode()).hexdigest()
        == hashlib.sha256(MYO_PASSWORD.encode()).hexdigest()
    ):
        token = _make_session_token()
        _SESSION_TOKENS.add(token)
        response.set_cookie(
            "myo_session", token, httponly=True, samesite="lax", max_age=86400 * 30
        )
        return {"status": "ok"}
        raise HTTPException(status_code=401, detail="Senha incorreta")


@app.post("/api/logout")
async def api_logout(request: Request, response: Response):
    token = request.cookies.get("myo_session")
    if token:
        _SESSION_TOKENS.discard(token)
        response.delete_cookie("myo_session")
        return RedirectResponse(url="/login", status_code=303)


# API Stripe Revenue


@app.get("/api/stripe-revenue")
async def get_stripe_revenue():
    """Receita real via Stripe — requer STRIPE_SECRET_KEY no .env."""
    if not STRIPE_KEY:
        return JSONResponse(
            {"error": "STRIPE_SECRET_KEY não configurada", "configured": False}
        )
        try:
            url = "https://api.stripe.com/v1/balance_transactions?limit=50&type=charge"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {STRIPE_KEY}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

                transactions = data.get("data", [])
                total_bruto = sum(t.get("amount", 0) for t in transactions) / 100
                total_taxa = sum(t.get("fee", 0) for t in transactions) / 100
                total_liquido = total_bruto - total_taxa
                moeda = (
                    transactions[0].get("currency", "brl").upper()
                    if transactions
                    else "BRL"
                )

                return JSONResponse(
                    {
                        "configured": True,
                        "total_bruto": round(total_bruto, 2),
                        "total_taxa": round(total_taxa, 2),
                        "total_liquido": round(total_liquido, 2),
                        "num_transacoes": len(transactions),
                        "moeda": moeda,
                        "atualizado_em": datetime.now(timezone.utc).isoformat(),
                    }
                )
        except Exception as e:
            return JSONResponse({"error": str(e), "configured": True})


# ORCH Engine — Pain to Product

_orch_state: dict = {
    "running": False,
    "mode": "",
    "started_at": "",
    "pid": None,
    "log": [],
}
_orch_rw_lock = threading.Lock()

ORCH_RESULT_FILE = BASE_DIR / "outputs" / "main_run" / "main_result.json"


class OrchRunBody(BaseModel):
    mode: str = "demo"
    niche: str = "restaurant"
    problem: str = "profit margin pricing"
    subreddits: str = "restaurantowners,smallbusiness"
    rounds: int = 3
    complaints_file: str = ""
    competitors_file: str = ""


def _orch_log(msg: str):
    with _orch_rw_lock:
        _orch_state["log"].append(
            {"ts": datetime.now(timezone.utc).strftime("%H:%M:%S"), "msg": msg}
        )
        if len(_orch_state["log"]) > 150:
            _orch_state["log"] = _orch_state["log"][-150:]


def _save_orch_to_notion(
    idea: str,
    summary: dict,
    score: float,
    financeiro: dict,
    status: str = "novo",
    resultado_real: str = "",
) -> str | None:
    """
    Cria/atualiza página no Notion com a decisão ORCH.
    Retorna o page_id criado (ou None se não configurado).
    Block 6: rastreia status (novo → executado/rejeitado) e resultado_real.
    """
    token = os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "")
    if not token or not db_id:
        return None
        try:
            body_text = (
                f"Score ORCH: {score}/100\n"
                f"ROI: {financeiro.get('roi_pct',0)}% | "
                f"Custo: R${financeiro.get('custo',0):.0f} | "
                f"Lucro est.: R${financeiro.get('lucro_estimado',0):.0f}\n"
                f"Cliente: {summary.get('target_customer','')}\n"
                f"Dor: {summary.get('core_problem','')}\n"
                f"Solução: {summary.get('proposed_solution','')}"
            )
            if resultado_real:
                body_text += f"\n\nResultado real: {resultado_real}"
                body_text = body_text[:2000]

                notion_status = (
                    status
                    if status in ("novo", "executado", "rejeitado", "aguardando")
                    else "novo"
                )
                payload = json.dumps(
                    {
                        "parent": {"database_id": db_id},
                        "properties": {
                            "titulo": {
                                "title": [{"text": {"content": f"ORCH: {idea}"[:100]}}]
                            },
                            "status": {"select": {"name": notion_status}},
                            "modo_execucao": {"select": {"name": "research_auto"}},
                            "descricao": {
                                "rich_text": [{"text": {"content": body_text}}]
                            },
                        },
                    }
                ).encode()
                req = urllib.request.Request(
                    "https://api.notion.com/v1/pages", data=payload, method="POST"
                )
                req.add_header("Authorization", f"Bearer {token}")
                req.add_header("Content-Type", "application/json")
                req.add_header("Notion-Version", "2022-06-28")
                resp_data = json.loads(urllib.request.urlopen(req, timeout=10).read())
                page_id = resp_data.get("id", "")
                _orch_log(f" Salvo no Notion: {idea[:40]} (status={notion_status})")
                return page_id
        except Exception as exc:
            _orch_log(f" Notion indisponível: {exc}")
            return None


def _update_notion_page_status(
    page_id: str, status: str, resultado_real: str = ""
) -> None:
    """Block 6 — Atualiza status de uma página Notion existente após execução."""
    token = os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY", "")
    if not token or not page_id:
        return
        try:
            props: dict = {"status": {"select": {"name": status}}}
            if resultado_real:
                props["descricao"] = {
                    "rich_text": [{"text": {"content": resultado_real[:2000]}}]
                }
                payload = json.dumps({"properties": props}).encode()
                req = urllib.request.Request(
                    f"https://api.notion.com/v1/pages/{page_id}",
                    data=payload,
                    method="PATCH",
                )
                req.add_header("Authorization", f"Bearer {token}")
                req.add_header("Content-Type", "application/json")
                req.add_header("Notion-Version", "2022-06-28")
                urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass


@app.post("/api/orchestrator/run")
async def orch_run(body: OrchRunBody):
    with _orch_rw_lock:
        if _orch_state["running"]:
            return {
                "status": "already_running",
                "message": "Orchestrator já está rodando",
            }

            # Block 3 — Controle de custo: bloqueia se custo API > 30% da receita do mês
            try:
                from agents.llm_router import get_monthly_cost_usd

                custo_api_usd = get_monthly_cost_usd()
                custo_api_brl = custo_api_usd * 5.0
                pnl_file = BASE_DIR / "outputs" / "pnl_history.json"
                receita_mes = 0.0
                if pnl_file.exists():
                    ph = json.loads(pnl_file.read_text(encoding="utf-8"))
                    mes_key = datetime.now(timezone.utc).strftime("%Y-%m")
                    receita_mes = ph.get(mes_key, {}).get("receita", 0.0)
                    if receita_mes > 0 and custo_api_brl > receita_mes * 1.5:
                        return JSONResponse(
                            status_code=402,
                            content={
                                "status": "budget_exceeded",
                                "message": (
                                    f"Custo de API (R${custo_api_brl:.0f}) "
                                    f"> 150% da receita (R${receita_mes:.0f}). "
                                    "Recarregue créditos antes de rodar."
                                ),
                                "custo_api_brl": round(custo_api_brl, 2),
                                "receita_mes": round(receita_mes, 2),
                            },
                        )
                        if receita_mes > 0 and custo_api_brl > receita_mes * 0.30:
                            log_evento(
                                "ORCH Engine",
                                f"Aviso: custo API = {int(custo_api_brl/receita_mes*100)}% da receita",
                                status="warn",
                            )
            except Exception:
                pass

                def _run():
                    cmd = [
                        sys.executable,
                        "main.py",
                        "--mode",
                        body.mode,
                        "--rounds",
                        str(body.rounds),
                    ]
                    if body.mode == "auto":
                        cmd += [
                            "--niche",
                            body.niche,
                            "--problem",
                            body.problem,
                            "--subreddits",
                            body.subreddits,
                        ]
                    elif body.mode == "json":
                        if body.complaints_file:
                            cmd += ["--complaints-file", body.complaints_file]
                            if body.competitors_file:
                                cmd += ["--competitors-file", body.competitors_file]

                                with _orch_rw_lock:
                                    _orch_state.update(
                                        {
                                            "running": True,
                                            "mode": body.mode,
                                            "started_at": datetime.now(
                                                timezone.utc
                                            ).isoformat(),
                                            "pid": None,
                                            "log": [],
                                        }
                                    )

                                    atualizar_fase(
                                        "opportunity",
                                        "rodando",
                                        produto="ORCH Engine",
                                        progresso=10,
                                    )
                                    log_evento(
                                        "ORCH Engine",
                                        f"Iniciado modo {body.mode.upper()}",
                                        fase="opportunity",
                                        status="info",
                                    )
                                    _orch_log(
                                        f" ORCH modo {body.mode.upper()} iniciado"
                                    )

                                    try:
                                        proc = subprocess.Popen(
                                            cmd,
                                            cwd=str(BASE_DIR),
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT,
                                            text=True,
                                            bufsize=1,
                                        )
                                        with _orch_rw_lock:
                                            _orch_state["pid"] = proc.pid

                                            for raw_line in proc.stdout:
                                                line = raw_line.rstrip()
                                                if not line:
                                                    continue
                                                    _orch_log(line)
                                                    ll = line.lower()
                                                    if (
                                                        "complaint" in ll
                                                        or "reclamação" in ll
                                                        or "coletando" in ll
                                                    ):
                                                        atualizar_fase(
                                                            "opportunity",
                                                            "rodando",
                                                            produto="ORCH Engine",
                                                            progresso=25,
                                                        )
                                                    elif (
                                                        "concorrent" in ll
                                                        or "competitor" in ll
                                                        or "pesquisando" in ll
                                                    ):
                                                        atualizar_fase(
                                                            "product",
                                                            "rodando",
                                                            produto="ORCH Engine",
                                                            progresso=50,
                                                        )
                                                    elif (
                                                        "debate" in ll
                                                        or "rodada" in ll
                                                        or "gpt" in ll
                                                    ):
                                                        atualizar_fase(
                                                            "content",
                                                            "rodando",
                                                            produto="ORCH Engine",
                                                            progresso=70,
                                                        )
                                                    elif (
                                                        "resultado" in ll
                                                        or "aprovad" in ll
                                                        or "rejeitad" in ll
                                                    ):
                                                        atualizar_fase(
                                                            "performance",
                                                            "rodando",
                                                            produto="ORCH Engine",
                                                            progresso=90,
                                                        )

                                                        proc.wait()
                                                        ok = proc.returncode == 0
                                    except Exception as exc:
                                        _orch_log(f" Erro interno: {exc}")
                                        ok = False

                                        with _orch_rw_lock:
                                            _orch_state["running"] = False
                                            _orch_state["pid"] = None

                                            if ok:
                                                _orch_log(
                                                    " ORCH concluído com sucesso."
                                                )
                                                log_evento(
                                                    "ORCH Engine",
                                                    "Pipeline ORCH concluído ",
                                                    fase="performance",
                                                    status="ok",
                                                )
                                                atualizar_fase(
                                                    "idle",
                                                    "done",
                                                    produto="ORCH Engine",
                                                    progresso=100,
                                                )
                                                threading.Thread(
                                                    target=_orch_auto_approval,
                                                    daemon=True,
                                                ).start()
                                            else:
                                                _orch_log(
                                                    " ORCH terminou com erro — verifique o log."
                                                )
                                                log_evento(
                                                    "ORCH Engine",
                                                    "Pipeline ORCH com erro",
                                                    fase="idle",
                                                    status="error",
                                                )
                                                atualizar_fase(
                                                    "idle",
                                                    "error",
                                                    produto="ORCH Engine",
                                                    progresso=100,
                                                )

                                                threading.Thread(
                                                    target=_run, daemon=True
                                                ).start()
                                                log_evento(
                                                    "ORCH Engine",
                                                    f"Orchestrator agendado [mode={body.mode}]",
                                                    status="info",
                                                )
                                                return {
                                                    "status": "ok",
                                                    "message": f"Orchestrator rodando em modo {body.mode.upper()}",
                                                }


def _orch_auto_approval():
    """Lê resultado ORCH e envia automaticamente para fila de aprovação."""
    if not ORCH_RESULT_FILE.exists():
        return
        try:
            data = json.loads(ORCH_RESULT_FILE.read_text(encoding="utf-8"))
            if data.get("status") == "rejeitado":
                score = data.get("score", {}).get("total", 0)
                reasons = data.get("score", {}).get("rejection_reasons", [])
                _orch_log(f" Oportunidade rejeitada (score {score}/100)")
                # Block 6 — Salva rejeição no Notion
                idea_rej = data.get("idea_name", "Oportunidade ORCH")
                summary_rej = data.get("summary", {})
                threading.Thread(
                    target=_save_orch_to_notion,
                    args=(
                        idea_rej,
                        summary_rej,
                        score,
                        {},
                        "rejeitado",
                        f"Rejeitado automaticamente. Motivos: {'; '.join(reasons[:3])}",
                    ),
                    daemon=True,
                ).start()
                return

                score = data.get("score", {}).get("total", 0)
                custo_usd = data.get("total_cost_usd", 0)
                custo_brl = round(custo_usd * 5.0, 2)
                lucro_est = round(score * 60.0, 2)
                idea = data.get("idea_name", "Oportunidade ORCH")
                summary = data.get("summary", {})
                financeiro = _avaliar_acao(custo_brl, lucro_est)
                impacto = financeiro["impacto"]

                approvals = _read_approvals()
                action_id = max((a["id"] for a in approvals), default=0) + 1
                desc = (
                    f"Score ORCH: {score}/100 | "
                    f"Cliente: {summary.get('target_customer','?')} | "
                    f"Solução: {summary.get('proposed_solution','?')[:80]}"
                )
                novo = {
                    "id": action_id,
                    "acao": f"Lançar produto: {idea}",
                    "descricao": desc,
                    "impacto": impacto,
                    "produto": idea,
                    "financeiro": financeiro,
                    "status": "pending" if impacto == "alto" else "aprovado",
                    "criado_em": datetime.now(timezone.utc).isoformat(),
                    "fonte": "ORCH Engine",
                }
                approvals.append(novo)
                _write_approvals(approvals)

                # Block 6 — Salva no Notion com status correto
                notion_status = "aguardando" if impacto == "alto" else "executado"
                threading.Thread(
                    target=_save_orch_to_notion,
                    args=(idea, summary, score, financeiro, notion_status),
                    daemon=True,
                ).start()

                status_txt = (
                    "Aguardando aprovação" if impacto == "alto" else "Auto-aprovado"
                )
                _orch_log(f" {status_txt}: {idea} (ROI {financeiro['roi_pct']}%)")
                log_evento(
                    "ORCH Engine",
                    f"{status_txt}: {idea}",
                    status="warn" if impacto == "alto" else "ok",
                )

                if impacto == "alto":
                    roi_txt = (
                        f"\n Custo: R$ {financeiro['custo']:,.0f}"
                        f" | Lucro est.: R$ {financeiro['lucro_estimado']:,.0f}"
                        f" | ROI: {financeiro['roi_pct']}%"
                    )
                    _send_telegram(
                        f" <b>ORCH — Nova oportunidade #{action_id}</b>\n"
                        f"<b>{idea}</b>\nScore: {score}/100{roi_txt}\n"
                        f"Acesse: http://localhost:8000/orch"
                    )
        except Exception as exc:
            _orch_log(f" Erro ao processar aprovação automática: {exc}")


@app.get("/api/orchestrator/status")
async def orch_status():
    with _orch_rw_lock:
        return JSONResponse(dict(_orch_state))


@app.get("/api/system-health")
async def system_health():
    """Block 2 — Estado de saúde dos provedores LLM e modo do sistema."""
    import httpx as _httpx

    providers: dict = {}

    # Verifica Claude
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            with _httpx.Client(timeout=5) as c:
                r = c.post(
                    "https://api.anthropic.com/v1/messages",
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
                providers["claude"] = (
                    "ok" if r.status_code < 400 else f"erro_{r.status_code}"
                )
        except Exception as e:
            providers["claude"] = f"erro: {str(e)[:40]}"
        else:
            providers["claude"] = "sem_chave"

            # Verifica OpenAI
            openai_key = os.getenv("OPENAI_API_KEY", "")
            if openai_key:
                try:
                    with _httpx.Client(timeout=5) as c:
                        r = c.get(
                            "https://api.openai.com/v1/models",
                            headers={"Authorization": f"Bearer {openai_key}"},
                        )
                        providers["openai"] = (
                            "ok" if r.status_code < 400 else f"erro_{r.status_code}"
                        )
                except Exception as e:
                    providers["openai"] = f"erro: {str(e)[:40]}"
                else:
                    providers["openai"] = "sem_chave"

                    # Determina modo do sistema
                    ok_count = sum(1 for v in providers.values() if v == "ok")
                    if ok_count >= 2:
                        mode = "normal"
                    elif ok_count == 1:
                        mode = "degraded"
                    else:
                        mode = "heuristic"

                        # Custo LLM do mês
                        try:
                            from agents.llm_router import get_monthly_cost_usd

                            custo_api_usd = get_monthly_cost_usd()
                        except Exception:
                            custo_api_usd = 0.0

                            return JSONResponse(
                                {
                                    "mode": mode,
                                    "providers": providers,
                                    "custo_api_usd": round(custo_api_usd, 4),
                                    "custo_api_brl": round(custo_api_usd * 5.0, 2),
                                    "checked_at": datetime.now(
                                        timezone.utc
                                    ).isoformat(),
                                }
                            )


@app.get("/api/observability")
async def get_observability():
    """Lê tracker.jsonl e tracer.jsonl e retorna sumário + breakdown por modelo + recentes."""
    tracker_file = BASE_DIR / "outputs" / "observability" / "tracker.jsonl"
    tracer_file = BASE_DIR / "outputs" / "observability" / "tracer.jsonl"

    records = []
    if tracker_file.exists():
        for line in tracker_file.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                pass

    total_calls = len(records)
    total_cost = round(sum(r.get("cost_usd", 0) for r in records), 6)
    total_input = sum(r.get("input_tokens", 0) for r in records)
    total_output = sum(r.get("output_tokens", 0) for r in records)
    errors = sum(1 for r in records if r.get("status") == "error")
    error_rate = round(errors / total_calls * 100, 1) if total_calls else 0

    # Breakdown por modelo
    models: dict = {}
    for r in records:
        m = r.get("model", "unknown")
        if m not in models:
            models[m] = {
                "model": m,
                "calls": 0,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "errors": 0,
            }
        models[m]["calls"] += 1
        models[m]["cost_usd"] = round(models[m]["cost_usd"] + r.get("cost_usd", 0), 6)
        models[m]["input_tokens"] += r.get("input_tokens", 0)
        models[m]["output_tokens"] += r.get("output_tokens", 0)
        if r.get("status") == "error":
            models[m]["errors"] += 1

    by_model = sorted(models.values(), key=lambda x: x["cost_usd"], reverse=True)

    # Recentes (últimos 15)
    recent = records[-15:][::-1]

    # Tracer steps (últimos 10)
    traces = []
    if tracer_file.exists():
        for line in tracer_file.read_text(encoding="utf-8").splitlines():
            try:
                traces.append(json.loads(line))
            except Exception:
                pass
    recent_traces = traces[-10:][::-1]

    return JSONResponse(
        {
            "summary": {
                "total_calls": total_calls,
                "total_cost_usd": total_cost,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "errors": errors,
                "error_rate": error_rate,
            },
            "by_model": by_model,
            "recent": recent,
            "recent_traces": recent_traces,
        }
    )


@app.get("/api/orchestrator/result")
async def orch_result():
    if not ORCH_RESULT_FILE.exists():
        return JSONResponse(
            {"error": "Nenhum resultado disponível — rode o Orchestrator primeiro"}
        )
        try:
            return JSONResponse(
                json.loads(ORCH_RESULT_FILE.read_text(encoding="utf-8"))
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/orchestrator/opportunity")
async def orch_opportunity():
    """Extrai melhor oportunidade do resultado com cálculo de governança."""
    if not ORCH_RESULT_FILE.exists():
        return JSONResponse({"error": "Sem resultado"})
        try:
            data = json.loads(ORCH_RESULT_FILE.read_text(encoding="utf-8"))
            if data.get("status") == "rejeitado":
                return JSONResponse(
                    {
                        "status": "rejeitado",
                        "score": data.get("score", {}).get("total", 0),
                        "motivos": data.get("score", {}).get("rejection_reasons", []),
                    }
                )
                score = data.get("score", {}).get("total", 0)
                custo_usd = data.get("total_cost_usd", 0)
                custo_brl = round(custo_usd * 5.0, 2)
                lucro = round(score * 60.0, 2)
                fin = _avaliar_acao(custo_brl, lucro)
                return JSONResponse(
                    {
                        "status": "aprovada",
                        "acao": data.get("idea_name", "?"),
                        "score": score,
                        "custo": custo_brl,
                        "lucro": lucro,
                        "impacto": fin["impacto"],
                        "roi_pct": fin["roi_pct"],
                        "summary": data.get("summary", {}),
                        "next_actions": data.get("next_actions", [])[:3],
                    }
                )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/orch", response_class=HTMLResponse)
async def orch_page():
    return HTMLResponse(_build_orch_html())


def _build_orch_html() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MYO · ORCH Engine</title>
<style>
*, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
html, body { height:100%; overflow:hidden; }
body {
background:#020609; color:#e2e8f0;
font-family:Inter,system-ui,sans-serif;
display:flex; flex-direction:column;
}
button { font-family:inherit; cursor:pointer; transition:all .2s; border:none; }
button:hover { opacity:.85; transform:translateY(-1px); }
button:active { transform:translateY(0); }
button:disabled { opacity:.4; cursor:not-allowed; transform:none; }
input { font-family:inherit; outline:none; }

/* Layout */
#orch-top {
flex-shrink:0; height:52px;
background:#020609; border-bottom:1px solid #0d1f35;
display:flex; align-items:center; gap:10px; padding:0 20px;
}
#orch-main {
flex:1; display:grid; grid-template-columns:1fr 1fr;
gap:14px; padding:14px; overflow:hidden; min-height:0;
}
#orch-log {
flex-shrink:0; height:168px; border-top:1px solid #0a1520;
display:flex; flex-direction:column;
}

/* Top bar */
.orch-brand { color:#8b5cf6; font-weight:800; font-size:14px; margin-right:4px; }
.btn-mode {
border-radius:8px; padding:7px 15px;
font-size:11px; font-weight:700; white-space:nowrap;
}
.btn-demo { background:#3b82f618; color:#3b82f6; border:1px solid #3b82f633; }
.btn-auto { background:#10b98118; color:#10b981; border:1px solid #10b98133; }
.btn-json { background:#f59e0b18; color:#f59e0b; border:1px solid #f59e0b33; }
.btn-mode:hover { filter:brightness(1.25); opacity:1; }
.status-live {
margin-left:auto; display:flex; align-items:center; gap:6px;
font-size:10px; color:#1e3a5f; white-space:nowrap;
}
.status-dot {
width:6px; height:6px; border-radius:50%;
background:#1e3a5f; flex-shrink:0;
}
.status-dot.running { background:#f59e0b; animation:dot-pulse 1.2s infinite; }
.status-dot.done { background:#10b981; }
.status-dot.error { background:#ef4444; }

/* Panels */
.panel {
background:#060d17; border:1px solid #0d1f35; border-radius:14px;
padding:18px 20px; display:flex; flex-direction:column; overflow:hidden; min-height:0;
}
.panel-label {
color:#0d2a40; font-size:9px; font-weight:800;
text-transform:uppercase; letter-spacing:1px; margin-bottom:14px; flex-shrink:0;
}

/* Execution panel */
.progress-track {
background:#0a1520; border-radius:100px; height:6px;
margin-bottom:10px; overflow:hidden; flex-shrink:0;
}
.progress-fill {
height:100%; border-radius:100px;
background:linear-gradient(90deg,#3b82f6,#8b5cf6);
width:0%; transition:width 1.2s cubic-bezier(.4,0,.2,1);
}
.stage-steps { display:flex; gap:4px; margin-bottom:14px; flex-shrink:0; }
.step-dot {
flex:1; height:3px; border-radius:100px;
background:#0a1520; transition:background .5s;
}
.step-dot.done { background:#10b981; }
.step-dot.active { background:#f59e0b; animation:dot-pulse 1.2s infinite; }
.current-step {
font-size:13px; font-weight:700; color:#e2e8f0;
margin-bottom:6px; transition:all .3s ease;
flex-shrink:0; min-height:22px;
}
.step-detail {
font-size:10px; color:#1e3a5f; flex-shrink:0;
min-height:16px; transition:all .3s;
}
.exec-idle {
flex:1; display:flex; flex-direction:column;
align-items:center; justify-content:center;
gap:8px; color:#0d1f35;
}

/* Decision panel */
.decision-card {
padding:18px 20px;
background:linear-gradient(135deg,rgba(139,92,246,.12),rgba(79,70,229,.06));
border:1px solid rgba(139,92,246,.25); border-radius:0;
display:flex; flex-direction:column; gap:14px;
overflow-y:auto; height:100%;
animation:opp-pulse 3s infinite;
}
@keyframes opp-pulse {
0%,100% { box-shadow:0 0 10px rgba(139,92,246,.15); }
50% { box-shadow:0 0 28px rgba(139,92,246,.38); }
}
.opp-name { font-size:17px; font-weight:800; color:#e2e8f0; line-height:1.3; }
.opp-desc { font-size:11px; color:#64748b; line-height:1.6; }
.opp-metrics { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
.metric-box {
background:#030810; border:1px solid #0d1f35;
border-radius:8px; padding:10px; text-align:center;
}
.metric-val { font-size:14px; font-weight:800; }
.metric-lbl { font-size:9px; color:#1e3a5f; margin-top:2px; }
.gov-badge {
display:flex; align-items:center; gap:8px; padding:8px 12px;
border-radius:8px; font-size:11px; font-weight:700; flex-shrink:0;
}
.gov-alto { background:#f59e0b18; border:1px solid #f59e0b44; color:#f59e0b; }
.gov-medio { background:#3b82f618; border:1px solid #3b82f644; color:#3b82f6; }
.gov-baixo { background:#10b98118; border:1px solid #10b98144; color:#10b981; }
.opp-actions { display:flex; gap:10px; flex-shrink:0; }
.btn-approve {
flex:1; padding:11px; border-radius:10px; font-weight:800; font-size:12px;
background:linear-gradient(135deg,#10b981,#059669); color:#fff;
box-shadow:0 0 16px #10b98133;
}
.btn-reject {
padding:11px 18px; border-radius:10px; font-weight:700; font-size:12px;
background:#ef444418; color:#ef4444; border:1px solid #ef444433;
}
.ranking-item {
display:flex; align-items:center; gap:10px; padding:7px 10px;
border-radius:8px; background:#030810; border:1px solid #0d1f35;
font-size:11px; transition:border-color .3s;
}
.ranking-item:hover { border-color:#8b5cf644; }
.decision-empty {
flex:1; display:flex; flex-direction:column;
align-items:center; justify-content:center;
gap:8px; color:#0d1f35; text-align:center;
}

/* Log */
#log-header {
padding:7px 16px; border-bottom:1px solid #080f18;
font-size:9px; font-weight:800; color:#0d2a40;
text-transform:uppercase; letter-spacing:1px;
flex-shrink:0; display:flex; align-items:center; justify-content:space-between;
}
#log-entries { flex:1; overflow-y:auto; padding:6px 16px; display:flex; flex-direction:column; }
.log-e {
font-family:'Courier New',monospace; font-size:10px;
line-height:1.7; color:#1e3a5f; white-space:pre-wrap;
}
.log-e.ok { color:#10b981; }
.log-e.err { color:#ef4444; }
.log-e.warn { color:#f59e0b; }
.log-e.info { color:#3b82f6; }

/* Auto modal */
#auto-modal {
display:none; position:fixed; inset:0;
background:#00000088; z-index:1000;
align-items:center; justify-content:center;
}
#auto-modal.open { display:flex; }
.modal-box {
background:#060d17; border:1px solid #1e3a5f;
border-radius:14px; padding:24px;
width:380px; max-width:95vw;
}
.modal-title { font-size:14px; font-weight:800; margin-bottom:16px; color:#10b981; }
.f-lbl { font-size:9px; font-weight:800; color:#1e3a5f; text-transform:uppercase;
letter-spacing:.5px; margin-bottom:4px; }
.f-inp {
width:100%; background:#030810; color:#e2e8f0;
border:1px solid #0d1f35; border-radius:8px;
padding:9px 12px; font-size:11px; margin-bottom:12px;
}
.f-inp:focus { border-color:#10b98155; }

/* Anim */
@keyframes dot-pulse { 0%,100%{opacity:1} 50%{opacity:.2} }
@keyframes fadein { from{opacity:0;transform:translateY(5px)} to{opacity:1;transform:none} }
.fi { animation:fadein .4s ease; }
</style>
</head>
<body>

<!-- Block 2: Banner de modo degradado (oculto por padrão) -->
<div id="degraded-banner" style="display:none;position:sticky;top:0;z-index:200;
background:#f59e0b18;border-bottom:1px solid #f59e0b44;
padding:6px 20px;font-size:10px;font-weight:700;color:#f59e0b;
display:flex;align-items:center;gap:10px">
<span></span>
<span id="degraded-msg">Sistema em modo degradado — alguma API indisponível</span>
<span id="degraded-provider" style="opacity:.7;font-weight:400"></span>
</div>

<!-- TOP BAR -->
<div id="orch-top">
<a href="/" style="text-decoration:none;margin-right:2px">
<span style="color:#1e3a5f;font-size:11px;font-weight:700">← MYO</span>
</a>
<div style="width:1px;height:18px;background:#0d1f35;margin:0 6px"></div>
<span class="orch-brand"> ORCH</span>
<div style="width:1px;height:18px;background:#0d1f35;margin:0 4px"></div>

<button id="btn-demo" class="btn-mode btn-demo" onclick="runOrch('demo')"> Demo</button>
<button id="btn-auto" class="btn-mode btn-auto" onclick="openAutoModal()"> Auto</button>
<button id="btn-json" class="btn-mode btn-json" onclick="runOrch('json')"> JSON</button>

<div class="status-live">
<div class="status-dot" id="status-dot"></div>
<span id="status-text">Aguardando</span>
<span id="status-time" style="color:#0d1f35;margin-left:4px"></span>
</div>
</div>

<!-- MAIN 2-col -->
<div id="orch-main">

<!-- EXECUÇÃO (esquerda) -->
<div class="panel">
<div class="panel-label"> Execução em tempo real</div>

<div class="progress-track">
<div class="progress-fill" id="prog-fill"></div>
</div>
<div class="stage-steps" id="stage-dots"></div>

<div class="current-step" id="current-step">—</div>
<div class="step-detail" id="step-detail">Pressione um botão acima para iniciar</div>

<div class="exec-idle" id="exec-idle">
<div style="font-size:34px"></div>
<div style="font-size:13px;font-weight:700">Aguardando execução</div>
<div style="font-size:10px">Demo · Auto (Reddit) · JSON</div>
</div>
</div>

<!-- DECISÃO (direita) -->
<div class="panel" style="padding:0;overflow:hidden" id="decision-panel">
<div id="decision-empty" class="decision-empty" style="padding:20px">
<div style="font-size:34px"></div>
<div style="font-size:13px;font-weight:700;color:#1e3a5f">Nenhuma oportunidade ainda</div>
<div style="font-size:10px;color:#0d1f35">Execute o ORCH para ver oportunidades aqui</div>
</div>
<div id="decision-content" style="display:none;height:100%;overflow-y:auto"></div>
</div>

</div><!-- /main -->

<!-- LOG -->
<div id="orch-log">
<div id="log-header">
<span> Atividade</span>
<button onclick="clearLog()"
style="background:transparent;color:#0d1f35;border:none;font-size:9px;
cursor:pointer;font-family:inherit;padding:0">limpar</button>
</div>
<div id="log-entries">
<span class="log-e" style="color:#0d1f35">Aguardando…</span>
</div>
</div>

<!-- MODAL AUTO -->
<div id="auto-modal" onclick="closeAutoModal(event)">
<div class="modal-box" onclick="event.stopPropagation()">
<div class="modal-title"> Modo Auto — Reddit + Perplexity</div>
<div class="f-lbl">Nicho</div>
<input id="inp-niche" class="f-inp" value="restaurant" placeholder="ex: restaurant">
<div class="f-lbl">Problema principal</div>
<input id="inp-problem" class="f-inp" value="profit margin pricing">
<div class="f-lbl">Subreddits (vírgula)</div>
<input id="inp-subreddits" class="f-inp" value="restaurantowners,smallbusiness">
<div style="display:flex;gap:10px;margin-top:4px">
<button onclick="runOrch('auto')"
style="flex:1;background:#10b981;color:#fff;border-radius:9px;
padding:11px;font-weight:800;font-size:12px">
Rodar Auto
</button>
<button onclick="closeAutoModal()"
style="background:#0d1f3522;color:#475569;border:1px solid #0d1f35;
border-radius:9px;padding:11px 16px;font-size:11px">
Cancelar
</button>
</div>
</div>
</div>

<script>
const STAGES = [
{label:'Coletando dores', detail:'Buscando reclamações no Reddit…', pct:15},
{label:'Pesquisando concorrentes', detail:'Analisando gaps de mercado…', pct:35},
{label:'Pain Radar (Claude)', detail:'Clusterizando dores e pontuando…', pct:55},
{label:'Debate GPT × Claude', detail:'Orquestrando rodadas de debate…', pct:80},
{label:'Decisão final', detail:'Calculando score e rejeição…', pct:95},
{label:'Concluído', detail:'Resultado salvo em outputs/main_run/', pct:100},
];

let _running = false, _pollIv = null, _lastLogLen = 0;
let _currentOpp = null, _startTime = null;

// Stage dots init
(function(){
const c = document.getElementById('stage-dots');
STAGES.forEach((_,i) => {
const d = document.createElement('div');
d.className = 'step-dot'; d.id = 'dot-'+i;
c.appendChild(d);
});
})();

// Status
function setStatus(state, text) {
document.getElementById('status-dot').className = 'status-dot ' + (state||'');
document.getElementById('status-text').textContent = text;
}
function updateTime() {
if (!_startTime) return;
const s = Math.floor((Date.now()-_startTime)/1000);
const el = document.getElementById('status-time');
const m = Math.floor(s/60), sec = s%60;
if (el) el.textContent = '· '+(m>0?m+'min ':'')+sec+'s';
}
setInterval(updateTime, 1000);

// Progress
function setProgress(pct, idx, label, detail) {
document.getElementById('prog-fill').style.width = pct+'%';
document.getElementById('current-step').textContent = label;
document.getElementById('step-detail').textContent = detail||'';
for (let i=0; i<STAGES.length; i++) {
const d = document.getElementById('dot-'+i);
if (d) d.className = 'step-dot '+(i<idx?'done':i===idx?'active':'');
}
}

function setExecRunning(on) {
document.getElementById('exec-idle').style.display = on ? 'none' : 'flex';
}

// Modal
function openAutoModal() { document.getElementById('auto-modal').classList.add('open'); }
function closeAutoModal(e) {
if (!e || e.target===document.getElementById('auto-modal'))
document.getElementById('auto-modal').classList.remove('open');
}

// Run
async function runOrch(mode) {
if (_running) { addLog(' Já está rodando…','warn'); return; }
closeAutoModal();

const body = {mode};
if (mode==='auto') {
body.niche = document.getElementById('inp-niche')?.value || 'restaurant';
body.problem = document.getElementById('inp-problem')?.value || 'profit margin';
body.subreddits = document.getElementById('inp-subreddits')?.value || 'restaurantowners';
}

clearLog(); showDecisionEmpty();
setProgress(5,-1,'Iniciando…','Preparando ambiente…');
setExecRunning(true); setStatus('running','Rodando');
_startTime = Date.now(); _lastLogLen = 0;
['btn-demo','btn-auto','btn-json'].forEach(id=>{
const b=document.getElementById(id); if(b) b.disabled=true;
});
addLog(' ORCH modo '+mode.toUpperCase()+' iniciado','info');

const res = await fetch('/api/orchestrator/run',{
method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify(body)
}).catch(()=>null);
const data = res ? await res.json().catch(()=>({})) : {};
addLog(' → '+(data.message||'Iniciado'), data.status==='already_running'?'warn':'info');

_running = true;
_pollIv = setInterval(poll, 1500);
}

// Poll
async function poll() {
const res = await fetch('/api/orchestrator/status').catch(()=>null);
if (!res) return;
const data = await res.json().catch(()=>({}));
const logs = data.log||[];
for (let i=_lastLogLen; i<logs.length; i++) { addLog(logs[i].msg); inferStage(logs[i].msg); }
_lastLogLen = logs.length;

if (!data.running && _running) {
_running = false; clearInterval(_pollIv); _pollIv = null;
const last = logs[logs.length-1]?.msg||'';
const ok = /|sucesso/i.test(last);
if (ok) {
setProgress(100,STAGES.length-1,'Concluído ','Carregando decisão…');
setStatus('done','Concluído');
await loadDecision();
} else {
setProgress(0,-1,'Erro na execução','Verifique o log abaixo');
setStatus('error','Erro');
setExecRunning(false);
}
['btn-demo','btn-auto','btn-json'].forEach(id=>{
const b=document.getElementById(id); if(b) b.disabled=false;
});
}
}

function inferStage(msg) {
const m = msg.toLowerCase();
if (/coletando|reddit|reclamação|complaint/.test(m)) setProgress(15,0,STAGES[0].label,STAGES[0].detail);
else if (/concorrent|competitor|pesquisando/.test(m)) setProgress(35,1,STAGES[1].label,STAGES[1].detail);
else if (/pain radar|cluster|dor/.test(m)) setProgress(55,2,STAGES[2].label,STAGES[2].detail);
else if (/debate|rodada|gpt|claude/.test(m)) setProgress(80,3,STAGES[3].label,STAGES[3].detail);
else if (/resultado|aprovad|rejeitad|score/.test(m)) setProgress(95,4,STAGES[4].label,STAGES[4].detail);
}

// Decision
function showDecisionEmpty() {
document.getElementById('decision-empty').style.display = 'flex';
document.getElementById('decision-content').style.display = 'none';
_currentOpp = null;
}

async function loadDecision() {
const res = await fetch('/api/orchestrator/opportunity').catch(()=>null);
if (!res) return;
const data = await res.json().catch(()=>({}));
if (data.error) { addLog(' '+data.error,'err'); setExecRunning(false); return; }
if (data.status==='rejeitado') { setExecRunning(false); renderRejected(data); return; }
_currentOpp = data; setExecRunning(false); renderApproved(data);
}

function fmtBRL(v) { return 'R$ '+Math.round(v||0).toLocaleString('pt-BR'); }

function renderApproved(data) {
const imp = data.impacto||'medio';
const cor = {alto:'#f59e0b',medio:'#3b82f6',baixo:'#10b981'}[imp]||'#3b82f6';
const govLabel = {
alto:' Requer aprovação humana',
medio:' Executado com aviso',
baixo:' Auto-aprovado',
}[imp]||' Verificar';
const sum = data.summary||{};
const roi = Math.round((data.lucro||0)-(data.custo||0));
const acoes = (data.next_actions||[]).map((a,i)=>`
<div class="ranking-item fi" style="animation-delay:${i*80}ms">
<span style="font-size:14px">${['','',''][i]||'→'}</span>
<span style="color:#94a3b8">${a}</span>
</div>`).join('');

document.getElementById('decision-empty').style.display = 'none';
document.getElementById('decision-content').style.display = 'block';
document.getElementById('decision-content').innerHTML = `
<div class="decision-card fi">
<div>
<div style="font-size:9px;font-weight:800;color:#8b5cf699;text-transform:uppercase;
letter-spacing:1px;margin-bottom:6px"> Oportunidade detectada</div>
<div class="opp-name">${data.acao||'—'}</div>
<div class="opp-desc" style="margin-top:6px">
O sistema encontrou uma oportunidade com alto potencial de lucro.<br>
${sum.proposed_solution||sum.core_problem||''}
</div>
</div>

<div class="opp-metrics">
<div class="metric-box">
<div class="metric-val" style="color:#ef4444">${fmtBRL(data.custo)}</div>
<div class="metric-lbl"> Custo</div>
</div>
<div class="metric-box">
<div class="metric-val" style="color:#3b82f6">${fmtBRL(data.lucro)}</div>
<div class="metric-lbl"> Potencial</div>
</div>
<div class="metric-box">
<div class="metric-val" style="color:#10b981">+${fmtBRL(roi)}</div>
<div class="metric-lbl"> ROI</div>
</div>
</div>

<div style="display:flex;align-items:center;gap:8px">
<div class="gov-badge gov-${imp}">${govLabel}</div>
<span style="font-size:11px;color:#1e3a5f">${data.roi_pct||0}% retorno</span>
</div>

<div class="opp-actions">
<button class="btn-approve" onclick="executeOpp(true)"> Aprovar</button>
<button class="btn-reject" onclick="executeOpp(false)"> Rejeitar</button>
</div>

${acoes?`<div>
<div style="font-size:9px;font-weight:800;color:#0d2a40;text-transform:uppercase;
letter-spacing:1px;margin-bottom:8px">PRÓXIMAS AÇÕES</div>
<div style="display:flex;flex-direction:column;gap:6px">${acoes}</div>
</div>`:''}
</div>`;
}

function renderRejected(data) {
const motivos = (data.motivos||[]).map(m=>`
<div style="display:flex;gap:8px;font-size:11px;color:#64748b;line-height:1.6">
<span style="color:#ef444466"></span><span>${m}</span>
</div>`).join('');
document.getElementById('decision-empty').style.display = 'none';
document.getElementById('decision-content').style.display = 'block';
document.getElementById('decision-content').innerHTML = `
<div style="padding:20px;height:100%;display:flex;flex-direction:column;gap:14px">
<div style="font-size:9px;font-weight:800;color:#ef444499;text-transform:uppercase;
letter-spacing:1px"> Oportunidade rejeitada</div>
<div style="font-size:20px;font-weight:800;color:#e2e8f0">Score: ${data.score}/100</div>
<div style="background:#ef444408;border:1px solid #ef444422;border-radius:10px;
padding:14px;display:flex;flex-direction:column;gap:6px">
${motivos||'<div style="color:#475569;font-size:11px">Score abaixo do limiar mínimo</div>'}
</div>
<div style="color:#1e3a5f;font-size:11px">
Tente ajustar o nicho ou problema e rode novamente.
</div>
</div>`;
}

async function executeOpp(approved) {
if (!_currentOpp) return;
document.querySelectorAll('.btn-approve,.btn-reject').forEach(b=>b.disabled=true);
if (!approved) { addLog(' Oportunidade rejeitada pelo usuário','warn'); showDecisionEmpty(); return; }
addLog('⏳ Enviando para aprovação…','info');
const payload = {
acao:'Lançar produto: '+_currentOpp.acao,
descricao:'Score ORCH: '+_currentOpp.score+'/100',
produto:_currentOpp.acao,
custo:_currentOpp.custo,
lucro_estimado:_currentOpp.lucro,
};
const res = await fetch('/api/request-approval',{
method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify(payload)
}).catch(()=>null);
const data = res ? await res.json().catch(()=>({})) : {};
addLog(data.message||'Enviado', /auto|baixo/.test(data.status||'')?'ok':'warn');
document.querySelectorAll('.btn-approve,.btn-reject').forEach(b=>b.disabled=false);
}

// Log
function addLog(msg, cls) {
const c = document.getElementById('log-entries');
if (c.querySelector('span')?.textContent?.includes('Aguardando')) c.innerHTML='';
const line = document.createElement('div');
line.className = 'log-e fi '+(cls||autoClass(msg));
line.textContent = msg;
c.appendChild(line);
c.scrollTop = c.scrollHeight;
}
function autoClass(msg) {
if (/|concluído|sucesso|aprovad|ok/i.test(msg)) return 'ok';
if (/|erro|error/i.test(msg)) return 'err';
if (/|warn|alerta/i.test(msg)) return 'warn';
if (/|→|info|iniciand/i.test(msg)) return 'info';
return '';
}
function clearLog() {
document.getElementById('log-entries').innerHTML =
'<span class="log-e" style="color:#0d1f35">Log limpo.</span>';
}

// Init
(async()=>{
const res = await fetch('/api/orchestrator/status').catch(()=>null);
const data = res ? await res.json().catch(()=>({})) : {};
if (data.running) {
_running=true; _startTime=Date.now();
(data.log||[]).forEach(l=>addLog(l.msg));
_lastLogLen=(data.log||[]).length;
setStatus('running','Rodando'); setExecRunning(true);
setProgress(10,0,'Em execução…','Processo em andamento…');
['btn-demo','btn-auto','btn-json'].forEach(id=>{
const b=document.getElementById(id); if(b) b.disabled=true;
});
_pollIv=setInterval(poll,1500);
} else {
const r2 = await fetch('/api/orchestrator/result').catch(()=>null);
const d2 = r2 ? await r2.json().catch(()=>({})) : {};
if (!d2.error) {
await loadDecision();
if (_currentOpp) {
setProgress(100,STAGES.length-1,'Último resultado carregado','Execute novamente para atualizar');
setStatus('done','Pronto'); setExecRunning(false);
}
}
}
})();

// Block 2 — Verifica saúde dos provedores e mostra banner degradado
async function checkSystemHealth() {
const res = await fetch('/api/system-health').catch(()=>null);
if (!res || !res.ok) return;
const data = await res.json().catch(()=>({}));
const banner = document.getElementById('degraded-banner');
const msg = document.getElementById('degraded-msg');
const provSpan = document.getElementById('degraded-provider');
if (!banner) return;
if (data.mode === 'normal') {
banner.style.display = 'none';
} else {
banner.style.display = 'flex';
const failing = Object.entries(data.providers||{})
.filter(([,v])=>v!=='ok').map(([k,v])=>`${k}: ${v}`).join(' | ');
msg.textContent = data.mode === 'heuristic'
? ' APIs indisponíveis — rodando em modo heurístico (respostas simuladas)'
: ' Sistema em modo degradado — uma API indisponível';
provSpan.textContent = failing ? `(${failing})` : '';
if (data.custo_api_brl > 0) {
provSpan.textContent += ` | Custo API mês: R$${data.custo_api_brl.toFixed(2)}`;
}
}
}
checkSystemHealth();
setInterval(checkSystemHealth, 60000);
</script>
</body>
</html>"""


# CLI


def main():
    parser = argparse.ArgumentParser(description="MYO Control Server v3")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    os.chdir(str(BASE_DIR))
    print(f"\n MYO System v3 — http://localhost:{args.port}")
    print(f" Home executiva : http://localhost:{args.port}/")
    print(f" ORCH Engine : http://localhost:{args.port}/orch")
    print(f" Operacional : http://localhost:{args.port}/dashboard")
    print(f" Executivo : http://localhost:{args.port}/executive")
    print(f" API : http://localhost:{args.port}/docs\n")
    uvicorn.run(
        "myo_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
