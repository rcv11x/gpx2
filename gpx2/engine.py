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

from .features import EscrituraIgnorada
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
        # Ajustes que este ratón acepta pero no aplica (la tasa de reporte por
        # receptor, por ejemplo). Se anotan la primera vez para no reintentarlos
        # cada pocos segundos y llenar el registro de errores repetidos.
        self.imposibles: set[str] = set()

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

    def _asegurar_host(self) -> Cambio | None:
        """Pone el ratón en modo host si no lo está ya.

        Hay que comprobarlo en cada aplicación, no una sola vez: el modo host
        NO persiste — el ratón vuelve a onboard al dormirse o reconectar. Y
        mientras mande el perfil interno, el firmware reimpone su propio DPI y
        su tasa, así que todo lo que escribiéramos se perdería en silencio.
        """
        if self.raton.onboard is None:
            return None
        try:
            if self.raton.onboard.es_host():
                return None
            cambio = Cambio("modo", "onboard", "host")
            if not self.raton.asegurar_host():
                cambio.ok = False
                cambio.error = "el ratón no aceptó el cambio"
            return cambio
        except Exception as e:
            return Cambio("modo", "onboard", "host", ok=False, error=str(e))

    def aplicar(self, perfil: Perfil) -> list[Cambio]:
        """Aplica el perfil y devuelve la lista de cambios efectuados."""
        cambios: list[Cambio] = []
        # Primero el modo: pasar a host puede cambiar lo que el ratón reporta,
        # así que el estado se lee después.
        cambio_modo = self._asegurar_host()
        if cambio_modo is not None:
            cambios.append(cambio_modo)
        actual = self.estado()

        for ajuste, valor in perfil.ajustes.campos().items():
            previo = getattr(actual, ajuste, None)
            if previo == valor or ajuste in self.imposibles:
                continue                       # ya estaba, o no se puede
            cambio = Cambio(ajuste, previo, valor)
            try:
                self._escribir(ajuste, valor)
            except EscrituraIgnorada as e:
                cambio.ok = False
                cambio.error = str(e)
                self.imposibles.add(ajuste)
            except Exception as e:
                cambio.ok = False
                cambio.error = str(e)
            cambios.append(cambio)

        self.perfil_activo = perfil.id
        return cambios

    def ha_derivado(self, perfil: Perfil) -> bool:
        """¿El ratón ha dejado de tener lo que dice el perfil?

        Pasa sin avisar: al despertarse, el ratón vuelve a los ajustes de su
        perfil interno. No hay ninguna notificación que escuchar, así que la
        única forma de enterarse es mirar.
        """
        actual = self.estado()
        for ajuste, valor in perfil.ajustes.campos().items():
            if ajuste in self.imposibles:
                continue
            if getattr(actual, ajuste, None) != valor:
                return True
        return False

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
