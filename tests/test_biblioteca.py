"""Downloads de bases para o computador (app/biblioteca.py e app/rotas_downloads.py)."""

import asyncio
import json
import time
from datetime import datetime, timezone

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient

from app.biblioteca import (
    NENHUM_REGISTRO,
    RE_NOME_BASE,
    GerenciadorDownloads,
    GravadorNdjson,
    ndjson_para_parquet,
    nome_padrao,
    normalizar_nome,
)
from app.consulta import ErroConsulta
from app.main import criar_app
from app.rotas_downloads import router
from tests.conftest import ApiFalsa

FINAIS = {"concluido", "erro", "cancelado"}


class ApiLenta(ApiFalsa):
    """Entrega a 1ª página na hora e trava nas seguintes (até o download ser cancelado)."""

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        resposta = super().__call__(request)
        if request.url.path != "/spec.json" and int(request.url.params.get("offset", 0)) > 0:
            await asyncio.sleep(60)
        return resposta


@pytest.fixture
def pasta(tmp_path):
    return tmp_path / "dados"


@pytest.fixture
def montar(config, pasta):
    """Cria o app de teste (com o router de downloads) sobre a API falsa informada."""
    abertos: list[TestClient] = []

    def _montar(api=None) -> TestClient:
        config.pasta_dados = pasta
        app = criar_app(config, transport=httpx.MockTransport(api or ApiFalsa()))
        if not any(getattr(r, "path", None) == "/api/downloads" for r in app.routes):
            app.include_router(router)
        c = TestClient(app)
        c.__enter__()
        abertos.append(c)
        return c

    yield _montar
    for c in abertos:
        gerenciador = getattr(c.app.state, "downloads", None)
        if gerenciador is not None:
            c.portal.call(gerenciador.fechar)
        c.__exit__(None, None, None)


def esperar(c: TestClient, download_id: str, condicao=lambda d: d["status"] in FINAIS, timeout: float = 10.0) -> dict:
    fim = time.monotonic() + timeout
    while True:
        d = c.get(f"/api/downloads/{download_id}").json()
        if condicao(d):
            return d
        if time.monotonic() > fim:
            raise AssertionError(f"tempo esgotado esperando o download: {d}")
        time.sleep(0.01)


def baixar(c: TestClient, **corpo) -> dict:
    r = c.post("/api/downloads", json=corpo)
    assert r.status_code == 201, r.text
    return esperar(c, r.json()["id"])


def ler_parquet(caminho):
    con = duckdb.connect()
    try:
        tipos = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(caminho)]).fetchall()
        linhas = con.execute("SELECT * FROM read_parquet(?)", [str(caminho)]).fetchall()
    finally:
        con.close()
    return [(t[0], t[1]) for t in tipos], linhas


# --------------------------------------------------------------------------- #
# Download completo
# --------------------------------------------------------------------------- #


def test_download_completo_gera_parquet_e_metadados(montar, pasta):
    c = montar()
    r = c.post("/api/downloads", json={"dataset": "cnes-estabelecimentos"})
    assert r.status_code == 201
    inicial = r.json()
    assert set(inicial) == {
        "id", "dataset", "nome", "filtros", "status", "paginas", "registros",
        "iniciado_em", "terminado_em", "erro", "avisos",
    }
    assert len(inicial["id"]) == 12 and int(inicial["id"], 16) >= 0
    assert inicial["status"] in {"na_fila", "baixando", "convertendo", "concluido"}

    d = esperar(c, inicial["id"])
    assert d["status"] == "concluido", d
    assert d["nome"] == "cnes-estabelecimentos"
    assert d["registros"] == 45 and d["paginas"] == 4  # 20 + 20 + 5 e a página vazia do fim
    assert d["erro"] is None and d["terminado_em"]

    bases = pasta / "bases"
    assert sorted(p.name for p in bases.iterdir()) == ["cnes-estabelecimentos.json", "cnes-estabelecimentos.parquet"]

    tipos, linhas = ler_parquet(bases / "cnes-estabelecimentos.parquet")
    assert tipos == [("codigo_cnes", "VARCHAR"), ("nome_fantasia", "VARCHAR"), ("endereco.uf", "VARCHAR")]
    assert len(linhas) == 45
    assert linhas[0] == ("0", "UBS 0", "SP") and linhas[-1] == ("44", "UBS 44", "SP")

    meta = json.loads((bases / "cnes-estabelecimentos.json").read_text(encoding="utf-8"))
    assert set(meta) == {
        "nome", "dataset", "titulo", "filtros", "registros", "colunas", "baixado_em", "url_origem", "avisos", "paginas",
    }
    assert meta["nome"] == "cnes-estabelecimentos" and meta["dataset"] == "cnes-estabelecimentos"
    assert meta["titulo"] == "Estabelecimentos de saúde"
    assert meta["filtros"] == {} and meta["registros"] == 45 and meta["paginas"] == 4
    assert meta["colunas"] == ["codigo_cnes", "nome_fantasia", "endereco.uf"]
    assert meta["url_origem"] == "https://api.teste/cnes/estabelecimentos"
    assert meta["avisos"] == []
    assert datetime.fromisoformat(meta["baixado_em"]).utcoffset() == timezone.utc.utcoffset(None)


