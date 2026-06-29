# Chaine RAG avec multi-LLM fallback et prompt structure
from __future__ import annotations

import re
from typing import Any, Generator

import structlog

from app.core.settings import settings

log = structlog.get_logger()

# Erreurs qui déclenchent le passage au backend suivant.
# On est délibérément larges : quota, surcharge, modèle introuvable, réseau…
# La seule raison de NE PAS passer au suivant serait une erreur de
# format de requête (mais ça arriverait sur tous les backends de toute façon).
_RETRYABLE = (
    "quota", "429", "resource_exhausted", "rate limit",
    "overloaded", "too many requests", "capacity",
    "not_found", "404", "not found", "unavailable",
    "503", "502", "500", "connection", "timeout",
)


# Prompt templates

SYSTEM_PROMPT = """\
You are an expert assistant in forest science, environmental policy and \
international terminology. You answer questions about forest definitions \
using a structured knowledge graph derived from Lund (2018) "Definitions of \
Forest, Deforestation, Afforestation and Reforestation."

OUTPUT FORMAT — follow this exactly:

**1. <Organisation / Country> (<Year>)**
<Definition text.>
> Source: <source_title> | <organisation> | <year>

**2. ...**  (repeat for each distinct definition)

**Summary**
2-3 sentences comparing or synthesising the definitions above.

RULES:
- Base your answer ONLY on the provided context passages.
- One numbered item per distinct definition — do NOT merge definitions.
- Cite sources with the [N] notation matching the numbered passages.
- Preserve technical terms and numerical thresholds exactly as in the source.
- If context is insufficient, clearly state what is missing — do NOT invent.
- Non-English definitions may be quoted as-is with a language note.
"""


def _format_context(docs: list[dict]) -> str:
    """Formate les documents récupérés en bloc numéroté pour le prompt."""
    blocks = []
    for i, doc in enumerate(docs, 1):
        m = doc.get("metadata", {})
        lines = [f"[{i}]"]
        if m.get("label"):   lines.append(f"  Term: {m['label']}")
        if m.get("def"):     lines.append(f"  Definition: {m['def'][:600]}")

        meta = []
        if m.get("country"): meta.append(f"Country: {m['country']}")
        if m.get("year"):    meta.append(f"Year: {m['year']}")
        if m.get("scope"):   meta.append(f"Scope: {m['scope']}")
        if m.get("org"):     meta.append(f"Organization: {m['org']}")
        if meta: lines.append("  " + " | ".join(meta))

        if doc.get("graph_context"):
            lines.append(f"  [Graph context: {doc['graph_context'][:250]}]")

        lines.append(f"  [Sources: {', '.join(doc.get('sources', ['?']))} "
                     f"| RRF: {doc.get('rrf_score', 0):.4f}]")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


SYSTEM_PROMPT_LLM_ONLY = """\
You are an expert assistant in forest science, environmental policy and \
international terminology. Answer the question about forest definitions \
using your training knowledge of international standards and organizations \
(FAO, UNFCCC, IPCC, EU, World Bank, etc.).

OUTPUT FORMAT — follow this exactly:

**1. <Organisation / Country> (<Year>)**
<Definition text.>

**2. ...**  (repeat for each distinct definition you know)

**Summary**
2-3 sentences comparing or synthesising the definitions above.

RULES:
- Answer from your own knowledge — no retrieved context is provided.
- Preserve technical terms and numerical thresholds exactly as in the standards.
- If you are uncertain about a specific value or date, say so explicitly.
"""


def build_prompt_llm_only(query: str) -> tuple[str, str]:
    """Mode A — aucun contexte, le LLM répond depuis ses connaissances."""
    user_prompt = f"Question: {query}\n\nAnswer:"
    return SYSTEM_PROMPT_LLM_ONLY, user_prompt


def build_prompt(query: str, docs: list[dict]) -> tuple[str, str]:
    """Retourne (system_prompt, user_prompt)."""
    context = _format_context(docs)
    user_prompt = (
        f"Context passages ({len(docs)} documents retrieved):\n"
        f"{context}\n\n"
        f"Question: {query}\n\n"
        "Answer (with citations [N]):"
    )
    return SYSTEM_PROMPT, user_prompt


# Construction des LLM backends

