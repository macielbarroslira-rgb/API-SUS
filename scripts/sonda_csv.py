"""Sonda: as bases de assistência devolvem mais registros pedindo CSV (Accept: text/csv)?"""

import json
import time
import urllib.request

BASE = "https://apidadosabertos.saude.gov.br"


def get(caminho, accept):
    req = urllib.request.Request(BASE + caminho, headers={"Accept": accept, "User-Agent": "API-SUS-diagnostico"})
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.headers.get("Content-Type"), r.read(), time.monotonic() - inicio
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read(), time.monotonic() - inicio


for caminho in [
    "/assistencia-a-saude/sia-procedimentos-ambulatoriais?limit=1000&offset=0",
    "/assistencia-a-saude/sia-procedimentos-ambulatoriais?nu_comp=202401&co_ibge=355030&limit=1000&offset=0",
    "/assistencia-a-saude/cnes-leitos?limit=1000&offset=0",
    "/assistencia-a-saude/cnes-leitos?nu_comp=202401&co_ibge=355030&limit=1000&offset=0",
    "/assistencia-a-saude/hospitais-e-leitos?limit=50&offset=0",
]:
    for accept in ("application/json", "text/csv"):
        status, tipo, corpo, dur = get(caminho, accept)
        texto = corpo.decode("utf-8", "replace")
        if "json" in (tipo or ""):
            try:
                d = json.loads(texto)
                n = len(next(iter(d.values()))) if isinstance(d, dict) else len(d)
            except Exception:  # noqa: BLE001
                n = "?"
            info = f"registros JSON={n}"
        else:
            linhas = [x for x in texto.splitlines() if x.strip()]
            info = f"linhas CSV={len(linhas)} (com cabeçalho) | início: {texto[:160]!r}"
        print(f"{caminho} [Accept {accept}] status={status} tipo={tipo} {dur:.1f}s {info}")