def test_download_com_filtros_e_nome_padrao(montar, pasta):
    c = montar()
    d = baixar(c, dataset="arboviroses-dengue", filtros={"nu_ano": 2024, "id_municip": "355030"})
    assert d["status"] == "concluido" and d["registros"] == 4
    assert d["nome"] == "arboviroses-dengue__nu_ano-2024__id_municip-355030"
    assert d["filtros"] == {"nu_ano": 2024, "id_municip": "355030"}
    meta = json.loads((pasta / "bases" / f"{d['nome']}.json").read_text(encoding="utf-8"))
    assert meta["filtros"] == {"nu_ano": 2024, "id_municip": "355030"}
    assert meta["colunas"] == ["dt_notific", "id_municip", "classi_fin"]
    _, linhas = ler_parquet(pasta / "bases" / f"{d['nome']}.parquet")
    assert {linha[1] for linha in linhas} == {"355030"}


def test_nao_usa_o_cache_de_respostas(config, montar):
    config.cache_ttl = 300
    api = ApiFalsa()
    c = montar(api)
    baixar(c, dataset="cnes-estabelecimentos")
    antes = len(api.chamadas)
    baixar(c, dataset="cnes-estabelecimentos")
    assert len(api.chamadas) - antes == 4  # baixou tudo de novo


# --------------------------------------------------------------------------- #
# Validação
# --------------------------------------------------------------------------- #


def test_dataset_inexistente_404(montar):
    c = montar()
    r = c.post("/api/downloads", json={"dataset": "nao-existe"})
    assert r.status_code == 404
    assert c.get("/api/downloads").json() == {"downloads": []}


def test_filtros_invalidos_422(montar, pasta):
    c = montar()
    r = c.post("/api/downloads", json={"dataset": "arboviroses-dengue"})  # nu_ano é obrigatório
    assert r.status_code == 422 and "nu_ano" in r.json()["erro"]
    r = c.post("/api/downloads", json={"dataset": "arboviroses-dengue", "filtros": {"nu_ano": "abc"}})
    assert r.status_code == 422 and "erro" in r.json()
    r = c.post("/api/downloads", json={"dataset": "cnes-estabelecimentos", "filtros": {"uf": "SP"}})
    assert r.status_code == 422 and "Disponíveis" in r.json()["erro"]
    r = c.post("/api/downloads", json={"dataset": "cnes-estabelecimentos", "nome": "!!!"})
    assert r.status_code == 422 and "Nome" in r.json()["erro"]
    assert c.get("/api/downloads").json() == {"downloads": []}
    assert list((pasta / "bases").iterdir()) == []


def test_download_inexistente_404(montar):
    c = montar()
    assert c.get("/api/downloads/abcdef012345").status_code == 404
    assert c.delete("/api/downloads/abcdef012345").status_code == 404


# --------------------------------------------------------------------------- #
# Nomes
# --------------------------------------------------------------------------- #


def test_nomes_duplicados_ganham_sufixo(montar, pasta):
    c = montar()
    filtros = {"nu_ano": 2024}
    nomes = [baixar(c, dataset="arboviroses-dengue", filtros=filtros)["nome"] for _ in range(3)]
    base = "arboviroses-dengue__nu_ano-2024"
    assert nomes == [base, f"{base}-2", f"{base}-3"]
    for nome in nomes:
        assert (pasta / "bases" / f"{nome}.parquet").exists()

    # listagem: mais recentes primeiro
    assert [d["nome"] for d in c.get("/api/downloads").json()["downloads"]] == nomes[::-1]


