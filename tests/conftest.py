import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import criar_app

SPEC = json.loads((Path(__file__).parent / "fixtures" / "swagger_exemplo.json").read_text(encoding="utf-8"))
BASE = "https://api.teste"

# 7 notificações de dengue em 2024 (3 por página => 3 páginas: 3, 3, 1)
DENGUE = [
    {"dt_notific": f"2024-01-0{i + 1}", "id_municip": "355030" if i % 2 == 0 else "330455", "classi_fin": "10"}
    for i in range(7)
]
# 45 estabelecimentos (limit máximo 20 => páginas de 20, 20, 5)
ESTABELECIMENTOS = [{"codigo_cnes": i, "nome_fantasia": f"UBS {i}", "endereco": {"uf": "SP"}} for i in range(45)]


class ApiFalsa:
    """Imita a API oficial: offset = número da página."""

    def __init__(self):
        self.chamadas: list[httpx.URL] = []
        self.ignorar_offset = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append(request.url)
        caminho, q = request.url.path, request.url.params
        if caminho == "/spec.json":
            return httpx.Response(200, json=SPEC)
        limit, offset = int(q.get("limit", 20)), int(q.get("offset", 0))
        if self.ignorar_offset:
            offset = 0
        if caminho == "/arboviroses/dengue":
            if q.get("id_municip") == "erro":
                return httpx.Response(400, json={"erro": "municipio invalido"})
            dados = [d for d in DENGUE if not q.get("id_municip") or d["id_municip"] == q["id_municip"]]
            return httpx.Response(200, json={"dengue": dados[offset * limit:(offset + 1) * limit]})
        if caminho == "/cnes/estabelecimentos":
            if limit > 20:
                return httpx.Response(400, json={"erro": "limit deve ser <= 20"})
            return httpx.Response(200, json={"estabelecimentos": ESTABELECIMENTOS[offset * limit:(offset + 1) * limit]})
        if caminho.startswith("/cnes/estabelecimentos/"):
            return httpx.Response(200, json={"codigo_cnes": int(caminho.rsplit("/", 1)[1]), "nome_fantasia": "UBS X"})
        return httpx.Response(404, json={"erro": "não encontrado"})


@pytest.fixture
def api_falsa():
    return ApiFalsa()


@pytest.fixture
def config(tmp_path):
    return Config(
        base_url=BASE,
        spec_urls=[f"{BASE}/spec.json"],
        spec_cache=tmp_path / "cache.json",
        tentativas=1,
        cache_ttl=0,
    )


@pytest.fixture
def cliente(config, api_falsa):
    app = criar_app(config, transport=httpx.MockTransport(api_falsa))
    with TestClient(app) as c:
        yield c
