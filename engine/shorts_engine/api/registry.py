from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..common.errors import EngineError
from pydantic import BaseModel, ValidationError

Handler = Callable[[Any, BaseModel, dict[str, str]], Awaitable[dict[str, Any]]]


class Registry:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[type[BaseModel], Handler]] = {}

    def add(self, method: str, model: type[BaseModel], handler: Handler) -> None:
        self.routes[method] = (model, handler)

    async def dispatch(self, method: str, params: dict[str, Any], secrets: dict[str, str], app: Any) -> dict[str, Any]:
        route = self.routes.get(method)
        if not route:
            raise EngineError("METHOD_NOT_FOUND", f"Unknown method '{method}'.")
        model, handler = route
        try:
            validated = model.model_validate(params or {})
        except ValidationError as exc:
            raise EngineError(
                "INVALID_PARAMS",
                "The request parameters are not valid.",
                details={"errors": exc.errors(include_url=False)[:8]},
            ) from exc
        return await handler(app, validated, secrets)