def test_nome_informado_e_normalizado(montar, pasta):
    c = montar()
    d = baixar(c, dataset="arboviroses-dengue", filtros={"nu_ano": 2024}, nome="  Dengue São Paulo! ")
    assert d["nome"] == "dengue-sao-paulo" and d["status"] == "concluido"
    assert (pasta / "bases" / "dengue-sao-paulo.parquet").exists()
    # o mesmo nome de novo não sobrescreve a base existente
    d = baixar(c, dataset="arboviroses-dengue", filtros={"nu_ano": 2024}, nome="dengue-sao-paulo")
    assert d["nome"] == "dengue-sao-paulo-2"


def test_regras_de_nome():
    assert nome_padrao("arboviroses-dengue", {"nu_ano": 2024}) == "arboviroses-dengue__nu_ano-2024"
    assert nome_padrao("x", {"uf": ["SP", "RJ"], "vazio": "Ação"}) == "x__uf-sp-rj__vazio-acao"
    longo = nome_padrao("arboviroses-dengue", {"id_municip": "9" * 200})
    assert len(longo) <= 80 and RE_NOME_BASE.fullmatch(longo)
    assert normalizar_nome("Leitos UTI 2024") == "leitos-uti-2024"
    assert len(normalizar_nome("a" * 200)) == 80
    with pytest.raises(ErroConsulta):
        normalizar_nome("???")
    assert normalizar_nome("../../etc/passwd") == "etc-passwd"  # sem caminhos


def test_sufixo_respeita_tamanho_maximo(montar, pasta):
    c = montar()
    nome = "a" * 80
    primeiro = baixar(c, dataset="cnes-estabelecimentos", nome=nome)["nome"]
    segundo = baixar(c, dataset="cnes-estabelecimentos", nome=nome)["nome"]
    assert primeiro == nome
    assert segundo == "a" * 78 + "-2" and RE_NOME_BASE.fullmatch(segundo)


# --------------------------------------------------------------------------- #
# Zero registros, erros e cancelamento
# --------------------------------------------------------------------------- #


def test_zero_registros_nao_cria_base(montar, pasta):
    c = montar()
    d = baixar(c, dataset="arboviroses-dengue", filtros={"nu_ano": 2024, "id_municip": "000000"})
    assert d["status"] == "concluido" and d["registros"] == 0
    assert NENHUM_REGISTRO in d["avisos"]
    assert list((pasta / "bases").iterdir()) == []


def test_erro_da_api_oficial_apaga_parciais(montar, pasta):
    c = montar()
    d = baixar(c, dataset="arboviroses-dengue", filtros={"nu_ano": 2024, "id_municip": "erro"})
    assert d["status"] == "erro"
    assert "400" in d["erro"] and "municipio invalido" in d["erro"]
    assert list((pasta / "bases").iterdir()) == []


def test_cancelamento_apaga_parciais(montar, pasta):
    c = montar(ApiLenta())
    inicial = c.post("/api/downloads", json={"dataset": "cnes-estabelecimentos"}).json()
    d = esperar(c, inicial["id"], lambda d: d["registros"] >= 20)
    assert d["status"] == "baixando" and d["paginas"] == 1
    bases = pasta / "bases"
    assert (bases / "cnes-estabelecimentos.ndjson.parcial").exists()

    r = c.delete(f"/api/downloads/{inicial['id']}")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "cancelado" and d["terminado_em"]
    assert list(bases.iterdir()) == []
    # cancelar de novo não muda nada
    assert c.delete(f"/api/downloads/{inicial['id']}").json()["status"] == "cancelado"
    # o nome volta a ficar livre
    assert c.post("/api/downloads", json={"dataset": "cnes-estabelecimentos"}).json()["nome"] == "cnes-estabelecimentos"


