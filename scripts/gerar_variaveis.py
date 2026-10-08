"""Descobre as variáveis (colunas) reais de cada base e testa se a paginação funciona.

A especificação oficial não documenta as colunas, então elas são descobertas
na prática (1 registro). A paginação é testada pedindo 2 páginas de 50:
algumas bases da API oficial devolvem páginas incompletas ou repetidas, e
somas feitas sobre elas sairiam incompletas. Resultado: docs/variaveis.json.

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
from app.consulta import Consulta, ErroConsulta, executar, extrair_registros  # noqa: E402
from app.catalogo import montar_url  # noqa: E402


async def testar_paginacao(cliente, config, catalogo, ds) -> dict:
    """ok: paginação normal. incompleta: página curta seguida de mais dados.
    repetida: páginas diferentes devolvem o mesmo conteúdo."""
    lim, off = ds.param_limit, ds.param_offset
    if not (lim and off):
        return {"paginacao": "sem paginação"}
    tamanho = min(50, int(lim.maximo or 50))
    inicio = int(off.padrao or 0)
    url = montar_url(config, catalogo, ds, {})
    p0 = extrair_registros(await cliente.get_json(url, {lim.nome: tamanho, off.nome: inicio}), ds.chave_lista)
    p1 = extrair_registros(await cliente.get_json(url, {lim.nome: tamanho, off.nome: inicio + 1}), ds.chave_lista)
    if p0 and p1 and p0 == p1:
        estado = "repetida"
    elif 0 < len(p0) < tamanho and p1:
        estado = "incompleta"
    else:
        estado = "ok"
    return {"paginacao": estado, "teste_paginacao": f"pedidos {tamanho}: página 1 = {len(p0)}, página 2 = {len(p1)}"}


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
                resultado[ds.id].update(await testar_paginacao(cliente, config, catalogo, ds))
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
    for estado in ("ok", "incompleta", "repetida", "sem paginação"):
        ids = [k for k, r in resultado.items() if r.get("paginacao") == estado]
        print(f"paginação {estado}: {len(ids)} {ids if estado != 'ok' else ''}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
