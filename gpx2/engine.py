# -*- coding: utf-8 -*-
"""
Capa 4b — Motor de aplicación.

Coge un perfil y lo aplica al ratón. Su única regla interesante: **manda sólo
lo que cambia**. Reenviar un ajuste que ya está puesto no es inofensivo — cada
escritura consume ciclos de la memoria del ratón y añade una oportunidad de
fallo. Además, así el registro de actividad dice algo útil ("DPI 800 → 1600")
en vez de repetir lo mismo cada vez que arranca un juego.
"""

from __future__ import annotations

from dataclasses import dataclass

from .profiles import Ajustes, Perfil


@dataclass
class Cambio:
    ajuste: str
    de: object
    a: object
    ok: bool = True
    error: str | None = None

    def __str__(self) -> str:
        flecha = f"{self.ajuste}: {self.de} → {self.a}"
        return flecha if self.ok else f"{flecha}  ✗ {self.error}"


class Motor:
    def __init__(self, raton):
        self.raton = raton
        self.perfil_activo: str | None = None

    # -- lectura --------------------------------------------------------------

    def estado(self) -> Ajustes:
        """Los ajustes actuales del ratón, en el mismo formato que un perfil."""
        actual = Ajustes()
        if self.raton.dpi is not None:
            try:
                actual.dpi = self.raton.dpi.get().actual
            except Exception:
                pass
        if self.raton.rate is not None:
            try:
                actual.report_rate_hz = self.raton.rate.get().actual_hz
            except Exception:
                pass
        return actual

    # -- escritura ------------------------------------------------------------

    def aplicar(self, perfil: Perfil) -> list[Cambio]:
        """Aplica el perfil y devuelve la lista de cambios efectuados."""
        actual = self.estado()
        cambios: list[Cambio] = []

        for ajuste, valor in perfil.ajustes.campos().items():
            previo = getattr(actual, ajuste, None)
            if previo == valor:
                continue                       # ya estaba: no se toca
            cambio = Cambio(ajuste, previo, valor)
            try:
                self._escribir(ajuste, valor)
            except Exception as e:
                cambio.ok = False
                cambio.error = str(e)
            cambios.append(cambio)

        self.perfil_activo = perfil.id
        return cambios

    def _escribir(self, ajuste: str, valor) -> None:
        if ajuste == "dpi":
            if self.raton.dpi is None:
                raise RuntimeError("el ratón no permite ajustar el DPI")
            self.raton.dpi.set(int(valor))
        elif ajuste == "report_rate_hz":
            if self.raton.rate is None:
                raise RuntimeError("el ratón no permite ajustar la tasa de reporte")
            self.raton.rate.set(int(valor))
        else:
            raise RuntimeError(f"ajuste desconocido: {ajuste}")
