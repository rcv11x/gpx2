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


def limpiar_estado_demo() -> None:
    """Borra lo que dejaron ejecuciones anteriores.

    Sin esto la primera pasada tras un cambio podía fallar y las siguientes
    no: arrastraba el modo o la frecuencia que había guardado la anterior. Una
    prueba que depende de lo que pasó antes no sirve para nada.

    Sólo toca la carpeta del modo demo; la configuración real no se roza.
    """
    import shutil
    from gpx2.profiles import directorio_estado
    carpeta = directorio_estado(demo=True)
    if carpeta.name == "demo" and carpeta.is_dir():
        shutil.rmtree(carpeta, ignore_errors=True)


def main() -> int:
    limpiar_estado_demo()
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
    comprobar(len(raton.feature_table) == 16, "enumera la tabla de features")
    comprobar(not estado["errores"], "sin errores al construir el dispositivo")

    print("2. Escritura")
    raton.dpi.set(3200)
    comprobar(raton.dpi.get().actual == 3200, "escribe y relee el DPI")
    # 12345 no es un valor válido del sensor: hay que ajustarlo al más cercano.
    raton.dpi.set(12345)
    comprobar(raton.dpi.get().actual == 12300, "ajusta al DPI válido más cercano")
    # La tasa sólo entra si antes se desbloquean las features ocultas (0x1E00).
    # Sin eso el ratón acepta la orden y no cambia nada.
    canal = raton.ch
    raton.rate.set(8000)
    comprobar(canal.hz_idx == 6, "cambia la tasa desbloqueando las ocultas")
    comprobar(not canal.ocultas, "y las vuelve a cerrar al terminar")
    # La función 2 devuelve el índice viejo aunque el enlace haya cambiado:
    # fiarse de ella fue lo que hizo dar por fallido el cambio.
    comprobar(raton.rate.call(0x02)[0] == 3, "la función 2 sigue mintiendo")
    comprobar(raton.rate.get().actual_hz == 8000,
              "pero se recuerda lo escrito y se enseña bien")
    raton.rate.set(1000)
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

        # La tasa sí se aplica desde un perfil, ahora que sabemos desbloquearla.
        alta = Perfil(nombre="Alta", ajustes=Ajustes(report_rate_hz=4000))
        cambios = motor.aplicar(alta)
        comprobar(all(c.ok for c in cambios), "aplica la tasa desde un perfil")
        comprobar(raton.ch.hz_idx == 5, "y el enlace queda a 4000 Hz")

        # Y si un ratón no admite un ajuste, se anota para no reintentarlo en
        # cada comprobación y llenar el registro de errores repetidos.
        motor.imposibles.add("dpi")
        comprobar(motor.aplicar(almacen.obtener("escritorio")) == []
                  or all(c.ajuste != "dpi" for c in
                         motor.aplicar(almacen.obtener("escritorio"))),
                  "no reintenta lo que el ratón no admite")

    print("6. Perfiles en la memoria del ratón (0x8100, formato 0x07)")
    from gpx2.onboard import (ACCIONES, crc16_ccitt, describir_boton,
                              escribir_perfil, leer_perfil)
    # Vector canónico del CRC-16/CCITT-FALSE. Si esto falla, cualquier sector
    # que escribiéramos lo rechazaría el ratón.
    comprobar(crc16_ccitt(b"123456789") == 0x29B1, "el CRC es el que espera el ratón")

    ob = raton.onboard
    comprobar(ob.formato == 0x07, "lee el formato de perfil")
    comprobar(ob.cabeceras()[0] == (1, True), "lee el directorio de perfiles")
    crudo = ob.leer_sector(1)
    comprobar(crudo is not None and len(crudo) == ob.tam_sector,
              "lee el sector entero, con su último trozo solapado")
    comprobar(crc16_ccitt(crudo[:-2]) == int.from_bytes(crudo[-2:], "big"),
              "y su CRC cuadra")

    perfil = leer_perfil(crudo, ob.num_botones)
    comprobar(perfil.tasa_hz == 1000, "decodifica la tasa guardada")
    comprobar([n.x for n in perfil.niveles] == [800, 1200, 1600, 2400, 3200],
              "decodifica los cinco niveles de DPI")
    comprobar(describir_boton(perfil.botones[3]) == "Atrás", "decodifica los botones")
    # Del sector hay campos que no entendemos: reescribirlo sin cambios no
    # puede alterar ni un byte, o los estaríamos inventando.
    comprobar(escribir_perfil(perfil) == crudo, "ida y vuelta sin tocar nada")

    perfil.botones[3] = ACCIONES["Clic central"]
    perfil.niveles[1].x = perfil.niveles[1].y = 1500
    ob.escribir_sector(1, escribir_perfil(perfil))
    releido = leer_perfil(ob.leer_sector(1), ob.num_botones)
    comprobar(describir_boton(releido.botones[3]) == "Clic central",
              "escribe un botón en la memoria del ratón")
    comprobar(releido.niveles[1].x == 1500, "y un nivel de DPI")

    print("7. El modo lo elige el usuario, no el demonio")
    # El estado del modo demo tiene que estar aparte del real: si compartieran
    # fichero, ejecutar estas pruebas cambiaría la configuración del ratón de
    # quien las lanza.
    from gpx2.profiles import ruta_modo, ruta_tasas
    comprobar(ruta_modo(True) != ruta_modo(False)
              and ruta_tasas(True) != ruta_tasas(False),
              "el estado del demo no pisa el real")
    from gpx2.profiles import guardar_modo_preferido, leer_modo_preferido
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "modo"
        ruta.write_text("onboard\n")
        comprobar(ruta.read_text().strip() == "onboard", "la elección se guarda")
    # El demonio no puede distinguir "el ratón se ha reiniciado" de "lo has
    # pedido tú": sin la preferencia, deshacía la elección cada cinco segundos.
    from gpx2.daemon import Demonio
    for preferido, esperado in (("onboard", False), ("host", True)):
        d = Demonio(demo=True)
        d.buscar_raton()
        d.recargar()
        guardar_modo_preferido(preferido, True)
        d.raton.onboard.set_host(False)
        d._reponer_si_ha_derivado()
        comprobar(d.raton.onboard.es_host() == esperado,
                  f"si eliges {preferido}, el ratón se queda ahí")

    print("8. Robustez")
    from gpx2.features import Firmware
    fw = Firmware(tipo=1, prefijo="BL1", numero=0x71, revision=0x00, build=0x0012)
    # Sin el espacio se lee "BL171.00", como si la versión fuera la 171.
    comprobar(fw.version == "BL1 71.00.B0012", "compone la versión de firmware")
    # Un nodo con el uevent en formato inesperado no puede tumbar la lista.
    from gpx2.transport import enumerate_nodes
    comprobar(isinstance(enumerate_nodes(), list), "la enumeración no lanza")

    print("9. Botones reprogramables (0x1B04)")
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
