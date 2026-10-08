"""Rotas HTTP para baixar bases completas para o computador (app local)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .biblioteca import GerenciadorDownloads

router = APIRouter(tags=["Downloads"])

# Ao cancelar, espera até este tempo (s) a limpeza dos arquivos parciais antes de responder.
ESPERA_CANCELAMENTO = 10.0


class CorpoDownload(BaseModel):
    dataset: str = Field(..., min_length=1, description="Base de origem (id do catálogo, operationId ou caminho).")
    filtros: dict[str, Any] = Field(default_factory=dict, description="Filtros aceitos pela API oficial.")
    nome: str | None = Field(
        None, description="Nome da base no computador. Vazio = gerado a partir da base e dos filtros."
    )

    model_config = {
        "json_schema_extra": {"examples": [{"dataset": "arboviroses-dengue", "filtros": {"nu_ano": 2024}}]}
    }


def obter_gerenciador(app: FastAPI) -> GerenciadorDownloads:
    """O gerenciador de downloads do app (criado na primeira vez que é usado)."""
    gerenciador = getattr(app.state, "downloads", None)
    if gerenciador is None:
        from .main import _obter_catalogo  # import tardio: main importa este módulo

        gerenciador = GerenciadorDownloads(app.state.config, app.state.cliente, lambda: _obter_catalogo(app))
        app.state.downloads = gerenciador
    return gerenciador


async def encerrar_downloads(app: FastAPI) -> None:
    """Cancela os downloads em andamento (para chamar ao desligar o app)."""
    gerenciador = getattr(app.state, "downloads", None)
    if gerenciador is not None:
        await gerenciador.fechar()


def _nao_encontrado(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/api/downloads",
    status_code=201,
    summary="Baixa uma base completa para o computador",
    description=(
        "Percorre todas as páginas da API oficial com os filtros informados e salva a base em "
        "`<pasta de dados>/bases/<nome>.parquet` (com os metadados em `<nome>.json`). O download roda "
        "em segundo plano: acompanhe por `GET /api/downloads/{id}`."
    ),
)
async def iniciar_download(request: Request, corpo: CorpoDownload):
    try:
        return await obter_gerenciador(request.app).iniciar(corpo.dataset, corpo.filtros, corpo.nome)
    except LookupError as exc:
        raise _nao_encontrado(exc) from exc


@router.get("/api/downloads", summary="Downloads desta sessão (mais recentes primeiro)")
async def listar_downloads(request: Request):
    return {"downloads": obter_gerenciador(request.app).listar()}


@router.get("/api/downloads/{download_id}", summary="Andamento de um download")
async def obter_download(request: Request, download_id: str):
    try:
        return obter_gerenciador(request.app).obter(download_id)
    except LookupError as exc:
        raise _nao_encontrado(exc) from exc


@router.delete("/api/downloads/{download_id}", summary="Cancela um download em andamento")
async def cancelar_download(request: Request, download_id: str):
    gerenciador = obter_gerenciador(request.app)
    try:
        gerenciador.cancelar(download_id)
        return await gerenciador.aguardar(download_id, timeout=ESPERA_CANCELAMENTO)
    except LookupError as exc:
        raise _nao_encontrado(exc) from exc