def _make_backends() -> list[tuple[str, Any]]:
    """
    Construit la liste ordonnée (nom, llm) des backends disponibles.
    Un backend sans clé API est ignoré silencieusement.
    """
    from langchain_core.messages import SystemMessage, HumanMessage  # noqa: F401
    backends: list[tuple[str, Any]] = []

    # 1. Gemini primary
    if settings.gemini_api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            backends.append(("gemini", ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=settings.gemini_api_key,
                temperature=0.1,
            )))
        except Exception as e:
            log.warning("gemini_init_failed", error=str(e))

    # 2. Gemini backup (quota)
    if settings.gemini_api_key_2:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            backends.append(("gemini-2", ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=settings.gemini_api_key_2,
                temperature=0.1,
            )))
        except Exception as e:
            log.warning("gemini2_init_failed", error=str(e))

    # 3. DeepSeek (API OpenAI-compatible)
    if settings.deepseek_api_key:
        try:
            from langchain_openai import ChatOpenAI
            backends.append(("deepseek", ChatOpenAI(
                model=settings.deepseek_model,
                api_key=settings.deepseek_api_key,
                base_url="https://api.deepseek.com/v1",
                temperature=0.1,
                max_tokens=4096,
            )))
        except Exception as e:
            log.warning("deepseek_init_failed", error=str(e))

    # 4. Claude (Anthropic)
    if settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic
            backends.append(("claude", ChatAnthropic(
                model=settings.claude_model,
                anthropic_api_key=settings.anthropic_api_key,
                temperature=0.1,
                max_tokens=4096,
            )))
        except Exception as e:
            log.warning("claude_init_failed", error=str(e))

    # 5. OpenAI GPT
    if settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
            backends.append(("openai", ChatOpenAI(
                model=settings.openai_model,
                openai_api_key=settings.openai_api_key,
                temperature=0.1,
                max_tokens=4096,
            )))
        except Exception as e:
            log.warning("openai_init_failed", error=str(e))

    # 6. Groq (Llama)
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq
            backends.append(("groq", ChatGroq(
                model=settings.groq_model,
                groq_api_key=settings.groq_api_key,
                temperature=0.1,
                max_tokens=4096,
            )))
        except Exception as e:
            log.warning("groq_init_failed", error=str(e))

    return backends


def _is_retryable(error: Exception) -> bool:
    msg = str(error).lower()
    return any(kw in msg for kw in _RETRYABLE)


# Chaîne RAG principale

class RAGChain:
    """
    Chaîne RAG avec multi-LLM fallback.
    Premier backend disponible qui réussit est utilisé.
    Si quota/rate-limit → backend suivant automatiquement.
    """

    def __init__(self):
        self._backends = _make_backends()
        if not self._backends:
            log.warning("no_llm_backend", msg="Aucun provider LLM configuré dans .env")

    def generate_llm_only(self, query: str) -> dict[str, Any]:
        """Mode A — génération sans contexte RAG."""
        from langchain_core.messages import SystemMessage, HumanMessage
        system_prompt, user_prompt = build_prompt_llm_only(query)
        messages = [SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)]
        last_error: Exception | None = None
        for name, llm in self._backends:
            try:
                response = llm.invoke(messages)
                return {"answer": response.content, "model": name,
                        "usage": getattr(response, "usage_metadata", {})}
            except Exception as e:
                last_error = e
                if not _is_retryable(e):
                    raise
        raise RuntimeError(f"Tous les backends LLM ont échoué. Dernier: {last_error}")

    def generate(self, query: str, docs: list[dict]) -> dict[str, Any]:
        from langchain_core.messages import SystemMessage, HumanMessage

        system_prompt, user_prompt = build_prompt(query, docs)
        messages = [SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)]

        last_error: Exception | None = None
        for name, llm in self._backends:
            try:
                log.info("llm_attempt", backend=name)
                response = llm.invoke(messages)
                log.info("llm_success", backend=name)
                return {
                    "answer": response.content,
                    "model":  name,
                    "usage":  getattr(response, "usage_metadata", {}),
                }
            except Exception as e:
                log.warning("llm_error", backend=name, error=str(e)[:120])
                last_error = e
                if not _is_retryable(e):
                    raise

        raise RuntimeError(
            f"Tous les backends LLM ont échoué. Dernier: {last_error}"
        )

    def generate_stream(self, query: str, docs: list[dict]) -> Generator[str, None, None]:
        from langchain_core.messages import SystemMessage, HumanMessage

        system_prompt, user_prompt = build_prompt(query, docs)
        messages = [SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)]

        for name, llm in self._backends:
            try:
                for chunk in llm.stream(messages):
                    yield chunk.content
                return
            except Exception as e:
                if not _is_retryable(e):
                    raise
                log.warning("llm_stream_fallback", backend=name, error=str(e)[:80])

        raise RuntimeError("Tous les backends LLM ont échoué (stream).")

    @property
    def active_backends(self) -> list[str]:
        return [name for name, _ in self._backends]


# Évaluation basique

class RAGEvaluator:

    @staticmethod
    def context_utilization(answer: str, docs: list[dict]) -> float:
        cited = set(re.findall(r'\[(\d+)\]', answer))
        if not docs: return 0.0
        return round(len(cited) / len(docs), 3)

    @staticmethod
    def answer_coverage(answer: str, docs: list[dict]) -> float:
        all_keywords: set[str] = set()
        for doc in docs:
            # Exclure les docs synthétiques (Table3/critères) du calcul :
            # leur format tabulaire crée des faux négatifs de couverture.
            if "threshold" in doc.get("sources", []):
                continue
            deftext = doc.get("metadata", {}).get("def", "")
            words = re.findall(r'\b[a-zA-Z]{5,}\b', deftext.lower())
            all_keywords.update(words[:20])
        if not all_keywords: return 0.0
        answer_lower = answer.lower()
        found = sum(1 for kw in all_keywords if kw in answer_lower)
        return round(found / len(all_keywords), 3)

    def evaluate(self, query: str, answer: str, docs: list[dict]) -> dict:
        return {
            "context_utilization": self.context_utilization(answer, docs),
            "answer_coverage":     self.answer_coverage(answer, docs),
            "n_docs_retrieved":    len(docs),
            "sources_used":        list({d.get("metadata", {}).get("country", "")
                                         for d in docs
                                         if d.get("metadata", {}).get("country")}),
        }
