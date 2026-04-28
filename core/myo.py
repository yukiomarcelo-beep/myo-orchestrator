#!/usr/bin/env python3
"""
MYO — Menu Principal
Ponto de entrada único para todo o sistema.
Uso: python3 myo.py
"""

import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import time

from core.safe_exec import safe_exec

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# ── Cores ──────────────────────────────────────────────────
C = "\033[0m"  # reset
B = "\033[1m"  # bold
DIM = "\033[2m"  # dim
CY = "\033[96m"  # cyan
PK = "\033[95m"  # pink/purple
GR = "\033[92m"  # green
YL = "\033[93m"  # yellow
RD = "\033[91m"  # red
BL = "\033[94m"  # blue
GY = "\033[90m"  # gray


def clr():
    os.system("clear")


def header():
    print(f"""
{PK}{B}  ╔══════════════════════════════════════════════╗
  ║          MYO — Pipeline de Negócio           ║
  ╚══════════════════════════════════════════════╝{C}
""")


def sep(label=""):
    if label:
        print(f"\n{GY}  ─── {label} ───────────────────────────{C}")
    else:
        print(f"{GY}  ──────────────────────────────────────────────{C}")


def ask(prompt, default=""):
    val = input(f"{CY}  → {prompt}{C} ").strip()
    return val if val else default


def run(cmd, cwd=BASE):
    print(f"\n{GY}  Executando...{C}\n")
    safe_exec(shlex.split(cmd), cwd=cwd)
    print(f"\n{GR}  ✓ Concluído.{C}")
    input(f"\n{GY}  Pressione Enter para voltar ao menu...{C}")


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ═══════════════════════════════════════════════════════════
# MENUS
# ═══════════════════════════════════════════════════════════


def menu_main():
    while True:
        clr()
        header()
        print(f"  {B}O que você quer fazer hoje?{C}\n")

        print(f"  {CY}{B}[ NOVA IDEIA ]{C}")
        print(f"  {B}1{C}  Avaliar nova ideia de produto/negócio")
        print(f"  {B}2{C}  Rodar pipeline completo (do zero ao dashboard)")

        sep("CONTEÚDO & PRODUÇÃO")
        print(f"  {B}3{C}  Registrar performance de conteúdo publicado")
        print(f"  {B}4{C}  Validar interesse do mercado")
        print(f"  {B}5{C}  Decidir se devo escalar um produto")

        sep("VENDAS & LEADS")
        print(f"  {B}6{C}  Adicionar lead novo (alguém me mandou mensagem)")
        print(f"  {B}7{C}  Ver pipeline de leads (kanban)")
        print(f"  {B}8{C}  Atualizar estágio de um lead")

        sep("FINANCEIRO")
        print(f"  {B}9{C}  Simular cenários de crescimento")
        print(f"  {B}10{C} Calcular margem de um produto")

        sep("NOTION")
        print(f"  {B}13{C} Notion Engine (processar itens da database)")

        sep("DASHBOARD")
        print(f"  {B}11{C} Abrir dashboard no navegador")
        print(f"  {B}12{C} Iniciar servidor (celular/rede)")

        sep()
        print(f"  {B}0{C}  Sair\n")

        op = ask("Escolha uma opção:").strip()

        if op == "1":
            menu_avaliar_ideia()
        elif op == "2":
            menu_pipeline_completo()
        elif op == "3":
            menu_performance()
        elif op == "4":
            menu_validacao()
        elif op == "5":
            menu_scaling()
        elif op == "6":
            menu_add_lead()
        elif op == "7":
            menu_ver_pipeline()
        elif op == "8":
            menu_update_lead()
        elif op == "9":
            menu_simulator()
        elif op == "10":
            menu_financeiro()
        elif op == "11":
            menu_dashboard_local()
        elif op == "12":
            menu_servidor()
        elif op == "13":
            menu_notion()
        elif op == "0":
            sys.exit(0)
        else:
            print(f"\n{RD}  Opção inválida.{C}")
            time.sleep(1)


