"""App de computador: sobe a API-SUS só nesta máquina e abre o navegador.

    python -m app.desktop

É também o ponto de entrada do executável gerado pelo PyInstaller (api-sus.spec).

Variáveis de ambiente:
    API_SUS_PORTA      porta fixa (padrão: 8765 se estiver livre; senão, qualquer porta livre)
    API_SUS_NAO_ABRIR  1 = não abre o navegador (testes, uso remoto)
    API_SUS_PASTA      pasta das bases baixadas e exportações (padrão: ~/API-SUS-dados)
"""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn

# Imports absolutos: no executável este arquivo roda como script principal (fora do pacote).
from app import __version__
from app.config import Config
from app.main import criar_app

HOST = "127.0.0.1"  # só este computador acessa o app
PORTA_PADRAO = 8765
ESPERA_MAXIMA = 300.0  # segundos; sem internet o catálogo pode demorar a cair na reserva
AVISO_DEMORA = 5.0
LINHA = "=" * 64


class ErroDesktop(Exception):
    """Problema ao iniciar o app; a mensagem já está pronta para o usuário."""


# ---------------------------------------------------------------------- #
# Porta
# ---------------------------------------------------------------------- #


def endurecer(config: Config) -> Config:
    """Segurança do app de computador: só a própria página conversa com o servidor.

    Sem CORS (a não ser que CORS_ORIGENS seja definido), com o cabeçalho Host restrito a
    127.0.0.1/localhost (contra DNS rebinding) e, pelo middleware de main.py, pedidos de
    alteração vindos de outros sites recusados. Assim um site aberto no navegador não
    consegue ler, baixar nem apagar as bases do usuário.
    """
    if not os.environ.get("CORS_ORIGENS"):
        config.cors_origens = []
    if not config.hosts_permitidos:
        config.hosts_permitidos = ["127.0.0.1", "localhost"]
    return config


def porta_livre(porta: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: não "divide" a porta com outro programa
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, porta))
        except OSError:
            return False
    return True


def porta_qualquer(host: str = HOST) -> int:
    """Uma porta livre escolhida pelo sistema operacional."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def porta_do_ambiente() -> int | None:
    texto = os.environ.get("API_SUS_PORTA", "").strip()
    if not texto:
        return None
    try:
        porta = int(texto)
    except ValueError:
        porta = 0
    if not 1 <= porta <= 65535:
        raise ErroDesktop(f"API_SUS_PORTA inválida: '{texto}'. Use um número de 1 a 65535.")
    return porta


def escolher_porta(preferida: int = PORTA_PADRAO, host: str = HOST) -> int:
    """API_SUS_PORTA, se definida; senão a preferida, se livre; senão qualquer porta livre."""
    fixa = porta_do_ambiente()
    if fixa is not None:
        if not porta_livre(fixa, host):
            raise ErroDesktop(
                f"A porta {fixa} (API_SUS_PORTA) já está em uso por outro programa. "
                "Feche esse programa ou escolha outra porta."
            )
        return fixa
    if porta_livre(preferida, host):
        return preferida
    return porta_qualquer(host)


# ---------------------------------------------------------------------- #
# Servidor
# ---------------------------------------------------------------------- #


def url_do_app(porta: int) -> str:
    return f"http://{HOST}:{porta}/"


def consultar_health(url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """GET /health direto (sem proxy do sistema: o endereço é local)."""
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with abridor.open(url + "health", timeout=timeout) as resp:
            if resp.status != 200:
                return None
            dados = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    # "catalogo_carregado" distingue o API-SUS de outro programa que use a mesma porta.
    if isinstance(dados, dict) and dados.get("status") == "ok" and "catalogo_carregado" in dados:
        return dados
    return None


def criar_servidor(config: Config, porta: int, transport: httpx.AsyncBaseTransport | None = None) -> uvicorn.Server:
    app = criar_app(config, transport=transport)
    return uvicorn.Server(
        uvicorn.Config(
            app,  # o objeto, não "app.main:app": funciona também no executável
            host=HOST,
            port=porta,
            reload=False,
            log_level="info",
            access_log=False,  # a página consulta o andamento dos downloads o tempo todo
            use_colors=False,  # o console clássico do Windows mostraria os códigos de cor como lixo
            loop="asyncio",
            http="h11",
            ws="none",
            lifespan="on",
        )
    )


def _parado(parar: threading.Event | None) -> bool:
    return parar is not None and parar.is_set()


def rodar_servidor(servidor: uvicorn.Server) -> None:
    """Corpo da thread do servidor. Se a porta não abrir, o uvicorn chama sys.exit();
    aqui isso só encerra a thread (main() percebe e avisa)."""
    try:
        servidor.run()
    except SystemExit:
        pass


def esperar_pronto(
    url: str, thread: threading.Thread, parar: threading.Event | None = None, limite: float = ESPERA_MAXIMA
) -> dict[str, Any] | None:
    """Espera o /health responder. None se o servidor morrer, demorar demais ou for interrompido."""
    inicio = time.monotonic()
    avisou = False
    while time.monotonic() - inicio < limite:
        if not thread.is_alive() or _parado(parar):
            return None
        saude = consultar_health(url)
        if saude is not None:
            return saude
        if not avisou and time.monotonic() - inicio > AVISO_DEMORA:
            print("Carregando o catálogo de bases do Ministério da Saúde (pode levar até um minuto)...", flush=True)
            avisou = True
        time.sleep(0.25)
    return None


def parar_servidor(servidor: uvicorn.Server, thread: threading.Thread, espera: float = 15.0) -> None:
    servidor.should_exit = True
    try:
        thread.join(espera)
        if thread.is_alive():
            servidor.force_exit = True
            thread.join(5.0)
    except KeyboardInterrupt:  # segundo Ctrl+C: encerra sem esperar
        servidor.force_exit = True


def _interromper(_sinal: int, _quadro: Any) -> None:
    raise KeyboardInterrupt


@contextmanager
def sinais_de_encerramento() -> Iterator[None]:
    """Fechar o terminal (SIGHUP), SIGTERM e Ctrl+Break encerram com a mesma elegância do Ctrl+C."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    anteriores: dict[int, Any] = {}
    for nome in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        sinal = getattr(signal, nome, None)
        if sinal is None or signal.getsignal(sinal) == signal.SIG_IGN:
            continue  # ignorado de propósito (ex.: nohup): respeita
        try:
            anteriores[sinal] = signal.signal(sinal, _interromper)
        except (OSError, ValueError):
            pass
    try:
        yield
    finally:
        for sinal, tratador in anteriores.items():
            signal.signal(sinal, tratador)


