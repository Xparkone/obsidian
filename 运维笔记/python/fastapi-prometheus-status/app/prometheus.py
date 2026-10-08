from __future__ import annotations

from typing import Any

import httpx


class PrometheusError(RuntimeError):
    """Prometheus API 请求或返回内容无效。"""


class PrometheusClient:
    def __init__(self, base_url: str, timeout: float, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = token

    async def query(self, promql: str) -> list[dict[str, Any]]:
        return await self._request("/api/v1/query", {"query": promql}, "vector")

    async def query_range(self, promql: str, start: float, end: float, step: str) -> list[dict[str, Any]]:
        return await self._request(
            "/api/v1/query_range",
            {"query": promql, "start": start, "end": end, "step": step},
            "matrix",
        )

    async def _request(self, path: str, params: dict[str, Any], expected_type: str) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}{path}",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PrometheusError(str(exc)) from exc
        if payload.get("status") != "success":
            raise PrometheusError(str(payload.get("error", "Prometheus query failed")))
        data = payload.get("data", {})
        if data.get("resultType") != expected_type:
            raise PrometheusError(f"expected {expected_type} result, got {data.get('resultType')!r}")
        return data.get("result", [])


def value(result: dict[str, Any]) -> float:
    """取 instant-vector sample 的数值。"""
    return float(result["value"][1])


def last_range_value(result: dict[str, Any]) -> float:
    """取 range-matrix 最后一点的数值。"""
    points = result.get("values") or []
    if not points:
        raise PrometheusError("empty range series")
    return float(points[-1][1])


def labels(result: dict[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in result.get("metric", {}).items()}
