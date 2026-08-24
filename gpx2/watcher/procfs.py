# -*- coding: utf-8 -*-
"""
Vigilante de reserva: mirar /proc cada pocos segundos.

Feo pero universal: funciona en cualquier escritorio, con o sin GameMode, y no
depende de que el lanzador del juego coopere. Sólo busca los ejecutables que
algún perfil menciona, así que el coste es bajo aunque haya cientos de procesos.
"""

from __future__ import annotations

import asyncio
import logging
import os

from .base import Juego, Vigilante, identificar

log = logging.getLogger("gpx2.watcher.procfs")


class VigilanteProcfs(Vigilante):
    nombre = "procfs"

    def __init__(self, patrones_fn, intervalo: float = 3.0):
        """`patrones_fn` devuelve la lista de nombres a buscar. Es una función
        y no una lista porque los perfiles pueden cambiar en caliente."""
        self.patrones_fn = patrones_fn
        self.intervalo = intervalo
        self._tarea: asyncio.Task | None = None
        self._activos: dict[int, Juego] = {}

    async def iniciar(self, al_empezar, al_terminar) -> None:
        self._tarea = asyncio.create_task(self._bucle(al_empezar, al_terminar))

    async def _bucle(self, al_empezar, al_terminar) -> None:
        while True:
            try:
                self._una_pasada(al_empezar, al_terminar)
            except Exception as e:
                log.debug("fallo en la pasada: %s", e)
            await asyncio.sleep(self.intervalo)

    def _una_pasada(self, al_empezar, al_terminar) -> None:
        patrones = [p.lower() for p in self.patrones_fn() if p]

        # ¿Alguno de los que teníamos ha desaparecido?
        for pid in [p for p in self._activos if not os.path.isdir(f"/proc/{p}")]:
            juego = self._activos.pop(pid)
            log.info("juego terminado: %s", juego)
            al_terminar(juego)

        if not patrones:
            return

        for entrada in os.listdir("/proc"):
            if not entrada.isdigit():
                continue
            pid = int(entrada)
            if pid in self._activos:
                continue
            try:
                comm = open(f"/proc/{pid}/comm").read().strip().lower()
            except OSError:
                continue
            if not any(p == comm or p in comm for p in patrones):
                continue
            juego = identificar(pid, origen=self.nombre)
            if juego is None:
                continue
            self._activos[pid] = juego
            log.info("juego detectado: %s (pid %d)", juego, pid)
            al_empezar(juego)

    async def parar(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            self._tarea = None