# ---------------------------------------------------------------------- #
# Navegador, pasta e console
# ---------------------------------------------------------------------- #


def deve_abrir_navegador() -> bool:
    return os.environ.get("API_SUS_NAO_ABRIR", "").strip().lower() not in {"1", "true", "sim", "yes", "on"}


def _restaurar_bibliotecas_do_sistema() -> None:
    """No Linux, o executável do PyInstaller aponta LD_LIBRARY_PATH para as bibliotecas
    embutidas; o navegador precisa das do sistema."""
    meipass = getattr(sys, "_MEIPASS", None)
    valor = os.environ.get("LD_LIBRARY_PATH")
    if not meipass or valor is None or meipass not in valor:
        return
    original = os.environ.get("LD_LIBRARY_PATH_ORIG")
    if original:
        os.environ["LD_LIBRARY_PATH"] = original
    else:
        del os.environ["LD_LIBRARY_PATH"]


def abrir_navegador(url: str) -> bool:
    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False  # sem tela: evita abrir um navegador de texto dentro deste terminal
        _restaurar_bibliotecas_do_sistema()
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:  # noqa: BLE001 - qualquer falha aqui só impede a abertura automática
        return False


def preparar_pasta(pasta: Path) -> str | None:
    """Cria a pasta de dados (bases/ e exportacoes/). Devolve um aviso se não conseguir."""
    try:
        for sub in ("bases", "exportacoes"):
            (pasta / sub).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"Não foi possível criar a pasta de dados {pasta}: {exc}"
    return None


