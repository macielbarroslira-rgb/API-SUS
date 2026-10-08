"""Uso pelo terminal, sem subir o servidor.

    python -m app.cli bases [--busca dengue]
    python -m app.cli variaveis arboviroses-dengue [--amostra -f nu_ano=2024]
    python -m app.cli dados arboviroses-dengue -f nu_ano=2024 -c dt_notific,id_municip -n 500 -o dengue.csv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .catalogo import ErroCatalogo, carregar_catalogo
from .cliente import ClienteDataSUS, ErroUpstream
from .config import Config
from .consulta import Consulta, ErroConsulta, amostrar_variaveis, executar, para_csv


def _filtros(pares: list[str]) -> dict[str, Any]:
    saida: dict[str, Any] = {}
    for par in pares:
        if "=" not in par:
            raise SystemExit(f"Filtro inválido '{par}'. Use nome=valor.")
        nome, valor = par.split("=", 1)
        saida[nome.strip()] = valor.strip()
    return saida


async def _rodar(args: argparse.Namespace) -> int:
    config = Config.do_ambiente()
    cliente = ClienteDataSUS(config)
    try:
        catalogo = await carregar_catalogo(config, cliente)
        if args.comando == "bases":
            for ds in catalogo.listar(args.busca, args.grupo):
                print(f"{ds.id:55} {ds.grupo:30} {ds.resumo}")
            return 0

        ds = catalogo.buscar(args.base)
        if ds is None:
            print(f"Base '{args.base}' não encontrada. Rode: python -m app.cli bases", file=sys.stderr)
            return 1

        if args.comando == "variaveis":
            print("Filtros:")
            for p in ds.parametros:
                print(f"  {p.nome:30} {p.tipo:10} {'(obrigatório) ' if p.obrigatorio else ''}{p.descricao}")
            print("Variáveis documentadas:")
            for c in ds.campos:
                print(f"  {c.nome:30} {c.tipo:15} {c.descricao}")
            if args.amostra or not ds.campos:
                amostra = await amostrar_variaveis(cliente, config, catalogo, ds, _filtros(args.filtro))
                print("Variáveis encontradas na amostra:")
                for nome in amostra["variaveis"]:
                    print(f"  {nome:30} ex.: {amostra['exemplos'].get(nome, '')}")
            return 0

        resultado = await executar(
            cliente,
            config,
            catalogo,
            ds,
            Consulta(
                filtros=_filtros(args.filtro),
                colunas=[c.strip() for c in args.colunas.split(",")] if args.colunas else None,
                max_registros=args.max_registros,
            ),
        )
        for aviso in resultado.avisos:
            print(f"aviso: {aviso}", file=sys.stderr)
        destino = Path(args.saida) if args.saida else None
        if destino and destino.suffix.lower() == ".csv":
            destino.write_text(para_csv(resultado, args.separador), encoding="utf-8")
        else:
            texto = json.dumps(resultado.como_dict(), ensure_ascii=False, indent=2, default=str)
            if destino:
                destino.write_text(texto, encoding="utf-8")
            else:
                print(texto)
        print(f"{resultado.total} registro(s), {resultado.paginas_consultadas} página(s).", file=sys.stderr)
        return 0
    except (ErroCatalogo, ErroConsulta) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    except ErroUpstream as exc:
        print(f"erro na API oficial: {exc.mensagem}", file=sys.stderr)
        return 3
    finally:
        await cliente.fechar()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("bases", help="lista as bases disponíveis")
    p.add_argument("--busca")
    p.add_argument("--grupo")

    p = sub.add_parser("variaveis", help="mostra filtros e variáveis de uma base")
    p.add_argument("base")
    p.add_argument("--amostra", action="store_true", help="consulta registros reais para descobrir variáveis")
    p.add_argument("-f", "--filtro", action="append", default=[], help="nome=valor (repetível)")

    p = sub.add_parser("dados", help="baixa os dados de uma base")
    p.add_argument("base")
    p.add_argument("-f", "--filtro", action="append", default=[], help="nome=valor (repetível)")
    p.add_argument("-c", "--colunas", help="variáveis separadas por vírgula")
    p.add_argument("-n", "--max-registros", type=int)
    p.add_argument("-o", "--saida", help="arquivo .csv ou .json (padrão: imprime JSON)")
    p.add_argument("--separador", default=",")

    return asyncio.run(_rodar(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
