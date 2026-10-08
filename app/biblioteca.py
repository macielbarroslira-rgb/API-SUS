"""Downloads de bases completas para o computador (pasta de dados do app local).

Cada download percorre todas as páginas da API oficial, grava os registros em disco à medida
que chegam (NDJSON, sem acumular na memória) e, no fim, converte tudo para Parquet com o DuckDB:

    bases/<nome>.parquet   dados (todas as colunas como texto; colunas aninhadas achatadas, ex.: "endereco.uf")
    bases/<nome>.json      metadados (base de origem, filtros, registros, colunas, avisos...)

Arquivos temporários terminam em ".parcial" e são apagados se o download falhar ou for cancelado.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .catalogo import Catalogo, Dataset
from .cliente import ClienteDataSUS, ErroUpstream
from .config import Config
from .consulta import Consulta, ErroConsulta, Resultado, executar, validar_filtros

log = logging.getLogger("api_sus")

RE_NOME_BASE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
TAMANHO_NOME = 80
PARCIAL = ".parcial"
MAX_SIMULTANEOS = 2
HISTORICO_MAX = 200  # downloads terminados guardados na memória

# Um download pode buscar a base inteira, bem além dos limites das consultas comuns.
MAX_REGISTROS_DOWNLOAD = 50_000_000
MAX_PAGINAS_DOWNLOAD = 500_000

ATIVOS = frozenset({"na_fila", "baixando", "convertendo"})
NENHUM_REGISTRO = "Nenhum registro encontrado"


class ErroDownload(Exception):
    """Falha durante o download, com mensagem pronta para o usuário."""


# --------------------------------------------------------------------------- #
# Nomes das bases
# --------------------------------------------------------------------------- #


def pasta_bases(config: Config) -> Path:
    return Path(config.pasta_dados) / "bases"


def slug(texto: Any) -> str:
    """"Dengue São Paulo!" -> "dengue-sao-paulo" (sem acento, minúsculas, só [a-z0-9_-])."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9_-]+", "-", sem_acento).strip("-_")


def _encurtar(nome: str, tamanho: int = TAMANHO_NOME) -> str:
    return nome[:tamanho].rstrip("-_")


def nome_padrao(dataset_id: str, filtros: dict[str, Any]) -> str:
    """Nome da base a partir da base de origem e dos filtros, ex.: "arboviroses-dengue__nu_ano-2024"."""
    partes = [slug(dataset_id) or "base"]
    for chave, valor in filtros.items():
        valores = valor if isinstance(valor, list) else [valor]
        texto = slug("-".join(str(v) for v in valores))
        partes.append(f"{slug(chave)}-{texto}".strip("-") if texto else slug(chave))
    return _encurtar("__".join(p for p in partes if p)) or "base"


def normalizar_nome(nome: str) -> str:
    """Normaliza o nome escolhido pelo usuário para um nome de base válido."""
    normalizado = _encurtar(slug(nome))
    if not RE_NOME_BASE.fullmatch(normalizado):
        raise ErroConsulta(
            f"Nome de base inválido: '{nome}'. Use letras, números, '-' ou '_' (até {TAMANHO_NOME} caracteres)."
        )
    return normalizado


def _limpar_filtros(filtros: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (filtros or {}).items() if v is not None and v != "" and v != []}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _apagar(*caminhos: Path) -> None:
    for caminho in caminhos:
        with contextlib.suppress(OSError):
            caminho.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Gravação em disco
# --------------------------------------------------------------------------- #


def _texto(valor: Any) -> str | None:
    """Todas as colunas da base local são texto; None continua nulo."""
    if valor is None or isinstance(valor, str):
        return valor
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


