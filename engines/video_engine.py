#!/usr/bin/env python3
"""
Video Engine — Pipeline AI
Transforma conteúdo do Content Engine em vídeos prontos para postar.

Fluxo:
  Content Output
  → Script Generator   (Claude)     — roteiro otimizado para vídeo
  → Variation Engine   (GPT)        — 3 versões agressivas + 3 elegantes
  → Select Best        (lógica)     — seleciona a melhor versão
  → Voice Engine       (ElevenLabs) — gera áudio narrado
  → Video Engine       (HeyGen)     — gera vídeo com avatar
  → Distribution Queue              — agenda publicação
  → Save Assets                     — persiste localmente

Uso:
  python video_engine.py                       # pega melhor conteúdo automaticamente
  python video_engine.py --title "CFO Digital"
  python video_engine.py --json '{...}'
  python video_engine.py --script-only          # apenas gera scripts sem TTS/vídeo
"""
import asyncio, json, os, sys, time, glob
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
HEYGEN_API_KEY     = os.getenv("HEYGEN_API_KEY", "")
CLAUDE_MODEL       = "claude-sonnet-4-6"
GPT_MODEL          = os.getenv("GPT_MODEL", "gpt-4o")
ELEVENLABS_VOICE   = os.getenv("ELEVENLABS_VOICE_ID", "")
OUTPUTS_DIR        = "outputs"

# ─── API helpers ──────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict | list:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for a, b in [("{", "}"), ("[", "]")]:
            s, e = raw.find(a), raw.rfind(b) + 1
            if s != -1 and e > s:
                try:
                    return json.loads(raw[s:e])
                except Exception:
                    pass
        return {"raw": raw}


async def _claude(prompt: str, max_tokens: int = 1600) -> tuple[dict | list, dict]:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não configurada")
    payload = {"model": CLAUDE_MODEL, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = data.get("content", [{}])[0].get("text", "")
    u = data.get("usage", {})
    return _parse_json(raw), {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((u.get("input_tokens", 0) * 3e-6) + (u.get("output_tokens", 0) * 15e-6), 6),
    }


async def _gpt(prompt: str) -> tuple[dict | list, dict]:
    if not OPENAI_API_KEY or "sua-chave" in OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY não configurada")
    payload = {"model": GPT_MODEL, "input": prompt}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = "\n".join(i.get("content", [{}])[0].get("text", "")
                    for i in data.get("output", []) if i.get("type") == "message")
    u = data.get("usage", {})
    return _parse_json(raw), {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((u.get("input_tokens", 0) * 2.5e-6) + (u.get("output_tokens", 0) * 10e-6), 6),
    }


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _p_script(content: dict) -> str:
    hook   = content.get("selected_hook", "")
    angle  = content.get("selected_angle", {})
    angle_text = angle.get("titulo", "") if isinstance(angle, dict) else str(angle)
    return f"""Você é um roteirista especialista em vídeos curtos de alto impacto.

Crie um roteiro de vídeo de até 30 segundos para:

Tema: {content['idea_title']}
Público: {content.get('target_audience', '')}
Gancho escolhido: {hook}
Ângulo: {angle_text}

Estrutura obrigatória:
- Hook (0-3s): primeira frase que para o scroll — chocante, direto, específico
- Desenvolvimento (4-22s): 2-3 pontos rápidos, linguagem falada, sem jargão
- CTA (23-30s): ação clara e urgente

Regras:
- Escrito como se fosse falado (linguagem coloquial)
- Máximo 120 palavras no total
- Cada seção claramente separada

Responda APENAS em JSON válido:

{{
  "hook": "",
  "desenvolvimento": "",
  "cta": "",
  "roteiro_completo": "",
  "duracao_estimada": "28s",
  "tom": "direto"
}}"""


def _p_variations(script: dict) -> str:
    roteiro = script.get("roteiro_completo", "")
    return f"""Com base neste roteiro de vídeo:

{roteiro}

Crie 6 variações:
- 3 versões AGRESSIVAS: mais urgentes, provocadoras, diretas, com números e dados
- 3 versões ELEGANTES: mais sofisticadas, aspiracionais, premium, com autoridade

Para cada variação mantenha a estrutura hook + desenvolvimento + cta.

Responda APENAS em JSON válido:

{{
  "agressivas": [
    {{"hook": "", "desenvolvimento": "", "cta": "", "roteiro_completo": ""}},
    {{"hook": "", "desenvolvimento": "", "cta": "", "roteiro_completo": ""}},
    {{"hook": "", "desenvolvimento": "", "cta": "", "roteiro_completo": ""}}
  ],
  "elegantes": [
    {{"hook": "", "desenvolvimento": "", "cta": "", "roteiro_completo": ""}},
    {{"hook": "", "desenvolvimento": "", "cta": "", "roteiro_completo": ""}},
    {{"hook": "", "desenvolvimento": "", "cta": "", "roteiro_completo": ""}}
  ]
}}"""


# ─── ElevenLabs TTS ───────────────────────────────────────────────────────────

async def _elevenlabs_tts(text: str, voice_id: str = None) -> dict:
    if not ELEVENLABS_API_KEY or "sua-chave" in ELEVENLABS_API_KEY:
        return {"error": "ELEVENLABS_API_KEY não configurada", "audio_url": None}

    vid = voice_id or ELEVENLABS_VOICE or "21m00Tcm4TlvDq8ikWAM"  # Rachel (padrão)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    payload = {
        "text": text[:2500],
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, json=payload, headers=headers)
            r.raise_for_status()

        # salvar áudio localmente
        os.makedirs(OUTPUTS_DIR, exist_ok=True)
        ts    = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{OUTPUTS_DIR}/audio_{ts}.mp3"
        with open(fname, "wb") as f:
            f.write(r.content)

        latency = int((time.time() - t0) * 1000)
        size_kb = len(r.content) // 1024
        return {"audio_file": fname, "audio_url": fname, "size_kb": size_kb,
                "latency_ms": latency, "error": None}

    except httpx.HTTPStatusError as e:
        return {"error": f"ElevenLabs {e.response.status_code}: {e.response.text[:200]}",
                "audio_url": None}
    except Exception as e:
        return {"error": str(e), "audio_url": None}


