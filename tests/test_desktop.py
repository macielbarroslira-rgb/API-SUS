"""App de computador (app/desktop.py): escolha de porta, subida do servidor e encerramento."""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from app import desktop

RAIZ = Path(__file__).resolve().parent.parent


def _ocupar() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((desktop.HOST, 0))
    sock.listen()
    return sock


def _esperar_health(porta: int, limite: float = 30.0, proc: subprocess.Popen | None = None) -> dict:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if proc is not None and proc.poll() is not None:
            pytest.fail(f"o app encerrou antes de responder:\n{proc.stdout.read() if proc.stdout else ''}")
        saude = desktop.consultar_health(desktop.url_do_app(porta))
        if saude is not None:
            return saude
        time.sleep(0.1)
    pytest.fail(f"/health não respondeu em {limite} s")


@pytest.fixture
def ambiente(monkeypatch, tmp_path, config):
    """Porta livre fixa, pasta temporária e navegador falso (só registra as URLs)."""
    porta = desktop.porta_qualquer()
    monkeypatch.setenv("API_SUS_PORTA", str(porta))
    monkeypatch.setenv("API_SUS_NAO_ABRIR", "1")
    monkeypatch.setenv("API_SUS_PASTA", str(tmp_path / "dados"))
    config.pasta_dados = tmp_path / "dados"
    abertos: list[str] = []
    monkeypatch.setattr(desktop, "abrir_navegador", lambda url: abertos.append(url) or True)
    return porta, abertos


@contextmanager
def rodando(config, api_falsa):
    """Roda desktop.main() numa thread e encerra ao sair do bloco."""
    parar = threading.Event()
    resultado: dict[str, int] = {}
    thread = threading.Thread(
        target=lambda: resultado.update(codigo=desktop.main(config, httpx.MockTransport(api_falsa), parar)),
        daemon=True,
    )
    thread.start()
    try:
        yield resultado
    finally:
        parar.set()
        thread.join(30)
        assert not thread.is_alive(), "o servidor não encerrou"


# ---------------------------------------------------------------------- #
# Porta
# ---------------------------------------------------------------------- #


def test_usa_a_porta_preferida_quando_livre(monkeypatch):
    monkeypatch.delenv("API_SUS_PORTA", raising=False)
    livre = desktop.porta_qualquer()
    assert desktop.porta_livre(livre)
    assert desktop.escolher_porta(livre) == livre


def test_porta_ocupada_escolhe_outra_livre(monkeypatch):
    monkeypatch.delenv("API_SUS_PORTA", raising=False)
    with _ocupar() as sock:
        ocupada = sock.getsockname()[1]
        assert not desktop.porta_livre(ocupada)
        porta = desktop.escolher_porta(ocupada)
        assert porta != ocupada
        assert desktop.porta_livre(porta)


def test_porta_da_variavel_de_ambiente(monkeypatch):
    livre = desktop.porta_qualquer()
    monkeypatch.setenv("API_SUS_PORTA", str(livre))
    assert desktop.escolher_porta(1) == livre
    with _ocupar() as sock:
        monkeypatch.setenv("API_SUS_PORTA", str(sock.getsockname()[1]))
        with pytest.raises(desktop.ErroDesktop, match="já está em uso"):
            desktop.escolher_porta()
    for invalida in ("abc", "0", "70000"):
        monkeypatch.setenv("API_SUS_PORTA", invalida)
        with pytest.raises(desktop.ErroDesktop, match="inválida"):
            desktop.escolher_porta()


# ---------------------------------------------------------------------- #
# main()
# ---------------------------------------------------------------------- #


def test_main_sobe_o_servidor_e_health_responde(config, api_falsa, ambiente, tmp_path, capsys):
    porta, abertos = ambiente
    url = desktop.url_do_app(porta)
    with rodando(config, api_falsa) as resultado:
        saude = _esperar_health(porta)
        assert saude["catalogo_carregado"] is True
        with httpx.Client(trust_env=False, timeout=10) as http:
            assert http.get(url + "health").json()["status"] == "ok"
            assert http.get(url + "api/datasets").json()["total"] == 3
            pagina = http.get(url)
            assert pagina.status_code == 200 and "<html" in pagina.text.lower()
    assert resultado["codigo"] == 0
    assert abertos == []  # API_SUS_NAO_ABRIR=1
    assert (tmp_path / "dados" / "bases").is_dir() and (tmp_path / "dados" / "exportacoes").is_dir()
    saida = capsys.readouterr().out
    assert f"API-SUS rodando em {url}" in saida
    assert str(tmp_path / "dados") in saida
    assert "feche esta janela" in saida.lower()
    assert "API-SUS encerrado." in saida