class GravadorNdjson:
    """Consumidor de executar(): grava cada lote como NDJSON e acumula a união ordenada das colunas."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.colunas: list[str] = []
        self.registros = 0
        self.avisos: list[str] = []
        self._mapa: dict[str, str] = {}  # nome original -> nome gravado
        self._minusculas: set[str] = set()
        self._arquivo = caminho.open("w", encoding="utf-8", newline="\n")

    def __call__(self, lote: list[dict[str, Any]]) -> None:
        linhas = [
            json.dumps({self._coluna(k): _texto(v) for k, v in registro.items()}, ensure_ascii=False)
            for registro in lote
        ]
        if linhas:
            self._arquivo.write("\n".join(linhas) + "\n")
            self.registros += len(linhas)

    def fechar(self) -> None:
        self._arquivo.close()

    def _coluna(self, original: str) -> str:
        final = self._mapa.get(original)
        if final is not None:
            return final
        final = original if original.strip() else "sem_nome"
        # O DuckDB não diferencia maiúsculas de minúsculas em nomes de colunas ("Nome" = "nome").
        if final.lower() in self._minusculas:
            n = 2
            while f"{final}_{n}".lower() in self._minusculas:
                n += 1
            final = f"{final}_{n}"
        if final != original:
            self.avisos.append(f"A coluna '{original}' foi gravada como '{final}' (nome repetido ou vazio).")
        self._mapa[original] = final
        self._minusculas.add(final.lower())
        self.colunas.append(final)
        return final


def ndjson_para_parquet(origem: Path, destino: Path, colunas: list[str], conexao: Any = None) -> None:
    """Converte o NDJSON gravado para Parquet (todas as colunas VARCHAR, na ordem de ``colunas``)."""
    import duckdb

    con = conexao if conexao is not None else duckdb.connect(":memory:")
    try:
        relacao = con.read_json(
            str(origem), format="newline_delimited", columns={c: "VARCHAR" for c in colunas}
        )
        relacao.write_parquet(str(destino), compression="zstd")
    finally:
        con.close()


class _ClienteSemCache:
    """Repassa as chamadas ao cliente do app sem guardar as páginas no cache de respostas
    (num download grande, o cache só ocuparia memória: cada página é lida uma única vez)."""

    def __init__(self, cliente: ClienteDataSUS):
        self._cliente = cliente

    async def get_json(self, url: str, params: dict[str, Any] | None = None, usar_cache: bool = True) -> Any:
        return await self._cliente.get_json(url, params, usar_cache=False)


# --------------------------------------------------------------------------- #
# Gerenciador
# --------------------------------------------------------------------------- #


@dataclass
class Download:
    id: str
    dataset: str
    nome: str
    filtros: dict[str, Any]
    status: str = "na_fila"
    paginas: int = 0
    registros: int = 0
    iniciado_em: str = field(default_factory=_agora)
    terminado_em: str | None = None
    erro: str | None = None
    avisos: list[str] = field(default_factory=list)
    tarefa: asyncio.Task | None = field(default=None, repr=False)

    @property
    def ativo(self) -> bool:
        return self.status in ATIVOS

    @property
    def reservando_nome(self) -> bool:
        """Ativo, ou cancelado mas ainda apagando os arquivos parciais."""
        return self.ativo or (self.tarefa is not None and not self.tarefa.done())

    def como_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dataset": self.dataset,
            "nome": self.nome,
            "filtros": self.filtros,
            "status": self.status,
            "paginas": self.paginas,
            "registros": self.registros,
            "iniciado_em": self.iniciado_em,
            "terminado_em": self.terminado_em,
            "erro": self.erro,
            "avisos": list(self.avisos),
        }


class GerenciadorDownloads:
    """Fila de downloads de bases (até MAX_SIMULTANEOS ao mesmo tempo), com estado em memória."""

    def __init__(
        self,
        config: Config,
        cliente: ClienteDataSUS,
        obter_catalogo: Callable[[], Awaitable[Catalogo]],
    ):
        self.config = config
        self.cliente = cliente
        self._obter_catalogo = obter_catalogo
        self._config_grande = dataclasses.replace(
            config, max_registros_teto=MAX_REGISTROS_DOWNLOAD, max_paginas_teto=MAX_PAGINAS_DOWNLOAD
        )
        self._semaforo = asyncio.Semaphore(MAX_SIMULTANEOS)
        self._downloads: dict[str, Download] = {}
        self.pasta = pasta_bases(config)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._apagar_parciais_esquecidos()

    # ------------------------------------------------------------------ #
    # API pública

    async def iniciar(
        self, dataset_id: str, filtros: dict[str, Any] | None = None, nome: str | None = None
    ) -> dict[str, Any]:
        """Valida o pedido e põe o download na fila.

        Levanta LookupError se a base não existe e ErroConsulta se os filtros ou o nome são inválidos.
        """
        catalogo = await self._obter_catalogo()
        ds = catalogo.buscar(dataset_id)
        if ds is None:
            raise LookupError(f"Base '{dataset_id}' não encontrada. Consulte GET /api/datasets.")
        filtros = _limpar_filtros(filtros)
        validar_filtros(ds, filtros)
        if nome and nome.strip():
            base = normalizar_nome(nome)
        else:  # tamanho de página e posição inicial não entram no nome
            controle = {p.nome for p in (ds.param_limit, ds.param_offset) if p}
            base = nome_padrao(ds.id, {k: v for k, v in filtros.items() if k not in controle})

        d = Download(id=self._novo_id(), dataset=ds.id, nome=self._nome_livre(base), filtros=filtros)
        self._downloads[d.id] = d
        d.tarefa = asyncio.create_task(self._baixar(d, catalogo, ds), name=f"download-{d.nome}")
        self._podar_historico()
        log.info("Download %s na fila: %s -> %s", d.id, ds.id, d.nome)
        return d.como_dict()

    def listar(self) -> list[dict[str, Any]]:
        """Downloads desta sessão, mais recentes primeiro."""
        return [d.como_dict() for d in reversed(self._downloads.values())]

    def obter(self, download_id: str) -> dict[str, Any]:
        return self._buscar(download_id).como_dict()

    def cancelar(self, download_id: str) -> dict[str, Any]:
        """Cancela o download se ainda estiver em andamento (os arquivos parciais são apagados)."""
        d = self._buscar(download_id)
        if d.ativo:
            d.status, d.terminado_em = "cancelado", _agora()
            if d.tarefa is not None and not d.tarefa.done():
                d.tarefa.cancel()
        return d.como_dict()

    async def aguardar(self, download_id: str, timeout: float | None = None) -> dict[str, Any]:
        """Espera o download terminar (ou o tempo esgotar) e devolve o estado atual."""
        d = self._buscar(download_id)
        if d.tarefa is not None and not d.tarefa.done():
            await asyncio.wait({d.tarefa}, timeout=timeout)
        return d.como_dict()

    async def fechar(self) -> None:
        """Cancela todos os downloads em andamento e espera a limpeza dos arquivos parciais."""
        pendentes = [d.tarefa for d in self._downloads.values() if d.tarefa is not None and not d.tarefa.done()]
        for d in list(self._downloads.values()):
            self.cancelar(d.id)
        if pendentes:
            await asyncio.gather(*pendentes, return_exceptions=True)

    # ------------------------------------------------------------------ #
    # Execução

    async def _baixar(self, d: Download, catalogo: Catalogo, ds: Dataset) -> None:
        ndjson = self.pasta / f"{d.nome}.ndjson{PARCIAL}"
        try:
            async with self._semaforo:
                d.status = "baixando"
                gravador = GravadorNdjson(ndjson)

                def consumir(lote: list[dict[str, Any]]) -> None:
                    gravador(lote)
                    d.registros = gravador.registros

                def progresso(paginas: int, _buscados: int) -> None:
                    d.paginas = paginas

                try:
                    resultado = await executar(
                        _ClienteSemCache(self.cliente),  # type: ignore[arg-type]
                        self._config_grande,
                        catalogo,
                        ds,
                        Consulta(filtros=d.filtros, max_registros=0),
                        consumidor=consumir,
                        progresso=progresso,
                    )
                finally:
                    gravador.fechar()
                d.paginas, d.registros = resultado.paginas_consultadas, gravador.registros
                d.avisos = [*resultado.avisos, *gravador.avisos]

                if gravador.registros == 0:
                    _apagar(ndjson)
                    d.avisos.append(NENHUM_REGISTRO)
                    self._terminar(d, "concluido")
                    return

                d.status = "convertendo"
                await self._converter(ndjson, self._arquivo(d, ".parquet" + PARCIAL), gravador.colunas)
                self._publicar(d, ds, resultado, gravador.colunas)
                _apagar(ndjson)
                self._terminar(d, "concluido")
                log.info("Download %s concluído: %s (%d registros)", d.id, d.nome, d.registros)
        except asyncio.CancelledError:
            self._apagar_parciais(d)
            self._terminar(d, "cancelado")
            log.info("Download %s cancelado: %s", d.id, d.nome)
            raise
        except Exception as exc:  # noqa: BLE001 - o erro vira o status do download
            esperado = isinstance(exc, (ErroUpstream, ErroConsulta, ErroDownload, OSError))
            log.warning("Download %s falhou: %s", d.id, exc, exc_info=not esperado)
            self._apagar_parciais(d)
            d.erro = _mensagem_erro(exc)
            self._terminar(d, "erro")

    async def _converter(self, origem: Path, destino: Path, colunas: list[str]) -> None:
        """Roda a conversão numa thread; se o download for cancelado, interrompe o DuckDB."""
        try:
            import duckdb
        except ImportError as exc:
            raise ErroDownload("O pacote 'duckdb' não está instalado (pip install duckdb).") from exc

        con = duckdb.connect(":memory:")
        trabalho = asyncio.ensure_future(asyncio.to_thread(ndjson_para_parquet, origem, destino, colunas, con))
        try:
            await asyncio.shield(trabalho)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                con.interrupt()
            # espera a thread soltar os arquivos antes de apagá-los
            await asyncio.wait({trabalho})
            with contextlib.suppress(BaseException):
                trabalho.result()
            raise
        except Exception as exc:
            raise ErroDownload(f"Falha ao converter os dados baixados para Parquet: {exc}") from exc

    def _publicar(self, d: Download, ds: Dataset, resultado: Resultado, colunas: list[str]) -> None:
        """Grava os metadados e troca os arquivos parciais pelos definitivos."""
        metadados = {
            "nome": d.nome,
            "dataset": ds.id,
            "titulo": ds.resumo or ds.id,
            "filtros": d.filtros,
            "registros": d.registros,
            "colunas": colunas,
            "baixado_em": _agora(),
            "url_origem": resultado.url,
            "avisos": d.avisos,
            "paginas": resultado.paginas_consultadas,
        }
        json_parcial = self._arquivo(d, ".json" + PARCIAL)
        json_parcial.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")
        parquet = self._arquivo(d, ".parquet")
        self._arquivo(d, ".parquet" + PARCIAL).replace(parquet)
        try:
            json_parcial.replace(self._arquivo(d, ".json"))
        except OSError:
            _apagar(parquet)  # sem metadados a base ficaria invisível
            raise

    # ------------------------------------------------------------------ #
    # Auxiliares

    def _arquivo(self, d: Download, extensao: str) -> Path:
        return self.pasta / f"{d.nome}{extensao}"

    def _apagar_parciais(self, d: Download) -> None:
        _apagar(*(self._arquivo(d, ext + PARCIAL) for ext in (".ndjson", ".parquet", ".json")))

    def _apagar_parciais_esquecidos(self) -> None:
        for caminho in self.pasta.glob(f"*{PARCIAL}"):
            _apagar(caminho)

    @staticmethod
    def _terminar(d: Download, status: str) -> None:
        d.status, d.terminado_em = status, _agora()

    def _buscar(self, download_id: str) -> Download:
        d = self._downloads.get(download_id)
        if d is None:
            raise LookupError(f"Download '{download_id}' não encontrado.")
        return d

    def _novo_id(self) -> str:
        while True:
            ident = secrets.token_hex(6)
            if ident not in self._downloads:
                return ident

    def _ocupado(self, nome: str) -> bool:
        if (self.pasta / f"{nome}.parquet").exists() or (self.pasta / f"{nome}.json").exists():
            return True
        return any(d.nome == nome and d.reservando_nome for d in self._downloads.values())

    def _nome_livre(self, base: str) -> str:
        """O próprio nome, ou com "-2", "-3"... se já houver base ou download com ele."""
        if not self._ocupado(base):
            return base
        n = 2
        while True:
            sufixo = f"-{n}"
            nome = _encurtar(base, TAMANHO_NOME - len(sufixo)) + sufixo
            if not self._ocupado(nome):
                return nome
            n += 1

    def _podar_historico(self) -> None:
        terminados = [d for d in self._downloads.values() if not d.reservando_nome]
        for d in terminados[: max(0, len(terminados) - HISTORICO_MAX)]:
            del self._downloads[d.id]


def _mensagem_erro(exc: Exception) -> str:
    if isinstance(exc, ErroUpstream):
        return exc.mensagem
    if isinstance(exc, (ErroConsulta, ErroDownload)):
        return str(exc)
    if isinstance(exc, OSError):
        motivo = exc.strerror or str(exc)
        return (
            f"Não foi possível gravar a base na pasta de dados ({motivo}). "
            "Verifique o espaço livre em disco e as permissões da pasta."
        )
    return f"Erro inesperado durante o download ({type(exc).__name__}: {exc})."
