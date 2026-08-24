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
from gpx2.features import EscrituraIgnorada
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
    comprobar(estado["dpi"].actual == 800, "lee el DPI actual")
    # El sensor del PRO X 2 llega a 44000: sale del flujo paginado de 0x2202 f2,
    # que el simulador reproduce byte a byte del volcado real.
    comprobar(estado["dpi"].minimo == 100 and estado["dpi"].maximo == 44000,
              "decodifica el rango de DPI")
    comprobar(len(raton.dpi._lista()) == 957, "reconstruye la lista completa de DPIs")
    comprobar(estado["rate"].actual_hz == 1000, "lee la tasa de reporte")
    # El simulador va por receptor: ahí el ratón declara hasta 8000 Hz.
    comprobar(estado["rate"].disponibles == [8000, 4000, 2000, 1000, 500, 250, 125],
              "decodifica las tasas de esta conexión")
    # Y por cable sólo llegaría a 1000: son capacidades distintas.
    comprobar(estado["rate"].otra_conexion == [1000, 500, 250, 125],
              "y las de la otra vía")
    comprobar(estado["battery"].percent == 78, "lee la batería")
    comprobar(estado["onboard"].startswith("onboard"), "lee el modo onboard/host")
    comprobar(len(raton.feature_table) == 15, "enumera la tabla de features")
    comprobar(not estado["errores"], "sin errores al construir el dispositivo")

    print("2. Escritura")
    raton.dpi.set(3200)
    comprobar(raton.dpi.get().actual == 3200, "escribe y relee el DPI")
    # 12345 no es un valor válido del sensor: hay que ajustarlo al más cercano.
    raton.dpi.set(12345)
    comprobar(raton.dpi.get().actual == 12300, "ajusta al DPI válido más cercano")
    # El ratón real acepta la orden y no la aplica; hay que detectarlo, no
    # dar por bueno que no hubo excepción.
    try:
        raton.rate.set(500)
        ignorada = None
    except EscrituraIgnorada as e:
        ignorada = str(e)
    comprobar(ignorada is not None, "detecta que el ratón ignoró la tasa")
    comprobar(ignorada and "enlace" in ignorada, "y explica por qué al usuario")
    comprobar(raton.rate.get().actual_hz == 1000, "la tasa sigue donde estaba")
    comprobar(raton.onboard.set_host(True), "pasa el ratón a modo host")
    comprobar(raton.onboard.set_host(False), "y lo devuelve a modo onboard")
    # Tras reconectarse el ratón vuelve a onboard y rechaza las escrituras con
    # un error interno; hay que devolverlo a host antes de tocar nada.
    comprobar(raton.asegurar_host() is True, "asegurar_host() lo recupera")
    comprobar(raton.asegurar_host() is True, "y no molesta si ya estaba")

    print("3. Perfiles en disco")
    with tempfile.TemporaryDirectory() as tmp:
        almacen = Almacen(Path(tmp))
        almacen.guardar(Perfil(
            nombre="Escritorio", por_defecto=True,
            ajustes=Ajustes(dpi=1600, report_rate_hz=1000)))
        almacen.guardar(Perfil(
            nombre="Shooter", ajustes=Ajustes(dpi=800, report_rate_hz=1000),
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
        raton.onboard.set_host(False)      # como lo encuentra tras reconectar
        cambios = motor.aplicar(almacen.obtener("shooter"))
        comprobar(len(cambios) == 2, "aplica lo que difiere y además pasa a host")
        comprobar(cambios[0].ajuste == "modo", "el modo host se arregla primero")
        comprobar(raton.dpi.get().actual == 800, "el DPI queda aplicado")
        cambios = motor.aplicar(almacen.obtener("shooter"))
        comprobar(cambios == [], "reaplicar el mismo perfil no manda nada")

        # El ratón vuelve a sus ajustes internos al despertarse, y sigue
        # respondiendo: hay que notarlo mirando, no esperando un aviso.
        perfil = almacen.obtener("shooter")
        comprobar(not motor.ha_derivado(perfil), "no ve deriva donde no la hay")
        raton.dpi.set(3200)                     # como si se hubiera despertado
        comprobar(motor.ha_derivado(perfil), "detecta que el ratón se ha desviado")
        motor.aplicar(perfil)
        comprobar(raton.dpi.get().actual == 800, "y lo repone")

        comprobar(motor.perfil_activo == "shooter", "recuerda el perfil activo")
        # La tasa no se puede escribir por receptor: se anota una vez y no se
        # reintenta en cada comprobación.
        otro = Perfil(nombre="Alta", ajustes=Ajustes(report_rate_hz=500))
        fallos_1 = [c for c in motor.aplicar(otro) if not c.ok]
        comprobar(len(fallos_1) == 1, "informa una vez de lo que no se puede")
        comprobar("report_rate_hz" in motor.imposibles, "y lo recuerda")
        comprobar(motor.aplicar(otro) == [], "no lo reintenta sin parar")

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
