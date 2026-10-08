"""Gera .github/workflows/baixar-planilha.yml com o menu de bases da especificação.

    python scripts/gerar_workflow_planilha.py docs/swagger.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalogo import montar_datasets  # noqa: E402

MODELO = """\
# Arquivo gerado por scripts/gerar_workflow_planilha.py — não edite à mão.
name: Baixar planilha

on:
  workflow_dispatch:
    inputs:
      base:
        description: "Base de dados (veja a lista e as colunas em https://macielbarroslira-rgb.github.io/API-SUS/)"
        type: choice
        default: arboviroses-dengue
        options:
{opcoes}
      filtros:
        description: "Filtros (opcional). Ex.: nu_ano=2024; id_municip=355030"
        type: string
        required: false
      colunas:
        description: "Colunas separadas por vírgula (vazio = todas)"
        type: string
        required: false
      max_registros:
        description: "Máximo de linhas"
        type: string
        default: "1000"
      formato:
        description: "Formato do arquivo"
        type: choice
        default: xlsx
        options:
          - xlsx
          - csv

permissions:
  contents: read

jobs:
  planilha:
    name: ${{{{ inputs.base }}}}
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Consultar a API oficial e gerar a planilha
        env:
          BASE: ${{{{ inputs.base }}}}
          FILTROS: ${{{{ inputs.filtros }}}}
          COLUNAS: ${{{{ inputs.colunas }}}}
          MAX: ${{{{ inputs.max_registros }}}}
          FORMATO: ${{{{ inputs.formato }}}}
          DATASUS_SPEC_CACHE: docs/swagger.json
        run: |
          mkdir -p saida
          args=(dados "$BASE" -n "$MAX" -o "saida/$BASE.$FORMATO" --separador ";" --resumo resumo.md)
          if [ -n "$FILTROS" ]; then args+=(-f "$FILTROS"); fi
          if [ -n "$COLUNAS" ]; then args+=(-c "$COLUNAS"); fi
          if ! python -m app.cli "${{args[@]}}" 2> erro.log; then
            {{
              echo "## ❌ Não foi possível gerar a planilha"
              echo '```'
              cat erro.log
              echo '```'
            }} >> "$GITHUB_STEP_SUMMARY"
            cat erro.log
            exit 1
          fi
          cat erro.log
          {{
            cat resumo.md
            echo ""
            echo "📥 **Para baixar:** role até o fim desta página, em **Artifacts**, e clique em **planilha-$BASE**."
          }} >> "$GITHUB_STEP_SUMMARY"
      - uses: actions/upload-artifact@v4
        with:
          name: planilha-${{{{ inputs.base }}}}
          path: saida/
          retention-days: 7
"""


def main(spec_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    ids = sorted(
        ds.id for ds in montar_datasets(spec).values() if not any(p.local == "path" for p in ds.parametros)
    )
    opcoes = "\n".join(f"          - {i}" for i in ids)
    destino = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "baixar-planilha.yml"
    destino.write_text(MODELO.format(opcoes=opcoes), encoding="utf-8")
    print(f"{destino}: {len(ids)} bases")


if __name__ == "__main__":
    main(sys.argv[1])