# ── 1. AVALIAR IDEIA ────────────────────────────────────────
def menu_avaliar_ideia():
    clr()
    header()
    print(f"  {CY}{B}Avaliar nova ideia de negócio{C}\n")
    print("  O sistema vai analisar e dar um score 0-100 com prioridade.\n")

    titulo = ask("Nome da ideia (ex: CFO Digital, Mentoria Instagram):")
    if not titulo:
        return

    print(f"\n  {DIM}Opções de entrada:{C}")
    print(f"  {B}1{C}  Só o nome (rápido)")
    print(f"  {B}2{C}  Nome + descrição + público (análise mais precisa)")
    modo = ask("Modo [1]:", "1")

    if modo == "2":
        desc = ask("Descreva o produto/serviço em 1-2 linhas:")
        publico = ask("Público-alvo (ex: MEI, mães empreendedoras):")
        mercado = ask("Mercado/nicho (ex: finanças, maternidade):")
        payload = json.dumps(
            {
                "idea_title": titulo,
                "idea_description": desc,
                "target_audience": publico,
                "market": mercado,
            },
            ensure_ascii=False,
        )
        cmd = f"{PY} opportunity_scorer.py --json '{payload}'"
    else:
        cmd = f'{PY} opportunity_scorer.py "{titulo}"'

    run(cmd)


# ── 2. PIPELINE COMPLETO ────────────────────────────────────
def menu_pipeline_completo():
    clr()
    header()
    print(f"  {CY}{B}Pipeline Completo — Master Controller{C}\n")
    print("  Roda todos os engines em sequência: avalia → cria produto")
    print("  → conteúdo → vídeo → funil → CRM → performance → escala.\n")

    objetivo = ask("Qual o objetivo? (ex: lançar curso de Excel para MEI):")
    if not objetivo:
        return

    mercado = ask("Mercado/nicho (opcional, Enter para pular):")

    print(f"\n  {B}Modo de execução:{C}")
    print(f"  {B}1{C}  Auto       — roda tudo sem parar (mais rápido)")
    print(f"  {B}2{C}  Semi-auto  — pausa nas decisões importantes (recomendado)")
    print(f"  {B}3{C}  Manual     — pausa em cada etapa (controle total)")
    modo_op = ask("Modo [2]:", "2")
    modos = {"1": "auto", "2": "semi_auto", "3": "manual"}
    modo = modos.get(modo_op, "semi_auto")

    cmd = f'{PY} master_controller.py --mode {modo} --objective "{objetivo}"'
    if mercado:
        cmd += f' --market "{mercado}"'
    run(cmd)


# ── 3. PERFORMANCE ──────────────────────────────────────────
def menu_performance():
    clr()
    header()
    print(f"  {CY}{B}Registrar performance de conteúdo publicado{C}\n")
    print("  Use depois de publicar um vídeo, reels ou carrossel.")
    print("  O sistema calcula o score e diz o que repetir/evitar.\n")

    titulo = ask("Título/nome do conteúdo (ex: CFO Digital — reels #1):")
    if not titulo:
        return

    tipo = ask("Tipo [video/carrossel/post/stories]:", "video")
    plat = ask("Plataforma [instagram/youtube/tiktok]:", "instagram")

    print(f"\n  {DIM}Métricas (só preencha o que tiver, Enter para 0):{C}")
    views = ask("Views:", "0")
    likes = ask("Likes:", "0")
    comments = ask("Comentários:", "0")
    saves = ask("Salvamentos:", "0")
    shares = ask("Compartilhamentos:", "0")
    clicks = ask("Cliques no link:", "0")
    leads = ask("Leads captados:", "0")

    cmd = (
        f"{PY} performance_engine.py "
        f'--title "{titulo}" '
        f"--type {tipo} "
        f"--platform {plat} "
        f"--views {views} --likes {likes} --comments {comments} "
        f"--saves {saves} --shares {shares} --clicks {clicks} --leads {leads}"
    )
    run(cmd)


# ── 4. VALIDAÇÃO ────────────────────────────────────────────
def menu_validacao():
    clr()
    header()
    print(f"  {CY}{B}Validar interesse do mercado{C}\n")
    print("  Análise mais profunda: DMs recebidos, leads e engajamento")
    print("  Decisão: escalar / ajustar / descartar.\n")

    titulo = ask("Produto/ideia que quer validar:")
    if not titulo:
        return

    plat = ask("Plataforma [instagram]:", "instagram")

    print(f"\n  {DIM}Métricas do conteúdo de teste:{C}")
    views = ask("Views:", "0")
    likes = ask("Likes:", "0")
    comments = ask("Comentários:", "0")
    saves = ask("Salvamentos:", "0")
    clicks = ask("Cliques no link:", "0")
    dms = ask("DMs/mensagens recebidas:", "0")
    leads = ask("Leads captados:", "0")

    payload = json.dumps(
        {
            "idea_title": titulo,
            "platform": plat,
            "views": int(views or 0),
            "likes": int(likes or 0),
            "comments": int(comments or 0),
            "saves": int(saves or 0),
            "clicks": int(clicks or 0),
            "dm_requests": int(dms or 0),
            "leads": int(leads or 0),
        },
        ensure_ascii=False,
    )
    run(f"{PY} validation_engine.py --json '{payload}'")


