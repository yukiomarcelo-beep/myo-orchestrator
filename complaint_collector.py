#!/usr/bin/env python3
"""
Complaint Collector

Coleta reclamações de dores em fontes abertas (Reddit, RSS, JSON local).
Calcula intensidade emocional, intenção comercial e frequência.

Saída compatível com PainRadarAdapter.

Uso direto:
 python complaint_collector.py # exemplo embutido
 python complaint_collector.py --queries "q1,q2,q3" --subreddits "sub1,sub2"
 python complaint_collector.py --json inputs/complaints.json

Como módulo:
 from complaint_collector import ComplaintCollector
 collector = ComplaintCollector()
 complaints = collector.collect_reddit_search(queries, subreddits, limit_per_query=15)
 payload = collector.export_payload(complaints, "outputs/complaints.json")
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree


# Dataclass

@dataclass
class ComplaintRecord:
    text: str
    source: str = "unknown"
    author: Optional[str] = None
    url: Optional[str] = None
    frequency_hint: float = 1.0 # 1–10 (calculado por upvotes/comentários)
    emotional_intensity: float = 5.0 # 1–10
    commercial_intent: float = 5.0 # 1–10
    metadata: Dict[str, Any] = field(default_factory=dict)


# Text Scorer (heurístico, sem custo de API)

class TextScorer:
    """
    Calcula emotional_intensity e commercial_intent via heurísticas
    de palavras-chave. Rápido, sem chamadas de API.
    """

    _EMOTIONAL_HIGH = [
        "perco", "perco dinheiro", "perde", "falindo", "falência", "dívida",
        "desespero", "impossível", "frustr", "ódio", "odeio", "detesto",
        "não aguento", "insustentável", "caindo", "quebrando", "socorro",
        "nunca funciona", "não resolve", "péssimo", "horrível", "terrível",
        "não entendo nada", "perdido", "confuso", "erro", "bug",
        "burnout", "esgotado", "estressado", "cansado",
        "losing money", "losing profit", "can't figure", "terrible",
        "frustrated", "hopeless", "disaster", "nightmare",
    ]
    _EMOTIONAL_MED = [
        "problema", "dificuldade", "desafio", "preocupado", "não consigo",
        "não sei", "não funciona", "difícil", "complicado", "confuso",
        "errado", "errei", "difícil de entender",
        "problem", "issue", "struggle", "difficult", "hard to",
        "can't understand", "not working", "broken",
    ]
    _COMMERCIAL_HIGH = [
        "solução", "ferramenta", "software", "app", "sistema", "plataforma",
        "quero contratar", "preciso de ajuda", "quanto custa", "pagar",
        "assinar", "mensalidade", "testei", "tentei usar", "usava",
        "existe algo", "tem algum", "qual o melhor", "recomenda",
        "solution", "tool", "software", "app", "platform", "pricing",
        "how much", "subscription", "willing to pay", "tried",
        "looking for", "any recommendation", "best tool",
    ]
    _COMMERCIAL_MED = [
        "como fazer", "como funciona", "como resolver", "tutorial", "aprendo",
        "aprendi", "estratégia", "método", "técnica", "dica",
        "how to", "how do", "strategy", "method", "tips", "guide",
    ]

    def emotional_intensity(self, text: str) -> float:
        t = text.lower()
        score = 3.0
        for kw in self._EMOTIONAL_HIGH:
            if kw in t:
                score += 1.2
        for kw in self._EMOTIONAL_MED:
            if kw in t:
                score += 0.5
        # exclamações e maiúsculas intensificam
        score += min(2.0, text.count("!") * 0.3)
        score += min(1.0, sum(1 for c in text if c.isupper()) / max(len(text), 1) * 15)
        return round(min(10.0, max(1.0, score)), 1)

    def commercial_intent(self, text: str) -> float:
        t = text.lower()
        score = 3.0
        for kw in self._COMMERCIAL_HIGH:
            if kw in t:
                score += 1.2
        for kw in self._COMMERCIAL_MED:
            if kw in t:
                score += 0.5
        # palavras que indicam busca ativa
        if any(w in t for w in ["busco", "procuro", "quero", "need", "want", "seeking"]):
            score += 1.0
        return round(min(10.0, max(1.0, score)), 1)


# Complaint Collector

class ComplaintCollector:
    """
    Coleta reclamações de:
    - Reddit (JSON público, sem auth)
    - RSS feeds
    - Arquivo JSON local
    """

    REDDIT_BASE = "https://www.reddit.com"
    USER_AGENT = "MYO-ComplaintCollector/1.0 (research)"
    REQUEST_DELAY = 1.2 # segundos entre requests para não ser bloqueado

    def __init__(self, scorer: Optional[TextScorer] = None):
        self.scorer = scorer or TextScorer()
        self._req_count = 0

    # Reddit

    def collect_reddit_search(
        self,
        queries: List[str],
        subreddits: Optional[List[str]] = None,
        limit_per_query: int = 15,
        min_score: int = 1,
        min_length: int = 40,
    ) -> List[ComplaintRecord]:
        """
        Busca posts no Reddit por queries + subreddits.
        Usa a API pública JSON (sem OAuth, sem chave).

        Args:
            queries: lista de termos de busca
            subreddits: lista de subreddits para restringir a busca
            limit_per_query: posts por query (máx 25 por chamada)
            min_score: upvote mínimo para incluir
            min_length: tamanho mínimo do texto (chars)
        """
        records: List[ComplaintRecord] = []
        targets = subreddits if subreddits else [None] # None = busca global

        for query in queries:
            for sub in targets:
                recs = self._fetch_reddit(
                    query = query,
                    subreddit = sub,
                    limit = min(limit_per_query, 25),
                    min_score = min_score,
                    min_length = min_length,
                )
                records.extend(recs)
                time.sleep(self.REQUEST_DELAY)

        return self._deduplicate(records)

    def _fetch_reddit(
        self,
        query: str,
        subreddit: Optional[str],
        limit: int,
        min_score: int,
        min_length: int,
    ) -> List[ComplaintRecord]:
        if subreddit:
            url = f"{self.REDDIT_BASE}/r/{subreddit}/search.json"
            source = f"reddit/r/{subreddit}"
        else:
            url = f"{self.REDDIT_BASE}/search.json"
            source = "reddit"

        params = urllib.parse.urlencode({
            "q": query,
            "sort": "relevance",
            "limit": limit,
            "type": "link",
            "restrict_sr": "1" if subreddit else "0",
        })
        full_url = f"{url}?{params}"

        try:
            req = urllib.request.Request(full_url)
            req.add_header("User-Agent", self.USER_AGENT)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            print(f" Reddit fetch error [{source}|{query[:30]}]: {e}")
            return []

        records: List[ComplaintRecord] = []
        children = data.get("data", {}).get("children", [])
        for child in children:
            d = child.get("data", {})
            title = (d.get("title") or "").strip()
            selftext = (d.get("selftext") or "").strip()
            permalink = d.get("permalink")
            author = d.get("author")
            score = float(d.get("score", 1) or 1)
            num_comments = float(d.get("num_comments", 0) or 0)

            text = f"{title}. {selftext}".strip()
            if not text or len(text) < min_length:
                continue
            if score < min_score:
                continue
            # filtra posts sem relevância à dor (muito curtos ou só promoção)
            if selftext and len(selftext) < 20 and not title:
                continue

            frequency_hint = min(10.0, 1.0 + (score / 50.0) + (num_comments / 20.0))

            records.append(ComplaintRecord(
                text = text[:800], # trunca para economizar tokens
                source = source,
                author = author,
                url = f"{self.REDDIT_BASE}{permalink}" if permalink else None,
                frequency_hint = round(frequency_hint, 2),
                emotional_intensity = self.scorer.emotional_intensity(text),
                commercial_intent = self.scorer.commercial_intent(text + f" query:{query}"),
                metadata = {
                    "query": query,
                    "upvotes": int(score),
                    "comments": int(num_comments),
                    "subreddit": d.get("subreddit"),
                },
            ))

        return records

    # RSS

    def collect_rss(
        self,
        url: str,
        source_tag: Optional[str] = None,
        max_items: int = 30,
    ) -> List[ComplaintRecord]:
        """
        Coleta itens de um feed RSS/Atom.

        Args:
            url: URL do feed
            source_tag: tag de fonte (ex: "reddit_rss", "ycombinator")
            max_items: máximo de itens
        """
        source = source_tag or self._guess_source(url)
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", self.USER_AGENT)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            root = ElementTree.fromstring(raw)
        except Exception as e:
            print(f" RSS error [{url[:50]}]: {e}")
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item") or root.findall(".//atom:entry", ns)
        records: List[ComplaintRecord] = []

        for item in items[:max_items]:
            title = self._safe_text(item.find("title"))
            summary = (
                self._safe_text(item.find("description")) or
                self._safe_text(item.find("summary")) or
                self._safe_text(item.find("atom:summary", ns))
            )
            link = self._safe_text(item.find("link"))
            author = self._safe_text(item.find("author"))

            summary = self._strip_html(summary)
            text = f"{title}. {summary}".strip()
            if len(text) < 40:
                continue

            records.append(ComplaintRecord(
                text = text[:800],
                source = source,
                author = author or None,
                url = link or None,
                frequency_hint = 1.0,
                emotional_intensity = self.scorer.emotional_intensity(text),
                commercial_intent = self.scorer.commercial_intent(text),
                metadata = {"feed_url": url},
            ))

        return self._deduplicate(records)

    # JSON local

    def collect_from_json(
        self,
        filepath: str,
        source_tag: Optional[str] = None,
    ) -> List[ComplaintRecord]:
        """
        Lê reclamações de um arquivo JSON local.
        Aceita lista de strings ou lista de dicts com campo "text".
        """
        path = Path(filepath)
        if not path.exists():
            print(f" Arquivo não encontrado: {filepath}")
            return []

        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("complaints", [])
        source = source_tag or path.stem

        records: List[ComplaintRecord] = []
        for item in items:
            if isinstance(item, str):
                text = item.strip()
                meta: Dict[str, Any] = {}
            else:
                text = str(item.get("text", "")).strip()
                meta = {k: v for k, v in item.items() if k != "text"}

            if len(text) < 20:
                continue

            records.append(ComplaintRecord(
                text = text[:800],
                source = item.get("source", source) if isinstance(item, dict) else source,
                author = item.get("author") if isinstance(item, dict) else None,
                url = item.get("url") if isinstance(item, dict) else None,
                frequency_hint = float(item.get("frequency_hint", 1.0)) if isinstance(item, dict) else 1.0,
                emotional_intensity = self.scorer.emotional_intensity(text),
                commercial_intent = self.scorer.commercial_intent(text),
                metadata = meta,
            ))

        return self._deduplicate(records)

    # Export

    def export_payload(
        self,
        records: List[ComplaintRecord],
        output_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Converte para lista de dicts compatível com PainRadarAdapter.
        Ordena por relevância (emotional * commercial * frequency).

        Args:
            records: lista de ComplaintRecord
            output_path: caminho para salvar JSON (opcional)
        """
        payload = [asdict(r) for r in records]
        # ordena por relevância descrescente
        payload.sort(
            key=lambda x: (
                x.get("emotional_intensity", 0) *
                x.get("commercial_intent", 0) *
                x.get("frequency_hint", 1)
            ),
            reverse=True,
        )

        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            print(f" {len(payload)} reclamações salvas em: {output_path}")

        return payload

    # Helpers

    def _deduplicate(self, records: List[ComplaintRecord]) -> List[ComplaintRecord]:
        seen: set[str] = set()
        unique: List[ComplaintRecord] = []
        for record in records:
            key = re.sub(r"\s+", " ", record.text.lower()).strip()[:120]
            if key in seen:
                continue
            seen.add(key)
            unique.append(record)
        return unique

    @staticmethod
    def _safe_text(node: Any) -> str:
        return (node.text or "").strip() if node is not None else ""

    @staticmethod
    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text or "").strip()

    @staticmethod
    def _guess_source(url: str) -> str:
        domain = re.sub(r"https?://", "", url).split("/")[0]
        return domain.replace("www.", "").split(".")[0]