# ─── HeyGen Video ─────────────────────────────────────────────────────────────

async def _heygen_video(idea_title: str, script: str, audio_url: str = None) -> dict:
    if not HEYGEN_API_KEY or "sua-chave" in HEYGEN_API_KEY:
        return {"error": "HEYGEN_API_KEY não configurada", "video_url": None, "video_id": None}

    payload = {
        "video_inputs": [{
            "character": {"type": "avatar", "avatar_id": "default", "avatar_style": "normal"},
            "voice": {"type": "text", "input_text": script[:1000], "voice_id": "default"},
        }],
        "aspect_ratio": "9:16",
        "test": True,  # modo teste — sem consumir créditos em dev
    }

    if audio_url and audio_url.startswith("http"):
        payload["video_inputs"][0]["voice"] = {"type": "audio", "audio_url": audio_url}

    headers = {"X-Api-Key": HEYGEN_API_KEY, "Content-Type": "application/json"}

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post("https://api.heygen.com/v2/video/generate",
                             json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()

        video_id  = data.get("data", {}).get("video_id", "")
        latency   = int((time.time() - t0) * 1000)
        return {"video_id": video_id, "video_url": None,
                "status": "processing", "latency_ms": latency, "error": None}

    except httpx.HTTPStatusError as e:
        return {"error": f"HeyGen {e.response.status_code}: {e.response.text[:200]}",
                "video_url": None, "video_id": None}
    except Exception as e:
        return {"error": str(e), "video_url": None, "video_id": None}


async def _heygen_status(video_id: str, max_wait: int = 120) -> dict:
    """Faz polling do status do vídeo HeyGen até ficar pronto ou timeout."""
    if not HEYGEN_API_KEY or not video_id:
        return {"status": "unknown", "video_url": None}

    headers = {"X-Api-Key": HEYGEN_API_KEY}
    url     = f"https://api.heygen.com/v1/video_status.get?video_id={video_id}"
    waited  = 0

    while waited < max_wait:
        await asyncio.sleep(5)
        waited += 5
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url, headers=headers)
                r.raise_for_status()
                data = r.json().get("data", {})
            status = data.get("status", "")
            if status == "completed":
                return {"status": "completed", "video_url": data.get("video_url", "")}
            if status in ("failed", "error"):
                return {"status": "failed", "video_url": None}
        except Exception:
            pass

    return {"status": "timeout", "video_url": None}


# ─── Distribution Queue (local) ───────────────────────────────────────────────

def _criar_distribuicao(video_result: dict, caption: str, platforms: list = None) -> list:
    platforms = platforms or ["instagram", "tiktok", "youtube_shorts"]
    ts = time.strftime("%Y%m%d_%H%M%S")
    queue = []
    for i, platform in enumerate(platforms):
        queue.append({
            "id":           f"{ts}_{platform}",
            "video_url":    video_result.get("video_url") or video_result.get("video_id", ""),
            "caption":      caption,
            "platform":     platform,
            "status":       "pending",
            "scheduled_at": None,  # preencher com agendamento futuro
        })
    return queue


