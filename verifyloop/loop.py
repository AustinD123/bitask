"""The fix loop: ask the model for a fix, verify it, and feed back the failure.

fix() runs one case against one model. Attempt 1 gets the buggy file and the
visible test. Each retry gets the task, the previous attempt and the cleaned
failure output, not the whole history. The hidden test is run afterwards and
is never put in a prompt. Every attempt is logged to out/runs/.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from verifyloop.case import Case
from verifyloop.llm import DailyLimitReached, LLMError, complete
from verifyloop.toolchain import verify

RUNS_DIR = Path("out/runs")
SYSTEM_PROMPT = (
    "You fix C/C++ bugs. Return the complete corrected file in a single fenced "
    "code block. Do not change function signatures."
)
RETURN_INSTRUCTION = "Return the complete corrected file in a single fenced code block."
_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)
_PRAGMA = re.compile(r"#\s*pragma\s+(diagnostic|clang|GCC)\b")
_BANNED = ("no_sanitize", "__asan", "VERIFY_NONCE")


@dataclass
class Attempt:
    """One round trip: the prompt, the reply, the code extracted from it, and the visible verdict."""

    number: int
    prompt: list[dict]
    response: str
    code: str | None
    stage: str  # a VerifyResult stage, or no_code, rejected or llm_error
    output: str  # the cleaned failure output, or the reason for no_code or rejected
    usage: dict
    result: dict | None = None


@dataclass
class FixRun:
    """All attempts for one case, one model and one trial, plus the hidden-test verdicts."""

    case_id: str
    model: str
    trial: int
    attempts: list[Attempt] = field(default_factory=list)
    hidden_first: dict | None = None  # hidden test on attempt 1's candidate
    hidden_final: dict | None = None  # hidden test on the final candidate

    @property
    def passed(self) -> bool:
        """True if the final candidate passes the visible test."""
        return self.attempts[-1].stage == "ok"

    def to_dict(self) -> dict:
        """Return the run as plain data for the log and the bench."""
        return asdict(self)


def extract_code(text: str) -> str | None:
    """Return the body of the last fenced code block in ``text``, or None if there is none."""
    blocks = _FENCE.findall(text)
    return blocks[-1] if blocks else None


def guardrail(code: str) -> str | None:
    """Return the reason to reject a candidate before it is compiled, or None if it is allowed."""
    for needle in _BANNED:
        if needle in code:
            return f"candidate contains {needle!r}"
    if _PRAGMA.search(code):
        return "candidate contains a #pragma diagnostic, clang or GCC directive"
    return None


def fix(
    case: Case,
    model: str,
    max_attempts: int = 5,
    trial: int = 0,
    progress: Callable[[Attempt], None] | None = None,
) -> FixRun:
    """Run the fix loop for ``case`` with ``model`` and log it to out/runs/.

    Stops at the first candidate that passes the visible test, or after
    ``max_attempts``. Then runs the hidden test on attempt 1's candidate and on
    the final one. ``progress`` is called with each finished attempt.
    """
    run = FixRun(case_id=case.id, model=model, trial=trial)
    messages = _first_messages(case)
    for number in range(1, max_attempts + 1):
        attempt = _attempt(case, model, trial, number, messages)
        run.attempts.append(attempt)
        if progress:
            progress(attempt)
        if attempt.stage in ("ok", "llm_error"):
            break  # a provider error is not retried: the run ends and the bench moves on
        messages = _retry_messages(case, attempt)
    first, final = run.attempts[0], run.attempts[-1]
    run.hidden_first = _hidden(case, first)
    run.hidden_final = run.hidden_first if final is first else _hidden(case, final)
    _log(run)
    return run


def _attempt(case: Case, model: str, trial: int, number: int, messages: list[dict]) -> Attempt:
    """Send one prompt, extract the code, and check it against the visible test."""
    try:
        response, usage = complete(messages, model, trial=trial)
    except DailyLimitReached:
        raise  # the whole bench stops on the daily limit, so it is not a per-run error
    except LLMError as error:
        no_usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_s": 0.0, "cache_hit": False}
        return Attempt(number=number, prompt=messages, response="", code=None, stage="llm_error",
                       output=str(error), usage=no_usage)
    code = extract_code(response)
    base = {"number": number, "prompt": messages, "response": response, "code": code, "usage": usage}
    if code is None:
        return Attempt(**base, stage="no_code", output="no code block in response")
    reason = guardrail(code)
    if reason:
        return Attempt(**base, stage="rejected", output=reason)
    result = verify(code, case)
    return Attempt(**base, stage=result.stage, output=result.output, result=result.to_dict())


def _hidden(case: Case, attempt: Attempt) -> dict | None:
    """Run the hidden test on a candidate that reached the compiler. Rejected or missing code is never run."""
    if attempt.stage in ("no_code", "rejected", "llm_error"):
        return None
    return verify(attempt.code, case, test="hidden").to_dict()


def _first_messages(case: Case) -> list[dict]:
    """The system prompt and the first user message: the task, the buggy file, the header and the visible test."""
    buggy = (case.directory / case.editable).read_text(encoding="utf-8")
    header = (case.directory / case.header).read_text(encoding="utf-8")
    visible = (case.directory / case.test).read_text(encoding="utf-8")
    user = (
        f"Task: {case.description}\n\n"
        f"Buggy file ({case.editable}):\n{_fence(case, buggy)}\n\n"
        f"Header ({case.header}):\n{_fence(case, header)}\n\n"
        f"Visible test ({case.test}):\n{_fence(case, visible)}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _retry_messages(case: Case, previous: Attempt) -> list[dict]:
    """A compact retry: the original task, the previous attempt, and only the latest failure."""
    task = _first_messages(case)[1]["content"]
    previous_text = _fence(case, previous.code) if previous.code else previous.response
    user = (
        f"{task}\n\nYour previous attempt:\n{previous_text}\n\n"
        f"It failed at stage {previous.stage}:\n{previous.output}\n\n{RETURN_INSTRUCTION}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _fence(case: Case, text: str) -> str:
    """Wrap ``text`` in a fenced block tagged with the case language."""
    language = "cpp" if case.lang == "cpp" else "c"
    return f"```{language}\n{text}\n```"


def _log(run: FixRun) -> None:
    """Write one JSON file with every attempt of this run to out/runs/."""
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%f")
    model = run.model.replace("/", "-")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{stamp}_{run.case_id}_{model}.json"
    path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
