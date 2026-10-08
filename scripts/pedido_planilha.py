"""Gera a planilha pedida numa issue do GitHub (workflow "Planilha por pedido").

O corpo da issue (preenchido pela página web) traz linhas "chave: valor":

    base: assistencia-a-saude-hospitais-e-leitos
    filtros: uf=SP
    colunas:
    agrupar_por: nome_do_municipio_onde_fica_o_hospital
    somar: quantidade_total_de_leitos_do_hosptial
    max_registros: 0
    formato: xlsx

Os valores são passados ao CLI como argumentos (sem shell). Saídas em $GITHUB_OUTPUT:
arquivo (nome do arquivo gerado) e base.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHAVES = ("base", "filtros", "colunas", "agrupar_por", "somar", "max_registros", "formato")


def ler_pedido(corpo: str) -> dict[str, str]:
    pedido: dict[str, str] = {}
    for linha in (corpo or "").splitlines():
        m = re.match(r"^\s*([a-z_]+)\s*:\s*(.*?)\s*$", linha)
        if m and m.group(1) in CHAVES and m.group(1) not in pedido:
            pedido[m.group(1)] = m.group(2).strip("` ")
    if not pedido.get("base"):
        raise ValueError("O pedido não informa a base (linha 'base: ...').")
    if not re.fullmatch(r"[a-z0-9_-]+", pedido["base"]):
        raise ValueError(f"Nome de base inválido: {pedido['base']!r}")
    formato = pedido.get("formato") or "xlsx"
    if formato not in ("xlsx", "csv"):
        raise ValueError("formato deve ser xlsx ou csv")
    pedido["formato"] = formato
    pedido["max_registros"] = pedido.get("max_registros") or "1000"
    if not pedido["max_registros"].isdigit():
        raise ValueError("max_registros deve ser um número (0 = todas as linhas)")
    return pedido


def argumentos(pedido: dict[str, str], arquivo: str, resumo: str) -> list[str]:
    argv = ["dados", pedido["base"], "-n", pedido["max_registros"], "-o", arquivo, "--separador", ";", "--resumo", resumo]
    for chave, opcao in (("filtros", "-f"), ("colunas", "-c"), ("agrupar_por", "-g"), ("somar", "-s")):
        if pedido.get(chave):
            argv += [opcao, pedido[chave]]
    return argv


def main() -> int:
    from app import cli

    pedido = ler_pedido(os.environ.get("CORPO", ""))
    numero = os.environ.get("NUMERO", "0")
    Path("saida").mkdir(exist_ok=True)
    nome = f"planilha-{numero}-{pedido['base']}.{pedido['formato']}"
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as saida:
        saida.write(f"arquivo={nome}\nbase={pedido['base']}\n")
    return cli.main(argumentos(pedido, f"saida/{nome}", "resumo.md"))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(f"erro no pedido: {exc}", file=sys.stderr)
        sys.exit(2)
