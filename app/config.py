"""Configuração via variáveis de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


def _bool(valor: str | None, padrao: bool) -> bool:
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _lista(valor: str | None, padrao: list[str]) -> list[str]:
    if not valor:
        return padrao
    return [item.strip() for item in valor.split(",") if item.strip()]


@dataclass
class Config:
    # Host dos dados. Os endpoints de dados respondem SEM o prefixo /v1
    # (o /v1/ é só a página do Swagger UI).
    base_url: str = "https://apidadosabertos.saude.gov.br"

    # Onde procurar a especificação Swagger/OpenAPI (tentadas em ordem).
    spec_urls: list[str] = field(
        default_factory=lambda: ["https://apidadosabertos.saude.gov.br/static/swagger.json"]
    )
    # Arquivo local com a especificação (tem prioridade sobre as URLs, se existir).
    spec_arquivo: Path | None = None
    # Cópia da última especificação baixada com sucesso (usada se o site cair).
    spec_cache: Path = RAIZ_PROJETO / "data" / "swagger_cache.json"
    # Concatenar o basePath declarado na especificação à base_url.
    respeitar_basepath: bool = False

    timeout: float = 60.0
    tentativas: int = 3
    cache_ttl: int = 300  # segundos; 0 desliga o cache de respostas

    # Paginação: "pagina" => offset é o número da página (0, 1, 2...);
    # "registro" => offset é o índice do primeiro registro (0, 20, 40...).
    modo_offset: str = "pagina"
    tamanho_pagina_padrao: int = 20
    max_registros_padrao: int = 1000
    max_registros_teto: int = 100_000
    max_paginas_teto: int = 5_000
    # Acima disso, os dados detalhados não são guardados (o resumo agregado continua).
    max_linhas_detalhe: int = 1_000_000
    pausa_entre_paginas: float = 0.0

    cors_origens: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def do_ambiente(cls) -> "Config":
        cfg = cls()
        env = os.environ
        cfg.base_url = env.get("DATASUS_BASE_URL", cfg.base_url).rstrip("/")
        cfg.spec_urls = _lista(env.get("DATASUS_SPEC_URLS"), cfg.spec_urls)
        if env.get("DATASUS_SPEC_ARQUIVO"):
            cfg.spec_arquivo = Path(env["DATASUS_SPEC_ARQUIVO"])
        if env.get("DATASUS_SPEC_CACHE"):
            cfg.spec_cache = Path(env["DATASUS_SPEC_CACHE"])
        cfg.respeitar_basepath = _bool(env.get("DATASUS_RESPEITAR_BASEPATH"), cfg.respeitar_basepath)
        cfg.timeout = float(env.get("DATASUS_TIMEOUT", cfg.timeout))
        cfg.tentativas = int(env.get("DATASUS_TENTATIVAS", cfg.tentativas))
        cfg.cache_ttl = int(env.get("DATASUS_CACHE_TTL", cfg.cache_ttl))
        cfg.modo_offset = env.get("DATASUS_MODO_OFFSET", cfg.modo_offset).strip().lower()
        if cfg.modo_offset not in {"pagina", "registro"}:
            raise ValueError("DATASUS_MODO_OFFSET deve ser 'pagina' ou 'registro'")
        cfg.tamanho_pagina_padrao = int(env.get("DATASUS_TAMANHO_PAGINA", cfg.tamanho_pagina_padrao))
        cfg.max_registros_padrao = int(env.get("DATASUS_MAX_REGISTROS", cfg.max_registros_padrao))
        cfg.max_registros_teto = int(env.get("DATASUS_MAX_REGISTROS_TETO", cfg.max_registros_teto))
        cfg.max_linhas_detalhe = int(env.get("DATASUS_MAX_LINHAS_DETALHE", cfg.max_linhas_detalhe))
        cfg.pausa_entre_paginas = float(env.get("DATASUS_PAUSA_ENTRE_PAGINAS", cfg.pausa_entre_paginas))
        cfg.cors_origens = _lista(env.get("CORS_ORIGENS"), cfg.cors_origens)
        return cfg