def preparar_console() -> None:
    """Evita que um caractere acentuado derrube o app num console sem UTF-8."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def _pausar_se_janela() -> None:
    """No executável aberto com dois cliques, mantém a janela aberta para a mensagem de erro ser lida."""
    if not getattr(sys, "frozen", False):
        return
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("\nPressione Enter para fechar...")
    except (EOFError, KeyboardInterrupt, OSError):
        pass


def _avisos_do_catalogo(saude: dict[str, Any]) -> list[str]:
    origem = saude.get("origem_catalogo") or ""
    if not saude.get("catalogo_carregado"):
        return [
            "Atenção: não foi possível carregar o catálogo de bases agora "
            f"({saude.get('erro_catalogo') or 'motivo desconhecido'}). Verifique a internet."
        ]
    if origem.startswith(("reserva:", "cache:")):
        return [
            "Sem acesso à API oficial agora: usando a lista de bases guardada no app. "
            "Para baixar dados é preciso internet."
        ]
    return []


def anunciar(url: str, config: Config, saude: dict[str, Any], abrir: bool) -> None:
    for aviso in _avisos_do_catalogo(saude):
        print(aviso, flush=True)
    linhas = [
        "",
        LINHA,
        f"  API-SUS rodando em {url}",
        f"  Seus dados ficam em: {config.pasta_dados}",
        "  Feche esta janela (ou aperte Ctrl+C) para encerrar.",
        LINHA,
        "",
    ]
    print("\n".join(linhas), flush=True)
    if abrir and not abrir_navegador(url):
        print(f"Abra no navegador: {url}", flush=True)


def acompanhar(
    servidor: uvicorn.Server,
    thread: threading.Thread,
    url: str,
    config: Config,
    abrir: bool,
    parar: threading.Event | None,
) -> int:
    """Espera o servidor ficar pronto, avisa o usuário e fica de guarda até o fim. Devolve o código de saída."""
    saude = esperar_pronto(url, thread, parar)
    if saude is None:
        if _parado(parar):
            return 0
        if not thread.is_alive():
            erro = f"o servidor não conseguiu iniciar em {url} (veja as mensagens acima)."
        else:
            erro = f"o servidor não respondeu em {ESPERA_MAXIMA:.0f} s."
        print(f"Erro: {erro}", file=sys.stderr, flush=True)
        return 1
    anunciar(url, config, saude, abrir)
    while thread.is_alive() and not _parado(parar):
        thread.join(0.5)  # espera curta: o Ctrl+C é atendido logo
    if not thread.is_alive() and not servidor.should_exit:
        print("Erro: o servidor parou inesperadamente.", file=sys.stderr, flush=True)
        return 1
    return 0


# ---------------------------------------------------------------------- #
# Programa
# ---------------------------------------------------------------------- #


def main(
    config: Config | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    parar: threading.Event | None = None,
) -> int:
    """Sobe o servidor e fica rodando até Ctrl+C, a janela ser fechada ou `parar` ser acionado.

    `config`, `transport` e `parar` existem para os testes; o app usa os padrões.
    """
    print(f"API-SUS {__version__} - bases de dados abertos do Ministério da Saúde no seu computador", flush=True)
    abrir = deve_abrir_navegador()
    try:
        config = endurecer(config or Config.do_ambiente())
        fixa = porta_do_ambiente()
        if fixa is None and not porta_livre(PORTA_PADRAO) and consultar_health(url_do_app(PORTA_PADRAO)):
            url = url_do_app(PORTA_PADRAO)
            print(f"O API-SUS já está aberto em outra janela: {url}", flush=True)
            if abrir and abrir_navegador(url):
                print("Abrindo o navegador.", flush=True)
            return 0
        porta = escolher_porta()
    except (ErroDesktop, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr, flush=True)
        return 1

    aviso_pasta = preparar_pasta(config.pasta_dados)
    if aviso_pasta:
        print(f"Atenção: {aviso_pasta}", file=sys.stderr, flush=True)

    url = url_do_app(porta)
    servidor = criar_servidor(config, porta, transport)
    thread = threading.Thread(target=rodar_servidor, args=(servidor,), name="api-sus-servidor", daemon=True)
    print(f"Iniciando em {url} ...", flush=True)
    thread.start()

    codigo = 1
    with sinais_de_encerramento():
        try:
            codigo = acompanhar(servidor, thread, url, config, abrir, parar)
        except KeyboardInterrupt:
            print("\nEncerrando o API-SUS...", flush=True)
            codigo = 0
        parar_servidor(servidor, thread)
    print("API-SUS encerrado.", flush=True)
    return codigo


if __name__ == "__main__":
    multiprocessing.freeze_support()  # exigido pelo PyInstaller no Windows
    preparar_console()
    resultado = main()
    if resultado:
        _pausar_se_janela()
    sys.exit(resultado)