def _salvar_queue(queue: list, idea_title: str):
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    ts    = time.strftime("%Y%m%d_%H%M%S")
    slug  = idea_title.replace(" ", "_")[:25]
    fname = f"{OUTPUTS_DIR}/queue_{slug}_{ts}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    return fname


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def build_video(content: dict, script_only: bool = False) -> dict:
    title = content.get("idea_title", "")
    print(f"\n  Gerando vídeo: {title[:60]}")
    print("  " + "─" * 56)

    total_cost = 0.0

    # preparar input normalizado
    hooks  = content.get("hooks", [])
    angles = content.get("angles", [])
    scripts_existing = content.get("scripts", [])

    normalized = {
        "idea_title":      title,
        "target_audience": content.get("target_audience", ""),
        "selected_hook":   hooks[0] if hooks else "",
        "selected_angle":  angles[0] if angles else {},
    }

    # [1] Script — Claude
    print("  [1/4] Script via Claude...")
    # se já tem scripts do content_engine, usa o melhor como base
    if scripts_existing:
        base_script = scripts_existing[0]
        if isinstance(base_script, dict):
            base_script["roteiro_completo"] = (
                f"{base_script.get('gancho','')}\n"
                f"{base_script.get('desenvolvimento','')}\n"
                f"{base_script.get('cta','')}"
            )
        script = base_script
        print(f"        ✓ Usando script existente do Content Engine")
    else:
        script_raw, m1 = await _claude(_p_script(normalized))
        script = script_raw if isinstance(script_raw, dict) else {}
        total_cost += m1["cost"]
        print(f"        ✓ {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # [2] Variations — GPT
    print("  [2/4] Variations via GPT...")
    var_raw, m2 = await _gpt(_p_variations(script))
    variations = var_raw if isinstance(var_raw, dict) else {}
    total_cost += m2["cost"]
    n_vars = len(variations.get("agressivas", [])) + len(variations.get("elegantes", []))
    print(f"        ✓ {n_vars} variações · {m2['latency_ms']}ms · ${m2['cost']:.4f}")

    # selecionar melhor versão (padrão: primeira versão agressiva)
    all_versions = [script] + variations.get("agressivas", []) + variations.get("elegantes", [])
    selected = all_versions[0] if all_versions else script
    roteiro_final = selected.get("roteiro_completo", "") or (
        f"{selected.get('hook','')}\n{selected.get('desenvolvimento','')}\n{selected.get('cta','')}"
    )

    caption = f"🔥 {title}\n\nComente 'quero' para saber mais."

    result = {
        "idea_title":    title,
        "script":        script,
        "variations":    variations,
        "selected":      selected,
        "roteiro_final": roteiro_final,
        "caption":       caption,
        "audio":         {"status": "skipped"},
        "video":         {"status": "skipped"},
        "queue":         [],
        "total_cost":    0.0,
        "timestamp":     time.strftime("%Y%m%d_%H%M%S"),
    }

    if script_only:
        print("  [3/4] TTS — pulado (--script-only)")
        print("  [4/4] Vídeo — pulado (--script-only)")
    else:
        # [3] ElevenLabs TTS
        print("  [3/4] Voice via ElevenLabs...")
        audio = await _elevenlabs_tts(roteiro_final)
        result["audio"] = audio
        if audio.get("error"):
            print(f"        ⚠ {audio['error']}")
        else:
            print(f"        ✓ {audio.get('size_kb',0)}kb · {audio.get('latency_ms',0)}ms → {audio.get('audio_file','')}")

        # [4] HeyGen Video
        print("  [4/4] Vídeo via HeyGen...")
        video = await _heygen_video(title, roteiro_final, audio.get("audio_url"))
        result["video"] = video
        if video.get("error"):
            print(f"        ⚠ {video['error']}")
        elif video.get("video_id"):
            print(f"        ✓ video_id: {video['video_id']} (processando...)")
            print("        → aguardando HeyGen renderizar (máx 2min)...")
            status = await _heygen_status(video["video_id"], max_wait=120)
            result["video"].update(status)
            if status.get("video_url"):
                print(f"        ✓ URL: {status['video_url']}")

    # Distribution Queue
    queue = _criar_distribuicao(result["video"], caption)
    result["queue"] = queue
    qfname = _salvar_queue(queue, title)
    print(f"  Queue salva: {qfname}")

    result["total_cost"] = round(total_cost, 6)

    _salvar_local(result)
    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Persistência ─────────────────────────────────────────────────────────────

def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug  = result["idea_title"].replace(" ", "_")[:28]
    fname = f"{OUTPUTS_DIR}/video_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  Salvo em: {fname}")
    return fname


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa
        await salvar_tarefa(
            f"Vídeo: {result['idea_title'][:60]}",
            "video_engine",
            json.dumps(result, ensure_ascii=False, indent=2),
        )
    except Exception:
        pass


