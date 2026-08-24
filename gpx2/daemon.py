# -*- coding: utf-8 -*-
"""
El demonio.

Es el proceso que está siempre encendido. Su trabajo:

  * saber qué ratón hay conectado (y enterarse si lo desconectas)
  * escuchar a los vigilantes para saber cuándo arranca o acaba un juego
  * decidir qué perfil toca y aplicarlo
  * exponer todo eso en D-Bus para que la interfaz (o un script tuyo) lo use

No dibuja nada, así que no carga Qt: son ~13 MiB en vez de ~112.

    python3 -m gpx2.daemon            con el ratón real
    python3 -m gpx2.daemon --demo     con el ratón simulado
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from .device import discover
from .engine import Motor
from .profiles import Almacen, Perfil
from .watcher.gamemode import VigilanteGameMode
from .watcher.procfs import VigilanteProcfs

NOMBRE_BUS = "io.github.rcv11x.gpx2"
RUTA_BUS = "/io/github/rcv11x/gpx2"
IFACE = "io.github.rcv11x.gpx2.Manager"

log = logging.getLogger("gpx2.daemon")


class Demonio:
    def __init__(self, demo: bool = False):
        self.demo = demo
        self.raton = None
        self.motor: Motor | None = None
        self.almacen = Almacen()
        self.jugando: dict[int, str] = {}      # pid -> id de perfil aplicado
        self._pids: set[int] = set()           # visto por CUALQUIER vigilante
        self.servicio = None                   # interfaz D-Bus, para las señales

    # -- dispositivo ----------------------------------------------------------

    def buscar_raton(self) -> bool:
        if self.demo:
            from .mock import raton_simulado
            self.raton = raton_simulado()
        else:
            hallazgo = discover()
            if hallazgo.sin_permiso:
                log.warning("hay dispositivos HID++ sin permiso de acceso: %s "
                            "(falta la regla udev)",
                            ", ".join(n.path for n in hallazgo.sin_permiso))
            self.raton = hallazgo.ratones[0] if hallazgo.ratones else None

        if self.raton is None:
            self.motor = None
            return False
        self.motor = Motor(self.raton)
        log.info("ratón: %s (%s)", self.raton.nombre, self.raton.conexion)
        return True

    async def vigilar_conexion(self) -> None:
        """Reintenta cada pocos segundos mientras no haya ratón, y detecta
        también que lo has desconectado."""
        while True:
            await asyncio.sleep(5)
            if self.raton is None:
                if self.buscar_raton():
                    self.aplicar_por_defecto("ratón conectado")
            else:
                try:
                    self.motor.estado()
                except Exception:
                    log.info("se ha perdido el ratón")
                    self.raton, self.motor = None, None

    # -- perfiles -------------------------------------------------------------

    def recargar(self) -> list[str]:
        errores = self.almacen.cargar()
        for e in errores:
            log.warning("perfil ilegible: %s", e)
        if self.motor is not None:
            creado = self.almacen.crear_por_defecto_si_falta(self.motor.estado())
            if creado:
                log.info("creado el perfil por defecto '%s' con los ajustes "
                         "actuales del ratón", creado.nombre)
        return errores

    def aplicar(self, perfil: Perfil, motivo: str = "") -> list[str]:
        if self.motor is None:
            return ["no hay ningún ratón conectado"]
        cambios = self.motor.aplicar(perfil)
        if cambios:
            log.info("perfil '%s'%s: %s", perfil.nombre,
                     f" ({motivo})" if motivo else "",
                     "; ".join(str(c) for c in cambios))
        else:
            log.info("perfil '%s'%s: ya estaba aplicado", perfil.nombre,
                     f" ({motivo})" if motivo else "")
        if self.servicio is not None:
            self.servicio.emitir_perfil(perfil.id)
        return [str(c) for c in cambios]

    def aplicar_por_defecto(self, motivo: str = "") -> None:
        perfil = self.almacen.por_defecto()
        if perfil:
            self.aplicar(perfil, motivo)

    # -- reacción a los juegos ------------------------------------------------

    def juego_empieza(self, juego) -> None:
        # Los vigilantes se solapan a propósito (GameMode es rápido, /proc es
        # la red de seguridad), así que el mismo juego llega dos veces. Nos
        # quedamos con el primer aviso y descartamos el resto.
        if juego.pid in self._pids:
            return
        self._pids.add(juego.pid)

        perfil = self.almacen.buscar_para(juego)
        if self.servicio is not None:
            self.servicio.emitir_juego(True, str(juego))
        if perfil is None:
            log.info("%s: ningún perfil coincide, se deja como está", juego)
            return
        self.jugando[juego.pid] = perfil.id
        self.aplicar(perfil, f"empieza {juego}")

    def juego_termina(self, juego) -> None:
        if juego.pid not in self._pids:
            return
        self._pids.discard(juego.pid)
        self.jugando.pop(juego.pid, None)
        if self.servicio is not None:
            self.servicio.emitir_juego(False, str(juego))
        if self.jugando:
            return                      # queda otro juego abierto: no tocamos
        self.aplicar_por_defecto(f"termina {juego}")

    def patrones(self) -> list[str]:
        """Lo que el vigilante de /proc tiene que buscar: sale de los perfiles."""
        nombres: list[str] = []
        for p in self.almacen.lista():
            nombres.extend(p.activacion.ejecutables)
        return nombres

    # -- arranque -------------------------------------------------------------

    async def arrancar(self) -> None:
        self.buscar_raton()
        self.recargar()
        if self.raton is None:
            log.warning("no hay ningún ratón compatible; el demonio sigue "
                        "en marcha y lo aplicará en cuanto lo conectes")
        else:
            self.aplicar_por_defecto("arranque")

        await self._publicar_dbus()

        vigilantes = [VigilanteGameMode(), VigilanteProcfs(self.patrones)]
        for v in vigilantes:
            try:
                await v.iniciar(self.juego_empieza, self.juego_termina)
                log.info("vigilante activo: %s", v.nombre)
            except Exception as e:
                log.warning("no se pudo iniciar el vigilante %s: %s", v.nombre, e)

        asyncio.create_task(self.vigilar_conexion())

        parar = asyncio.Event()
        bucle = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            bucle.add_signal_handler(sig, parar.set)
        log.info("listo. Ctrl-C para salir")
        await parar.wait()

        for v in vigilantes:
            await v.parar()
        log.info("adiós")

    async def _publicar_dbus(self) -> None:
        try:
            from dbus_next import BusType
            from dbus_next.aio import MessageBus
        except ImportError:
            log.warning("dbus-next no está instalado: el demonio funciona, "
                        "pero la interfaz no podrá hablar con él")
            return
        from .dbus_service import ServicioGpx2

        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        self.servicio = ServicioGpx2(self)
        bus.export(RUTA_BUS, self.servicio)
        await bus.request_name(NOMBRE_BUS)
        self._bus = bus
        log.info("publicado en D-Bus como %s", NOMBRE_BUS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Demonio de gpx2")
    ap.add_argument("--demo", action="store_true",
                    help="usa un ratón simulado en vez del real")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S")

    try:
        asyncio.run(Demonio(demo=args.demo).arrancar())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
