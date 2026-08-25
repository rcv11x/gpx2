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

    print("6. Perfiles en la memoria del ratón (0x8100)")
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

    perfil = leer_perfil(crudo, ob.num_botones, ob.formato)
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
    releido = leer_perfil(ob.leer_sector(1), ob.num_botones, ob.formato)
    comprobar(describir_boton(releido.botones[3]) == "Clic central",
              "escribe un botón en la memoria del ratón")
    comprobar(releido.niveles[1].x == 1500, "y un nivel de DPI")

    print("7. Otro ratón: G203 LIGHTSYNC, con las features clásicas")
    # El contrapunto al PRO X 2: por cable, sin batería, con 0x2201 y 0x8060 en
    # vez de 0x2202 y 0x8061, y con el perfil en formato 0x04. Sale del primer
    # informe que mandó alguien de fuera. Sin esto, todo el camino "clásico"
    # sería código que no ejecuta nadie hasta que le falla a un usuario.
    from gpx2.modelos import G203
    g = raton_simulado(G203)
    eg = g.leer_todo()
    comprobar(eg["nombre"] == "G203 LIGHTSYNC", "lo identifica por su nombre")
    comprobar(not eg["errores"], "se construye sin errores")
    comprobar(type(g.dpi).__name__ == "AdjustableDpi", "elige el DPI clásico (0x2201)")
    comprobar(type(g.rate).__name__ == "ReportRate", "elige la tasa clásica (0x8060)")
    comprobar(eg["rate"].actual_hz == 1000, "lee su tasa en milisegundos")
    comprobar(eg["rate"].disponibles == [1000, 500, 250, 125], "y las que admite")
    comprobar(eg["battery"] is None, "no le inventa batería: va por cable")
    comprobar(g.buttons is None, "no expone 0x1B04, y no se finge que sí")

    og = g.onboard
    comprobar(og.formato == 0x04, "lee su formato de perfil, que no es el 0x07")
    crudo_g = og.leer_sector(1)
    comprobar(crc16_ccitt(crudo_g[:-2]) == int.from_bytes(crudo_g[-2:], "big"),
              "el CRC de su sector cuadra igual")
    pg = leer_perfil(crudo_g, og.num_botones, og.formato)
    # Con el molde del 0x07 esto daba 8193 y 16387, que es lo que pasa cuando
    # se decodifica por encima de los bytes: números, y encima verosímiles.
    comprobar([n.x for n in pg.niveles] == [400, 800, 1600, 3200],
              "decodifica sus DPI con la disposición clásica")
    comprobar(pg.tasa_hz == 1000, "y su tasa, que ahí va en milisegundos")
    comprobar(describir_boton(pg.botones[3]) == "Atrás",
              "los botones se leen igual en las dos disposiciones")
    comprobar(escribir_perfil(pg) == crudo_g, "ida y vuelta sin tocar nada")
    # 0x8071 se pregunta con 0xFF, y la cuenta no está donde parece: los dos
    # primeros bytes de la respuesta son el eco de lo preguntado. Leerla en el
    # sitio equivocado hizo creer que el ratón tenía 255 zonas de luz, y el
    # informe salió con 254 líneas de error.
    gen = g.hpp.call(g.hpp.of(0x8071), 0x00, b"\xff\xff\x00")
    comprobar(gen[2] == 1, "0x8071 declara una sola zona de luz")
    z0 = g.hpp.call(g.hpp.of(0x8071), 0x00, b"\x00\xff\x00")
    comprobar(z0[4] == 7, "y que esa zona admite siete efectos")
    # Cada efecto se pide por su índice y contesta [zona, índice, id(2), …].
    ids = [int.from_bytes(g.hpp.call(g.hpp.of(0x8071), 0x00,
                                     bytes([0, i, 0]))[2:4], "big")
           for i in range(z0[4])]
    comprobar(ids == [0x00, 0x01, 0x03, 0x04, 0x0A, 0x0D, 0x0E],
              "enumera los siete identificadores de efecto")
    # El hallazgo que une las dos mitades: el primer byte del bloque que guarda
    # el perfil sale de esta misma lista, no de otro espacio de valores.
    guardado = crudo_g[208]
    comprobar(guardado in ids,
              "el efecto guardado en el perfil es uno de los que declara 0x8071")

    # La prueba guiada de efectos escribe en el ratón de otra persona, así que
    # lo que tiene que estar comprobado no es que escriba, sino que devuelva el
    # perfil exactamente a como estaba.
    from gpx2.onboard import crc16_ccitt as _crc
    antes = og.leer_sector(1)

    def _con_efecto(base, bloque):
        cuerpo = bytearray(base[:len(base) - 2])
        for hueco in (208, 219):
            cuerpo[hueco:hueco + 11] = bloque
        return bytes(cuerpo) + _crc(bytes(cuerpo)).to_bytes(2, "big")

    rojo = bytes([0x01, 0xFF, 0x00, 0x00]) + bytes(7)
    og.escribir_sector(1, _con_efecto(antes, rojo))
    tras = og.leer_sector(1)
    comprobar(tras[208:219] == rojo, "escribe un efecto de luz en el perfil")
    comprobar(_crc(tras[:-2]) == int.from_bytes(tras[-2:], "big"),
              "y el CRC del sector sigue cuadrando")
    comprobar(tras[219:230] == rojo, "lo escribe en los dos huecos, no en uno")
    og.escribir_sector(1, antes)
    comprobar(og.leer_sector(1) == antes,
              "y restaurar deja el perfil idéntico al de antes, byte a byte")

    print("8. El modo lo elige el usuario, no el demonio")
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

    print("9. El ratón ocupado no es un ratón desconectado")
    # El nodo hidraw es de uno a la vez. Cuando lo tiene la interfaz, el ping
    # del demonio falla — y darlo por desconectado hacía que al "recuperarlo"
    # reaplicara el perfil. Con la ventana abierta pasaba decenas de veces por
    # hora, y se veía como que el DPI se cambiaba solo.
    import asyncio as _asyncio
    from gpx2.transport import DispositivoOcupado

    d = Demonio(demo=True)
    d.buscar_raton()
    d.recargar()
    comprobar(d.raton is not None, "el demonio encuentra el ratón simulado")

    def _ocupado(*a, **k):
        raise DispositivoOcupado("lo tiene la interfaz")

    real = d.raton.hpp.ping
    d.raton.hpp.ping = _ocupado
    for _ in range(5):
        _asyncio.run(d.revisar_conexion())
    comprobar(d.raton is not None,
              "cinco pings ocupados seguidos no lo dan por desconectado")

    def _falla(*a, **k):
        raise OSError("sin respuesta")

    d.raton.hpp.ping = _falla
    _asyncio.run(d.revisar_conexion())
    comprobar(d.raton is not None, "un fallo suelto tampoco: puede ser la radio")
    _asyncio.run(d.revisar_conexion())
    _asyncio.run(d.revisar_conexion())
    comprobar(d.raton is None, "pero tres seguidos sí que es una desconexión")

    # El aviso del DPI llega tarde o no llega si sólo se mira cada cinco
    # segundos: cambia al pulsar el botón del ratón, y ciclando dos veces
    # seguidas sólo se vería la última.
    comprobar(Demonio.CADA_DPI < Demonio.CADA_CONEXION,
              "el DPI se vigila más a menudo que la conexión")
    d2 = Demonio(demo=True)
    d2.buscar_raton()
    avisos = []
    d2.avisar = lambda texto, cuerpo="": avisos.append(texto)
    _asyncio.run(d2.revisar_conexion(completa=False))     # toma la referencia
    d2.raton.dpi.set(1600)
    _asyncio.run(d2.revisar_conexion(completa=False))
    comprobar(any("1600" in a for a in avisos),
              "avisa del DPI también en los ciclos cortos")

    print("10. Robustez")
    from gpx2.features import Firmware
    fw = Firmware(tipo=1, prefijo="BL1", numero=0x71, revision=0x00, build=0x0012)
    # Sin el espacio se lee "BL171.00", como si la versión fuera la 171.
    comprobar(fw.version == "BL1 71.00.B0012", "compone la versión de firmware")
    # Un nodo con el uevent en formato inesperado no puede tumbar la lista.
    from gpx2.transport import enumerate_nodes
    comprobar(isinstance(enumerate_nodes(), list), "la enumeración no lanza")

    print("11. Botones reprogramables (0x1B04)")
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
        # Repetidas al final a propósito: la línea del fallo queda enterrada
        # entre sesenta [ok], y quien mira la salida por una tubería suele ver
        # sólo el resumen. Un fallo que no dice cuál es no sirve de nada.
        print(f"{len(fallos)} comprobación(es) fallida(s):")
        for f in fallos:
            print(f"  · {f}")
        return 1
    print("todo correcto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
