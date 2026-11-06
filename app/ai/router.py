"""Barcha AI chaqiruvlari shu yerdan: rol → provayder, retry, fallback, JSON sxema, budjet, xarajat."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

from app.ai.pricing import Prices, cost_usd, image_cost
from app.ai.types import (
    BudgetExceededError,
    ImageClient,
    LLMClient,
    LLMResult,
    Message,
    NoProviderError,
    RawCompletion,
    SchemaError,
)
from app.content.formatting import strip_code_fences
from app.utils.security import mask_secrets

if TYPE_CHECKING:
    from app.db.repo import Repo
    from app.utils.budget import BudgetGuard

T = TypeVar("T", bound=BaseModel)

FALLBACK: dict[str, str] = {"writer": "editor", "editor": "writer", "fast": "writer"}
_NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 422})


def _retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return status not in _NON_RETRYABLE_STATUS


def parse_json(text: str, schema: type[T]) -> T:
    body = strip_code_fences(text)
    try:
        data: Any = json.loads(body)
    except json.JSONDecodeError:
        start, end = body.find("{"), body.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("JSON topilmadi") from None
        data = json.loads(body[start : end + 1])
    return schema.model_validate(data)


class AIRouter:
    def __init__(
        self,
        clients: Mapping[str, LLMClient | None],
        *,
        image: ImageClient | None = None,
        repo: Repo | None = None,
        budget: BudgetGuard | None = None,
        prices: Prices | None = None,
        timeout: float = 120.0,
        attempts: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.clients = dict(clients)
        self.image_client = image
        self.repo = repo
        self.budget = budget
        self.prices = prices
        self.timeout = timeout
        self.attempts = attempts
        self._sleep = sleep

    def has(self, role: str) -> bool:
        return self.clients.get(role) is not None

    def describe(self) -> dict[str, str]:
        out = {}
        for role, c in self.clients.items():
            out[role] = f"{c.provider}/{c.model}" if c else "—"
        out["image"] = f"{self.image_client.provider}/{self.image_client.model}" if self.image_client else "—"
        return out

    # --- matn ---

    async def complete(
        self,
        role: str,
        messages: Sequence[Message],
        *,
        schema: type[T] | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1500,
        essential: bool = True,
    ) -> LLMResult:
        if self.budget is not None:
            await self.budget.ensure(essential)
        msgs = self._with_schema(messages, schema) if schema else list(messages)
        primary = self.clients.get(role)
        last_exc: BaseException | None = None
        if primary is not None:
            try:
                return await self._run(primary, role, msgs, schema, temperature, max_tokens, fallback=False)
            except (SchemaError, BudgetExceededError):
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning("AI {} ({}) ishlamadi: {}", role, primary.model, mask_secrets(repr(exc))[:300])
        fb = self.clients.get(FALLBACK.get(role, "editor"))
        if fb is None or fb is primary:
            if last_exc is not None:
                raise last_exc
            raise NoProviderError(f"'{role}' roli uchun provayder sozlanmagan")
        logger.info("AI {}: zaxira model {} ishlatilmoqda", role, fb.model)
        return await self._run(fb, role, msgs, schema, temperature, max_tokens, fallback=True)

    def _with_schema(self, messages: Sequence[Message], schema: type[BaseModel]) -> list[Message]:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        instr = (
            "\n\nJavobni FAQAT bitta JSON obyekt ko'rinishida qaytar (markdown, izoh yoki boshqa matnsiz). "
            f"JSON sxema:\n{schema_json}"
        )
        msgs = list(messages)
        for i, m in enumerate(msgs):
            if m.role == "system":
                msgs[i] = Message("system", m.content + instr, images=m.images, cache=m.cache)
                return msgs
        return [Message("system", instr.strip(), cache=True), *msgs]

    async def _run(
        self,
        client: LLMClient,
        role: str,
        msgs: list[Message],
        schema: type[T] | None,
        temperature: float,
        max_tokens: int,
        *,
        fallback: bool,
    ) -> LLMResult:
        raw = await self._call(client, role, msgs, schema is not None, temperature, max_tokens)
        totals = [raw]
        parsed: Any = None
        if schema is not None:
            try:
                parsed = parse_json(raw.text, schema)
            except (ValueError, ValidationError) as exc:
                hint = str(exc).splitlines()[0][:200]
                retry_msgs = [
                    *msgs,
                    Message("assistant", raw.text),
                    Message(
                        "user",
                        f"Javobing JSON sxemaga mos emas ({hint}). Faqat sxemaga mos to'g'ri JSON qaytar.",
                    ),
                ]
                raw = await self._call(client, role, retry_msgs, True, temperature, max_tokens)
                totals.append(raw)
                try:
                    parsed = parse_json(raw.text, schema)
                except (ValueError, ValidationError) as exc2:
                    raise SchemaError(f"{role}/{client.model}: JSON sxemaga mos emas: {exc2}") from exc2
        inp = sum(r.input_tokens for r in totals)
        out = sum(r.output_tokens for r in totals)
        cached = sum(r.cached_tokens for r in totals)
        return LLMResult(
            text=raw.text,
            parsed=parsed,
            input_tokens=inp,
            output_tokens=out,
            cached_tokens=cached,
            model=client.model,
            provider=client.provider,
            role=role,
            fallback_used=fallback,
            cost_usd=cost_usd(client.model, inp, out, cached, self.prices),
        )

    async def _call(
        self,
        client: LLMClient,
        role: str,
        msgs: list[Message],
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> RawCompletion:
        for attempt in range(1, self.attempts + 1):
            try:
                raw = await asyncio.wait_for(
                    client.complete(
                        msgs, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens
                    ),
                    self.timeout,
                )
            except Exception as exc:
                await self._record(client, role, ok=False, error=repr(exc))
                if not _retryable(exc) or attempt == self.attempts:
                    raise
                await self._sleep(float(2 ** (attempt - 1)))
                continue
            await self._record(client, role, raw=raw)
            return raw
        raise RuntimeError("unreachable")

    async def _record(
        self,
        client: Any,
        role: str,
        *,
        raw: RawCompletion | None = None,
        ok: bool = True,
        error: str | None = None,
        cost: float | None = None,
    ) -> None:
        if self.repo is None:
            return
        try:
            if raw is not None and cost is None:
                cost = cost_usd(
                    client.model, raw.input_tokens, raw.output_tokens, raw.cached_tokens, self.prices
                )
            await self.repo.record_usage(
                role=role,
                provider=client.provider,
                model=client.model,
                input_tokens=raw.input_tokens if raw else 0,
                output_tokens=raw.output_tokens if raw else 0,
                cached_tokens=raw.cached_tokens if raw else 0,
                cost_usd=cost or 0.0,
                ok=ok,
                error=mask_secrets(error) if error else None,
            )
        except Exception as exc:  # DB xatosi AI chaqiruvini buzmasin
            logger.warning("llm_usage yozilmadi: {}", exc)

    # --- rasm ---

    async def image(self, prompt: str, size: str = "1024x1024") -> bytes | None:
        client = self.image_client
        if client is None:
            return None
        for attempt in (1, 2):
            try:
                data = await asyncio.wait_for(client.generate(prompt, size=size), self.timeout)
            except Exception as exc:
                await self._record(client, "image", ok=False, error=repr(exc))
                logger.warning(
                    "Rasm generatsiya xatosi ({}): {}", client.model, mask_secrets(repr(exc))[:300]
                )
                if attempt == 1 and _retryable(exc):
                    await self._sleep(1.0)
                    continue
                return None
            await self._record(client, "image", cost=image_cost(client.model, self.prices))
            return data
        return None

    # --- modellar mavjudligi ---

    async def check_models(self) -> list[str]:
        problems: list[str] = []
        seen: set[int] = set()
        for role, client in self.clients.items():
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            try:
                models = await client.list_models()
            except Exception as exc:
                problems.append(
                    f"{role} ({client.provider}/{client.model}): modellar ro'yxatini olib bo'lmadi — "
                    f"{mask_secrets(str(exc))[:200]}"
                )
                continue
            if models is not None and client.model not in models:
                problems.append(f"{role}: '{client.model}' modeli {client.provider} API'da topilmadi")
        return problems