def test_no_maximo_dois_downloads_simultaneos(montar, pasta):
    c = montar(ApiLenta())
    ids = [c.post("/api/downloads", json={"dataset": "cnes-estabelecimentos"}).json()["id"] for _ in range(3)]

    def status():
        return {d["id"]: d for d in c.get("/api/downloads").json()["downloads"]}

    fim = time.monotonic() + 10
    while sum(d["status"] == "baixando" and d["registros"] for d in status().values()) < 2:
        assert time.monotonic() < fim, status()
        time.sleep(0.01)
    time.sleep(0.05)
    atual = status()
    assert [atual[i]["status"] for i in ids] == ["baixando", "baixando", "na_fila"]
    # nomes distintos mesmo com downloads ativos iguais
    assert [atual[i]["nome"] for i in ids] == [
        "cnes-estabelecimentos", "cnes-estabelecimentos-2", "cnes-estabelecimentos-3"
    ]

    c.portal.call(c.app.state.downloads.fechar)
    assert {d["status"] for d in status().values()} == {"cancelado"}
    assert list((pasta / "bases").iterdir()) == []


# --------------------------------------------------------------------------- #
# Peças internas
# --------------------------------------------------------------------------- #


def test_parciais_esquecidos_sao_apagados_ao_criar_o_gerenciador(config, pasta):
    config.pasta_dados = pasta
    bases = pasta / "bases"
    bases.mkdir(parents=True)
    for nome in ("velha.ndjson.parcial", "velha.parquet.parcial", "velha.json.parcial", "boa.parquet", "boa.json"):
        (bases / nome).write_text("x")

    async def catalogo():
        raise AssertionError("não deve ser chamado")

    GerenciadorDownloads(config, None, catalogo)
    assert sorted(p.name for p in bases.iterdir()) == ["boa.json", "boa.parquet"]


def test_gravador_e_conversao_com_colunas_dificeis(tmp_path):
    origem, destino = tmp_path / "x.ndjson.parcial", tmp_path / "x.parquet"
    gravador = GravadorNdjson(origem)
    gravador([{"Nome": "A", "ativo": True, "valor": 10.5, "endereco.uf": "SP"}])
    gravador([{"nome": "b", "ativo": False, "valor": None, "col 'aspas\"": "ç", "": "vazio"}])
    gravador.fechar()
    assert gravador.registros == 2
    assert gravador.colunas == ["Nome", "ativo", "valor", "endereco.uf", "nome_2", "col 'aspas\"", "sem_nome"]
    assert len(gravador.avisos) == 2

    ndjson_para_parquet(origem, destino, gravador.colunas)
    tipos, linhas = ler_parquet(destino)
    assert [t[0] for t in tipos] == gravador.colunas and {t[1] for t in tipos} == {"VARCHAR"}
    assert linhas == [
        ("A", "true", "10.5", "SP", None, None, None),
        (None, "false", None, None, "b", "ç", "vazio"),
    ]


def test_cancelamento_durante_a_conversao_interrompe_o_duckdb(montar, pasta, monkeypatch):
    import app.biblioteca as biblioteca

    def conversao_lenta(origem, destino, colunas, conexao):
        destino.write_text("parcial")
        try:  # consulta demorada: só termina rápido se for interrompida
            conexao.execute("SELECT sum(hash(range)) FROM range(100000000000)").fetchall()
        finally:
            conexao.close()

    monkeypatch.setattr(biblioteca, "ndjson_para_parquet", conversao_lenta)
    c = montar()
    inicial = c.post("/api/downloads", json={"dataset": "cnes-estabelecimentos"}).json()
    esperar(c, inicial["id"], lambda d: d["status"] == "convertendo")
    bases = pasta / "bases"
    fim = time.monotonic() + 10
    while not (bases / "cnes-estabelecimentos.parquet.parcial").exists():
        assert time.monotonic() < fim
        time.sleep(0.01)
    time.sleep(0.2)  # deixa a consulta começar

    inicio = time.monotonic()
    d = c.delete(f"/api/downloads/{inicial['id']}").json()
    assert d["status"] == "cancelado"
    assert time.monotonic() - inicio < 5
    assert list(bases.iterdir()) == []


def test_tamanho_de_pagina_nao_entra_no_nome(montar):
    c = montar()
    d = baixar(c, dataset="arboviroses-dengue", filtros={"nu_ano": 2024, "limit": 2, "id_municip": ""})
    assert d["nome"] == "arboviroses-dengue__nu_ano-2024" and d["registros"] == 7
    assert d["filtros"] == {"nu_ano": 2024, "limit": 2}  # filtros vazios são descartados
