# -*- mode: python ; coding: utf-8 -*-
"""Gera o app de computador do API-SUS (um único executável) com o PyInstaller.

    pip install -r requirements.txt pyinstaller
    pyinstaller --noconfirm --clean api-sus.spec

Saída: dist/API-SUS (Linux e macOS) ou dist/API-SUS.exe (Windows).
O workflow .github/workflows/app-desktop.yml faz isso nos três sistemas.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

RAIZ = Path(SPECPATH)
sys.path.insert(0, str(RAIZ))


def modulos_do_pacote(pasta: Path, pacote: str) -> list[str]:
    """Todos os módulos de app/, lidos do disco (sem importar nada): inclui os que
    forem criados depois e não falha se algum ainda não existir."""
    nomes = []
    for arquivo in sorted(pasta.rglob("*.py")):
        relativo = arquivo.relative_to(pasta).with_suffix("")
        partes = [p for p in relativo.parts if p != "__init__"]
        if "__pycache__" in relativo.parts:
            continue
        nomes.append(".".join([pacote, *partes]))
    return nomes


ocultos = [
    *modulos_do_pacote(RAIZ / "app", "app"),
    # uvicorn carrega estes módulos a partir de texto (app.desktop usa asyncio + h11, sem websockets)
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    *collect_submodules("uvicorn"),
    "httpx",
    "h11",
    "anyio",
    "certifi",
    "openpyxl",
    "duckdb",
    # O duckdb importa estes módulos de dentro do código C++ (invisível ao PyInstaller);
    # sem eles, consultas com parâmetros falham com "Required module 'uuid' failed to import".
    "uuid",
    "decimal",
    "datetime",
    "pathlib",
    "collections",
    "collections.abc",
    "typing",
    "json",
    "numbers",
    "inspect",
]

dados = [
    (str(RAIZ / "docs" / "index.html"), "docs"),
    (str(RAIZ / "docs" / "swagger.json"), "docs"),
    (str(RAIZ / "docs" / "variaveis.json"), "docs"),
]

a = Analysis(
    [str(RAIZ / "app" / "desktop.py")],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=dados,
    hiddenimports=ocultos,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "_pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="API-SUS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX aumenta os alarmes falsos de antivírus
    runtime_tmpdir=None,
    console=True,  # a janela do terminal mostra o endereço; fechá-la encerra o app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
