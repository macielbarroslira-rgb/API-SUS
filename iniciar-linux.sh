#!/usr/bin/env bash
# Abre o API-SUS a partir do código (para quem tem Python 3.10 ou mais novo).
# Na primeira vez cria o ambiente .venv e instala as dependências (precisa de internet).
# Uso: ./iniciar-linux.sh   (ou dois cliques, escolhendo "Executar no terminal")

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
for candidato in python3 python; do
  if command -v "$candidato" > /dev/null 2>&1 && \
     "$candidato" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2> /dev/null; then
    PYTHON="$candidato"
    break
  fi
done
[ -n "$PYTHON" ] || falhar "Python 3.10 ou mais novo não encontrado. Instale pelo gerenciador de pacotes (ex.: sudo apt install python3 python3-venv) ou use o executável API-SUS-linux da release \"app\"."

if [ ! -x .venv/bin/python ]; then
  echo "Primeira execução: criando o ambiente Python em .venv ..."
  "$PYTHON" -m venv .venv || falhar "Não foi possível criar o ambiente. No Ubuntu/Debian: sudo apt install python3-venv"
fi

echo "Conferindo as dependências (na primeira vez demora alguns minutos)..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt \
  || falhar "Não foi possível instalar as dependências. Verifique a internet e tente de novo."

.venv/bin/python -m app.desktop
codigo=$?
if [ "$codigo" -ne 0 ]; then pausar; fi
exit "$codigo"
