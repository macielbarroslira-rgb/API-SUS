import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pedido_planilha import argumentos, ler_pedido  # noqa: E402

CORPO = """Pedido de planilha gerado pela página API-SUS.
👉 Clique em **Create** (Criar) para gerar.

```
base: assistencia-a-saude-hospitais-e-leitos
filtros: uf=SP; x=1
colunas:
agrupar_por: nome_do_municipio_onde_fica_o_hospital
somar: quantidade_total_de_leitos_do_hosptial
max_registros: 0
formato: xlsx
```"""


def test_le_pedido_e_monta_argumentos():
    pedido = ler_pedido(CORPO)
    assert pedido["base"] == "assistencia-a-saude-hospitais-e-leitos" and pedido["colunas"] == ""
    assert argumentos(pedido, "saida/a.xlsx", "r.md") == [
        "dados", "assistencia-a-saude-hospitais-e-leitos", "-n", "0", "-o", "saida/a.xlsx", "--separador", ";",
        "--resumo", "r.md", "-f", "uf=SP; x=1", "-g", "nome_do_municipio_onde_fica_o_hospital",
        "-s", "quantidade_total_de_leitos_do_hosptial",
    ]


@pytest.mark.parametrize("corpo", ["", "filtros: a=1", "base: ../../etc", "base: x\nformato: pdf", "base: x\nmax_registros: tudo"])
def test_pedidos_invalidos(corpo):
    with pytest.raises(ValueError):
        ler_pedido(corpo)
