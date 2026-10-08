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


## Testar na web (sem instalar nada)

### Página web (GitHub Pages)

A pasta `docs/` tem uma versão da interface que roda **só no navegador**: lê o `swagger.json`
oficial e consulta a API do Ministério da Saúde direto do seu computador. Para publicar:

1. No GitHub, abra **Settings → Pages**.
2. Em **Build and deployment → Source**, escolha **Deploy from a branch**.
3. Selecione o branch onde está o código (ex.: `main`) e a pasta **`/docs`**. Clique em **Save**.
4. Em alguns minutos a página fica em `https://<seu-usuario>.github.io/API-SUS/`.

> O modo direto só funciona se a API oficial permitir chamadas de outros sites (CORS).
> Isso não foi verificado. Se a página mostrar erro de acesso, use o modo
> **"Pelo servidor API-SUS"** com o endereço do Codespaces (abaixo).

### Codespaces (API completa rodando no GitHub)

1. Na página do repositório, clique em **Code → Codespaces → Create codespace**.
2. Aguarde a instalação; a API sobe sozinha na porta 8000 e o navegador abre a interface.
3. A aba **Ports** mostra o endereço público (`https://...app.github.dev`). Para usá-lo na
   página do GitHub Pages, deixe a porta como **Public** (botão direito → Port Visibility).

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
| `max_registros` | Máximo de registros a buscar (padrão 1000, teto 100000). |
| `paginar` | `true` (padrão) percorre as páginas automaticamente. |
| `formato` | `json` (padrão) ou `csv`. |
| `separador` | Separador do CSV (padrão `,`; use `;` para o Excel em português). |

### Exemplos

> Os nomes de bases e filtros abaixo vêm de projetos públicos que usam a API.
> **Confirme na listagem `/api/datasets`**: o catálogo real é o da especificação oficial.

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
python -m app.cli dados arboviroses-dengue -f nu_ano=2024 -c dt_notific,id_municip -n 5000 -o dengue.csv
```

## Configuração (variáveis de ambiente)

| Variável | Padrão | Descrição |
|---|---|---|
| `DATASUS_BASE_URL` | `https://apidadosabertos.saude.gov.br` | Host dos dados (sem `/v1`) |
| `DATASUS_SPEC_URLS` | 4 caminhos candidatos do `swagger.json` | URLs da especificação, separadas por vírgula, tentadas em ordem |
| `DATASUS_SPEC_ARQUIVO` | | Arquivo local com a especificação (tem prioridade) |
| `DATASUS_SPEC_CACHE` | `data/swagger_cache.json` | Cópia da última especificação baixada, usada se o site estiver fora do ar |
| `DATASUS_RESPEITAR_BASEPATH` | `false` | Prefixar as chamadas com o `basePath` da especificação |
| `DATASUS_MODO_OFFSET` | `pagina` | `pagina`: `offset` = nº da página (0, 1, 2...). `registro`: `offset` = índice do registro (0, 20, 40...) |
| `DATASUS_TAMANHO_PAGINA` | `20` | Tamanho de página quando a especificação não declara `maximum`/`default` para `limit` |
| `DATASUS_MAX_REGISTROS` | `1000` | Padrão de `max_registros` |
| `DATASUS_MAX_REGISTROS_TETO` | `100000` | Valor máximo aceito em `max_registros` |
| `DATASUS_PAUSA_ENTRE_PAGINAS` | `0` | Segundos de espera entre páginas (para não sobrecarregar a API oficial) |
| `DATASUS_TIMEOUT` | `60` | Timeout de cada requisição (s) |
| `DATASUS_TENTATIVAS` | `3` | Tentativas em erros 5xx/429/conexão |
| `DATASUS_CACHE_TTL` | `300` | Cache em memória das respostas (s); `0` desliga |
| `CORS_ORIGENS` | `*` | Origens permitidas, separadas por vírgula |

## Pontos não verificados

Esta API foi escrita num ambiente **sem acesso de rede ao `apidadosabertos.saude.gov.br`**,
então não foi testada contra o serviço real. Os testes usam uma especificação **sintética**
(`tests/fixtures/swagger_exemplo.json`). As escolhas abaixo seguem fontes de terceiros e
são configuráveis:

- **Endereço do `swagger.json`**: a página `/v1/` cita `/static/swagger.json`. Como não sei se o
  caminho é relativo ao `/v1/`, a API tenta os dois (e também `swagger.json` na raiz). Se nenhum
  funcionar, baixe o arquivo pelo navegador e use `DATASUS_SPEC_ARQUIVO`.
- **Prefixo `/v1`**: um projeto público relata que os dados respondem **sem** o `/v1`
  (ex.: `https://apidadosabertos.saude.gov.br/arboviroses/dengue`), por isso esse é o padrão.
- **Semântica do `offset`**: fontes públicas indicam que o `offset` é o **número da página**, e não
  o índice do registro. Se a API devolver a mesma página duas vezes, a paginação é interrompida
  com um aviso, e basta trocar `DATASUS_MODO_OFFSET`.
- **Tamanho máximo de página**: varia entre as bases (há relatos de 20 no CNES e de 1000 na dengue).
  A API usa o `maximum` declarado na especificação. Se não houver, usa 20.
- **Autenticação**: um catálogo de terceiros diz que a API exige autenticação, mas projetos públicos
  fazem as chamadas sem credenciais. Esta API não envia credenciais.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```
