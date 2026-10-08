"""Diagnóstico da API de Dados Abertos do Ministério da Saúde (roda no GitHub Actions)."""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://apidadosabertos.saude.gov.br"
ORIGEM = "https://macielbarroslira-rgb.github.io"
CANDIDATOS_SPEC = [
    f"{BASE}/v1/static/swagger.json",
    f"{BASE}/static/swagger.json",
    f"{BASE}/v1/swagger.json",
    f"{BASE}/swagger.json",
    f"{BASE}/v1/openapi.json",
    f"{BASE}/openapi.json",
]


def get(url, metodo="GET", extra=None):
    cab = {"Origin": ORIGEM, "Accept": "application/json", "User-Agent": "API-SUS-diagnostico"}
    cab.update(extra or {})
    req = urllib.request.Request(url, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:  # noqa: BLE001
        return None, {}, str(e).encode()


def cors(cabecalhos):
    return {k: v for k, v in cabecalhos.items() if k.lower().startswith("access-control")} or "NENHUM cabeçalho CORS"


print("=" * 70)
status, cab, corpo = get(f"{BASE}/v1/")
print(f"Página /v1/: status={status}")
html = corpo.decode("utf-8", "replace")
for trecho in ("swagger.json", "openapi.json", "url:"):
    i = html.find(trecho)
    if i >= 0:
        print(f"  trecho com '{trecho}': {html[max(0, i - 120):i + 60]!r}")

spec, spec_url = None, None
for url in CANDIDATOS_SPEC:
    status, cab, corpo = get(url)
    print(f"SPEC {url}: status={status} tipo={cab.get('Content-Type')} cors={cors(cab)}")
    if status == 200 and spec is None:
        try:
            spec, spec_url = json.loads(corpo), url
        except ValueError:
            pass

if spec is None:
    print("Nenhuma especificação encontrada.")
    sys.exit(0)

with open("swagger.json", "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False)
print("=" * 70)
print(f"Especificação: {spec_url}")
print(f"  versão={spec.get('swagger') or spec.get('openapi')} info={spec.get('info')}")
print(f"  host={spec.get('host')} basePath={spec.get('basePath')} servers={spec.get('servers')}")
caminhos = spec.get("paths", {})
print(f"  {len(caminhos)} caminhos:")
for caminho, item in caminhos.items():
    op = item.get("get")
    if not op:
        continue
    params = [f"{p.get('name')}{'*' if p.get('required') else ''}" for p in op.get("parameters", []) if isinstance(p, dict)]
    print(f"    GET {caminho}  [{', '.join(params)}]  {op.get('summary', '')}")

print("=" * 70)
testes = [
    "/arboviroses/dengue?nu_ano=2024&limit=2&offset=0",
    "/v1/arboviroses/dengue?nu_ano=2024&limit=2&offset=0",
    "/cnes/estabelecimentos?limit=2&offset=0",
    "/v1/cnes/estabelecimentos?limit=2&offset=0",
]
for t in testes:
    status, cab, corpo = get(BASE + t)
    print(f"DADOS {t}: status={status} cors={cors(cab)}")
    print(f"   corpo: {corpo[:300].decode('utf-8', 'replace')!r}")
status, cab, _ = get(
    BASE + "/cnes/estabelecimentos?limit=1", "OPTIONS", {"Access-Control-Request-Method": "GET"}
)
print(f"PREFLIGHT OPTIONS: status={status} cors={cors(cab)}")

print("=" * 70)
print("AMOSTRAS E TEMPOS")
amostras = [
    "/assistencia-a-saude/sia-procedimentos-ambulatoriais?limit=2&offset=0",
    "/assistencia-a-saude/sih-procedimentos-hospitalares?limit=2&offset=0",
    "/assistencia-a-saude/cnes-leitos?limit=2&offset=0",
    "/assistencia-a-saude/cnes-profissionais?limit=1&offset=0",
    "/arboviroses/dengue?nu_ano=2024&limit=1000&offset=0",
    "/arboviroses/dengue?nu_ano=2024&id_municip=355030&limit=100&offset=0",
]
for t in amostras:
    inicio = time.monotonic()
    status, cab, corpo = get(BASE + t)
    dur = time.monotonic() - inicio
    texto = corpo.decode("utf-8", "replace")
    print(f"{t}: status={status} {dur:.1f}s {len(corpo)} bytes")
    if "limit=1000" not in t:
        print(f"   {texto[:900]}")

print("=" * 70)
print("SONDAGEM: paginação das bases de assistência e efeito do parâmetro 'campos'")


def sonda(caminho):
    inicio = time.monotonic()
    status, _, corpo = get(BASE + caminho)
    dur = time.monotonic() - inicio
    try:
        dados = json.loads(corpo)
        lista = next(iter(dados.values())) if isinstance(dados, dict) else dados
        n = len(lista)
        chaves = [(r.get("nu_comp"), r.get("co_ibge") or r.get("id_municip"), r.get("co_cnes")) for r in lista[:3]]
    except Exception:  # noqa: BLE001
        n, chaves = None, corpo[:150]
    print(f"{caminho}\n   status={status} {dur:.1f}s registros={n} amostra={chaves}")


for base in ["/assistencia-a-saude/cnes-leitos", "/assistencia-a-saude/sia-procedimentos-ambulatoriais"]:
    for q in ["limit=10&offset=0", "limit=10&offset=1", "limit=10&offset=2", "limit=100&offset=0",
              "limit=1000&offset=0", "limit=1000&offset=1",
              "nu_comp=202401&limit=1000&offset=0", "nu_comp=202401&co_ibge=355030&limit=1000&offset=0",
              "co_ibge=355030&limit=1000&offset=0"]:
        sonda(f"{base}?{q}")
for q in ["nu_ano=2024&limit=1000&offset=0&campos=dt_notific,cs_sexo",
          "nu_ano=2024&limit=100&offset=0&campos=dt_notific,cs_sexo",
          "nu_ano=2024&limit=1000&offset=1"]:
    sonda(f"/arboviroses/dengue?{q}")