# ── 5. SCALING ──────────────────────────────────────────────
def menu_scaling():
    clr()
    header()
    print(f"  {CY}{B}Decidir se devo escalar um produto{C}\n")
    print("  Combina performance + validação + conversão para decidir:")
    print("  ESCALAR (≥75) / OTIMIZAR (≥50) / PARAR (<50).\n")

    print(f"  {B}1{C}  Auto — pega dados existentes automaticamente")
    print(f"  {B}2{C}  Manual — informe os dados agora")
    op = ask("Opção [1]:", "1")

    if op == "2":
        titulo = ask("Produto:")
        perf = ask("Score de performance (0-100):", "0")
        valid = ask("Score de validação (0-100):", "0")
        leads = ask("Total de leads:", "0")
        sales = ask("Total de vendas:", "0")
        ticket = ask("Ticket médio (R$):", "297")
        payload = json.dumps(
            {
                "idea_title": titulo,
                "performance_score": float(perf),
                "validation_score": float(valid),
                "leads": int(leads),
                "sales": int(sales),
                "ticket": float(ticket),
            },
            ensure_ascii=False,
        )
        run(f"{PY} scaling_engine.py --json '{payload}'")
    else:
        titulo = ask("Produto específico (Enter para todos):", "")
        if titulo:
            run(f'{PY} scaling_engine.py --title "{titulo}"')
        else:
            run(f"{PY} scaling_engine.py")


# ── 6. ADICIONAR LEAD ───────────────────────────────────────
def menu_add_lead():
    clr()
    header()
    print(f"  {CY}{B}Adicionar lead novo{C}\n")
    print("  Use quando alguém mandar mensagem no Instagram, WhatsApp etc.")
    print("  O sistema classifica, dá score e gera follow-up.\n")

    nome = ask("Nome do lead:")
    if not nome:
        return

    fonte = ask("De onde veio? [instagram_bio/stories/reels/whatsapp/indicacao]:", "instagram_bio")
    msg = ask("O que ele escreveu? (cole a mensagem):")
    produto = ask("Qual produto mostrou interesse? (ex: CFO Digital):")

    payload = json.dumps(
        {"name": nome, "source": fonte, "message": msg, "idea_title": produto}, ensure_ascii=False
    )
    run(f"{PY} crm_engine.py --json '{payload}'")


# ── 7. VER PIPELINE ─────────────────────────────────────────
def menu_ver_pipeline():
    clr()
    header()
    print(f"  {CY}{B}Pipeline de Leads — Kanban{C}\n")
    run(f"{PY} crm_engine.py --pipeline")


# ── 8. UPDATE LEAD ──────────────────────────────────────────
def menu_update_lead():
    clr()
    header()
    print(f"  {CY}{B}Atualizar lead{C}\n")

    # Mostra pipeline primeiro
    print(f"  {DIM}Pipeline atual:{C}\n")
    safe_exec([PY, "crm_engine.py", "--pipeline"], cwd=BASE)

    print(f"\n  {DIM}Estágios: entrada / interessado / qualificado / cliente{C}")
    print(f"  {DIM}Status:   ativo / inativo / perdido / cliente{C}\n")

    lead_id = ask("ID do lead (ex: lead_001):")
    if not lead_id:
        return

    print("\n  O que quer atualizar?")
    print(f"  {B}1{C}  Estágio do pipeline")
    print(f"  {B}2{C}  Status")
    print(f"  {B}3{C}  Ambos")
    op = ask("Opção [1]:", "1")

    args = [PY, "crm_engine.py", "--update", lead_id]
    if op in ("1", "3"):
        stage = ask("Novo estágio [entrada/interessado/qualificado/cliente]:")
        args += ["--stage", stage]
    if op in ("2", "3"):
        status = ask("Novo status [ativo/inativo/perdido/cliente]:")
        args += ["--status", status]
    print(f"\n{GY}  Executando...{C}\n")
    safe_exec(args, cwd=BASE)
    print(f"\n{GR}  ✓ Concluído.{C}")
    input(f"\n{GY}  Pressione Enter para voltar ao menu...{C}")


