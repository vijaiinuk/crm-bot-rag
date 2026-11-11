"""One structured trace line per chat request (CLAUDE.md rule 8).

Interim: a JSON log line. OpenTelemetry -> Phoenix (S3.1.4) replaces `emit_trace`;
TraceRecord stays the shape. The question text is deliberately not recorded
until PII redaction exists.
"""

import json
import logging
from dataclasses import asdict, dataclass

_trace_log = logging.getLogger("chatbot.trace")


@dataclass(slots=True)
class TraceRecord:
    trace_id: str
    conversation_id: str
    sub: str
    tenant: str
    role: str
    allowed_modules: list[str]
    index_version: str
    prompt_version: str
    model_id: str
    message_chars: int
    input_tokens: int = 0
    output_tokens: int = 0
    outcome: str = "cancelled"  # answer | refusal:<kind> | error | cancelled
    latency_ms: float = 0.0


def emit_trace(record: TraceRecord) -> None:
    _trace_log.info(json.dumps(asdict(record), sort_keys=True))


def configure_logging() -> None:
    """Make `chatbot.*` INFO logs visible under uvicorn, which leaves the root logger bare."""
    logger = logging.getLogger("chatbot")
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
