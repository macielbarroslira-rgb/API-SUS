# API-SUS

API em Python (FastAPI) para **consultar e baixar dados da [API de Dados Abertos do Ministério da Saúde](https://apidadosabertos.saude.gov.br/v1/)** (DEMAS) escolhendo:

1. **a base de dados** (dengue, CNES, hospitais e leitos etc.);
2. **os filtros** que a base aceita (ano, município, UF...);
3. **as variáveis (colunas)** que você quer receber.

A resposta sai em **JSON ou CSV**, e a paginação da API oficial é percorrida automaticamente.

Também tem uma **interface web** (em `/`) e um **CLI** para usar no terminal.

## Como funciona

Nenhuma base fica fixa no código. Ao iniciar, a API baixa a especificação Swagger oficial
(`swagger.json`) e monta o catálogo a partir dela: cada operação `GET` vira uma base,
os parâmetros viram filtros e o schema de resposta vira a lista de variáveis. Quando o
Ministério publica uma base nova, basta chamar `POST /api/catalogo/recarregar`.

Quando a especificação não documenta as variáveis de uma base, a API consulta alguns
registros reais (amostra) para descobrir quais colunas existem.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abra:

- http://localhost:8000/ : interface web (escolher base, filtros e variáveis; ver tabela; baixar CSV/JSON)
- http://localhost:8000/docs : documentação interativa (Swagger) desta API

Com Docker:

```bash
docker build -t api-sus .
docker run -p 8000:8000 api-sus
```


## Baixar planilhas pelo navegador (sem instalar nada)

A API do Ministério da Saúde **não permite consulta direta de outros sites** (não envia
cabeçalhos CORS; verificado pelo workflow `Diagnóstico da API oficial`). Por isso a
planilha é gerada pelo próprio GitHub:

1. Veja as bases, filtros e colunas em **https://macielbarroslira-rgb.github.io/API-SUS/**
   e clique em **Gerar planilha** para obter os valores a preencher.
2. Abra **Actions → Baixar planilha → Run workflow**, preencha base, filtros
   (ex.: `nu_ano=2024; id_municip=355030`), colunas e máximo de linhas.
3. Quando a execução terminar (✅), abra-a: há um resumo com prévia dos dados e, no fim
   da página, em **Artifacts**, o arquivo `planilha-<base>` (Excel ou CSV).

O workflow `Atualizar catálogo` (semanal) mantém `docs/swagger.json` e `docs/variaveis.json`
(colunas descobertas consultando 1 registro de cada base) atualizados.

### Codespaces (API completa rodando no GitHub)

1. Na página do repositório, clique em **Code → Codespaces → Create codespace**.
2. Aguarde a instalação; a API sobe sozinha na porta 8000 e o navegador abre a interface,
   que consulta e baixa os dados diretamente.

## Resumos: agrupar e somar

Escolha variáveis categóricas para **agrupar** e numéricas para **somar**: o resultado traz,
para cada grupo, a quantidade de registros e as somas, mais uma linha **TOTAL**. A agregação é
feita página a página (sem guardar tudo na memória); acima de 1 milhão de linhas os dados
detalhados são omitidos, mas o resumo considera todas.

```bash
# leitos totais e SUS por UF (todas as linhas)
curl -o leitos.xlsx "http://localhost:8000/api/datasets/assistencia-a-saude-hospitais-e-leitos/dados?agrupar_por=unidade_da_federacao_onde_fica_o_hospital&somar=quantidade_total_de_leitos_do_hosptial,quantidade_total_de_leitos_sus_do_hosptial&max_registros=0&formato=xlsx"

python -m app.cli dados cnes-estabelecimentos -f "codigo_uf=35" -g codigo_tipo_unidade -n 0 -o cnes_sp.xlsx
```

A página web tem **consultas prontas** (com colunas conferidas nos dados reais).

## Endpoints

| Método | Caminho | O que faz |
|---|---|---|
| GET | `/health` | Estado do serviço e do catálogo |
| GET | `/api/catalogo` | Origem da especificação, total de bases e grupos temáticos |
| POST | `/api/catalogo/recarregar` | Baixa de novo a especificação oficial |
| GET | `/api/datasets?q=&grupo=` | Lista as bases (busca sem acento) |
| GET | `/api/datasets/{id}` | Detalhes: filtros (tipo, obrigatório, valores aceitos) e variáveis |
| GET | `/api/datasets/{id}/variaveis?amostra=true&<filtros>` | Variáveis documentadas e/ou descobertas por amostra |
| GET | `/api/datasets/{id}/dados?<filtros>&colunas=&formato=` | Dados filtrados |
| POST | `/api/datasets/{id}/dados` | Mesma coisa, com corpo JSON |

O `{id}` é o caminho da base com `-` no lugar de `/` (ex.: `/arboviroses/dengue` vira
`arboviroses-dengue`). O `operationId` ou o próprio caminho também são aceitos.

### Parâmetros de `/dados`

| Parâmetro | Descrição |
|---|---|
| *qualquer filtro da base* | Repassado à API oficial (ex.: `nu_ano=2024`). É validado contra a especificação: nome, tipo, valores permitidos e obrigatoriedade. |
| `colunas` | Variáveis a retornar, separadas por vírgula. Campos aninhados usam ponto (`endereco.uf`). Sem esse parâmetro, todas as colunas são retornadas. |
| `local.<coluna>` | Filtro de igualdade aplicado aqui, depois do download (para colunas que a API oficial não filtra). |
| `max_registros` | Máximo de registros a buscar (padrão 1000; `0` = todos, até o teto). |
| `agrupar_por` | Variáveis categóricas para o resumo, separadas por vírgula (ex.: `ds_procedimento`). |
| `somar` | Variáveis numéricas somadas em cada grupo (ex.: `qt_procedimento,nu_valor_procedimento`). |
| `paginar` | `true` (padrão) percorre as páginas automaticamente. |
| `formato` | `json` (padrão), `csv` ou `xlsx` (Excel: aba `resumo` com TOTAL, aba `dados`, aba `consulta`). |
| `separador` | Separador do CSV (padrão `,`; use `;` para o Excel em português). |

### Exemplos

```bash
# listar bases
curl "http://localhost:8000/api/datasets?q=dengue"

# ver filtros e variáveis
curl "http://localhost:8000/api/datasets/arboviroses-dengue/variaveis?amostra=true&nu_ano=2024"

# dados com variáveis selecionadas, em CSV
curl -o dengue.csv "http://localhost:8000/api/datasets/arboviroses-dengue/dados?nu_ano=2024&colunas=dt_notific,id_municip&max_registros=5000&formato=csv&separador=;"

# POST com corpo JSON
curl -X POST "http://localhost:8000/api/datasets/arboviroses-dengue/dados" \
  -H "Content-Type: application/json" \
  -d '{"filtros": {"nu_ano": 2024}, "colunas": ["dt_notific", "id_municip"], "max_registros": 500}'
```

Resposta JSON:

```json
{
  "dataset": "arboviroses-dengue",
  "url_origem": "https://apidadosabertos.saude.gov.br/arboviroses/dengue",
  "filtros": {"nu_ano": 2024},
  "colunas": ["dt_notific", "id_municip"],
  "paginas_consultadas": 1,
  "total": 500,
  "avisos": ["Limite de 500 registros atingido; pode haver mais dados. ..."],
  "dados": [{"dt_notific": "...", "id_municip": "..."}]
}
```

### CLI

```bash
python -m app.cli bases --busca cnes
python -m app.cli variaveis arboviroses-dengue --amostra -f nu_ano=2024
python -m app.cli dados arboviroses-dengue -f "nu_ano=2024; id_municip=355030" -c dt_notific,cs_sexo -n 5000 -o dengue.xlsx
```

## Configuração (variáveis de ambiente)

| Variável | Padrão | Descrição |
|---|---|---|
| `DATASUS_BASE_URL` | `https://apidadosabertos.saude.gov.br` | Host dos dados (sem `/v1`) |
| `DATASUS_SPEC_URLS` | `https://apidadosabertos.saude.gov.br/static/swagger.json` | URLs da especificação, separadas por vírgula, tentadas em ordem |
| `DATASUS_SPEC_ARQUIVO` | | Arquivo local com a especificação (tem prioridade) |
| `DATASUS_SPEC_CACHE` | `data/swagger_cache.json` | Cópia da última especificação baixada, usada se o site estiver fora do ar |
| `DATASUS_RESPEITAR_BASEPATH` | `false` | Prefixar as chamadas com o `basePath` da especificação |
| `DATASUS_MODO_OFFSET` | `pagina` | `pagina`: `offset` = nº da página (0, 1, 2...). `registro`: `offset` = índice do registro (0, 20, 40...) |
| `DATASUS_TAMANHO_PAGINA` | `20` | Tamanho de página quando a especificação não informa máximo nem `default` |
| `DATASUS_MAX_REGISTROS` | `1000` | Padrão de `max_registros` |
| `DATASUS_MAX_REGISTROS_TETO` | `100000` | Valor máximo aceito em `max_registros` |
| `DATASUS_PAUSA_ENTRE_PAGINAS` | `0` | Segundos de espera entre páginas (para não sobrecarregar a API oficial) |
| `DATASUS_TIMEOUT` | `60` | Timeout de cada requisição (s) |
| `DATASUS_TENTATIVAS` | `3` | Tentativas em erros 5xx/429/conexão |
| `DATASUS_CACHE_TTL` | `300` | Cache em memória das respostas (s); `0` desliga |
| `CORS_ORIGENS` | `*` | Origens permitidas, separadas por vírgula |

## Comportamento da API oficial

Verificado contra a API real (workflow `Diagnóstico da API oficial`):

- A especificação fica em `https://apidadosabertos.saude.gov.br/static/swagger.json` (113 bases).
- Os dados respondem **sem** o prefixo `/v1` (com `/v1` dá 404) e sem autenticação.
- A API **não envia cabeçalhos CORS**: navegadores não conseguem consultá-la de outros sites.
- O `offset` é o **número da página** (começa em 0); o tamanho máximo de página aparece só no
  texto da descrição do `limit` (ex.: 20 no CNES, 1000 na dengue) e é lido de lá. A base
  `economia-da-saude/bps` usa `pagina` (começa em 1) e `tamanhoPagina` (máx. 500).
- A especificação não documenta as colunas das respostas; elas são descobertas por amostra.
- O parâmetro `campos` da API faz ela responder **502 após ~60 s**; por isso não é usado (as
  colunas são selecionadas aqui).
- **Paginação com defeito em 11 bases** (teste automático em `docs/variaveis.json`), entre elas
  todas as bases novas de assistência: `sia-procedimentos-ambulatoriais`, `sih-procedimentos-hospitalares`,
  `cnes-leitos`, `cnes-equipamentos`, `cnes-profissionais`, `cnes-servicos-especializados` e
  `cnes-estabelecimentos` (de `assistencia-a-saude`). Elas devolvem 1–2 registros por página mesmo
  pedindo 1000, então **contagens e somas sobre elas saem incompletas**. A API-SUS continua
  buscando até uma página vazia e avisa explicitamente quando isso acontece. As demais 98 bases
  (incluindo `cnes/estabelecimentos` e `hospitais-e-leitos`) paginam corretamente.

## Testes

Os testes usam uma especificação **sintética** (`tests/fixtures/swagger_exemplo.json`) e uma API simulada.

```bash
pip install -r requirements-dev.txt
pytest
```
