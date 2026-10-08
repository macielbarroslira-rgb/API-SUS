"""Catálogo de bases de dados montado a partir da especificação Swagger/OpenAPI oficial.

Nenhum endpoint é fixado no código: tudo (bases, filtros, colunas) vem da
especificação publicada pelo Ministério da Saúde, o que mantém o catálogo
atualizado quando a API ganha novas bases.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .cliente import ClienteDataSUS, ErroUpstream
from .config import Config

NOMES_LIMIT = ("limit", "limite", "tamanhopagina")
NOMES_OFFSET = ("offset", "pagina", "page")


class ErroCatalogo(Exception):
    pass


@dataclass
class Parametro:
    nome: str
    local: str  # "query" ou "path"
    obrigatorio: bool = False
    tipo: str = "string"
    formato: str | None = None
    descricao: str = ""
    enum: list[Any] | None = None
    padrao: Any = None
    minimo: float | None = None
    maximo: float | None = None


@dataclass
class Campo:
    nome: str
    tipo: str = ""
    descricao: str = ""


@dataclass
class Dataset:
    id: str
    caminho: str
    grupo: str
    resumo: str = ""
    descricao: str = ""
    operation_id: str | None = None
    parametros: list[Parametro] = field(default_factory=list)
    campos: list[Campo] = field(default_factory=list)
    chave_lista: str | None = None  # chave do JSON que contém a lista de registros

    @property
    def param_limit(self) -> Parametro | None:
        return next((p for p in self.parametros if p.local == "query" and p.nome.lower() in NOMES_LIMIT), None)

    @property
    def param_offset(self) -> Parametro | None:
        return next((p for p in self.parametros if p.local == "query" and p.nome.lower() in NOMES_OFFSET), None)

    @property
    def paginavel(self) -> bool:
        return self.param_limit is not None and self.param_offset is not None

    def parametro(self, nome: str) -> Parametro | None:
        return next((p for p in self.parametros if p.nome == nome), None)

    def resumo_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "grupo": self.grupo,
            "caminho": self.caminho,
            "resumo": self.resumo,
            "paginavel": self.paginavel,
            "qtd_filtros": len([p for p in self.parametros if p not in (self.param_limit, self.param_offset)]),
            "qtd_variaveis_documentadas": len(self.campos),
        }

    def detalhe_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["paginavel"] = self.paginavel
        d["parametro_limit"] = self.param_limit.nome if self.param_limit else None
        d["parametro_offset"] = self.param_offset.nome if self.param_offset else None
        return d


@dataclass
class Catalogo:
    spec: dict[str, Any]
    origem: str
    carregado_em: str
    datasets: dict[str, Dataset]

    @property
    def base_path(self) -> str:
        if "basePath" in self.spec:
            return (self.spec.get("basePath") or "").rstrip("/")
        return ""

    def buscar(self, identificador: str) -> Dataset | None:
        ident = identificador.strip()
        if ident in self.datasets:
            return self.datasets[ident]
        caminho = "/" + ident.strip("/")
        for ds in self.datasets.values():
            if ds.operation_id == ident or ds.caminho == caminho:
                return ds
        return None

    def listar(self, termo: str | None = None, grupo: str | None = None) -> list[Dataset]:
        itens = list(self.datasets.values())
        if grupo:
            g = _normalizar(grupo)
            itens = [d for d in itens if _normalizar(d.grupo) == g]
        if termo:
            t = _normalizar(termo)
            itens = [
                d
                for d in itens
                if t in _normalizar(" ".join([d.id, d.caminho, d.grupo, d.resumo, d.descricao]))
            ]
        return sorted(itens, key=lambda d: (d.grupo, d.caminho))

    def grupos(self) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for d in self.datasets.values():
            contagem[d.grupo] = contagem.get(d.grupo, 0) + 1
        return dict(sorted(contagem.items()))


# --------------------------------------------------------------------------- #
# Utilitários
# --------------------------------------------------------------------------- #


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sem_acento.lower()


def _slug(caminho: str) -> str:
    s = _normalizar(caminho).replace("{", "").replace("}", "")
    s = re.sub(r"[^a-z0-9_]+", "-", s).strip("-")
    return s or "raiz"


def _resolver(spec: dict[str, Any], obj: Any, _visitados: frozenset[str] = frozenset()) -> Any:
    """Segue referências "$ref" locais (#/...)."""
    while isinstance(obj, dict) and "$ref" in obj:
        ref = obj["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in _visitados:
            return {}
        _visitados = _visitados | {ref}
        alvo: Any = spec
        for parte in ref[2:].split("/"):
            parte = parte.replace("~1", "/").replace("~0", "~")
            if not isinstance(alvo, dict) or parte not in alvo:
                return {}
            alvo = alvo[parte]
        obj = alvo
    return obj


def _mesclar_allof(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if "allOf" not in schema:
        return schema
    props: dict[str, Any] = dict(schema.get("properties") or {})
    for parte in schema["allOf"]:
        parte = _mesclar_allof(spec, _resolver(spec, parte))
        props.update(parte.get("properties") or {})
    return {**schema, "type": "object", "properties": props}


def _campos_de_objeto(spec: dict[str, Any], schema: dict[str, Any]) -> list[Campo]:
    campos = []
    for nome, prop in (schema.get("properties") or {}).items():
        prop = _resolver(spec, prop)
        tipo = prop.get("type", "") if isinstance(prop, dict) else ""
        if isinstance(tipo, list):
            tipo = "/".join(str(t) for t in tipo)
        if isinstance(prop, dict) and prop.get("format"):
            tipo = f"{tipo} ({prop['format']})" if tipo else prop["format"]
        desc = (prop.get("description") or prop.get("title") or "") if isinstance(prop, dict) else ""
        campos.append(Campo(nome=nome, tipo=tipo, descricao=desc))
    return campos


def _extrair_campos(spec: dict[str, Any], schema: Any) -> tuple[str | None, list[Campo]]:
    """Descobre as colunas a partir do schema de resposta.

    Retorna (chave_lista, campos). chave_lista é o nome da propriedade que
    envelopa a lista de registros, ex.: {"dengue": [...]} -> "dengue".
    """
    schema = _resolver(spec, schema)
    if not isinstance(schema, dict):
        return None, []
    schema = _mesclar_allof(spec, schema)

    if schema.get("type") == "array" or "items" in schema:
        item = _mesclar_allof(spec, _resolver(spec, schema.get("items") or {}))
        return None, _campos_de_objeto(spec, item) if isinstance(item, dict) else []

    props = schema.get("properties") or {}
    for nome, prop in props.items():
        prop = _resolver(spec, prop)
        if isinstance(prop, dict) and (prop.get("type") == "array" or "items" in prop):
            item = _mesclar_allof(spec, _resolver(spec, prop.get("items") or {}))
            if isinstance(item, dict) and item.get("properties"):
                return nome, _campos_de_objeto(spec, item)
    return None, _campos_de_objeto(spec, schema)


def _schema_resposta(op: dict[str, Any]) -> Any:
    respostas = op.get("responses") or {}
    resp = respostas.get("200") or respostas.get(200) or respostas.get("default") or {}
    if "schema" in resp:  # Swagger 2
        return resp["schema"]
    conteudo = resp.get("content") or {}  # OpenAPI 3
    for mime, corpo in conteudo.items():
        if "json" in mime and isinstance(corpo, dict) and "schema" in corpo:
            return corpo["schema"]
    for corpo in conteudo.values():
        if isinstance(corpo, dict) and "schema" in corpo:
            return corpo["schema"]
    return None


_RE_MAXIMO = re.compile(r"(?:menor ou igual(?: a)?|m[áa]ximo:?|at[ée])\s*(\d+)", re.IGNORECASE)


def _maximo_da_descricao(descricao: str) -> int | None:
    """A especificação oficial informa o tamanho máximo de página só no texto,
    ex.: "Deve ser menor ou igual 20." ou "(máximo: 500)"."""
    m = _RE_MAXIMO.search(descricao or "")
    return int(m.group(1)) if m else None


def _parametro(spec: dict[str, Any], bruto: Any) -> Parametro | None:
    p = _resolver(spec, bruto)
    if not isinstance(p, dict) or p.get("in") not in ("query", "path"):
        return None
    schema = _resolver(spec, p.get("schema") or {})  # OpenAPI 3 guarda o tipo em "schema"
    fonte = schema if isinstance(schema, dict) and schema else p
    maximo = fonte.get("maximum", p.get("maximum"))
    if maximo is None and str(p["name"]).lower() in NOMES_LIMIT:
        maximo = _maximo_da_descricao(p.get("description") or "")
    return Parametro(
        nome=p["name"],
        local=p["in"],
        obrigatorio=bool(p.get("required")) or p["in"] == "path",
        tipo=str(fonte.get("type") or p.get("type") or "string"),
        formato=fonte.get("format") or p.get("format"),
        descricao=p.get("description") or "",
        enum=fonte.get("enum") or p.get("enum"),
        padrao=fonte.get("default", p.get("default")),
        minimo=fonte.get("minimum", p.get("minimum")),
        maximo=maximo,
    )


def montar_datasets(spec: dict[str, Any]) -> dict[str, Dataset]:
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ErroCatalogo("Especificação inválida: campo 'paths' ausente.")

    datasets: dict[str, Dataset] = {}
    for caminho, item in spec["paths"].items():
        item = _resolver(spec, item)
        if not isinstance(item, dict):
            continue
        op = item.get("get")
        if not isinstance(op, dict):
            continue

        params_brutos: dict[tuple[str, str], Any] = {}
        for bruto in list(item.get("parameters") or []) + list(op.get("parameters") or []):
            p = _parametro(spec, bruto)
            if p:
                params_brutos[(p.local, p.nome)] = p  # o da operação sobrescreve o do caminho
        chave_lista, campos = _extrair_campos(spec, _schema_resposta(op))

        tags = op.get("tags") or []
        grupo = tags[0] if tags else (caminho.strip("/").split("/")[0] or "geral")

        ident = _slug(caminho)
        if ident in datasets:
            n = 2
            while f"{ident}-{n}" in datasets:
                n += 1
            ident = f"{ident}-{n}"

        datasets[ident] = Dataset(
            id=ident,
            caminho=caminho,
            grupo=grupo,
            resumo=(op.get("summary") or "").strip(),
            descricao=(op.get("description") or "").strip(),
            operation_id=op.get("operationId"),
            parametros=list(params_brutos.values()),
            campos=campos,
            chave_lista=chave_lista,
        )
    if not datasets:
        raise ErroCatalogo("A especificação não contém nenhuma operação GET.")
    return datasets


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def carregar_catalogo(config: Config, cliente: ClienteDataSUS) -> Catalogo:
    """Carrega a especificação: arquivo local -> URLs oficiais -> cópia em cache."""
    tentativas: list[str] = []

    if config.spec_arquivo:
        try:
            spec = json.loads(Path(config.spec_arquivo).read_text(encoding="utf-8"))
            return Catalogo(spec, f"arquivo:{config.spec_arquivo}", _agora(), montar_datasets(spec))
        except (OSError, ValueError, ErroCatalogo) as exc:
            tentativas.append(f"{config.spec_arquivo}: {exc}")

    for url in config.spec_urls:
        try:
            spec = await cliente.get_json(url, usar_cache=False)
            datasets = montar_datasets(spec)
        except (ErroUpstream, ErroCatalogo) as exc:
            tentativas.append(f"{url}: {getattr(exc, 'mensagem', exc)}")
            continue
        try:
            config.spec_cache.parent.mkdir(parents=True, exist_ok=True)
            config.spec_cache.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return Catalogo(spec, url, _agora(), datasets)

    if config.spec_cache.exists():
        try:
            spec = json.loads(config.spec_cache.read_text(encoding="utf-8"))
            return Catalogo(spec, f"cache:{config.spec_cache}", _agora(), montar_datasets(spec))
        except (OSError, ValueError, ErroCatalogo) as exc:
            tentativas.append(f"{config.spec_cache}: {exc}")

    raise ErroCatalogo(
        "Não foi possível carregar a especificação da API de Dados Abertos. Tentativas: "
        + " | ".join(tentativas)
    )


def montar_url(config: Config, catalogo: Catalogo, dataset: Dataset, valores_path: dict[str, Any]) -> str:
    caminho = dataset.caminho
    for nome, valor in valores_path.items():
        caminho = caminho.replace("{" + nome + "}", quote(str(valor), safe=""))
    base = config.base_url + (catalogo.base_path if config.respeitar_basepath else "")
    return base + caminho