# ── 9. SIMULADOR ────────────────────────────────────────────
def menu_simulator():
    clr()
    header()
    print(f"  {CY}{B}Simular cenários de crescimento{C}\n")
    print("  Mostra 6 cenários: o que acontece se você dobrar leads,")
    print("  melhorar conversão ou aumentar o ticket.\n")

    leads = ask("Quantos leads você tem hoje?", "20")
    conv = ask("Taxa de conversão % (ex: 15):", "15")
    ticket = ask("Ticket médio R$:", "297")
    custo = ask("Custo mensal R$ (ads + ferramentas):", "350")

    cmd = (
        f"{PY} growth_simulator.py "
        f"--leads {leads} "
        f"--conversion {conv} "
        f"--ticket {ticket} "
        f"--cost {custo}"
    )
    run(cmd)


# ── 10. FINANCEIRO ──────────────────────────────────────────
def menu_financeiro():
    clr()
    header()
    print(f"  {CY}{B}Calcular margem de produto{C}\n")
    print("  Calcula custo total, margem % e diz se deve escalar.\n")

    titulo = ask("Nome do produto:")
    criacao = ask("Custo de criação R$ (tempo, gravação, edição):", "100")
    aquis = ask("Custo de aquisição R$ (ads por venda):", "80")
    operac = ask("Custo operacional R$ (plataforma, suporte/mês):", "30")
    preco = ask("Preço de venda R$:", "297")

    payload = json.dumps(
        {
            "idea_title": titulo,
            "creation_cost": float(criacao),
            "acquisition_cost": float(aquis),
            "operational_cost": float(operac),
            "selling_price": float(preco),
        },
        ensure_ascii=False,
    )
    run(f"{PY} financial_engine.py --product '{payload}'")


# ── 11. DASHBOARD LOCAL ─────────────────────────────────────
def menu_dashboard_local():
    clr()
    header()
    print(f"  {CY}{B}Abrindo dashboard...{C}\n")

    root = os.path.dirname(BASE)  # sobe de core/ para a raiz do projeto
    dash = os.path.join(root, "dashboard.html")
    print("  Regenerando dados...", end=" ", flush=True)
    r = safe_exec([PY, "scripts/generate_dashboard.py"], cwd=root, capture_output=True)
    print("✓" if r.returncode == 0 else "✗")

    safe_exec(["open", dash])
    print(f"\n{GR}  Dashboard aberto no navegador.{C}")
    input(f"\n{GY}  Pressione Enter para voltar ao menu...{C}")


# ── 12. SERVIDOR ────────────────────────────────────────────
CLOUDFLARED = os.path.expanduser("~/bin/cloudflared")


def start_cloudflare_tunnel():
    """Inicia tunnel Cloudflare em background e retorna a URL pública."""
    if not os.path.exists(CLOUDFLARED):
        return None, "cloudflared não encontrado em ~/bin/cloudflared"
    import queue
    import re

    url_q = queue.Queue()
    log_path = os.path.join(BASE, "tunnel.log")

    def reader(proc):
        url_found = False
        with open(log_path, "w") as logf:
            for line in proc.stderr:
                logf.write(line)
                logf.flush()
                if not url_found:
                    m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
                    if m:
                        url_q.put(m.group(0))
                        url_found = True

    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", "http://localhost:8080"],
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    )
    t = threading.Thread(target=reader, args=(proc,), daemon=True)
    t.start()
    try:
        url = url_q.get(timeout=20)
        return proc, url
    except Exception:
        proc.terminate()
        return None, "Timeout — tunnel não respondeu"


