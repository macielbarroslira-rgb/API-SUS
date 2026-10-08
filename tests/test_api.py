import json

from app.consulta import achatar, extrair_registros
from tests.conftest import DENGUE


def test_health_e_catalogo(cliente):
    assert cliente.get("/health").json()["catalogo_carregado"] is True
    cat = cliente.get("/api/catalogo").json()
    assert cat["total_bases"] == 3
    assert cat["grupos"] == {"Agravo Arboviroses": 1, "CNES": 2}


def test_lista_e_busca_sem_acento(cliente):
    assert cliente.get("/api/datasets").json()["total"] == 3
    r = cliente.get("/api/datasets", params={"q": "saude"}).json()  # "saúde" no resumo
    assert [b["id"] for b in r["bases"]] == ["cnes-estabelecimentos"]
    r = cliente.get("/api/datasets", params={"grupo": "cnes"}).json()
    assert r["total"] == 2


def test_detalhe_e_404(cliente):
    d = cliente.get("/api/datasets/arboviroses-dengue").json()
    assert d["parametro_limit"] == "limit" and d["parametro_offset"] == "offset"
    # também encontra pelo operationId e pelo caminho
    assert cliente.get("/api/datasets/get_arboviroses_dengue").status_code == 200
    assert cliente.get("/api/datasets/nao-existe").status_code == 404


def test_paginacao_automatica_por_numero_de_pagina(cliente, api_falsa):
    r = cliente.get("/api/datasets/arboviroses-dengue/dados", params={"nu_ano": 2024}).json()
    assert r["total"] == 7 and not r["avisos"]
    assert r["paginas_consultadas"] == 4  # 3 + 3 + 1 e a página vazia que confirma o fim
    assert [str(u.params["offset"]) for u in api_falsa.chamadas[1:]] == ["0", "1", "2", "3"]
    assert all(u.params["limit"] == "3" for u in api_falsa.chamadas[1:])  # default do parâmetro na spec


def test_respeita_maximo_do_limit(cliente, api_falsa):
    r = cliente.get("/api/datasets/cnes-estabelecimentos/dados", params={"max_registros": 1000}).json()
    assert r["total"] == 45 and r["paginas_consultadas"] == 4
    assert {u.params["limit"] for u in api_falsa.chamadas[1:]} == {"20"}


def test_max_registros_trunca_e_avisa(cliente):
    r = cliente.get("/api/datasets/cnes-estabelecimentos/dados", params={"max_registros": 25}).json()
    assert r["total"] == 25
    assert any("Limite de 25" in a for a in r["avisos"])


def test_selecao_de_variaveis_e_colunas_aninhadas(cliente):
    r = cliente.get(
        "/api/datasets/cnes-estabelecimentos/dados",
        params={"colunas": "codigo_cnes,endereco.uf,inexistente", "max_registros": 2},
    ).json()
    assert r["colunas"] == ["codigo_cnes", "endereco.uf", "inexistente"]
    assert r["dados"][0] == {"codigo_cnes": 0, "endereco.uf": "SP", "inexistente": None}
    assert any("inexistente" in a for a in r["avisos"])


def test_filtro_oficial_e_local(cliente):
    r = cliente.get(
        "/api/datasets/arboviroses-dengue/dados", params={"nu_ano": 2024, "id_municip": "355030"}
    ).json()
    assert r["total"] == 4
    r = cliente.get(
        "/api/datasets/arboviroses-dengue/dados", params={"nu_ano": 2024, "local.dt_notific": "2024-01-03"}
    ).json()
    assert r["total"] == 1


def test_validacao_de_filtros(cliente):
    r = cliente.get("/api/datasets/arboviroses-dengue/dados")
    assert r.status_code == 422 and "nu_ano" in r.json()["erro"]
    r = cliente.get("/api/datasets/arboviroses-dengue/dados", params={"nu_ano": "abc"})
    assert r.status_code == 422
    r = cliente.get("/api/datasets/arboviroses-dengue/dados", params={"nu_ano": 2024, "uf": "SP"})
    assert r.status_code == 422 and "Disponíveis" in r.json()["erro"]
    r = cliente.get("/api/datasets/cnes-estabelecimentos/dados", params={"status": 5})
    assert r.status_code == 422


def test_parametro_de_caminho(cliente, api_falsa):
    r = cliente.get("/api/datasets/cnes-estabelecimentos-codigo_cnes/dados", params={"codigo_cnes": 2077485}).json()
    assert r["dados"] == [{"codigo_cnes": 2077485, "nome_fantasia": "UBS X"}]
    assert api_falsa.chamadas[-1].path == "/cnes/estabelecimentos/2077485"


def test_post_com_corpo_json(cliente):
    r = cliente.post(
        "/api/datasets/arboviroses-dengue/dados",
        json={"filtros": {"nu_ano": 2024}, "colunas": ["dt_notific"], "max_registros": 4},
    ).json()
    assert r["total"] == 4 and r["dados"][0] == {"dt_notific": "2024-01-01"}


