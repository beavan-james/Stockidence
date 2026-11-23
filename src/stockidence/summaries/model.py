"""The local model: Qwen3.5-4B served by Ollama (the `ollama` service in
docker-compose.yml, at OLLAMA_URL).

One chat call at a time, thinking off, with the model card's sampling
settings. Prompt tokens are counted before each call with Qwen's own
tokenizer file, since Ollama has no endpoint for counting: a prompt that
doesn't fit the context raises PromptTooLong instead of being cut off by the
server.

Two kinds of failure, handled differently by the callers:
  - the server can't be reached, answers with an error or times out:
    ModelUnavailable. The run stops, so nothing is stored as a fallback
    because the server was down.
  - the server answers but the output is unusable (cut off at the token
    limit, or it fails a check): the caller retries once at temperature 0,
    then falls back.
"""

from __future__ import annotations

import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import repo_root

log = logging.getLogger(__name__)

MODEL = "qwen3.5:4b-q4_K_M"
DEFAULT_URL = "http://localhost:11434"
# Matches OLLAMA_CONTEXT_LENGTH in docker-compose.yml; sent with every call,
# so the budget below and the server always agree.
CONTEXT = 16384
MARGIN = 0.10          # of the context, kept free for the chat template and miscounts
MESSAGE_OVERHEAD = 8   # tokens the chat template adds per message
# The model card's settings for use without thinking.
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5}
# A weekly section takes ~5 minutes on the server; a call this long means
# something is wrong.
TIMEOUT_SECONDS = 20 * 60

TOKENIZER_FILE = "qwen3.5-4b-tokenizer.json"  # baked into the image (Dockerfile)


class ModelUnavailable(RuntimeError):
    """The server couldn't be reached or answered with an error."""


class PromptTooLong(ValueError):
    def __init__(self, tokens: int, budget: int) -> None:
        super().__init__(f"prompt is {tokens} tokens, over the {budget}-token budget")
        self.tokens = tokens
        self.budget = budget


# --- token counting ---------------------------------------------------------

@dataclass(frozen=True)
class TokenCounter:
    name: str
    count: Callable[[str], int]

    def __call__(self, text: str) -> int:
        return self.count(text)


def estimate_tokens(text: str) -> int:
    """English news runs ~4 characters a Qwen token; dividing by 3 overcounts
    on purpose, so an estimated prompt never looks smaller than it is."""
    return math.ceil(len(text) / 3)


ESTIMATE = TokenCounter("estimate (3 characters a token)", estimate_tokens)


def tokenizer_path() -> Path:
    env = os.environ.get("QWEN_TOKENIZER")
    return Path(env) if env else repo_root() / "tokenizers" / TOKENIZER_FILE


def qwen_counter(path: Path | None = None) -> TokenCounter:
    """Qwen's tokenizer when its file is there, else the overcounting estimate."""
    path = path or tokenizer_path()
    if not path.is_file():
        log.warning("Qwen tokenizer not found at %s; estimating token counts instead", path)
        return ESTIMATE
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(path))
    return TokenCounter(f"tokenizer {path.name}",
                        lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids))


# --- chat ---------------------------------------------------------------------

@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int   # as the server counted them
    output_tokens: int
    seconds: float
    cut_off: bool       # stopped at the output limit, so the text is incomplete


class Ollama:
    def __init__(
        self,
        url: str = DEFAULT_URL,
        model: str = MODEL,
        *,
        count_tokens: TokenCounter = ESTIMATE,
        context: int = CONTEXT,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.count_tokens = count_tokens
        self.context = context
        self.client = client or httpx.Client(timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=10))
        self.clock = clock

    @classmethod
    def from_env(cls) -> Ollama:
        return cls(os.environ.get("OLLAMA_URL", DEFAULT_URL),
                   os.environ.get("OLLAMA_MODEL", MODEL),
                   count_tokens=qwen_counter())

    def input_budget(self, max_output: int) -> int:
        """Tokens left for the prompt: the context, less the margin and the
        room the reply may take."""
        return int(self.context * (1 - MARGIN)) - max_output

    def prompt_tokens(self, system: str, user: str) -> int:
        return self.count_tokens(system) + self.count_tokens(user) + 2 * MESSAGE_OVERHEAD

    def fits(self, system: str, user: str, max_output: int) -> bool:
        return self.prompt_tokens(system, user) <= self.input_budget(max_output)

    def chat(
        self,
        system: str,
        user: str,
        *,
        max_output: int,
        temperature: float | None = None,
        schema: dict[str, Any] | None = None,
    ) -> Reply:
        """One call. `schema` makes the server hold the reply to that JSON
        schema while it writes, so it always parses."""
        tokens = self.prompt_tokens(system, user)
        budget = self.input_budget(max_output)
        if tokens > budget:
            raise PromptTooLong(tokens, budget)
        options = {**SAMPLING, "num_ctx": self.context, "num_predict": max_output}
        if temperature is not None:
            options["temperature"] = temperature
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "think": False,
            "options": options,
        }
        if schema is not None:
            body["format"] = schema
        start = self.clock()
        try:
            response = self.client.post(f"{self.url}/api/chat", json=body)
        except httpx.HTTPError as e:  # connection refused, timeout, ...
            raise ModelUnavailable(f"{self.url}: {type(e).__name__}: {e}") from e
        if response.status_code != 200:
            raise ModelUnavailable(f"{self.url}: HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        return Reply(
            text=(data.get("message") or {}).get("content", ""),
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
            seconds=round(self.clock() - start, 1),
            cut_off=data.get("done_reason") == "length",
        )