# Exemplo de uso

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Complaint Collector")
    parser.add_argument("--queries", help="Queries separadas por vírgula")
    parser.add_argument("--subreddits", help="Subreddits separados por vírgula")
    parser.add_argument("--json", help="Arquivo JSON local de reclamações")
    parser.add_argument("--rss", help="URL de feed RSS")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default="outputs/complaints_reddit.json")
    args = parser.parse_args()

    collector = ComplaintCollector()

    if args.json:
        complaints = collector.collect_from_json(args.json)
    elif args.rss:
        complaints = collector.collect_rss(args.rss)
    else:
        queries = [q.strip() for q in (args.queries or
                   "restaurant owners losing money pricing,"
                   "small business cash flow problem,"
                   "restaurant margin problem").split(",")]
        subreddits = [s.strip() for s in (args.subreddits or
                      "restaurantowners,smallbusiness,entrepreneur").split(",")]

        print(f"\n Coletando {len(queries)} queries × {len(subreddits)} subreddits…")
        complaints = collector.collect_reddit_search(
            queries = queries,
            subreddits = subreddits,
            limit_per_query = args.limit,
        )

    payload = collector.export_payload(complaints, args.output)
    print(f"\n Total coletado: {len(payload)} reclamações")
    print(json.dumps(payload[:3], ensure_ascii=False, indent=2))
