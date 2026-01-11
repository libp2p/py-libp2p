"""
Optional AI/LLM assistant for the chat demo.

The assistant is intentionally lightweight: it attempts to use `transformers`
pipelines when available but gracefully falls back to heuristic summaries or
echo-style replies so the demo still works without extra dependencies.
"""

from __future__ import annotations

from collections import (
    deque,
)
import logging
import re
import textwrap
from typing import (
    Deque,
    Optional,
)

import trio

try:  # pragma: no cover - optional dependency
    from transformers import (
        pipeline,
    )
except Exception:  # pragma: no cover - keep demo runnable without transformers
    pipeline = None

logger = logging.getLogger("examples.chat.assistant")

DEFAULT_SUMMARY_MODEL = "sshleifer/distilbart-cnn-12-6"
DEFAULT_REPLY_MODEL = "microsoft/DialoGPT-small"


class ChatAssistant:
    """
    Helper that produces periodic summaries or AI-generated replies.

    Users can opt into this behaviour via CLI flags in the chat demo.
    """

    def __init__(
        self,
        *,
        mode: str,
        frequency: int = 5,
        model_name: str | None = None,
    ) -> None:
        self.mode = mode
        self.frequency = max(2, frequency)
        self.model_name = model_name
        self._history: Deque[str] = deque(maxlen=64)
        self._pipeline = self._load_pipeline()

    def _load_pipeline(self) -> Optional[object]:
        if pipeline is None:
            logger.info(
                "transformers is not installed; falling back to heuristic AI assistant"
            )
            return None
        task = "summarization" if self.mode == "summary" else "text-generation"
        model_name = self.model_name or (
            DEFAULT_SUMMARY_MODEL if task == "summarization" else DEFAULT_REPLY_MODEL
        )
        try:
            return pipeline(task, model=model_name)
        except Exception as exc:  # pragma: no cover - model download failures
            logger.warning(
                "Failed to initialize %s pipeline with model %s: %s; "
                "falling back to heuristics",
                task,
                model_name,
                exc,
            )
            return None

    async def handle_incoming(self, text: str, stream=None) -> None:
        """Process a message received from the remote peer."""
        self._history.append(text.strip())
        if self.mode == "summary":
            await self._maybe_print_summary()
        elif self.mode == "reply" and stream is not None:
            await self._maybe_send_reply(text, stream)

    async def handle_outgoing(self, text: str) -> None:
        """Track messages we send so summaries include our side too."""
        self._history.append(f"(me) {text.strip()}")

    async def _maybe_print_summary(self) -> None:
        if len(self._history) < self.frequency:
            return
        conversation = "\n".join(self._history)
        self._history.clear()
        summary = await self._run_summary(conversation)
        if summary:
            banner = "\x1b[35m[AI summary]\x1b[0m "  # purple text
            wrapped = textwrap.fill(summary, width=72)
            print(f"{banner}{wrapped}\n")

    async def _maybe_send_reply(self, text: str, stream) -> None:
        if len(self._history) % self.frequency != 0:
            return
        reply = await self._run_reply(text)
        if not reply:
            return
        payload = reply.strip() + "\n"
        try:
            await stream.write(payload.encode())
            banner = "\x1b[35m[AI reply]\x1b[0m"
            print(f"{banner} {reply}")
        except Exception as exc:
            logger.debug("Failed to send AI reply: %s", exc)

    async def _run_summary(self, text: str) -> str | None:
        if not text.strip():
            return None
        if self._pipeline is None or self.mode != "summary":
            return self._heuristic_summary(text)
        return await trio.to_thread.run_sync(self._call_summary_model, text)

    async def _run_reply(self, text: str) -> str | None:
        if self._pipeline is None or self.mode != "reply":
            return self._heuristic_reply(text)
        return await trio.to_thread.run_sync(self._call_reply_model, text)

    def _call_summary_model(self, text: str) -> str | None:
        try:
            result = self._pipeline(
                text,
                max_length=60,
                min_length=12,
                do_sample=False,
            )
            if isinstance(result, list) and result:
                return result[0].get("summary_text")
            if isinstance(result, dict):
                return result.get("summary_text")
        except Exception as exc:  # pragma: no cover
            logger.debug("Summary model failed: %s", exc)
        return self._heuristic_summary(text)

    def _call_reply_model(self, text: str) -> str | None:
        try:
            result = self._pipeline(
                text,
                max_length=50,
                num_return_sequences=1,
            )
            if isinstance(result, list) and result:
                return result[0].get("generated_text")
            if isinstance(result, dict):
                return result.get("generated_text")
        except Exception as exc:  # pragma: no cover
            logger.debug("Reply model failed: %s", exc)
        return self._heuristic_reply(text)

    @staticmethod
    def _heuristic_summary(text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if not sentences:
            return ""
        if len(sentences) == 1:
            return sentences[0]
        return " ".join(sentences[:2])

    @staticmethod
    def _heuristic_reply(text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        if len(cleaned) > 200:
            cleaned = cleaned[:200] + "..."
        return f"Thanks for sharing! You mentioned: \"{cleaned}\""


def build_assistant(args) -> ChatAssistant | None:
    """Helper used by the CLI to conditionally create an assistant."""
    if not getattr(args, "ai_assistant", False):
        return None
    return ChatAssistant(
        mode=args.ai_mode,
        frequency=args.ai_frequency,
        model_name=args.ai_model,
    )


