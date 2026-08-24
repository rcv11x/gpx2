# -*- coding: utf-8 -*-
"""
Prueba de humo: recorre todo el camino sin necesitar hardware ni interfaz.

    python3 -m tests.prueba_humo

No usa pytest a propósito: así se puede ejecutar en cualquier sitio sin
instalar nada. Si algún día crece, se migra.
"""

import sys
import tempfile
from pathlib import Path

from gpx2.engine import Motor
from gpx2.mock import raton_simulado
from gpx2.profiles import Activacion, Ajustes, Almacen, Perfil
from gpx2.watcher.base import Juego

fallos = []


def comprobar(condicion, descripcion):
    estado = "ok  " if condicion else "FALLO"
    print(f"  [{estado}] {descripcion}")
    if not condicion:
        fallos.append(descripcion)


def main() -> int:
    print("1. Protocolo y modelo de dispositivo")
    raton = raton_simulado()
    estado = raton.leer_todo()
    comprobar(estado["nombre"] == "PRO X SUPERLIGHT 2", "lee el nombre por HID++")
    comprobar(estado["dpi"].actual == 1600, "lee el DPI actual")
    comprobar(estado["dpi"].maximo == 32000, "decodifica el rango de DPI")
    comprobar(estado["rate"].actual_hz == 2000, "lee la tasa de reporte")
    comprobar(8000 in estado["rate"].disponibles, "decodifica las tasas disponibles")
    comprobar(estado["battery"].percent == 78, "lee la batería")
    comprobar(len(raton.feature_table) == 15, "enumera la tabla de features")
    comprobar(not estado["errores"], "sin errores al construir el dispositivo")

    print("2. Escritura")
    raton.dpi.set(3200)
    comprobar(raton.dpi.get().actual == 3200, "escribe y relee el DPI")
    raton.rate.set(8000)
    comprobar(raton.rate.get().actual_hz == 8000, "escribe y relee los Hz")

    print("3. Perfiles en disco")
    with tempfile.TemporaryDirectory() as tmp:
        almacen = Almacen(Path(tmp))
        almacen.guardar(Perfil(
            nombre="Escritorio", por_defecto=True,
            ajustes=Ajustes(dpi=1600, report_rate_hz=1000)))
        almacen.guardar(Perfil(
            nombre="Shooter", ajustes=Ajustes(dpi=800, report_rate_hz=4000),
            activacion=Activacion(ejecutables=["cs2"], steam_appids=[730])))
        errores = almacen.cargar()
        comprobar(not errores, "los TOML que escribimos se releen sin errores")
        comprobar(len(almacen.lista()) == 2, "se cargan los dos perfiles")
        comprobar(almacen.por_defecto().nombre == "Escritorio", "detecta el perfil por defecto")

        print("4. Emparejamiento juego → perfil")
        comprobar(almacen.buscar_para(Juego(pid=1, nombre="cs2", exe="/x/cs2")) is not None,
                  "empareja por nombre de ejecutable")
        comprobar(almacen.buscar_para(Juego(pid=1, nombre="otro", steam_appid=730)) is not None,
                  "empareja por AppID de Steam")
        comprobar(almacen.buscar_para(Juego(pid=1, nombre="firefox")) is None,
                  "no empareja lo que no toca")

        print("5. Motor: sólo manda lo que cambia")
        motor = Motor(raton)
        cambios = motor.aplicar(almacen.obtener("shooter"))
        comprobar(len(cambios) == 2, "aplica los dos ajustes que difieren")
        comprobar(raton.dpi.get().actual == 800, "el DPI queda aplicado")
        cambios = motor.aplicar(almacen.obtener("shooter"))
        comprobar(cambios == [], "reaplicar el mismo perfil no manda nada")
        comprobar(motor.perfil_activo == "shooter", "recuerda el perfil activo")

    print("6. Botones reprogramables (0x1B04)")
    botones = raton.buttons
    comprobar(botones is not None, "el ratón declara la feature de botones")
    controles = botones.controls()
    comprobar(len(controles) == 6, "enumera los seis controles")
    izquierdo = next(c for c in controles if c.cid == 0x0050)
    atras = next(c for c in controles if c.cid == 0x0053)
    central = next(c for c in controles if c.cid == 0x0052)
    comprobar(izquierdo.nombre == "Clic izquierdo", "pone nombre a los controles conocidos")
    comprobar(not izquierdo.admite(central), "respeta que el clic izquierdo no se puede mover")
    comprobar(atras.admite(central), "permite remapear el botón 4 al central")
    botones.remapear(atras.cid, central.cid)
    comprobar(botones.reporting(atras.cid).remapeado_a == central.cid, "el remapeo se guarda")
    botones.restaurar(atras.cid)
    comprobar(botones.reporting(atras.cid).remapeado_a == 0, "restaurar deja el botón como estaba")

    print()
    if fallos:
        print(f"{len(fallos)} comprobación(es) fallida(s)")
        return 1
    print("todo correcto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
