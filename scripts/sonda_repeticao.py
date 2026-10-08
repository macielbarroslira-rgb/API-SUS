"""Sonda: a partir de que página a base de UBS começa a repetir registros?"""

import hashlib
import json
import time
import urllib.request

BASE = "https://apidadosabertos.saude.gov.br/assistencia-a-saude/unidade-basicas-de-saude"


def pagina(offset, limit=1000):
    req = urllib.request.Request(f"{BASE}?limit={limit}&offset={offset}", headers={"User-Agent": "API-SUS-diagnostico"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    return next(iter(d.values())) if isinstance(d, dict) else d


vistos, cnes = set(), set()
inicio = time.monotonic()
for off in list(range(0, 80)) + [100, 200, 500, 1000, 1760]:
    regs = pagina(off)
    hashes = {hashlib.blake2b(json.dumps(r, sort_keys=True).encode(), digest_size=8).digest() for r in regs}
    novos = len(hashes - vistos)
    novos_cnes = len({r.get("cnes") for r in regs} - cnes)
    vistos |= hashes
    cnes |= {r.get("cnes") for r in regs}
    print(f"offset={off:5d} registros={len(regs):4d} novos={novos:4d} cnes_novos={novos_cnes:4d} "
          f"acumulado: registros_distintos={len(vistos)} cnes_distintos={len(cnes)} "
          f"primeiro={regs[0].get('cnes') if regs else None} ({time.monotonic() - inicio:.0f}s)")
