#!/usr/bin/env python3
"""
Competitor Collector

Coleta e perfiliza concorrentes usando Perplexity (principal) + scraping leve.

Usa Perplexity sonar para descobrir concorrentes e extrair dados estruturados.
Faz scraping mínimo nas páginas para complementar pricing e público.

Saída compatível com CompetitorResearchAdapter e PainRadarAdapter.

Uso direto:
 python competitor_collector.py # exemplo embutido
 python competitor_collector.py --niche "restaurant" --problem "margin pricing"

Como módulo:
 from competitor_collector import CompetitorCollector
 collector = CompetitorCollector()
 competitors = collector.search("restaurant", "profit margin pricing", max_results=8)
 payload = collector.export_payload(competitors, "outputs/competitors.json")
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
PERPLEXITY_MODEL = os.getenv("PERPLEXITY_MODEL", "sonar")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")


# Dataclass

@dataclass
class CompetitorRecord:
    name: str
    url: Optional[str] = None
    category: str = "unknown"
    summary: str = ""
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    pricing: Optional[str] = None
    target_customer: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# Perplexity Client

class PerplexityClient:
    """Chamadas à API Perplexity para pesquisa na web."""

    API_URL = "https://api.perplexity.ai/chat/completions"

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or PERPLEXITY_API_KEY
        self.model = model or PERPLEXITY_MODEL
        if not self.api_key:
            raise EnvironmentError("PERPLEXITY_API_KEY não configurada no .env")

    def search(self, query: str, max_tokens: int = 2000) -> tuple[str, float]:
        """Retorna (texto_resposta, custo_usd)."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Você é um pesquisador de mercado. "
                 "Responda sempre em JSON válido, sem markdown."},
                {"role": "user", "content": query},
            ],
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=45) as client:
            resp = client.post(self.API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        cost = round(
            usage.get("prompt_tokens", 0) * 1e-6 +
            usage.get("completion_tokens", 0) * 1e-6, 6
        )
        return text, cost


# GPT Fallback Client

class GPTClient:
    """Fallback para OpenAI quando Perplexity não está disponível."""

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model or GPT_MODEL
        if not self.api_key:
            raise EnvironmentError("OPENAI_API_KEY não configurada no .env")

    def search(self, query: str, max_tokens: int = 2000) -> tuple[str, float]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Você é um pesquisador de mercado. "
                 "Responda sempre em JSON válido, sem markdown."},
                {"role": "user", "content": query},
            ],
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=45) as client:
            resp = client.post("https://api.openai.com/v1/chat/completions",
                               json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        cost = round(
            usage.get("prompt_tokens", 0) * 2.5e-6 +
            usage.get("completion_tokens", 0) * 10e-6, 6
        )
        return text, cost


# Competitor Collector

class CompetitorCollector:
    """
    Coleta e perfiliza concorrentes para um nicho + problema.

    Estratégia:
    1. Usa Perplexity para identificar concorrentes reais na web
    2. Extrai dados estruturados (nome, categoria, preço, fraquezas, etc.)
    3. Faz scraping leve para complementar URLs não cobertas
    4. Deduplica e ordena por relevância
    """

    USER_AGENT = "MYO-CompetitorCollector/1.0 (research)"

    def __init__(self):
        try:
            self._client = PerplexityClient()
        except EnvironmentError:
            try:
                self._client = GPTClient()
                print(" Perplexity não disponível, usando GPT como fallback")
            except EnvironmentError:
                raise EnvironmentError(
                    "Configure PERPLEXITY_API_KEY ou OPENAI_API_KEY no .env"
                )
        self._total_cost = 0.0

    def search(
        self,
        niche_query: str,
        problem_query: str,
        max_results: int = 8,
    ) -> List[CompetitorRecord]:
        """
        Descobre e perfiliza concorrentes para um nicho + problema.

        Args:
            niche_query: nicho do produto (ex: "restaurant owners")
            problem_query: problema central (ex: "profit margin pricing cash flow")
            max_results: máximo de concorrentes a retornar

        Returns:
            lista de CompetitorRecord ordenada por relevância
        """
        print(f"\n Buscando concorrentes: {niche_query} | {problem_query}")

        # Etapa 1: descoberta de concorrentes
        candidates = self._discover_competitors(niche_query, problem_query, max_results)
        print(f" {len(candidates)} candidatos encontrados")

        # Etapa 2: perfil detalhado de cada um
        records: List[CompetitorRecord] = []
        for i, cand in enumerate(candidates[:max_results]):
            print(f" → [{i+1}/{min(len(candidates),max_results)}] Perfilizando: {cand.get('name','?')}")
            record = self._profile_competitor(cand, niche_query, problem_query)
            records.append(record)
            time.sleep(0.3) # evita rate limit

        print(f" Custo Perplexity: US$ {self._total_cost:.4f}")
        return self._deduplicate_competitors(records)

    def _discover_competitors(
        self,
        niche: str,
        problem: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Usa Perplexity para descobrir concorrentes reais na web."""
        prompt = f"""Pesquise na web e liste os {limit} principais concorrentes, ferramentas ou soluções
que atendem: nicho="{niche}", problema="{problem}".

Inclua: software, apps, serviços, consultorias, plataformas SaaS relevantes.

Responda APENAS em JSON:
{{
 "competitors": [
  {{
   "name": "nome da solução",
   "url": "url do site oficial ou nulo",
   "category": "software | app | consultoria | erp | planilha | outro",
   "one_liner": "o que faz em 1 frase",
   "pricing_raw": "preço ou faixa encontrada ou nulo",
   "target_raw": "público-alvo encontrado ou nulo"
  }}
 ]
}}"""

        try:
            text, cost = self._client.search(prompt, max_tokens=1500)
            self._total_cost += cost
            data = self._extract_json(text)
            return data.get("competitors", [])
        except Exception as e:
            print(f" Erro na descoberta: {e}")
            return []

    def _profile_competitor(
        self,
        candidate: Dict[str, Any],
        niche: str,
        problem: str,
    ) -> CompetitorRecord:
        """Gera perfil detalhado de um candidato (forças, fraquezas, etc.)."""
        name = candidate.get("name", "Sem nome")
        url = candidate.get("url")
        one_line = candidate.get("one_liner", "")
        pricing = candidate.get("pricing_raw")
        target = candidate.get("target_raw")
        category = candidate.get("category", "unknown")

        # Tenta enriquecer via scraping leve da página
        scraped = self._scrape_page(url) if url else {}
        if scraped.get("pricing") and not pricing:
            pricing = scraped["pricing"]
        if scraped.get("summary") and not one_line:
            one_line = scraped["summary"]

        # Análise de forças/fraquezas via IA
        prompt = f"""Analise brevemente o concorrente abaixo no contexto do problema "{problem}" para "{niche}".

Nome: {name}
URL: {url or 'desconhecida'}
Descrição: {one_line}
Preço: {pricing or 'desconhecido'}
Público: {target or 'desconhecido'}

Responda APENAS em JSON:
{{
 "summary": "descrição objetiva em 1 frase",
 "strengths": ["força 1", "força 2"],
 "weaknesses": ["fraqueza 1", "fraqueza 2", "fraqueza 3"],
 "pricing": "preço ou faixa clarificada",
 "target_customer": "público-alvo exato"
}}"""

        try:
            text, cost = self._client.search(prompt, max_tokens=600)
            self._total_cost += cost
            data = self._extract_json(text)
            return CompetitorRecord(
                name = name,
                url = url,
                category = category,
                summary = data.get("summary", one_line or ""),
                strengths = data.get("strengths", []),
                weaknesses = data.get("weaknesses", []),
                pricing = data.get("pricing") or pricing,
                target_customer = data.get("target_customer") or target,
                metadata = {"source": "perplexity", "niche": niche},
            )
        except Exception as e:
            print(f" Perfil falhou [{name}]: {e}")
            return CompetitorRecord(
                name = name,
                url = url,
                category = category,
                summary = one_line,
                pricing = pricing,
                target_customer = target,
                metadata = {"source": "perplexity_partial", "error": str(e)},
            )

    # Scraping leve

    def _scrape_page(self, url: str, timeout: int = 8) -> Dict[str, Any]:
        """
        Scraping mínimo de uma página para extrair pricing e resumo.
        Não usa BeautifulSoup — só regex + urllib.
        """
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", self.USER_AGENT)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(80_000).decode("utf-8", errors="ignore") # máx 80KB
        except Exception:
            return {}

        # Remove tags HTML
        text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()[:3000]

        # Meta description como summary
        meta_match = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
            raw, re.I
        )
        summary = meta_match.group(1).strip() if meta_match else text[:200]

        return {
            "summary": summary,
            "pricing": self._extract_pricing(text),
        }

    # Helpers

    def _extract_pricing(self, text: str) -> Optional[str]:
        patterns = [
            r"R\$\s*[\d.,]+(?:\s*/\s*m[êe]s)?",
            r"\$\d+(?:\.\d+)?(?:\s*/\s*mo(?:nth)?)?",
            r"USD\s*\d+",
            r"from\s+\$\d+",
            r"starting at\s+\$\d+",
            r"R\$\s*\d+(?:\.\d{3})*(?:,\d{2})?\s*(?:por|/)\s*m[êe]s",
            r"free(?:\s+tier)?",
            r"gratuito|grátis",
            r"sob consulta|on request|contact us",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return match.group(0)
        return None

    def _infer_target_customer(self, text: str) -> Optional[str]:
        text_l = text.lower()
        candidates = [
            "restaurantes" if any(t in text_l for t in ["restaurant", "restaurante", "food service"]) else None,
            "pequenas empresas" if any(t in text_l for t in ["small business", "smb", "pequenas empresas"]) else None,
            "varejo" if any(t in text_l for t in ["retail", "store", "shop owners", "varejo"]) else None,
            "e-commerce" if any(t in text_l for t in ["ecommerce", "e-commerce", "online stores"]) else None,
            "contadores" if any(t in text_l for t in ["accounting", "contabilidade", "contador"]) else None,
        ]
        for item in candidates:
            if item:
                return item
        return None

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"JSON não encontrado:\n{text[:200]}")

    @staticmethod
    def _guess_name_from_url(url: str) -> str:
        hostname = re.sub(r"https?://", "", url).split("/")[0]
        hostname = hostname.replace("www.", "")
        return hostname.split(".")[0].replace("-", " ").title()

    @staticmethod
    def _unique_urls(urls: List[str]) -> List[str]:
        seen: set[str] = set()
        out: List[str] = []
        for url in urls:
            normalized = url.split("?")[0].rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    @staticmethod
    def _deduplicate_competitors(
        records: List[CompetitorRecord],
    ) -> List[CompetitorRecord]:
        seen: set[str] = set()
        out: List[CompetitorRecord] = []
        for record in records:
            key = str((
                record.name.strip().lower(),
                (record.url or "").strip().lower().split("?")[0].rstrip("/"),
            ))
            if key in seen:
                continue
            seen.add(key)
            out.append(record)
        return out

    # Export

    def export_payload(
        self,
        records: List[CompetitorRecord],
        output_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Converte para lista de dicts compatível com CompetitorResearchAdapter.

        Args:
            records: lista de CompetitorRecord
            output_path: caminho para salvar JSON (opcional)
        """
        payload = [asdict(r) for r in records]

        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            print(f" {len(payload)} concorrentes salvos em: {output_path}")

        return payload


# Exemplo de uso

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Competitor Collector")
    parser.add_argument("--niche", default="restaurant")
    parser.add_argument("--problem", default="profit margin pricing cash flow")
    parser.add_argument("--max", type=int, default=8)
    parser.add_argument("--output", default="outputs/competitors_auto.json")
    args = parser.parse_args()

    collector = CompetitorCollector()
    competitors = collector.search(
        niche_query = args.niche,
        problem_query = args.problem,
        max_results = args.max,
    )
    payload = collector.export_payload(competitors, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
