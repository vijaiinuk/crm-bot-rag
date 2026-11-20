"""The real query path (S3.1.3b), replacing the mock responder. Design: docs/backlog.md.

pin       read the live index version once; meta, trace and search all use it
retrieve  hybrid search, filtered in SQL (rule 2), then rerank to the top excerpts
decide    best rerank score below threshold: no LLM call; a restricted-module
          template if a module the user lacks matches the question (catalogue
          profiles only, never chunks), else "not found"
generate  stream from the allowed excerpts only (rule 3), citation markers stripped
          and verified; a templated note when the question also involves modules
          the user lacks (partial access); never an LLM-written refusal (rule 7)
"""

from collections.abc import AsyncGenerator, Sequence

from psycopg_pool import AsyncConnectionPool

from chatbot.config import Settings
from chatbot.events import Citation, Citations, ContentEvent, Refusal, Token, TokenUsage, Usage
from chatbot.generation.markers import MarkerStream
from chatbot.generation.module_match import ModuleMatcher, embedding_similarity
from chatbot.generation.prompt import AnswerPrompt
from chatbot.ports.catalogue import ModuleCatalogue
from chatbot.ports.entitlements import Principal
from chatbot.ports.llm import Completion, StreamingLLMClient
from chatbot.ports.reranker import Reranker
from chatbot.ports.responder import Query, Versions
from chatbot.ports.retriever import Candidate, Retriever
from chatbot.refusals import not_found_message, partial_access_note, restricted_message

ANSWER_ROLE = "answer"


class RagResponder:
    def __init__(
        self,
        *,
        retriever: Retriever,
        reranker: Reranker,
        matcher: ModuleMatcher,
        llm: StreamingLLMClient,
        model_id: str,
        prompt: AnswerPrompt,
        catalogue: ModuleCatalogue,
        threshold: float,
        pool_k: int = 20,
        context_k: int = 5,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._matcher = matcher
        self._llm = llm
        self._model_id = model_id
        self._prompt = prompt
        self._catalogue = catalogue
        self._threshold = threshold
        self._pool_k = pool_k
        self._context_k = context_k
        self.last_invalid_citations = 0  # for tests and, later, the trace (S3.1.4)

    async def pin(self) -> Versions:
        live = await self._retriever.live_version()
        return Versions(str(live), self._prompt.version, self._model_id)

    async def respond(
        self,
        query: Query,
        principal: Principal,
        allowed_modules: frozenset[str],
        versions: Versions,
    ) -> AsyncGenerator[ContentEvent, None]:
        question = query.message
        candidates = await self._retriever.search(
            question, allowed_modules, self._pool_k, index_version=int(versions.index_version)
        )
        excerpts = await self._reranker.rerank(question, candidates, self._context_k)
        missing = await self._matcher.missing_modules(question, allowed_modules)
        best = excerpts[0].rerank_score if excerpts else None

        if best is None or best < self._threshold:
            yield self._refusal(missing)
            return

        messages = self._prompt.build(question, excerpts, allowed_modules)
        markers = MarkerStream()
        completion: Completion | None = None
        async for item in self._llm.stream(messages, role=ANSWER_ROLE):
            if isinstance(item, Completion):
                completion = item
            elif text := markers.feed(item):
                yield Token(text=text)
        tail = markers.finish()
        usage = (
            TokenUsage(
                input_tokens=completion.usage.input_tokens,
                output_tokens=completion.usage.output_tokens,
            )
            if completion
            else TokenUsage()
        )
        if markers.not_found:  # nothing was streamed: the sentinel is held back
            yield self._refusal(missing)
            yield Usage(usage=usage)
            return
        if tail:
            yield Token(text=tail)
        if missing:
            yield Token(text="\n\n" + partial_access_note(missing, self._catalogue))
        yield Citations(items=self._verified(markers.cited, excerpts))
        yield Usage(usage=usage)

    def _refusal(self, missing: Sequence[str]) -> Refusal:
        if missing:
            return Refusal(
                kind="restricted",
                message=restricted_message(missing, self._catalogue),
                missing_modules=sorted(missing),
            )
        return Refusal(kind="not_found", message=not_found_message())

    def _verified(self, cited: Sequence[int], excerpts: Sequence[Candidate]) -> list[Citation]:
        """Only numbers that were in the context; anything else is dropped and counted."""
        valid = [n for n in cited if 1 <= n <= len(excerpts)]
        self.last_invalid_citations = len(cited) - len(valid)
        return [
            Citation(
                chunk_id=excerpts[n - 1].chunk_id,
                doc_id=excerpts[n - 1].doc_id,
                anchor=excerpts[n - 1].anchor,
                title=excerpts[n - 1].breadcrumb.split(" > ")[0],
                breadcrumb=excerpts[n - 1].breadcrumb,
            )
            for n in valid
        ]


def build_rag_responder(
    settings: Settings, catalogue: ModuleCatalogue
) -> tuple[RagResponder, AsyncConnectionPool]:
    """Wire the real adapters. The caller opens and closes the returned pool."""
    from chatbot.adapters.litellm_client import LiteLLMClient
    from chatbot.adapters.st_embedder import SentenceTransformerEmbedder
    from chatbot.db import libpq_url
    from chatbot.generation.prompt import load_prompt
    from chatbot.models_config import load_models_config
    from chatbot.retrieval.hybrid import PgHybridRetriever, make_pool
    from chatbot.retrieval.rerank import CrossEncoderReranker

    config = load_models_config(settings.models_path)
    if config.embeddings is None or config.reranker is None or ANSWER_ROLE not in config.models:
        raise RuntimeError(
            f"{settings.models_path} needs embeddings, reranker and an `answer` role"
        )
    pool = make_pool(libpq_url(settings.database_url.get_secret_value()))
    embedder = SentenceTransformerEmbedder(config.embeddings)
    responder = RagResponder(
        retriever=PgHybridRetriever(pool, embedder),
        reranker=CrossEncoderReranker(config.reranker),
        matcher=ModuleMatcher(
            catalogue, embedding_similarity(embedder), config.embeddings.module_floor
        ),
        llm=LiteLLMClient(config, openrouter_api_key=settings.openrouter_api_key),
        model_id=config.models[ANSWER_ROLE].model_id,
        prompt=load_prompt(settings.answer_prompt_path),
        catalogue=catalogue,
        threshold=config.reranker.threshold,
    )
    return responder, pool