def menu_servidor():
    clr()
    header()
    print(f"  {CY}{B}Iniciar servidor (acesso via celular/rede){C}\n")

    ip = local_ip()
    print(f"  Wi-Fi local : {GR}http://{ip}:8080{C}")
    cf_ok = os.path.exists(CLOUDFLARED)
    if cf_ok:
        print(f"  Internet    : {GR}Cloudflare Tunnel disponível{C}\n")
    else:
        print(f"  Internet    : {YL}cloudflared não instalado{C}\n")

    print(f"  {B}1{C}  Iniciar servidor local (mesma rede Wi-Fi)")
    print(f"  {B}2{C}  Iniciar + Cloudflare Tunnel {GR}(acesso de qualquer lugar){C}")
    print(f"  {B}3{C}  Parar servidor / tunnel")
    print(f"  {B}0{C}  Voltar\n")

    op = ask("Opção:")

    if op == "1":
        log = os.path.join(BASE, "server.log")
        with open(log, "a") as log_f:
            subprocess.Popen(
                [PY, os.path.join(BASE, "server.py"), "--watch"],
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )
        time.sleep(2)
        print(f"\n{GR}  Servidor rodando em background.{C}")
        print(f"  Acesse: {GR}http://localhost:8080{C}")
        print(f"  Celular (Wi-Fi): {GR}http://{ip}:8080{C}")
        input(f"\n{GY}  Pressione Enter para voltar...{C}")

    elif op == "2":
        # Inicia servidor
        log = os.path.join(BASE, "server.log")
        with open(log, "a") as log_f:
            subprocess.Popen(
                [PY, os.path.join(BASE, "server.py"), "--watch"],
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )
        time.sleep(2)
        print(f"\n{GR}  Servidor iniciado.{C}")
        print("  Abrindo tunnel Cloudflare... aguarde ~10s\n")

        proc, result = start_cloudflare_tunnel()
        if proc:
            # Salva URL para referência
            url_file = os.path.join(BASE, "tunnel_url.txt")
            with open(url_file, "w") as f:
                f.write(result)
            print(f"  {GR}{B}✓ Tunnel ativo!{C}")
            print(f"\n  {CY}{B}URL pública:{C}")
            print(f"  {GR}{B}  {result}{C}")
            print("\n  Use essa URL no celular de qualquer lugar do mundo.")
            print("  (salva em tunnel_url.txt)")
        else:
            print(f"\n{RD}  Erro no tunnel: {result}{C}")

        input(f"\n{GY}  Pressione Enter para voltar (tunnel continua rodando)...{C}")

    elif op == "3":
        subprocess.run(["pkill", "-f", "python.*server.py"])
        subprocess.run(["pkill", "-f", "cloudflared"])
        print(f"\n{YL}  Servidor e tunnel encerrados.{C}")
        time.sleep(1)


# ── 13. NOTION ENGINE ───────────────────────────────────────
def menu_notion():
    clr()
    header()
    print(f"  {CY}{B}Notion Engine — Orquestrador de Database{C}\n")
    print("  Busca itens com status 'novo' na sua database Notion,")
    print("  processa via OpenAI e devolve o resultado estruturado.\n")

    print(f"  {DIM}Modos disponíveis na database:{C}")
    print(f"  • {B}research_auto{C}  — análise estratégica de oportunidades")
    print(f"  • {B}dan_koe{C}        — conteúdo raiz + posts + carrosséis + vídeos")
    print(f"  • {B}produto{C}        — estruturação de oferta\n")

    print(f"  {B}1{C}  Processar itens novos agora (uma vez)")
    print(f"  {B}2{C}  Watch mode (verifica a cada 60s em background)")
    print(f"  {B}3{C}  Watch mode com intervalo customizado")
    print(f"  {B}0{C}  Voltar\n")

    op = ask("Opção:")

    if op == "1":
        run(f"{PY} notion_engine.py")
    elif op == "2":
        log = os.path.join(BASE, "notion_engine.log")
        with open(log, "a") as log_f:
            subprocess.Popen(
                [PY, os.path.join(BASE, "notion_engine.py"), "--watch"],
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )
        time.sleep(1)
        print(f"\n{GR}  Notion Engine rodando em background.{C}")
        print("  Logs: tail -f notion_engine.log")
        input(f"\n{GY}  Pressione Enter para voltar...{C}")
    elif op == "3":
        intervalo = ask("Intervalo em segundos [60]:", "60")
        log = os.path.join(BASE, "notion_engine.log")
        with open(log, "a") as log_f:
            subprocess.Popen(
                [PY, os.path.join(BASE, "notion_engine.py"), "--watch", "--interval", intervalo],
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )
        time.sleep(1)
        print(f"\n{GR}  Notion Engine rodando a cada {intervalo}s.{C}")
        print("  Logs: tail -f notion_engine.log")
        input(f"\n{GY}  Pressione Enter para voltar...{C}")


# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        menu_main()
    except KeyboardInterrupt:
        print(f"\n\n{GY}  Até logo!{C}\n")
        sys.exit(0)
