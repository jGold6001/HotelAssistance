"""Composition root: builds the object graph from configuration.

Provider selection happens here and nowhere else, so domain and application
code never learns which backend is configured.
"""

import logging
from functools import lru_cache

from hotel_assistance.application.chat_orchestrator import ChatOrchestrator
from hotel_assistance.application.session_store import SessionStore
from hotel_assistance.config.settings import RetrievalMode, Settings, get_settings
from hotel_assistance.domain.services.candidate_retriever import (
    CandidateRetriever,
    KeywordCandidateRetriever,
)
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.search_validator import SearchValidator
from hotel_assistance.infrastructure.embeddings.openai_embeddings import (
    OpenAIEmbeddingProvider,
)
from hotel_assistance.infrastructure.hotel_search.client import (
    HotelSearchClient,
    HttpHotelSearchClient,
    UnavailableHotelSearchClient,
)
from hotel_assistance.infrastructure.hotel_search.simulator import (
    SimulatedHotelSearchClient,
)
from hotel_assistance.infrastructure.llm.openai_provider import OpenAIProvider
from hotel_assistance.infrastructure.llm.provider import LLMProvider
from hotel_assistance.infrastructure.retrieval.hybrid_retriever import (
    HybridCandidateRetriever,
)
from hotel_assistance.infrastructure.retrieval.semantic_retriever import (
    SemanticCandidateRetriever,
)
from hotel_assistance.infrastructure.transcript.recorder import ChatTranscriptRecorder

logger = logging.getLogger(__name__)


@lru_cache
def get_registry() -> FilterRegistry:
    registry = FilterRegistry.default()
    logger.info("filter registry loaded: %d filters", len(registry))
    return registry


@lru_cache
def get_session_store() -> SessionStore:
    return SessionStore()


def build_retriever(settings: Settings, registry: FilterRegistry) -> CandidateRetriever:
    if settings.retrieval_mode is RetrievalMode.KEYWORD:
        return KeywordCandidateRetriever(registry)

    semantic = SemanticCandidateRetriever(
        registry=registry,
        embedding_provider=OpenAIEmbeddingProvider(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
        ),
        cache_path=settings.embedding_cache_path,
        embedding_model_name=settings.openai_embedding_model,
    )
    if settings.retrieval_mode is RetrievalMode.SEMANTIC:
        return semantic
    return HybridCandidateRetriever(
        semantic=semantic,
        keyword=KeywordCandidateRetriever(registry, phrase_only=True),
    )


def build_llm_provider(settings: Settings) -> LLMProvider:
    return OpenAIProvider(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        fallback_model=settings.openai_fallback_model,
        fallback_max_words=settings.openai_fallback_max_words,
        temperature=settings.openai_temperature,
    )


def build_hotel_search_client(settings: Settings) -> HotelSearchClient:
    if settings.hotel_backend_url:
        return HttpHotelSearchClient(settings.hotel_backend_url, timeout=settings.hotel_backend_timeout)
    if settings.hotel_simulator_enabled:
        logger.info("no hotel backend configured: simulating one from the mock property database")
        return SimulatedHotelSearchClient()
    logger.info("no hotel backend configured: offer counts will be reported as unknown")
    return UnavailableHotelSearchClient()


@lru_cache
def get_transcript_recorder() -> ChatTranscriptRecorder:
    settings = get_settings()
    if settings.transcript_enabled:
        logger.info("chat turns are recorded under %s/", settings.transcript_dir)
    return ChatTranscriptRecorder(
        directory=settings.transcript_dir,
        enabled=settings.transcript_enabled,
    )


@lru_cache
def get_orchestrator() -> ChatOrchestrator:
    settings = get_settings()
    registry = get_registry()
    return ChatOrchestrator(
        registry=registry,
        retriever=build_retriever(settings, registry),
        llm_provider=build_llm_provider(settings),
        validator=SearchValidator(registry),
        hotel_search_client=build_hotel_search_client(settings),
        sessions=get_session_store(),
        top_k=settings.filter_top_k,
    )
