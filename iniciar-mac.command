#!/usr/bin/env bash
# Abre o API-SUS a partir do código (para quem tem Python 3.10 ou mais novo).
# Dois cliques no Finder abrem o Terminal e rodam este arquivo. Na primeira vez o macOS
# pode bloquear: clique com o botão direito (ou Control+clique) > Abrir > Abrir.
# Na primeira execução cria o ambiente .venv e instala as dependências (precisa de internet).

cd "$(dirname "$0")" || exit 1

pausar() {
  if [ -t 0 ]; then read -r -p "Pressione Enter para fechar..." _; fi
}

falhar() {
  echo ""
  echo "ERRO: $1"
  pausar
  exit 1
}

PYTHON=""
for candidato in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python; do
  if command -v "$candidato" > /dev/null 2>&1 && \
     "$candidato" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2> /dev/null; then
    PYTHON="$candidato"
    break
  fi
done
[ -n "$PYTHON" ] || falhar "Python 3.10 ou mais novo não encontrado. Instale em https://www.python.org/downloads/ (ou: brew install python) ou use o executável API-SUS-macos da release \"app\"."

if [ ! -x .venv/bin/python ]; then
  echo "Primeira execução: criando o ambiente Python em .venv ..."
  "$PYTHON" -m venv .venv || falhar "Não foi possível criar o ambiente Python em .venv."
fi

echo "Conferindo as dependências (na primeira vez demora alguns minutos)..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt \
  || falhar "Não foi possível instalar as dependências. Verifique a internet e tente de novo."

.venv/bin/python -m app.desktop
codigo=$?
if [ "$codigo" -ne 0 ]; then pausar; fi
exit "$codigo"
