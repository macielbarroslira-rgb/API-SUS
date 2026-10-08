"""API HTTP (FastAPI) para consultar as bases da API de Dados Abertos do Ministério da Saúde."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .catalogo import Catalogo, Dataset, ErroCatalogo, carregar_catalogo
from .cliente import ClienteDataSUS, ErroUpstream
from .config import Config
from .consulta import (
    Consulta,
    ErroConsulta,
    amostrar_variaveis,
    executar,
    para_csv,
    para_csv_agregado,
    para_xlsx,
)

PASTA_STATIC = Path(__file__).parent / "static"

# Parâmetros de controle do GET /dados; todo o resto da query string é repassado como filtro.
PARAMS_CONTROLE = {"colunas", "formato", "max_registros", "paginar", "separador", "amostra", "agrupar_por", "somar"}
PREFIXO_LOCAL = "local."


class CorpoConsulta(BaseModel):
    filtros: dict[str, Any] = Field(default_factory=dict, description="Filtros aceitos pela API oficial.")
    colunas: list[str] | None = Field(None, description="Variáveis (colunas) a retornar. Vazio = todas.")
    filtros_locais: dict[str, Any] | None = Field(
        None, description="Filtros de igualdade aplicados aqui, sobre os dados já baixados."
    )
    max_registros: int | None = Field(None, ge=0, description="Máximo de registros a buscar (0 = todos).")
    agrupar_por: list[str] = Field(default_factory=list, description="Variáveis categóricas para agrupar.")
    somar: list[str] = Field(default_factory=list, description="Variáveis numéricas a somar em cada grupo.")
    paginar: bool = Field(True, description="Percorrer as páginas automaticamente.")
    formato: Literal["json", "csv", "xlsx"] = "json"
    separador: str = Field(",", min_length=1, max_length=1)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filtros": {"nu_comp": 202401, "co_ibge": 355030},
                    "agrupar_por": ["ds_procedimento"],
                    "somar": ["qt_procedimento", "nu_valor_procedimento"],
                    "max_registros": 0,
                    "formato": "json",
                }
            ]
        }
    }


def criar_app(config: Config | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    config = config or Config.do_ambiente()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        app.state.cliente = ClienteDataSUS(config, transport=transport)
        app.state.catalogo = None
        app.state.erro_catalogo = None
        app.state.trava = asyncio.Lock()
        try:
            await _obter_catalogo(app)
        except HTTPException:
            pass  # tenta de novo na primeira requisição
        yield
        await app.state.cliente.fechar()

    app = FastAPI(
        title="API-SUS",
        version=__version__,
        description=(
            "Consulta as bases da API de Dados Abertos do Ministério da Saúde "
            "(https://apidadosabertos.saude.gov.br/v1/). Liste as bases, veja as variáveis "
            "disponíveis e baixe os dados filtrados em JSON ou CSV."
        ),
        lifespan=ciclo_de_vida,
    )
    app.state.config = config
    app.add_middleware(
        CORSMiddleware, allow_origins=config.cors_origens, allow_methods=["*"], allow_headers=["*"]
    )

    @app.exception_handler(ErroConsulta)
    async def _erro_consulta(_: Request, exc: ErroConsulta):
        return JSONResponse(status_code=422, content={"erro": str(exc)})

    @app.exception_handler(ErroUpstream)
    async def _erro_upstream(_: Request, exc: ErroUpstream):
        return JSONResponse(
            status_code=502,
            content={"erro": exc.mensagem, "status_origem": exc.status, "url_origem": exc.url},
        )

    # ------------------------------------------------------------------ #

    @app.get("/", include_in_schema=False)
    async def interface():
        return FileResponse(PASTA_STATIC / "index.html")

    @app.get("/health", tags=["Sistema"])
    async def health(request: Request):
        cat: Catalogo | None = request.app.state.catalogo
        return {
            "status": "ok",
            "versao": __version__,
            "catalogo_carregado": cat is not None,
            "origem_catalogo": cat.origem if cat else None,
            "erro_catalogo": request.app.state.erro_catalogo,
        }

    @app.get("/api/catalogo", tags=["Catálogo"], summary="Resumo do catálogo e grupos temáticos")
    async def catalogo(request: Request):
        cat = await _obter_catalogo(request.app)
        info = cat.spec.get("info") or {}
        return {
            "origem": cat.origem,
            "carregado_em": cat.carregado_em,
            "versao_api_oficial": info.get("version"),
            "titulo_api_oficial": info.get("title"),
            "total_bases": len(cat.datasets),
            "grupos": cat.grupos(),
        }

    @app.post("/api/catalogo/recarregar", tags=["Catálogo"], summary="Baixa de novo a especificação oficial")
    async def recarregar(request: Request):
        request.app.state.catalogo = None
        request.app.state.cliente.limpar_cache()
        cat = await _obter_catalogo(request.app)
        return {"origem": cat.origem, "carregado_em": cat.carregado_em, "total_bases": len(cat.datasets)}

    @app.get("/api/datasets", tags=["Bases"], summary="Lista as bases de dados disponíveis")
    async def listar(
        request: Request,
        q: str | None = Query(None, description="Busca por nome/descrição (sem acento)."),
        grupo: str | None = Query(None, description="Filtra por grupo temático."),
    ):
        cat = await _obter_catalogo(request.app)
        itens = cat.listar(q, grupo)
        return {"total": len(itens), "bases": [d.resumo_dict() for d in itens]}

    @app.get("/api/datasets/{dataset_id}", tags=["Bases"], summary="Detalhes, filtros e variáveis de uma base")
    async def detalhar(request: Request, dataset_id: str):
        _, ds = await _dataset(request.app, dataset_id)
        return ds.detalhe_dict()

    @app.get(
        "/api/datasets/{dataset_id}/variaveis",
        tags=["Bases"],
        summary="Variáveis (colunas) disponíveis em uma base",
        description=(
            "Retorna as variáveis documentadas na especificação. Com `amostra=true`, consulta alguns "
            "registros reais (aceitando filtros na query string) para descobrir as variáveis de fato "
            "retornadas e exemplos de valores."
        ),
    )
    async def variaveis(request: Request, dataset_id: str, amostra: bool = False):
        cat, ds = await _dataset(request.app, dataset_id)
        resposta: dict[str, Any] = {
            "dataset": ds.id,
            "documentadas": [{"nome": c.nome, "tipo": c.tipo, "descricao": c.descricao} for c in ds.campos],
            "filtros": [
                {"nome": p.nome, "obrigatorio": p.obrigatorio, "tipo": p.tipo, "descricao": p.descricao, "enum": p.enum}
                for p in ds.parametros
                if p not in (ds.param_limit, ds.param_offset) and p.nome != "campos"
            ],
        }
        if amostra or not ds.campos:
            filtros, _ = _separar_query(request)
            try:
                resposta["amostra"] = await amostrar_variaveis(
                    request.app.state.cliente, request.app.state.config, cat, ds, filtros
                )
            except ErroConsulta as exc:
                resposta["amostra"] = None
                resposta["aviso"] = f"Não foi possível amostrar: {exc} Informe os filtros na query string."
        return resposta

    @app.get(
        "/api/datasets/{dataset_id}/dados",
        tags=["Dados"],
        summary="Retorna os dados de uma base (filtros via query string)",
        description=(
            "Qualquer parâmetro da query string que não seja de controle é repassado como filtro para a "
            "API oficial (ex.: `?nu_ano=2024&id_municip=355030`). Filtros locais usam o prefixo "
            "`local.` (ex.: `local.sg_uf=SP`). Controle: `colunas` (separadas por vírgula), `formato` "
            "(json|csv|xlsx), `max_registros` (0 = todos), `paginar`, `separador`, `agrupar_por` e "
            "`somar` (separados por vírgula; ex.: `agrupar_por=ds_procedimento&somar=qt_procedimento`)."
        ),
    )
    async def dados_get(
        request: Request,
        dataset_id: str,
        colunas: str | None = Query(None, description="Variáveis a retornar, separadas por vírgula."),
        formato: Literal["json", "csv", "xlsx"] = "json",
        max_registros: int | None = Query(None, ge=0, description="0 = todos"),
        agrupar_por: str | None = Query(None, description="Variáveis categóricas, separadas por vírgula."),
        somar: str | None = Query(None, description="Variáveis numéricas a somar, separadas por vírgula."),
        paginar: bool = True,
        separador: str = Query(",", min_length=1, max_length=1),
    ):
        filtros, locais = _separar_query(request)

        def lista(texto: str | None) -> list[str]:
            return [c.strip() for c in (texto or "").split(",") if c.strip()]

        corpo = CorpoConsulta(
            filtros=filtros,
            colunas=lista(colunas) or None,
            agrupar_por=lista(agrupar_por),
            somar=lista(somar),
            filtros_locais=locais or None,
            max_registros=max_registros,
            paginar=paginar,
            formato=formato,
            separador=separador,
        )
        return await _consultar(request.app, dataset_id, corpo)

    @app.post(
        "/api/datasets/{dataset_id}/dados",
        tags=["Dados"],
        summary="Retorna os dados de uma base (filtros e variáveis no corpo JSON)",
    )
    async def dados_post(request: Request, dataset_id: str, corpo: CorpoConsulta):
        return await _consultar(request.app, dataset_id, corpo)

    return app


# ---------------------------------------------------------------------- #
# Auxiliares
# ---------------------------------------------------------------------- #


async def _obter_catalogo(app: FastAPI) -> Catalogo:
    if app.state.catalogo is not None:
        return app.state.catalogo
    async with app.state.trava:
        if app.state.catalogo is None:
            try:
                app.state.catalogo = await carregar_catalogo(app.state.config, app.state.cliente)
                app.state.erro_catalogo = None
            except ErroCatalogo as exc:
                app.state.erro_catalogo = str(exc)
                raise HTTPException(status_code=503, detail=str(exc)) from exc
    return app.state.catalogo


async def _dataset(app: FastAPI, dataset_id: str) -> tuple[Catalogo, Dataset]:
    cat = await _obter_catalogo(app)
    ds = cat.buscar(dataset_id)
    if ds is None:
        raise HTTPException(
            status_code=404, detail=f"Base '{dataset_id}' não encontrada. Consulte GET /api/datasets."
        )
    return cat, ds


def _separar_query(request: Request) -> tuple[dict[str, Any], dict[str, Any]]:
    filtros: dict[str, Any] = {}
    locais: dict[str, Any] = {}
    for chave in request.query_params.keys():
        if chave in PARAMS_CONTROLE:
            continue
        valores = request.query_params.getlist(chave)
        valor: Any = valores[0] if len(valores) == 1 else valores
        if chave.startswith(PREFIXO_LOCAL):
            locais[chave[len(PREFIXO_LOCAL):]] = valor
        else:
            filtros[chave] = valor
    return filtros, locais


async def _consultar(app: FastAPI, dataset_id: str, corpo: CorpoConsulta):
    cat, ds = await _dataset(app, dataset_id)
    resultado = await executar(
        app.state.cliente,
        app.state.config,
        cat,
        ds,
        Consulta(
            filtros=corpo.filtros,
            colunas=corpo.colunas,
            filtros_locais=corpo.filtros_locais,
            max_registros=corpo.max_registros,
            paginar=corpo.paginar,
            agrupar_por=corpo.agrupar_por,
            somar=corpo.somar,
        ),
    )
    if corpo.formato == "xlsx":
        return Response(
            content=para_xlsx(resultado),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{ds.id}.xlsx"',
                "X-Total-Registros": str(resultado.total),
            },
        )
    if corpo.formato == "csv":
        conteudo = (
            para_csv_agregado(resultado, corpo.separador)
            if resultado.agregado is not None
            else para_csv(resultado, corpo.separador)
        )
        return Response(
            content=conteudo,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{ds.id}.csv"',
                "X-Total-Registros": str(resultado.total),
            },
        )
    return resultado.como_dict()


app = criar_app()