def test_main_abre_o_navegador(config, api_falsa, ambiente, monkeypatch):
    porta, abertos = ambiente
    monkeypatch.delenv("API_SUS_NAO_ABRIR")
    with rodando(config, api_falsa):
        _esperar_health(porta)
        fim = time.monotonic() + 10
        while not abertos and time.monotonic() < fim:
            time.sleep(0.05)
    assert abertos == [desktop.url_do_app(porta)]


def test_segunda_abertura_reaproveita_o_app_ja_aberto(config, api_falsa, ambiente, monkeypatch, capsys):
    porta, abertos = ambiente
    with rodando(config, api_falsa):
        _esperar_health(porta)
        # Dois cliques de novo: a porta padrão está com o API-SUS, então só abre o navegador.
        monkeypatch.setattr(desktop, "PORTA_PADRAO", porta)
        monkeypatch.delenv("API_SUS_PORTA")
        monkeypatch.delenv("API_SUS_NAO_ABRIR")
        assert desktop.main(config) == 0
        assert abertos == [desktop.url_do_app(porta)]
    assert "já está aberto" in capsys.readouterr().out


def test_main_com_porta_ocupada_por_outro_programa(config, ambiente, monkeypatch, capsys):
    with _ocupar() as sock:
        monkeypatch.setenv("API_SUS_PORTA", str(sock.getsockname()[1]))
        assert desktop.main(config) == 1
    assert "já está em uso" in capsys.readouterr().err


# ---------------------------------------------------------------------- #
# Processo de verdade: Ctrl+C e SIGTERM encerram com elegância
# ---------------------------------------------------------------------- #


@pytest.mark.skipif(sys.platform == "win32", reason="sinais POSIX")
@pytest.mark.parametrize("sinal", [signal.SIGINT, signal.SIGTERM], ids=["ctrl-c", "sigterm"])
def test_processo_encerra_com_elegancia(tmp_path, sinal):
    porta = desktop.porta_qualquer()
    env = {
        **os.environ,
        "API_SUS_NAO_ABRIR": "1",
        "API_SUS_PORTA": str(porta),
        "API_SUS_PASTA": str(tmp_path / "dados"),
        # sem rede: o catálogo vem da especificação de teste
        "DATASUS_SPEC_ARQUIVO": str(RAIZ / "tests" / "fixtures" / "swagger_exemplo.json"),
        "DATASUS_SPEC_CACHE": str(tmp_path / "cache.json"),
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.desktop"],
        cwd=RAIZ,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    try:
        saude = _esperar_health(porta, proc=proc)
        assert saude["origem_catalogo"].startswith("arquivo:")
        proc.send_signal(sinal)
        saida, _ = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, saida
    assert "Traceback" not in saida
    assert "API-SUS encerrado." in saida


# ---------------------------------------------------------------------- #
# Navegador
# ---------------------------------------------------------------------- #


def test_navegador_no_linux_sem_tela_nao_abre(monkeypatch):
    chamadas: list[str] = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, new=0: chamadas.append(url) or True)
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert desktop.abrir_navegador("http://127.0.0.1:1/") is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert desktop.abrir_navegador("http://127.0.0.1:1/") is True
    assert chamadas == ["http://127.0.0.1:1/"]


def test_executavel_linux_devolve_as_bibliotecas_do_sistema_ao_navegador(monkeypatch):
    monkeypatch.setattr(desktop.sys, "_MEIPASS", "/tmp/_MEIabc", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIabc")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/meu")
    desktop._restaurar_bibliotecas_do_sistema()
    assert os.environ["LD_LIBRARY_PATH"] == "/usr/lib/meu"
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIabc")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    desktop._restaurar_bibliotecas_do_sistema()
    assert "LD_LIBRARY_PATH" not in os.environ