def _atualizar_dashboard():
    import subprocess, sys as _sys
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_dashboard.py")
    if not os.path.exists(script):
        return
    try:
        subprocess.run([_sys.executable, script], check=True, capture_output=True)
        dashboard = os.path.join(os.path.dirname(script), "dashboard.html")
        subprocess.Popen(["open", dashboard])
        print("  Dashboard atualizado.")
    except Exception as e:
        print(f"  Dashboard: {e}")


# ─── Display terminal ─────────────────────────────────────────────────────────

def _imprimir(result: dict):
    sc   = result.get("selected", {})
    var  = result.get("variations", {})
    aud  = result.get("audio", {})
    vid  = result.get("video", {})

    print("\n" + "═" * 62)
    print(f"  VIDEO ENGINE — {result['idea_title'][:40]}")
    print("═" * 62)

    print(f"\n  ─── Script selecionado ──────────────────────────────────")
    print(f"  Hook    : {sc.get('hook', sc.get('gancho', ''))}")
    print(f"  CTA     : {sc.get('cta', '')}")
    print(f"  Roteiro completo:")
    rf = result.get("roteiro_final", "")
    for line in rf.split("\n"):
        if line.strip():
            print(f"    {line}")

    n_agr = len(var.get("agressivas", []))
    n_ele = len(var.get("elegantes", []))
    print(f"\n  Variações: {n_agr} agressivas + {n_ele} elegantes")

    print(f"\n  ─── Produção ────────────────────────────────────────────")
    if aud.get("audio_file"):
        print(f"  Áudio  : {aud['audio_file']} ({aud.get('size_kb',0)}kb)")
    elif aud.get("error"):
        print(f"  Áudio  : ⚠ {aud['error']}")
    else:
        print(f"  Áudio  : {aud.get('status','')}")

    if vid.get("video_url"):
        print(f"  Vídeo  : {vid['video_url']}")
    elif vid.get("video_id"):
        print(f"  Vídeo  : ID {vid['video_id']} — status: {vid.get('status','')}")
    elif vid.get("error"):
        print(f"  Vídeo  : ⚠ {vid['error']}")
    else:
        print(f"  Vídeo  : {vid.get('status','')}")

    queue = result.get("queue", [])
    if queue:
        print(f"\n  ─── Distribution Queue ({len(queue)} itens) ─────────────────")
        for q in queue:
            print(f"  [{q['platform']:<16}] {q['status']} — {q['caption'][:50]}")

    print(f"\n  Caption: {result.get('caption','')}")
    print(f"  Custo  : ~${result['total_cost']:.4f}")
    print("═" * 62 + "\n")


# ─── Carregar conteúdo ────────────────────────────────────────────────────────

def _load_best_content() -> Optional[dict]:
    files = glob.glob(f"{OUTPUTS_DIR}/content_*.json")
    best  = None
    best_ts = ""
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            ts = data.get("timestamp", "")
            if ts > best_ts:
                best_ts = ts
                best = data
        except Exception:
            pass
    return best


def _load_content_by_title(title: str) -> Optional[dict]:
    for path in glob.glob(f"{OUTPUTS_DIR}/content_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if title.lower() in data.get("idea_title", "").lower():
                return data
        except Exception:
            pass
    return None


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    args        = sys.argv[1:]
    script_only = "--script-only" in args
    args        = [a for a in args if a != "--script-only"]
    content     = None

    if "--json" in args:
        idx     = args.index("--json")
        content = json.loads(args[idx + 1])

    elif "--title" in args:
        idx     = args.index("--title")
        title   = args[idx + 1] if idx + 1 < len(args) else ""
        content = _load_content_by_title(title)
        if not content:
            print(f"  Conteúdo não encontrado para: {title}")
            return

    else:
        content = _load_best_content()
        if content:
            print(f"\n  Conteúdo carregado: {content.get('idea_title','')} ({content.get('timestamp','')})")
        else:
            print("  Nenhum conteúdo encontrado. Rode content_engine.py primeiro.")
            return

    if not content.get("idea_title"):
        print("  idea_title obrigatório.")
        return

    if script_only:
        print("  Modo: script-only (sem TTS e vídeo)")

    await build_video(content, script_only=script_only)


if __name__ == "__main__":
    asyncio.run(main())