def test_saida_csv(cliente):
    r = cliente.get(
        "/api/datasets/arboviroses-dengue/dados",
        params={"nu_ano": 2024, "formato": "csv", "separador": ";", "colunas": "dt_notific,id_municip"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    linhas = r.content.decode("utf-8-sig").strip().split("\n")
    assert linhas[0] == "dt_notific;id_municip"
    assert len(linhas) == 1 + len(DENGUE)


def test_variaveis_documentadas_e_amostra(cliente):
    r = cliente.get("/api/datasets/arboviroses-dengue/variaveis").json()
    assert [c["nome"] for c in r["documentadas"]] == ["dt_notific", "id_municip", "classi_fin"]
    assert [f["nome"] for f in r["filtros"]] == ["nu_ano", "id_municip"]
    assert "amostra" not in r
    # sem filtro obrigatório, a amostra não é possível e a API avisa
    r = cliente.get("/api/datasets/arboviroses-dengue/variaveis", params={"amostra": True}).json()
    assert r["amostra"] is None and "nu_ano" in r["aviso"]
    r = cliente.get("/api/datasets/arboviroses-dengue/variaveis", params={"amostra": True, "nu_ano": 2024}).json()
    assert r["amostra"]["variaveis"] == ["dt_notific", "id_municip", "classi_fin"]
    # base sem schema documentado: amostra automática
    r = cliente.get("/api/datasets/cnes-estabelecimentos/variaveis").json()
    assert r["amostra"]["variaveis"] == ["codigo_cnes", "nome_fantasia", "endereco.uf"]


def test_pagina_repetida_interrompe(cliente, api_falsa):
    api_falsa.ignorar_offset = True
    r = cliente.get("/api/datasets/cnes-estabelecimentos/dados", params={"max_registros": 100}).json()
    assert r["total"] == 20 and r["paginas_consultadas"] == 2
    assert any("mesma página" in a for a in r["avisos"])


def test_erro_da_api_oficial_vira_502(cliente):
    r = cliente.get("/api/datasets/arboviroses-dengue/dados", params={"nu_ano": 2024, "id_municip": "erro"})
    assert r.status_code == 502 and r.json()["status_origem"] == 400
    # limit acima do máximo declarado na especificação é barrado antes de chamar a API
    r = cliente.get("/api/datasets/cnes-estabelecimentos/dados", params={"limit": 50})
    assert r.status_code == 422


def test_cache_da_especificacao(config, api_falsa, tmp_path):
    import httpx
    from fastapi.testclient import TestClient

    from app.main import criar_app

    with TestClient(criar_app(config, transport=httpx.MockTransport(api_falsa))):
        pass
    assert json.loads(config.spec_cache.read_text())["info"]["version"] == "0.0-teste"

    def fora_do_ar(_):
        return httpx.Response(503)

    with TestClient(criar_app(config, transport=httpx.MockTransport(fora_do_ar))) as c:
        assert c.get("/api/catalogo").json()["origem"].startswith("cache:")


def test_catalogo_indisponivel_vira_503(tmp_path):
    import httpx
    from fastapi.testclient import TestClient

    from app.config import Config
    from app.main import criar_app

    cfg = Config(base_url="https://x", spec_urls=["https://x/s"], spec_cache=tmp_path / "nada.json", tentativas=1)
    with TestClient(criar_app(cfg, transport=httpx.MockTransport(lambda _: httpx.Response(503)))) as c:
        assert c.get("/health").json()["catalogo_carregado"] is False
        assert c.get("/api/datasets").status_code == 503


def test_extrair_registros_formatos():
    assert extrair_registros([{"a": 1}]) == [{"a": 1}]
    assert extrair_registros({"x": [{"a": 1}]}) == [{"a": 1}]
    assert extrair_registros({"a": 1, "b": [1]}) == [{"a": 1, "b": [1]}]
    assert extrair_registros(None) == []
    assert achatar({"a": {"b": {"c": 1}}, "l": [1, 2]}) == {"a.b.c": 1, "l": "[1, 2]"}


def test_maximo_lido_da_descricao():
    from app.catalogo import _maximo_da_descricao

    assert _maximo_da_descricao("Quantidade de itens retornados por página. Deve ser menor ou igual 20.") == 20
    assert _maximo_da_descricao("Quantidade de registros por página (máximo: 500).") == 500
    assert _maximo_da_descricao("Quantidade por página") is None


def test_paginacao_que_comeca_em_1_sem_enviar_campos(config, api_falsa):
    import httpx
    from fastapi.testclient import TestClient

    from app.main import criar_app
    from tests.conftest import SPEC

    spec = json.loads(json.dumps(SPEC))
    spec["paths"]["/bps"] = {
        "get": {
            "parameters": [
                {"name": "pagina", "in": "query", "type": "integer", "default": 1},
                {"name": "tamanhoPagina", "in": "query", "type": "integer", "description": "(máximo: 500)."},
                {"name": "campos", "in": "query", "type": "string"},
            ]
        }
    }
    chamadas = []

    def handler(req):
        chamadas.append(req.url)
        if req.url.path == "/spec.json":
            return httpx.Response(200, json=spec)
        pagina = int(req.url.params["pagina"])
        itens = [{"id": i, "preco": i * 2, "extra": "x"} for i in range(700)]
        ini = (pagina - 1) * int(req.url.params["tamanhoPagina"])
        return httpx.Response(200, json={"itens": itens[ini:ini + 500]})

    with TestClient(criar_app(config, transport=httpx.MockTransport(handler))) as c:
        r = c.get("/api/datasets/bps/dados", params={"colunas": "id,preco", "max_registros": 5000}).json()
    assert r["total"] == 700 and r["paginas_consultadas"] == 3
    assert r["dados"][0] == {"id": 0, "preco": 0}
    assert [u.params["pagina"] for u in chamadas[1:]] == ["1", "2", "3"]
    # "campos" derruba a API oficial (502), então nunca é enviado automaticamente
    assert all(u.params["tamanhoPagina"] == "500" and "campos" not in u.params for u in chamadas[1:])


def test_saida_xlsx(cliente):
    import io

    from openpyxl import load_workbook

    r = cliente.get(
        "/api/datasets/arboviroses-dengue/dados",
        params={"nu_ano": 2024, "formato": "xlsx", "colunas": "dt_notific,id_municip"},
    )
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    linhas = list(wb["dados"].values)
    assert linhas[0] == ("dt_notific", "id_municip") and len(linhas) == 1 + len(DENGUE)
    assert ("Registros", len(DENGUE)) in list(wb["consulta"].values)


def test_cli_filtros_e_resumo(tmp_path, monkeypatch, api_falsa, config):
    import httpx

    from app import cli
    from app.cliente import ClienteDataSUS

    assert cli._filtros(["nu_ano=2024; id_municip=355030", "x=1"]) == {"nu_ano": "2024", "id_municip": "355030", "x": "1"}

    original = ClienteDataSUS.__init__
    monkeypatch.setattr(
        ClienteDataSUS, "__init__", lambda self, cfg, transport=None: original(self, cfg, httpx.MockTransport(api_falsa))
    )
    monkeypatch.setattr(cli.Config, "do_ambiente", classmethod(lambda cls: config))
    saida, resumo = tmp_path / "d.xlsx", tmp_path / "r.md"
    codigo = cli.main(["dados", "arboviroses-dengue", "-f", "nu_ano=2024", "-o", str(saida), "--resumo", str(resumo)])
    assert codigo == 0 and saida.stat().st_size > 0
    texto = resumo.read_text()
    assert "7 registro(s)" in texto and "| dt_notific | id_municip | classi_fin |" in texto


def _app_com(config, handler):
    import httpx
    from fastapi.testclient import TestClient

    from app.main import criar_app

    return TestClient(criar_app(config, transport=httpx.MockTransport(handler)))


SPEC_SIMPLES = {
    "swagger": "2.0",
    "paths": {"/base": {"get": {"parameters": [
        {"name": "limit", "in": "query", "type": "integer", "description": "Deve ser menor ou igual 1000."},
        {"name": "offset", "in": "query", "type": "integer", "default": 0},
    ]}}},
}


def test_avisa_quando_a_api_devolve_paginas_incompletas(config):
    """Imita o SIA real: pede 1000, vem 1 registro por página, mas as páginas seguintes têm dados."""
    import httpx

    def handler(req):
        if req.url.path == "/spec.json":
            return httpx.Response(200, json=SPEC_SIMPLES)
        off = int(req.url.params["offset"])
        return httpx.Response(200, json={"b": [{"id": off, "qt": 1}] if off < 5 else []})

    with _app_com(config, handler) as c:
        r = c.get("/api/datasets/base/dados", params={"somar": "qt", "max_registros": 0}).json()
    assert r["total"] == 5 and r["paginas_consultadas"] == 6
    assert any("páginas incompletas (1 registro(s) quando foram pedidos 1000)" in a for a in r["avisos"])
    assert any("INCOMPLETOS" in a for a in r["avisos"])


def test_avisa_quando_a_api_ignora_a_pagina(config):
    """Imita o CNES-leitos real: qualquer offset devolve o mesmo registro."""
    import httpx

    def handler(req):
        if req.url.path == "/spec.json":
            return httpx.Response(200, json=SPEC_SIMPLES)
        return httpx.Response(200, json={"b": [{"id": 1, "qt": 2}]})

    with _app_com(config, handler) as c:
        r = c.get("/api/datasets/base/dados", params={"somar": "qt", "max_registros": 0}).json()
    assert r["total"] == 1 and r["paginas_consultadas"] == 2
    assert r["agregado"]["totais"] == {"registros": 1, "soma_qt": 2}
    assert any("mesma página para páginas diferentes" in a for a in r["avisos"])
