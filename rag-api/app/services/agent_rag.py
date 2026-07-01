# Agent RAG - le LLM choisit lui-meme quel outil utiliser
from __future__ import annotations

import json
from typing import Any

import structlog

from app.core.settings import settings
from app.services.graph_store import GraphStore, get_graph_store
from app.services.vector_store import VectorStore, get_vector_store
from app.services.rag_chain import RAGChain, SYSTEM_PROMPT, _format_context

log = structlog.get_logger()


AGENT_SYSTEM_PROMPT = """\
You are an intelligent research assistant with access to tools for searching \
forest definitions. You must decide which tool(s) to call based on the user's \
question, then synthesize the results into a final answer.

Available tools:
1. sparql_search - Search by structured criteria (concept type, country, \
organization, year). Best for precise queries like "FAO definition" or \
"definitions from Brazil".
2. vector_search - Semantic similarity search. Best for broad or conceptual \
questions like "what is deforestation" or "definitions mentioning carbon".

INSTRUCTIONS:
- Analyze the question and decide which tool(s) to use.
- You can call multiple tools if needed.
- Respond with a JSON array of tool calls, then I will give you the results.
- After receiving results, write your final answer with citations [N].

Respond ONLY with a JSON array like:
[{"tool": "sparql_search", "query": "forest FAO"}, \
{"tool": "vector_search", "query": "minimum area definition forest"}]
"""


class AgentRAG:
    """Agent qui decide quels outils utiliser pour repondre."""

    def __init__(
        self,
        graph_store: GraphStore | None = None,
        vector_store: VectorStore | None = None,
    ):
        self._gs = graph_store or get_graph_store()
        self._vs = vector_store or get_vector_store()
        self._chain = RAGChain()

    def _execute_tool(self, tool_name: str, query: str, top_k: int = 8) -> list[dict]:
        """Execute un outil et retourne les documents."""
        if tool_name == "sparql_search":
            results = self._gs.search_by_keyword(query, top_k=top_k)
            docs = []
            for i, r in enumerate(results):
                docs.append({
                    "text": f"Term: {r.get('label', '')} - {r.get('def', '')}",
                    "metadata": {
                        "uri": r.get("uri", ""),
                        "label": r.get("label", ""),
                        "def": r.get("def", ""),
                        "country": r.get("country", ""),
                        "year": r.get("year", ""),
                        "scope": r.get("scope", ""),
                        "org": r.get("org", ""),
                    },
                    "sources": ["sparql"],
                    "rrf_score": round(1.0 / (60 + i + 1), 6),
                })
            return docs

        elif tool_name == "vector_search":
            if not self._vs.is_indexed():
                return []
            return self._vs.search(query, top_k=top_k)

        return []

    def run(self, query: str, top_k: int = 8) -> dict[str, Any]:
        """Execute l'agent : planification -> outils -> reponse."""
        from langchain_core.messages import SystemMessage, HumanMessage

        # Etape 1 : demander au LLM quels outils utiliser
        plan_messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=f"Question: {query}"),
        ]

        plan_result = None
        for name, llm in self._chain._backends:
            try:
                plan_result = llm.invoke(plan_messages)
                model_used = name
                break
            except Exception:
                continue

        if not plan_result:
            raise RuntimeError("Aucun LLM disponible pour l'agent")

        # Etape 2 : parser les appels d'outils
        tool_calls = self._parse_tool_calls(plan_result.content)
        log.info("agent_plan", tools=tool_calls, query=query[:60])

        # Etape 3 : executer les outils
        all_docs = []
        tools_used = []
        for call in tool_calls:
            tool_name = call.get("tool", "")
            tool_query = call.get("query", query)
            docs = self._execute_tool(tool_name, tool_query, top_k=top_k)
            all_docs.extend(docs)
            tools_used.append(tool_name)
            log.info("agent_tool", tool=tool_name, results=len(docs))

        # Fallback si l'agent n'a rien trouve
        if not all_docs:
            all_docs = self._execute_tool("vector_search", query, top_k=top_k)
            tools_used.append("vector_search (fallback)")

        # Dedoublonner par URI
        seen = set()
        unique_docs = []
        for doc in all_docs:
            uri = doc.get("metadata", {}).get("uri", "")
            if uri and uri in seen:
                continue
            seen.add(uri)
            unique_docs.append(doc)

        # Enrichissement graphe
        for doc in unique_docs[:top_k]:
            uri = doc.get("metadata", {}).get("uri", "")
            if uri and not doc.get("graph_context"):
                ctx = self._gs.get_context(uri)
                if ctx:
                    doc["graph_context"] = ctx

        docs_final = unique_docs[:top_k]

        # Etape 4 : generer la reponse finale avec le contexte
        result = self._chain.generate(query, docs_final)

        return {
            "answer": result["answer"],
            "model": result.get("model", ""),
            "docs": docs_final,
            "tools_used": tools_used,
            "agent_plan": tool_calls,
        }

    @staticmethod
    def _parse_tool_calls(content: str) -> list[dict]:
        """Parse la reponse du LLM pour extraire les appels d'outils."""
        # Chercher un JSON array dans la reponse
        content = content.strip()

        # Essayer de parser directement
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

        # Chercher un JSON array dans le texte
        import re
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Fallback : utiliser les deux outils par defaut
        return [
            {"tool": "sparql_search", "query": ""},
            {"tool": "vector_search", "query": ""},
        ]
