# -*- coding: utf-8 -*-
"""
Vigilante principal: Feral GameMode.

Es la fuente de mejor calidad que existe en Linux para saber que ha arrancado
un juego. Steam, Lutris, Heroic y Bottles activan GameMode por su cuenta, y
GameMode publica en D-Bus el PID exacto en el momento de arrancar. Nada de
sondear, nada de adivinar por el nombre de la ventana.

    señal GameRegistered(pid, ruta)    -> ha empezado
    señal GameUnregistered(pid, ruta)  -> ha terminado
"""

from __future__ import annotations

import logging

from .base import Juego, Vigilante, identificar

SERVICIO = "com.feralinteractive.GameMode"
RUTA = "/com/feralinteractive/GameMode"
IFACE = "com.feralinteractive.GameMode"

log = logging.getLogger("gpx2.watcher.gamemode")


class VigilanteGameMode(Vigilante):
    nombre = "gamemode"

    def __init__(self):
        self.bus = None
        self.iface = None
        self._al_empezar = None
        self._al_terminar = None
        self._vistos: dict[int, Juego] = {}

    async def iniciar(self, al_empezar, al_terminar) -> None:
        from dbus_next import BusType
        from dbus_next.aio import MessageBus

        self._al_empezar, self._al_terminar = al_empezar, al_terminar
        self.bus = await MessageBus(bus_type=BusType.SESSION).connect()

        # GameMode es un servicio "activable": si preguntamos por él sin más,
        # D-Bus lo arrancaría. No queremos arrancar gamemoded sólo porque
        # nuestro demonio se haya iniciado, así que primero comprobamos si ya
        # está vivo, y si no, esperamos a que aparezca.
        dbus_obj = self.bus.get_proxy_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            await self.bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus"))
        dbus_iface = dbus_obj.get_interface("org.freedesktop.DBus")

        if await dbus_iface.call_name_has_owner(SERVICIO):
            await self._conectar()
        else:
            log.info("GameMode no está en marcha; esperando a que aparezca")

            def cambio_de_dueño(nombre, antiguo, nuevo):
                if nombre == SERVICIO and nuevo:
                    import asyncio
                    asyncio.create_task(self._conectar())

            dbus_iface.on_name_owner_changed(cambio_de_dueño)

    async def _conectar(self) -> None:
        if self.iface is not None:
            return
        obj = self.bus.get_proxy_object(
            SERVICIO, RUTA, await self.bus.introspect(SERVICIO, RUTA))
        self.iface = obj.get_interface(IFACE)
        self.iface.on_game_registered(self._registrado)
        self.iface.on_game_unregistered(self._retirado)
        log.info("conectado a GameMode")

        # Puede que ya hubiera un juego corriendo antes que nosotros.
        try:
            for pid, _ruta in await self.iface.call_list_games():
                self._registrado(pid, "")
        except Exception as e:
            log.debug("no se pudo consultar la lista de juegos: %s", e)

    # -- manejadores de señal -------------------------------------------------

    def _registrado(self, pid: int, _ruta: str) -> None:
        if pid in self._vistos:
            return
        juego = identificar(pid, origen=self.nombre)
        if juego is None:
            return
        self._vistos[pid] = juego
        log.info("juego detectado: %s (pid %d)", juego, pid)
        if self._al_empezar:
            self._al_empezar(juego)

    def _retirado(self, pid: int, _ruta: str) -> None:
        juego = self._vistos.pop(pid, None)
        if juego is None:
            return
        log.info("juego terminado: %s", juego)
        if self._al_terminar:
            self._al_terminar(juego)

    async def parar(self) -> None:
        if self.bus is not None:
            self.bus.disconnect()
            self.bus = None
            self.iface = None
