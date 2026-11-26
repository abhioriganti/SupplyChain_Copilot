"""Per-session answer cache for repeated questions (no Streamlit dependency; unit-testable).

Rules (kept deliberately conservative so a cached answer is never wrong for its context):
  * Only successful agent answers are cached.
  * A cached answer is reused only for a *standalone* question: one of the app's suggested questions
    (written to be self-contained) or any question asked with no prior conversation. A typed follow-up
    such as "break that down by mode" depends on history and is always sent to the agent.
  * Reuse is always labelled in the UI ("reused from earlier in this session") with an "Ask again live"
    option; the cache lives in the user's session only and is cleared with the conversation.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from supplychain_copilot.agent.client import AgentAnswer


def normalize(question: str) -> str:
    q = re.sub(r"\s+", " ", (question or "").strip().lower())
    return q.rstrip("?.! ")


@dataclass
class AnswerCache:
    standalone_questions: set[str] = field(default_factory=set)
    _store: dict[str, AgentAnswer] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.standalone_questions = {normalize(q) for q in self.standalone_questions}

    def is_cacheable(self, question: str, has_history: bool) -> bool:
        return normalize(question) in self.standalone_questions or not has_history

    def get(self, question: str, has_history: bool) -> AgentAnswer | None:
        if not self.is_cacheable(question, has_history):
            return None
        hit = self._store.get(normalize(question))
        return copy.deepcopy(hit) if hit is not None else None

    def put(self, question: str, answer: AgentAnswer, has_history: bool) -> bool:
        if not answer.ok or not self.is_cacheable(question, has_history):
            return False
        self._store[normalize(question)] = copy.deepcopy(answer)
        return True

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
