"""
Mock search API standing in for a real web search provider.

Generates (deterministically, seeded) a corpus of ~10,000 pre-crawled
(url, title, snippet) documents spanning a wide vocabulary of topical
domains, and exposes a `search(query, k)` function that scores documents
against a query with simple TF-style word-overlap relevance. This is
sufficient to exercise the full pipeline (ranking, deduplication, citation
resolution) without needing network access or a real search API key.

The corpus is generated once and cached to disk at `settings.dataset_path`.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
from dataclasses import dataclass, asdict
from functools import lru_cache

from ..config import settings

_DOMAINS = [
    "example.org", "researchhub.io", "datainsight.net", "wikinet.org", "scholarly.press",
    "techjournal.com", "opendata.gov", "quarterlyreview.com", "encyclonet.org", "labnotes.dev",
    "policybrief.org", "marketwatchdog.com", "sciencedaily.example", "archive-press.org",
    "globalstudies.edu", "innovationtimes.com", "peerreviewed.journal", "newsdesk.example",
]

_TOPIC_SEEDS = [
    "climate change", "artificial intelligence", "renewable energy", "quantum computing",
    "public health", "supply chain", "cybersecurity", "space exploration", "genomics",
    "urban planning", "monetary policy", "biodiversity", "labor markets", "semiconductor",
    "education technology", "autonomous vehicles", "ocean conservation", "vaccine development",
    "electric vehicles", "financial regulation", "machine learning", "5G networks",
    "food security", "water scarcity", "nuclear energy", "housing policy", "immigration",
    "cryptocurrency", "gene therapy", "wildfire management", "remote work", "data privacy",
    "robotics", "biotechnology", "trade policy", "mental health", "carbon capture",
    "agriculture technology", "smart cities", "disinformation", "digital currency",
]

_STANCE_TEMPLATES = [
    "A comprehensive overview of {topic}, covering recent developments and open questions.",
    "Researchers report significant progress in {topic}, though critics urge caution.",
    "New data suggests {topic} is advancing faster than earlier projections indicated.",
    "A skeptical analysis questioning mainstream assumptions about {topic}.",
    "Industry leaders discuss the economic implications of {topic} for the coming decade.",
    "A policy brief outlining regulatory approaches to {topic} across major economies.",
    "Historical context and background on how {topic} evolved over the last 20 years.",
    "Field experts debate the risks and benefits associated with {topic}.",
    "A technical deep-dive into the methods and tools used in {topic}.",
    "Case studies illustrating real-world applications of {topic}.",
    "An investigative report uncovering funding sources behind {topic} initiatives.",
    "A comparative study of {topic} approaches across different countries.",
]

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


@dataclass
class Document:
    url: str
    title: str
    snippet: str
    domain: str
    topic_seed: str

    def to_dict(self) -> dict:
        return asdict(self)


def _generate_corpus(n: int, seed: int = 42) -> list[Document]:
    rng = random.Random(seed)
    docs: list[Document] = []
    for i in range(n):
        topic = rng.choice(_TOPIC_SEEDS)
        # occasionally blend two topics so multi-word queries have material to match
        if rng.random() < 0.35:
            topic2 = rng.choice(_TOPIC_SEEDS)
            topic_text = f"{topic} and {topic2}"
        else:
            topic_text = topic
        template = rng.choice(_STANCE_TEMPLATES)
        domain = rng.choice(_DOMAINS)
        title = template.format(topic=topic_text).rstrip(".")
        snippet = (
            f"{template.format(topic=topic_text)} "
            f"This piece examines {topic_text} through multiple lenses, drawing on "
            f"{rng.choice(['peer-reviewed studies', 'industry reports', 'government data', 'expert interviews'])} "
            f"to assess {rng.choice(['impact', 'feasibility', 'adoption trends', 'long-term outlook'])}."
        )
        slug = re.sub(r"[^a-z0-9]+", "-", topic_text.lower()).strip("-")
        url = f"https://{domain}/articles/{slug}-{i:05d}"
        docs.append(Document(url=url, title=title, snippet=snippet, domain=domain, topic_seed=topic))
    return docs


def ensure_dataset() -> list[Document]:
    path = settings.dataset_path
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [Document(**d) for d in raw]

    docs = _generate_corpus(settings.dataset_size)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([d.to_dict() for d in docs], f)
    return docs


@lru_cache(maxsize=1)
def _corpus_with_index() -> tuple[list[Document], dict[str, set[int]]]:
    docs = ensure_dataset()
    index: dict[str, set[int]] = {}
    for idx, doc in enumerate(docs):
        for tok in set(_tokenize(doc.title + " " + doc.snippet)):
            index.setdefault(tok, set()).add(idx)
    return docs, index


def _score(query_tokens: list[str], doc: Document) -> float:
    doc_tokens = _tokenize(doc.title + " " + doc.snippet)
    if not doc_tokens:
        return 0.0
    doc_set = set(doc_tokens)
    overlap = sum(1 for t in query_tokens if t in doc_set)
    if overlap == 0:
        return 0.0
    # simple normalized overlap score, log-dampened by doc length
    raw = overlap / max(len(set(query_tokens)), 1)
    length_penalty = 1.0 / (1.0 + math.log(1 + len(doc_tokens) / 20))
    return round(min(1.0, raw * 0.7 + length_penalty * 0.3), 4)


def search(query: str, k: int = 8) -> list[dict]:
    """Return up to k documents ranked by relevance to `query`."""
    docs, index = _corpus_with_index()
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    candidate_ids: set[int] = set()
    for tok in query_tokens:
        candidate_ids |= index.get(tok, set())

    # Fall back to a random sample if nothing matched (keeps pipeline resilient
    # to obscure topics, mirroring a real search engine's "related results").
    if not candidate_ids:
        rng = random.Random(hash(query) & 0xFFFFFFFF)
        candidate_ids = set(rng.sample(range(len(docs)), min(50, len(docs))))

    scored = [(_score(query_tokens, docs[i]), i) for i in candidate_ids]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, idx in scored[:k]:
        doc = docs[idx]
        results.append({
            "url": doc.url,
            "title": doc.title,
            "snippet": doc.snippet,
            "relevance_score": score,
        })
    return results
