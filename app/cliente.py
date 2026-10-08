"""Cliente HTTP para a API de Dados Abertos do Ministério da Saúde."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from .config import Config


class ErroUpstream(Exception):
    """Falha ao consultar a API do Ministério da Saúde."""

    def __init__(self, mensagem: str, status: int | None = None, url: str | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.url = url


class ClienteDataSUS:
    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._http = httpx.AsyncClient(
            timeout=config.timeout,
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "API-SUS/1.0"},
            transport=transport,
        )
        self._cache: dict[str, tuple[float, Any]] = {}

    async def fechar(self) -> None:
        await self._http.aclose()

    def limpar_cache(self) -> None:
        self._cache.clear()

    async def get_json(self, url: str, params: dict[str, Any] | None = None, usar_cache: bool = True) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        chave = url + "?" + json.dumps(params, sort_keys=True, default=str)
        agora = time.monotonic()
        if usar_cache and self.config.cache_ttl > 0:
            item = self._cache.get(chave)
            if item and agora - item[0] < self.config.cache_ttl:
                return item[1]

        ultimo_erro: ErroUpstream | None = None
        for tentativa in range(max(1, self.config.tentativas)):
            if tentativa:
                await asyncio.sleep(min(2**tentativa, 10))
            try:
                resp = await self._http.get(url, params=params)
            except httpx.TimeoutException as exc:
                ultimo_erro = ErroUpstream(
                    f"Tempo esgotado ({self.config.timeout:.0f}s) esperando {url} ({type(exc).__name__}). "
                    "A API oficial pode estar lenta para este filtro; tente filtros mais restritos ou "
                    "aumente DATASUS_TIMEOUT.",
                    url=url,
                )
                continue
            except httpx.HTTPError as exc:
                ultimo_erro = ErroUpstream(f"Falha de conexão com {url}: {type(exc).__name__} {exc}", url=url)
                continue

            if resp.status_code >= 500 or resp.status_code == 429:
                ultimo_erro = ErroUpstream(
                    f"A API do Ministério da Saúde respondeu {resp.status_code}: {resp.text[:500]}",
                    status=resp.status_code,
                    url=str(resp.request.url),
                )
                continue
            if resp.status_code >= 400:
                raise ErroUpstream(
                    f"A API do Ministério da Saúde respondeu {resp.status_code}: {resp.text[:500]}",
                    status=resp.status_code,
                    url=str(resp.request.url),
                )
            try:
                dados = resp.json()
            except ValueError as exc:
                raise ErroUpstream(
                    f"Resposta não é JSON válido ({exc}): {resp.text[:200]}",
                    status=resp.status_code,
                    url=str(resp.request.url),
                ) from exc

            if usar_cache and self.config.cache_ttl > 0:
                if len(self._cache) > 500:
                    self._cache.clear()
                self._cache[chave] = (agora, dados)
            return dados

        assert ultimo_erro is not None
        raise ultimo_erro
