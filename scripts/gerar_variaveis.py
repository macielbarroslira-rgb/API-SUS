"""Consulta 1 registro de cada base para descobrir as variáveis (colunas) reais.

A especificação oficial não documenta as colunas, então elas são descobertas
na prática. Resultado: docs/variaveis.json (usado pela página web).

    python scripts/gerar_variaveis.py docs/swagger.json docs/variaveis.json
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalogo import Catalogo, montar_datasets  # noqa: E402
from app.cliente import ClienteDataSUS, ErroUpstream  # noqa: E402
from app.config import Config  # noqa: E402
from app.consulta import Consulta, ErroConsulta, executar  # noqa: E402


async def main(spec_path: str, saida: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    config = Config(cache_ttl=0, timeout=90, tentativas=2)
    catalogo = Catalogo(spec, spec_path, "", montar_datasets(spec))
    cliente = ClienteDataSUS(config)
    trava = asyncio.Semaphore(4)
    resultado: dict[str, dict] = {}

    async def amostrar(ds):
        if any(p.local == "path" for p in ds.parametros):
            resultado[ds.id] = {"erro": "base consultada por código (parâmetro no caminho)"}
            return
        filtros = {ds.param_limit.nome: 1} if ds.param_limit else {}
        async with trava:
            try:
                res = await executar(
                    cliente, config, catalogo, ds, Consulta(filtros=filtros, max_registros=1, paginar=False)
                )
                resultado[ds.id] = {"variaveis": res.colunas}
            except (ErroUpstream, ErroConsulta) as exc:
                resultado[ds.id] = {"erro": str(getattr(exc, "mensagem", exc))[:300]}
        print(f"{ds.id}: {resultado[ds.id]}", flush=True)

    await asyncio.gather(*(amostrar(ds) for ds in catalogo.datasets.values()))
    await cliente.fechar()
    Path(saida).write_text(
        json.dumps(
            {"gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bases": dict(sorted(resultado.items()))},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    ok = sum(1 for r in resultado.values() if "variaveis" in r)
    print(f"{ok}/{len(resultado)} bases com variáveis descobertas.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
