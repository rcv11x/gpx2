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
from .transport import DispositivoOcupado
from .engine import Motor
from .profiles import Almacen, Perfil, leer_modo_preferido
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
        self.almacen = Almacen(demo=demo)
        self._bus = None
        self._id_aviso = 0
        self._dpi_visto: int | None = None
        self._aviso_onboard = False
        # Pings fallidos seguidos. Por radio se pierde alguno de vez en cuando,
        # y uno solo no puede significar "lo has desconectado".
        self._fallos_seguidos = 0
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
        # La tasa se recuerda en disco porque el ratón no informa de la suya;
        # en modo demo va a otra carpeta, como los perfiles.
        if self.raton.rate is not None and hasattr(self.raton.rate, "demo"):
            self.raton.rate.demo = self.demo
        self.motor = Motor(self.raton)
        log.info("ratón: %s (%s)", self.raton.nombre, self.raton.conexion)
        return True

    # Cada cuánto se mira. El DPI mucho más a menudo que la conexión: cambia
    # cuando pulsas el botón del ratón, y avisarte cinco segundos después de
    # haberlo pulsado no sirve de nada. Peor: si ciclas dos veces seguidas, con
    # cinco segundos sólo se ve la última y parece que el aviso salga a ratos.
    CADA_DPI = 1.5
    CADA_CONEXION = 5.0

    async def vigilar_conexion(self) -> None:
        """Reintenta mientras no haya ratón, y detecta que lo has desconectado."""
        desde_la_ultima = 0.0
        while True:
            await asyncio.sleep(self.CADA_DPI)
            desde_la_ultima += self.CADA_DPI
            completa = desde_la_ultima >= self.CADA_CONEXION
            if completa:
                desde_la_ultima = 0.0
            await self.revisar_conexion(completa=completa)

    async def revisar_conexion(self, completa: bool = True) -> None:
        """Un ciclo de vigilancia. Separado del bucle para poder probarlo.

        En los ciclos cortos sólo se mira el DPI, que es lo que cambia mientras
        usas el ratón. Buscarlo cuando no está, comprobar el enlace y reponer
        el perfil son cosas de los ciclos largos: no hace falta hacerlas tres
        veces más a menudo, y cada una es una petición más por el mismo canal
        que usa la interfaz.

        Distinguir "no contesta" de "no está" es lo que evita que el perfil se
        reaplique solo cada dos por tres: el nodo hidraw es de uno a la vez, y
        cuando lo tiene la interfaz este ping falla sin que el ratón se haya
        movido de sitio.
        """
        if self.raton is None:
            if not completa:
                return
            if self.buscar_raton():
                self.aplicar_por_defecto("ratón conectado")
            return

        if not completa:
            # Ciclo corto: sólo el DPI. Si el nodo está ocupado, ya se mirará.
            try:
                await self._mirar_dpi()
            except DispositivoOcupado:
                pass
            except Exception as e:
                log.debug("no se pudo mirar el DPI: %s", e)
            return

        try:
            # `estado()` se traga los errores para poder pintar la interfaz
            # aunque falle un ajuste, así que no sirve para saber si el ratón
            # sigue ahí: hay que preguntárselo.
            if not self.raton.hpp.ping(timeout=0.5):
                raise OSError("sin respuesta")
        except DispositivoOcupado:
            # El nodo lo tiene otro proceso, normalmente la interfaz. Eso NO es
            # que el ratón se haya ido: es que está ocupado medio segundo.
            # Darlo por perdido hacía que al recuperarlo se reaplicara el
            # perfil, y con la ventana abierta —que mira cada 800 ms— eso
            # pasaba decenas de veces por hora.
            return
        except Exception:
            self._fallos_seguidos += 1
            # Un fallo suelto no es una desconexión: por radio se pierde un
            # paquete de vez en cuando. Tres oportunidades antes de darlo por ido.
            if self._fallos_seguidos < 3:
                log.debug("el ratón no ha contestado (%d de 3)",
                          self._fallos_seguidos)
                return
            log.info("se ha perdido el ratón")
            self.raton, self.motor = None, None
            self._fallos_seguidos = 0
            return

        self._fallos_seguidos = 0
        try:
            await self._mirar_dpi()
            self._reponer_si_ha_derivado()
        except DispositivoOcupado:
            return
        except Exception as e:
            # Que falle revisar el estado no significa que el ratón no esté:
            # el ping acaba de contestar.
            log.debug("no se pudo revisar el estado: %s", e)

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
        if self._prefiere_onboard():
            if not self._aviso_onboard:
                log.info("el ratón está en modo onboard porque lo has elegido: "
                         "manda su memoria y los perfiles por juego no se aplican")
                self._aviso_onboard = True
            return ["el ratón está en modo onboard"]
        self._aviso_onboard = False
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
        # Este cambio lo hemos hecho nosotros: no hay que avisar de él como si
        # el usuario hubiera pulsado el botón del ratón. Se vuelve a tomar la
        # referencia en la siguiente vuelta.
        self._dpi_visto = None
        return [str(c) for c in cambios]

    def _prefiere_onboard(self) -> bool:
        """¿Ha pedido el usuario que mande el ratón? Se relee cada vez: la
        interfaz puede cambiarlo mientras el demonio está en marcha."""
        return leer_modo_preferido(self.demo) == "onboard"

    async def _mirar_dpi(self) -> None:
        """Avisa si el DPI ha cambiado sin que lo hayamos pedido nosotros.

        Pasa cuando pulsas el botón del propio ratón: nadie nos lo cuenta, así
        que hay que verlo mirando.
        """
        if self.raton is None or self.raton.dpi is None:
            return
        try:
            ahora = self.raton.dpi.get().actual
        except Exception:
            return
        if self._dpi_visto is not None and ahora != self._dpi_visto:
            await self.avisar(f"{ahora} DPI", "Sensibilidad del ratón")
        self._dpi_visto = ahora

    def _reponer_si_ha_derivado(self) -> None:
        """Vuelve a poner el perfil activo si el ratón se ha desviado.

        El ratón sigue respondiendo, así que la comprobación de conexión no ve
        nada raro, pero al despertarse ha vuelto a los ajustes de su perfil
        interno. Sin esto, el DPI se pierde en silencio.
        """
        # Si has elegido modo onboard, mandas tú: el ratón está así porque lo
        # has pedido, no porque se haya reiniciado. Sin esta comprobación el
        # demonio te devolvía a host cada cinco segundos.
        if self._prefiere_onboard():
            return

        # Encontrar el ratón en onboard cuando has pedido host significa que se
        # ha reiniciado por su cuenta: el modo ES la deriva, aunque los valores
        # coincidan por casualidad. Y esto no puede depender de que haya un
        # perfil activo: si el ratón arrancó en onboard, nunca llegó a
        # aplicarse ninguno y el modo no se recuperaría jamás.
        onboard = self.raton.onboard
        if onboard is not None and not onboard.es_host():
            activo = self.motor.perfil_activo
            perfil = (self.almacen.obtener(activo) if activo
                      else self.almacen.por_defecto())
            if perfil is not None:
                self.aplicar(perfil, "el ratón había vuelto a sus ajustes")
            else:
                self.raton.asegurar_host()
                log.info("el ratón había vuelto a modo onboard; devuelto a host")
            return

        activo = self.motor.perfil_activo
        perfil = self.almacen.obtener(activo) if activo else None
        if perfil is None:
            return

        # En modo host no se toca nada: una diferencia con el perfil la ha
        # hecho alguien a propósito —tú, o la interfaz— y reponerla sería
        # pelearse con quien está usando el programa: mueves el DPI y cinco
        # segundos después vuelve solo.

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

    async def avisar(self, texto: str, cuerpo: str = "") -> None:
        """Manda un aviso al escritorio, si hay quien lo reciba.

        Es lo que hace útil el botón de cambiar DPI: pulsarlo sin saber a qué
        has saltado no sirve de mucho, y el ratón no tiene pantalla. Si el
        escritorio no expone el servicio de notificaciones, no pasa nada.
        """
        if self._bus is None:
            return
        try:
            introspeccion = await self._bus.introspect(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            objeto = self._bus.get_proxy_object(
                "org.freedesktop.Notifications",
                "/org/freedesktop/Notifications", introspeccion)
            iface = objeto.get_interface("org.freedesktop.Notifications")
            # El id 0 crea un aviso nuevo; devolver el suyo y reutilizarlo hace
            # que se sustituya en pantalla en vez de apilarse al pulsar varias
            # veces seguidas.
            self._id_aviso = await iface.call_notify(
                "gpx2", self._id_aviso, "input-mouse", texto, cuerpo, [],
                {}, 2500)
        except Exception as e:
            log.debug("no se pudo avisar al escritorio: %s", e)

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
