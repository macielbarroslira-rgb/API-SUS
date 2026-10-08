"""Agrupamento por categorias e somatórios (ex.: produção por procedimento, leitos por tipo)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_MILHAR_BR = re.compile(r"-?\d{1,3}(\.\d{3})+(,\d+)?")
_DECIMAL_VIRGULA = re.compile(r"-?\d+,\d+")


def numero(valor: Any) -> float | None:
    """Converte para número. Aceita 1234, "1234.5", "1234,5" e "1.234,56"."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return None
    if _MILHAR_BR.fullmatch(texto):
        texto = texto.replace(".", "").replace(",", ".")
    elif _DECIMAL_VIRGULA.fullmatch(texto):
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _limpo(x: float) -> int | float:
    return int(x) if float(x).is_integer() else round(x, 6)


@dataclass
class _Grupo:
    registros: int = 0
    somas: dict[str, float] = field(default_factory=dict)


@dataclass
class Agregador:
    """Acumula registros (já achatados) página a página, sem guardá-los na memória."""

    agrupar_por: list[str]
    somar: list[str]
    grupos: dict[tuple, _Grupo] = field(default_factory=dict)
    nao_numericos: dict[str, int] = field(default_factory=dict)
    vistas: set[str] = field(default_factory=set)

    def adicionar(self, plano: dict[str, Any]) -> None:
        self.vistas.update(plano)
        chave = tuple("" if plano.get(c) is None else plano.get(c) for c in self.agrupar_por)
        grupo = self.grupos.get(chave)
        if grupo is None:
            grupo = self.grupos[chave] = _Grupo(somas={c: 0.0 for c in self.somar})
        grupo.registros += 1
        for c in self.somar:
            valor = plano.get(c)
            n = numero(valor)
            if n is None:
                if valor not in (None, ""):
                    self.nao_numericos[c] = self.nao_numericos.get(c, 0) + 1
                continue
            grupo.somas[c] += n

    def colunas(self) -> list[str]:
        return [*self.agrupar_por, "registros", *(f"soma_{c}" for c in self.somar)]

    def resultado(self) -> dict[str, Any]:
        def ordem(item: tuple[tuple, _Grupo]):
            _, g = item
            primeira = g.somas[self.somar[0]] if self.somar else g.registros
            return -primeira

        linhas = []
        for chave, g in sorted(self.grupos.items(), key=ordem):
            linha: dict[str, Any] = dict(zip(self.agrupar_por, chave))
            linha["registros"] = g.registros
            for c in self.somar:
                linha[f"soma_{c}"] = _limpo(g.somas[c])
            linhas.append(linha)

        totais: dict[str, Any] = {"registros": sum(g.registros for g in self.grupos.values())}
        for c in self.somar:
            totais[f"soma_{c}"] = _limpo(sum(g.somas[c] for g in self.grupos.values()))

        avisos = []
        for c in [*self.agrupar_por, *self.somar]:
            if self.vistas and c not in self.vistas:
                avisos.append(f"Variável '{c}' não existe nos dados desta base.")
        for c, n in self.nao_numericos.items():
            avisos.append(f"{n} valor(es) não numérico(s) em '{c}' foram ignorados na soma.")
        return {
            "agrupar_por": self.agrupar_por,
            "somar": self.somar,
            "colunas": self.colunas(),
            "grupos": len(linhas),
            "linhas": linhas,
            "totais": totais,
            "avisos": avisos,
        }
