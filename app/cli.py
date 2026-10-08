"""Uso pelo terminal, sem subir o servidor.

    python -m app.cli bases [--busca dengue]
    python -m app.cli variaveis arboviroses-dengue [--amostra -f nu_ano=2024]
    python -m app.cli dados arboviroses-dengue -f nu_ano=2024 -c dt_notific,id_municip -n 500 -o dengue.csv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .catalogo import ErroCatalogo, carregar_catalogo
from .cliente import ClienteDataSUS, ErroUpstream
from .config import Config
from .consulta import (
    Consulta,
    ErroConsulta,
    achatar,
    amostrar_variaveis,
    executar,
    para_csv,
    para_csv_agregado,
    para_xlsx,
)


def _lista(texto: str | None) -> list[str]:
    return [c.strip() for c in (texto or "").split(",") if c.strip()]


def _filtros(pares: list[str]) -> dict[str, Any]:
    """Aceita "-f a=1 -f b=2" e também "a=1; b=2" num único valor."""
    saida: dict[str, Any] = {}
    for par in (item.strip() for bloco in pares for item in bloco.replace("\n", ";").split(";")):
        if not par:
            continue
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
                colunas=_lista(args.colunas) or None,
                max_registros=args.max_registros,
                agrupar_por=_lista(args.agrupar_por),
                somar=_lista(args.somar),
            ),
        )
        for aviso in resultado.avisos:
            print(f"aviso: {aviso}", file=sys.stderr)
        destino = Path(args.saida) if args.saida else None
        if destino and destino.suffix.lower() == ".xlsx":
            destino.write_bytes(para_xlsx(resultado))
        elif destino and destino.suffix.lower() == ".csv":
            if resultado.agregado is not None:
                destino.write_text(para_csv_agregado(resultado, args.separador), encoding="utf-8")
                if resultado.registros:
                    detalhe = destino.with_name(destino.stem + "_dados.csv")
                    detalhe.write_text(para_csv(resultado, args.separador), encoding="utf-8")
            else:
                destino.write_text(para_csv(resultado, args.separador), encoding="utf-8")
        else:
            texto = json.dumps(resultado.como_dict(), ensure_ascii=False, indent=2, default=str)
            if destino:
                destino.write_text(texto, encoding="utf-8")
            else:
                print(texto)
        print(f"{resultado.total} registro(s), {resultado.paginas_consultadas} página(s).", file=sys.stderr)
        if args.resumo:
            Path(args.resumo).write_text(_resumo_markdown(resultado), encoding="utf-8")
        return 0
    except (ErroCatalogo, ErroConsulta) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    except ErroUpstream as exc:
        print(f"erro na API oficial: {exc.mensagem}", file=sys.stderr)
        return 3
    finally:
        await cliente.fechar()


def _resumo_markdown(resultado, linhas_previa: int = 10) -> str:
    """Resumo da consulta em Markdown (usado na página do GitHub Actions)."""

    def celula(v: Any) -> str:
        return ("" if v is None else str(v)).replace("|", "\\|").replace("\n", " ")[:80]

    partes = [
        f"## {resultado.total} registro(s) de `{resultado.dataset}`",
        "",
        f"- Filtros: `{json.dumps(resultado.filtros, ensure_ascii=False)}`",
        f"- Páginas consultadas: {resultado.paginas_consultadas}",
        f"- Origem: {resultado.url}",
        *[f"- ⚠️ {a}" for a in resultado.avisos],
        "",
        f"**Variáveis ({len(resultado.colunas)}):** " + ", ".join(f"`{c}`" for c in resultado.colunas),
        "",
    ]
    ag = resultado.agregado
    if ag is not None:
        def fmt(v: Any) -> str:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").removesuffix(",00")
            return celula(v)

        titulo = " e ".join(f"`{c}`" for c in ag["agrupar_por"]) or "total geral"
        partes.append(f"### Resumo por {titulo} ({ag['grupos']} grupo(s); mostrando até 30)")
        partes.append("")
        partes.append("| " + " | ".join(ag["colunas"]) + " |")
        partes.append("|" + "---|" * len(ag["colunas"]))
        for linha in ag["linhas"][:30]:
            partes.append("| " + " | ".join(fmt(linha.get(c)) for c in ag["colunas"]) + " |")
        total = ["**TOTAL**" if i == 0 else "" for i in range(len(ag["agrupar_por"]))]
        total += [f"**{fmt(ag['totais'][c])}**" for c in ag["colunas"][len(ag["agrupar_por"]):]]
        partes.append("| " + " | ".join(total) + " |")
        partes.append("")
    if resultado.registros:
        cols = resultado.colunas[:12]
        partes.append(f"### Prévia ({min(linhas_previa, resultado.total)} primeiras linhas, até 12 colunas)")
        partes.append("")
        partes.append("| " + " | ".join(cols) + " |")
        partes.append("|" + "---|" * len(cols))
        for r in resultado.registros[:linhas_previa]:
            plano = achatar(r)
            partes.append("| " + " | ".join(celula(plano.get(c)) for c in cols) + " |")
    return "\n".join(partes) + "\n"


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
    p.add_argument("-n", "--max-registros", type=int, help="máximo de registros (0 = todos)")
    p.add_argument("-g", "--agrupar-por", help="variáveis categóricas para agrupar, separadas por vírgula")
    p.add_argument("-s", "--somar", help="variáveis numéricas a somar, separadas por vírgula")
    p.add_argument("-o", "--saida", help="arquivo .xlsx, .csv ou .json (padrão: imprime JSON)")
    p.add_argument("--separador", default=",")
    p.add_argument("--resumo", help="grava um resumo em Markdown neste arquivo")

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return asyncio.run(_rodar(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
