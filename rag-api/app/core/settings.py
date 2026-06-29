# Configuration de l'application
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM providers (tous optionnels — chaîne de fallback)
    anthropic_api_key:  str = ""
    claude_model:       str = "claude-sonnet-4-6"

    openai_api_key:     str = ""
    openai_model:       str = "gpt-4o-mini"

    gemini_api_key:     str = ""
    gemini_api_key_2:   str = ""          # backup quota Gemini
    gemini_model:       str = "gemini-2.5-flash"

    deepseek_api_key:   str = ""
    deepseek_model:     str = "deepseek-chat"

    groq_api_key:       str = ""
    groq_model:         str = "llama-3.3-70b-versatile"

    # Compatibilité avec l'ancien champ llm_provider/llm_model
    @property
    def llm_provider(self) -> str:
        if self.gemini_api_key:      return "gemini"
        if self.deepseek_api_key:    return "deepseek"
        if self.anthropic_api_key:   return "anthropic"
        if self.openai_api_key:      return "openai"
        if self.groq_api_key:        return "groq"
        return "none"

    @property
    def llm_model(self) -> str:
        if self.gemini_api_key:      return self.gemini_model
        if self.deepseek_api_key:    return self.deepseek_model
        if self.anthropic_api_key:   return self.claude_model
        if self.openai_api_key:      return self.openai_model
        if self.groq_api_key:        return self.groq_model
        return "none"

    # Graphe RDF
    ttl_path:    Path = Path("../data/forest_kg.ttl")
    table3_path: Path = Path("../data/table3.csv")
    criteria_path: Path = Path("../data/criteria.csv")

    # Vector Store
    chroma_path:       str  = "./chroma_db"
    chroma_collection: str  = "forest_definitions"
    embed_model:       str  = "all-MiniLM-L6-v2"

    # Retrieval
    retrieval_top_k: int   = 12
    retrieval_alpha: float = 0.6

    # API
    api_host:  str = "0.0.0.0"
    api_port:  int = 8000
    log_level: str = "info"

    # SPARQL namespaces
    base_uri:    str = "http://example.org/forest-def/"
    agrovoc_uri: str = "http://aims.fao.org/aos/agrovoc/"

    @property
    def sparql_prefixes(self) -> str:
        return f"""
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dct:  <http://purl.org/dc/terms/>
PREFIX ex:   <{self.base_uri}>
PREFIX agv:  <{self.agrovoc_uri}>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
"""

    def active_providers(self) -> list[str]:
        """Retourne la liste des providers LLM disponibles."""
        out = []
        if self.gemini_api_key:    out.append("gemini")
        if self.gemini_api_key_2:  out.append("gemini-2")
        if self.deepseek_api_key:  out.append("deepseek")
        if self.anthropic_api_key: out.append("anthropic")
        if self.openai_api_key:    out.append("openai")
        if self.groq_api_key:      out.append("groq")
        return out


settings = Settings()
