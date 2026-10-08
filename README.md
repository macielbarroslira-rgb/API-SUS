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

## App no computador

Um programa para usar no seu computador, **sem instalar Python**: ele baixa as bases do
Ministério da Saúde para uma pasta sua e deixa explorar os dados pelo navegador, mesmo sem
depender do GitHub.

### Baixar e abrir

1. Abra a release **app**: <https://github.com/macielbarroslira-rgb/API-SUS/releases/tag/app>
   e baixe o arquivo do seu sistema:

   | Sistema | Arquivo |
   |---|---|
   | Windows 10/11 (64 bits) | `API-SUS-windows.exe` |
   | macOS com chip Apple (M1 ou mais novo) | `API-SUS-macos.zip` |
   | Linux (64 bits) | `API-SUS-linux` |

2. **Dois cliques** no arquivo. Abre uma janela de terminal (é o app rodando) e, alguns
   segundos depois, o navegador em <http://127.0.0.1:8765/>. Se o navegador não abrir,
   digite esse endereço nele.
3. Para encerrar, **feche a janela do terminal** (ou aperte `Ctrl+C` nela).

O app só atende o próprio computador (`127.0.0.1`): ninguém na rede acessa. Se você der dois
cliques de novo com ele já aberto, ele só abre o navegador no app que já está rodando.

### Avisos na primeira vez (o executável não é assinado)

Os executáveis **não são assinados digitalmente** (a assinatura exige certificados pagos da
Microsoft e da Apple). Eles são gerados pelo próprio GitHub, a partir deste código, pelo workflow
[`App no computador`](.github/workflows/app-desktop.yml), que também testa cada um antes de publicar.
Por isso o sistema avisa na primeira vez:

- **Windows**: aparece "O Windows protegeu o computador" (SmartScreen). Clique em
  **Mais informações** → **Executar assim mesmo**. Alguns antivírus desconfiam de programas
  feitos com PyInstaller; se o seu bloquear, use a alternativa com Python abaixo.
- **macOS**: dê dois cliques no `.zip` para extrair o `API-SUS-macos`. Depois, **botão direito
  (ou Control+clique) no arquivo → Abrir → Abrir**. No macOS 15 (Sequoia) ou mais novo esse
  atalho não aparece: tente abrir uma vez, vá em **Ajustes do Sistema → Privacidade e
  Segurança** e clique em **Abrir Mesmo Assim**. Se você baixou o arquivo sem o `.zip`, ele
  chega sem permissão de execução; no Terminal: `chmod +x ~/Downloads/API-SUS-macos`.
- **Linux**: o arquivo chega sem permissão de execução. Rode no terminal
  `chmod +x API-SUS-linux && ./API-SUS-linux` (pelo terminal você vê as mensagens e encerra com
  `Ctrl+C`).

### Onde ficam os dados

Na pasta **`API-SUS-dados`** dentro da sua pasta pessoal (`~/API-SUS-dados`; no Windows,
`C:\Users\<seu usuário>\API-SUS-dados`). O endereço também aparece na janela do terminal.

- `bases/`: cada base baixada vira um arquivo Parquet (todas as colunas como texto) e um `.json`
  com a origem, os filtros usados, a data do download e os avisos. Dá para abrir o Parquet em
  outras ferramentas (DuckDB, Python, R, Power BI).
- `exportacoes/`: cópia de cada planilha exportada.

Apagar o app não apaga os dados. Para usar outra pasta, defina a variável `API_SUS_PASTA`.

### O que dá para fazer

1. **Baixar bases**: escolha a base e os filtros da API oficial (ano, município...). O download
   roda em segundo plano, mostra o andamento, pode ser cancelado e fica salvo na pasta.
2. **Filtrar por categorias**: para cada coluna o app lista os valores existentes e quantos
   registros cada um tem; marque os que interessam. Os filtros são em cascata (ao filtrar uma
   coluna, as outras mostram só os valores que sobraram).
3. **Agrupar e somar**: resumo por categorias com contagem de registros, somas e linha TOTAL.
4. **Exportar**: Excel (abas `resumo`, `dados` e `consulta`) ou CSV (separador `;`, abre direto
   no Excel em português).

Como tudo acontece sobre a cópia local, filtrar e resumir é rápido e não depende da API oficial
(a internet só é necessária para baixar). As 7 bases de assistência que paginam com defeito na
API oficial (veja [Comportamento da API oficial](#comportamento-da-api-oficial)) continuam
podendo vir incompletas; o app avisa quando isso acontece.

### Alternativa com Python (sem o executável)

Para quem tem **Python 3.10 ou mais novo**: baixe o código (**Code → Download ZIP** ou
`git clone`) e dê dois cliques no lançador do seu sistema:

| Sistema | Lançador |
|---|---|
| Windows | `iniciar-windows.bat` |
| macOS | `iniciar-mac.command` (na primeira vez: botão direito → Abrir) |
| Linux | `iniciar-linux.sh` (ou `./iniciar-linux.sh` no terminal) |

Na primeira vez o lançador cria o ambiente `.venv` e instala as dependências (precisa de
internet e demora alguns minutos); depois abre direto. É o mesmo que rodar `python -m app.desktop`.

### Limitações

- Executáveis sem assinatura digital (veja os avisos acima).
- O executável de macOS é só para Macs com chip Apple; em Macs com processador Intel, use o
  lançador com Python.
- O executável de Linux é gerado no Ubuntu mais recente; em distribuições antigas ele pode não
  abrir (erro de `GLIBC`). Nesse caso, use o lançador com Python.
- Na primeira abertura o executável demora alguns segundos (ele se descompacta antes de rodar).

### Opções

| Variável | Padrão | Descrição |
|---|---|---|
| `API_SUS_PASTA` | `~/API-SUS-dados` | Pasta das bases baixadas e das exportações |
| `API_SUS_PORTA` | `8765` (ou outra livre) | Porta fixa do app |
| `API_SUS_NAO_ABRIR` | | `1` = não abre o navegador sozinho |

Para gerar o executável na sua máquina: `pip install -r requirements.txt pyinstaller` e
`pyinstaller --noconfirm --clean api-sus.spec` (sai em `dist/`).

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

1. Abra **https://macielbarroslira-rgb.github.io/API-SUS/**, escolha uma consulta pronta ou uma
   base, os filtros, as colunas e (opcional) **agrupar por / somar**.
2. Clique em **Gerar planilha**: abre no GitHub um pedido (*issue*) já preenchido. Clique em **Create**.
3. O workflow `Planilha por pedido` gera o Excel e comenta no pedido o resumo e o link
   **⬇️ baixar** (o arquivo fica na release `planilhas`). Só o dono/colaboradores do
   repositório conseguem disparar.

Alternativa manual: **Actions → Baixar planilha → Run workflow**, preenchendo os mesmos campos;
o arquivo sai em **Artifacts** no fim da página da execução.

> Os workflows disparados por issue e por "Run workflow" só funcionam quando estão no branch
> padrão (`main`) do repositório.

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
