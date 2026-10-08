"""Rotas HTTP das bases já baixadas para o computador (app local): listar, explorar, filtrar e exportar."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import local
from .consulta import ErroConsulta

router = APIRouter(tags=["Bases no computador"])

TIPOS_ARQUIVO = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}

_DESCRICAO_FILTROS = (
    '{"coluna": ["valor1", "valor2"]}: a coluna deve ter um dos valores (null na lista = vazio). '
    "Várias colunas se combinam (E)."
)


class CorpoConsultaLocal(BaseModel):
    filtros: dict[str, Any] = Field(default_factory=dict, description=_DESCRICAO_FILTROS)
    colunas: list[str] | None = Field(None, description="Colunas a retornar. Vazio = todas.")
    agrupar_por: list[str] | None = Field(None, description="Colunas (categorias) para agrupar.")
    somar: list[str] | None = Field(None, description="Colunas numéricas a somar em cada grupo.")
    limite: int = Field(500, description=f"Máximo de linhas detalhadas na resposta (0 a {local.LIMITE_CONSULTA_MAX}).")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filtros": {"sg_uf": ["SP", "RJ"]},
                    "agrupar_por": ["ds_procedimento"],
                    "somar": ["qt_procedimento"],
                    "limite": 100,
                }
            ]
        }
    }


class CorpoExportacaoLocal(BaseModel):
    filtros: dict[str, Any] = Field(default_factory=dict, description=_DESCRICAO_FILTROS)
    colunas: list[str] | None = Field(None, description="Colunas a exportar. Vazio = todas.")
    agrupar_por: list[str] | None = Field(None, description="Colunas (categorias) para agrupar.")
    somar: list[str] | None = Field(None, description="Colunas numéricas a somar em cada grupo.")
    formato: Literal["xlsx", "csv"] = Field("xlsx", description="xlsx (Excel) ou csv (separador ';').")


def _pasta(request: Request) -> Path:
    return Path(request.app.state.config.pasta_dados)


@contextlib.contextmanager
def _traduzir_erros() -> Iterator[None]:
    """Base ou coluna inexistente vira 404 (ErroConsulta vira 422 no handler global do app)."""
    try:
        yield
    except local.NaoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _filtros_da_query(texto: str | None) -> dict[str, Any]:
    if not texto or not texto.strip():
        return {}
    try:
        filtros = json.loads(texto)
    except ValueError as exc:
        raise ErroConsulta(f"O parâmetro 'filtros' deve ser um JSON válido: {exc}") from exc
    if not isinstance(filtros, dict):
        raise ErroConsulta('O parâmetro \'filtros\' deve ser um objeto JSON {"coluna": [valores]}.')
    return filtros


# As rotas são síncronas (def): o FastAPI as roda numa thread, sem travar o servidor enquanto o DuckDB trabalha.


@router.get("/api/local/bases", summary="Bases baixadas para o computador (mais recentes primeiro)")
def listar_bases(request: Request):
    pasta = _pasta(request)
    return {"pasta": str(pasta), "bases": local.listar_bases(pasta)}


@router.delete("/api/local/bases/{nome}", summary="Apaga uma base do computador")
def excluir_base(request: Request, nome: str):
    with _traduzir_erros():
        return {"removida": local.excluir_base(_pasta(request), nome)}


@router.get(
    "/api/local/bases/{nome}/colunas",
    summary="Colunas de uma base: valores distintos, vazios, se é numérica e um exemplo",
)
def colunas(request: Request, nome: str):
    with _traduzir_erros():
        return local.colunas(_pasta(request), nome)


@router.get(
    "/api/local/bases/{nome}/categorias/{coluna:path}",
    summary="Valores (categorias) de uma coluna e quantos registros têm cada um",
    description=(
        "Aplica os filtros das OUTRAS colunas e ignora o filtro da própria coluna (filtros em cascata). "
        "`busca` procura um trecho do valor, sem diferenciar maiúsculas nem acentos."
    ),
)
def categorias(
    request: Request,
    nome: str,
    coluna: str,
    busca: str | None = Query(None, description="Trecho a procurar nos valores."),
    limite: int = Query(200, description=f"Máximo de valores (1 a {local.LIMITE_CATEGORIAS_MAX})."),
    filtros: str | None = Query(None, description=f"JSON {_DESCRICAO_FILTROS}"),
):
    with _traduzir_erros():
        return local.categorias(_pasta(request), nome, coluna, busca, limite, _filtros_da_query(filtros))


@router.post(
    "/api/local/bases/{nome}/consulta",
    summary="Filtra uma base do computador e, se pedido, agrupa e soma",
)
def consultar(request: Request, nome: str, corpo: CorpoConsultaLocal):
    with _traduzir_erros():
        return local.consultar(
            _pasta(request), nome, corpo.filtros, corpo.colunas, corpo.agrupar_por, corpo.somar, corpo.limite
        )


@router.post(
    "/api/local/bases/{nome}/exportar",
    summary="Exporta a consulta para Excel (xlsx) ou CSV",
    description=(
        "Exporta TODOS os registros filtrados. xlsx: abas `resumo` (se houver agrupamento/soma), `dados` e "
        "`consulta`. csv: o resumo, se houver, senão os dados (separador ';', UTF-8 com BOM). Uma cópia fica "
        "em `<pasta de dados>/exportacoes/`."
    ),
)
def exportar(request: Request, nome: str, corpo: CorpoExportacaoLocal):
    with _traduzir_erros():
        caminho, sugerido = local.exportar(
            _pasta(request), nome, corpo.formato, corpo.filtros, corpo.colunas, corpo.agrupar_por, corpo.somar
        )
    return FileResponse(
        caminho,
        filename=sugerido,
        media_type=TIPOS_ARQUIVO[corpo.formato],
        headers={"X-Arquivo-Salvo": quote(str(caminho))},
    )
