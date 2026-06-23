"""Input and tool-output guardrails for agent conversations."""

from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

ENV_CONTENT_SAFETY_ENDPOINT = "AZURE_CONTENT_SAFETY_ENDPOINT"
ENV_CONTENT_SAFETY_KEY = "AZURE_CONTENT_SAFETY_KEY"
CONTENT_SAFETY_CATEGORIES = ("Hate", "SelfHarm", "Sexual", "Violence")
CONTENT_SAFETY_SEVERITY_THRESHOLD = 2


class PromptInjectionError(ValueError):
    """Raised when a user message looks like prompt injection."""


class ContentPolicyViolationError(ValueError):
    """Raised when generated output violates content policy."""


@dataclass(frozen=True)
class _InjectionRule:
    pattern: re.Pattern[str]
    score: int


@dataclass(frozen=True)
class _RedactionSpan:
    start: int
    end: int
    label: str


class Guardrails:
    """Detect prompt injection and redact PII from tool outputs."""

    _EMAIL_RE = re.compile(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        re.IGNORECASE,
    )
    _CA_PHONE_RE = re.compile(
        r"(?<!\w)(?:\+?1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?"
        r"[2-9]\d{2}[\s.-]?\d{4}(?:\s*(?:x|ext\.?)\s*\d{1,6})?(?!\w)",
        re.IGNORECASE,
    )
    _NZ_PHONE_RE = re.compile(
        r"(?<!\w)(?:\+64|0064|0)(?:[\s.-]?\d){7,10}(?!\w)",
        re.IGNORECASE,
    )
    _PRESIDIO_CANDIDATE_RE = re.compile(r"[@\d]")

    def __init__(
        self,
        *,
        injection_threshold: int = 4,
        content_safety_endpoint: str | None = None,
        content_safety_key: str | None = None,
        content_safety_client: Any | None = None,
    ) -> None:
        self.injection_threshold = injection_threshold
        self._analyzer: Any | None = None
        self._analyzer_unavailable = False
        self.content_safety_endpoint = content_safety_endpoint or os.getenv(
            ENV_CONTENT_SAFETY_ENDPOINT
        )
        self.content_safety_key = content_safety_key or os.getenv(
            ENV_CONTENT_SAFETY_KEY
        )
        self._content_safety_client = content_safety_client
        self._injection_rules = (
            _InjectionRule(
                re.compile(
                    r"\b(?:ignore|disregard|forget|skip|override)\b.{0,80}"
                    r"\b(?:previous|above|prior|earlier|system|developer)\b.{0,40}"
                    r"\b(?:instructions?|directives?|messages?|prompt|rules?)\b",
                    re.IGNORECASE | re.DOTALL,
                ),
                6,
            ),
            _InjectionRule(
                re.compile(
                    r"\b(?:you are|act as|become|pretend to be)\b.{0,40}"
                    r"\b(?:system|developer|admin|root|superuser)\b",
                    re.IGNORECASE | re.DOTALL,
                ),
                6,
            ),
            _InjectionRule(
                re.compile(
                    r"\b(?:reveal|show|print|dump|leak|exfiltrate)\b.{0,80}"
                    r"\b(?:system prompt|developer message|hidden instructions?|"
                    r"internal policy|chain[- ]of[- ]thought)\b",
                    re.IGNORECASE | re.DOTALL,
                ),
                6,
            ),
            _InjectionRule(
                re.compile(
                    r"\b(?:jailbreak|DAN|do anything now|bypass safety|"
                    r"disable guardrails|ignore safety|unfiltered mode|"
                    r"developer mode)\b",
                    re.IGNORECASE,
                ),
                5,
            ),
            _InjectionRule(
                re.compile(
                    r"(?:<\|/?(?:system|developer|assistant)\|>|"
                    r"</?(?:system|developer|assistant)>|"
                    r"```(?:system|developer|assistant)|"
                    r"^\s*#{2,}\s*(?:system|developer|assistant)\b|"
                    r"\[(?:system|developer|assistant)\])",
                    re.IGNORECASE | re.MULTILINE,
                ),
                5,
            ),
            _InjectionRule(
                re.compile(
                    r"\b(?:new|updated|replacement|higher priority)\s+"
                    r"(?:instructions?|rules?|system prompt)\b",
                    re.IGNORECASE,
                ),
                5,
            ),
            _InjectionRule(
                re.compile(
                    r"\b(?:system|developer|assistant)\s*:\s*"
                    r"(?:ignore|you are|new instructions?|override|reveal)",
                    re.IGNORECASE,
                ),
                5,
            ),
        )

    def sanitise_input(self, text: str) -> str:
        """Neutralise suspicious instruction text or reject likely injection."""
        normalised = unicodedata.normalize("NFKC", text)
        score = sum(
            rule.score
            for rule in self._injection_rules
            if rule.pattern.search(normalised)
        )
        if score > self.injection_threshold:
            raise PromptInjectionError("Potential prompt injection detected.")

        sanitised = text
        for rule in self._injection_rules:
            sanitised = rule.pattern.sub("[neutralised instruction]", sanitised)
        return sanitised

    def strip_pii_from_tool_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of tool output with email and phone PII redacted."""
        return self._redact_value(data)

    async def filter_output(self, text: str) -> str:
        """Reject generated text that Content Safety rates above policy threshold.

        If Content Safety is not configured (no endpoint/key), the text is
        returned unfiltered — this avoids hard failures in local dev or
        environments where Content Safety is an optional guard.
        """
        try:
            client = self._get_content_safety_client()
        except RuntimeError:
            # Content Safety not configured — skip filtering gracefully
            return text

        result = await asyncio.to_thread(
            _analyze_text,
            client,
            text,
        )

        for category_analysis in _category_analyses(result):
            severity = _model_value(category_analysis, "severity")
            category = _normalise_category(_model_value(category_analysis, "category"))
            if (
                category in CONTENT_SAFETY_CATEGORIES
                and severity is not None
                and int(severity) > CONTENT_SAFETY_SEVERITY_THRESHOLD
            ):
                raise ContentPolicyViolationError(category)

        return text

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._redact_value(item) for item in value]
        if isinstance(value, Mapping):
            return {key: self._redact_value(item) for key, item in value.items()}
        return value

    def _redact_text(self, text: str) -> str:
        spans = self._collect_pii_spans(text)
        if not spans:
            return text

        redacted = text
        for span in reversed(self._merge_spans(spans)):
            redacted = redacted[: span.start] + span.label + redacted[span.end :]
        return redacted

    def _collect_pii_spans(self, text: str) -> list[_RedactionSpan]:
        spans: list[_RedactionSpan] = []

        for match in self._EMAIL_RE.finditer(text):
            spans.append(_RedactionSpan(match.start(), match.end(), "[REDACTED_EMAIL]"))
        for regex in (self._CA_PHONE_RE, self._NZ_PHONE_RE):
            for match in regex.finditer(text):
                spans.append(
                    _RedactionSpan(match.start(), match.end(), "[REDACTED_PHONE]")
                )

        analyzer = (
            self._get_analyzer()
            if not spans and self._PRESIDIO_CANDIDATE_RE.search(text)
            else None
        )
        if analyzer is not None:
            try:
                results = analyzer.analyze(
                    text=text,
                    language="en",
                    entities=["EMAIL_ADDRESS", "PHONE_NUMBER"],
                    score_threshold=0.5,
                )
            except Exception:
                results = []

            for result in results:
                entity_type = getattr(result, "entity_type", "")
                label = (
                    "[REDACTED_EMAIL]"
                    if entity_type == "EMAIL_ADDRESS"
                    else "[REDACTED_PHONE]"
                )
                spans.append(_RedactionSpan(result.start, result.end, label))

        return spans

    def _get_analyzer(self) -> Any | None:
        if self._analyzer is not None:
            return self._analyzer
        if self._analyzer_unavailable:
            return None

        try:
            from presidio_analyzer import AnalyzerEngine

            self._analyzer = AnalyzerEngine()
        except Exception:
            self._analyzer_unavailable = True
            return None
        return self._analyzer

    def _get_content_safety_client(self) -> Any:
        if self._content_safety_client is not None:
            return self._content_safety_client
        if not self.content_safety_endpoint or not self.content_safety_key:
            raise RuntimeError(
                f"Missing Content Safety configuration. Set "
                f"{ENV_CONTENT_SAFETY_ENDPOINT} and {ENV_CONTENT_SAFETY_KEY}."
            )

        try:
            from azure.ai.contentsafety import ContentSafetyClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError as exc:
            raise RuntimeError("Azure AI Content Safety SDK is not installed.") from exc

        self._content_safety_client = ContentSafetyClient(
            self.content_safety_endpoint,
            AzureKeyCredential(self.content_safety_key),
        )
        return self._content_safety_client

    def _merge_spans(self, spans: list[_RedactionSpan]) -> list[_RedactionSpan]:
        ordered = sorted(spans, key=lambda span: (span.start, -(span.end - span.start)))
        merged: list[_RedactionSpan] = []
        for span in ordered:
            if not merged or span.start >= merged[-1].end:
                merged.append(span)
                continue
            previous = merged[-1]
            if span.end > previous.end:
                merged[-1] = _RedactionSpan(previous.start, span.end, previous.label)
        return merged


async def filter_output(text: str) -> str:
    """Filter generated output with Azure AI Content Safety."""
    return await Guardrails().filter_output(text)


def _analyze_text(client: Any, text: str) -> Any:
    operation = getattr(client, "analyze", None) or getattr(client, "analyze_text")
    return operation(
        {
            "text": text,
            "categories": list(CONTENT_SAFETY_CATEGORIES),
        }
    )


def _category_analyses(result: Any) -> list[Any]:
    analyses = _model_value(result, "categories_analysis")
    if analyses is None:
        analyses = _model_value(result, "categoriesAnalysis")
    if analyses is None and isinstance(result, Mapping):
        analyses = result.get("categories_analysis") or result.get("categoriesAnalysis")
    return list(analyses or [])


def _normalise_category(category: Any) -> str:
    value = getattr(category, "value", category)
    if isinstance(value, str):
        return value
    return str(value)


def _model_value(model: Any, key: str) -> Any:
    if isinstance(model, Mapping):
        return model.get(key)
    return getattr(model, key, None)
