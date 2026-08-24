#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Banco de pruebas HID++ — ingeniería inversa con el ratón delante.

No usa los decodificadores de `gpx2.features`: habla directamente con el
dispositivo y enseña los bytes en crudo. La idea es justo esa — si el
decodificador estuviera bien no haría falta esta herramienta.

    sudo python3 depurar.py                # sólo lee, no toca nada
    sudo python3 depurar.py --escribir     # además prueba escrituras
    sudo python3 depurar.py --escribir --dpi 3200

Toda escritura se hace anotando antes el valor original y restaurándolo al
final, y sólo afecta a DPI / modo onboard: nada que pueda dejar el ratón
inservible.
"""

from __future__ import annotations

import argparse
import os
import select
import statistics
import struct
import sys
import time
from glob import glob

from gpx2.hidpp import (IDX_DIRECT, IDX_RECEIVER, Hidpp, HidppError,
                        NoResponse)
from gpx2.transport import RawChannel, enumerate_nodes


# ---------------------------------------------------------------------------
# HID++ 1.0 — el protocolo del receptor
# ---------------------------------------------------------------------------
#
# El receptor no habla HID++ 2.0: usa el protocolo viejo, de registros. Un
# registro es un número de 0 a 255 con hasta tres bytes de contenido (o
# dieciséis, si es "largo"). No hay forma de preguntar cuáles existen: se
# prueban todos y se mira cuál contesta algo que no sea "dirección inválida".

SUB_LEER, SUB_ESCRIBIR = 0x81, 0x80
SUB_LEER_LARGO, SUB_ESCRIBIR_LARGO = 0x83, 0x82
ERROR_HIDPP1 = 0x8F

ERRORES_1_0 = {
    0x01: "orden inválida", 0x02: "dirección inválida", 0x03: "valor inválido",
    0x04: "falló la conexión", 0x05: "demasiados dispositivos",
    0x06: "ya existe", 0x07: "ocupado", 0x08: "dispositivo desconocido",
    0x09: "error de recursos", 0x0A: "petición no disponible",
    0x0B: "parámetro no admitido", 0x0C: "PIN incorrecto",
}


class Hidpp10:
    """Conversación HID++ 1.0 con un receptor.

    El paquete es [report_id][índice][sub_id][dirección][p0][p1][p2]. La
    respuesta buena repite sub_id y dirección; la mala llega con sub_id 0x8F.
    """

    def __init__(self, canal, indice: int = 0xFF):
        self.ch = canal
        self.indice = indice

    def _intercambio(self, sub: int, direccion: int, params: bytes,
                     report_id: int, timeout: float) -> bytes:
        from gpx2.hidpp import LEN
        cabeza = bytes([report_id, self.indice, sub, direccion])
        with self.ch.sesion():
            self.ch.drain()
            self.ch.write((cabeza + params).ljust(LEN[report_id], b"\x00"))
            limite = time.monotonic() + timeout
            while True:
                queda = limite - time.monotonic()
                if queda <= 0:
                    raise NoResponse(f"registro 0x{direccion:02X}: sin respuesta")
                datos = self.ch.read(queda)
                if datos is None or len(datos) < 5 or datos[1] != self.indice:
                    continue
                if datos[2] == ERROR_HIDPP1 and datos[3] == sub and datos[4] == direccion:
                    raise HidppError(datos[5], legacy=True)
                if datos[2] == sub and datos[3] == direccion:
                    return datos[4:]

    def leer(self, direccion: int, params: bytes = b"\x00\x00\x00",
             timeout: float = 0.4) -> bytes:
        from gpx2.hidpp import SHORT
        return self._intercambio(SUB_LEER, direccion, params, SHORT, timeout)

    def leer_largo(self, direccion: int, params: bytes = b"\x00\x00\x00",
                   timeout: float = 0.4) -> bytes:
        from gpx2.hidpp import SHORT
        return self._intercambio(SUB_LEER_LARGO, direccion, params, SHORT, timeout)

    def escribir(self, direccion: int, params: bytes,
                 timeout: float = 0.6) -> bytes:
        from gpx2.hidpp import SHORT
        return self._intercambio(SUB_ESCRIBIR, direccion, params.ljust(3, b"\x00"),
                                 SHORT, timeout)

    def escribir_largo(self, direccion: int, params: bytes,
                       timeout: float = 0.6) -> bytes:
        from gpx2.hidpp import LONG
        return self._intercambio(SUB_ESCRIBIR_LARGO, direccion,
                                 params.ljust(16, b"\x00"), LONG, timeout)


# Lo que se sabe de los registros de un receptor, para poner nombre a lo que
# aparezca. Sale de la documentación de Logitech y de Solaar.
REGISTROS = {
    0x00: "notificaciones",
    0x01: "banderas de botones / detección de mano",
    0x02: "conexión del receptor",
    0x03: "configuración de dispositivos",
    0x07: "estado de batería",
    0x09: "intercambio de Fn",
    0x0D: "carga de batería",
    0x17: "iluminación del teclado",
    0x51: "tres LEDs",
    0x63: "DPI del ratón",
    0xB2: "emparejamiento",
    0xB3: "actividad de dispositivos",
    0xB5: "información del receptor",
    0xC0: "descubrimiento Bolt",
    0xC1: "emparejamiento Bolt",
    0xF1: "firmware",
    0xFB: "identificador único Bolt",
}


# ---------------------------------------------------------------------------
# Utilidades de presentación
# ---------------------------------------------------------------------------

def titulo(texto: str) -> None:
    print(f"\n{'=' * 72}\n{texto}\n{'=' * 72}")


def hx(datos: bytes) -> str:
    return datos.hex(" ")


def u16(datos: bytes, i: int) -> int:
    return int.from_bytes(datos[i:i + 2], "big")


class Sonda:
    """Envuelve un Hidpp para llamar por fid (no por índice) y no reventar."""

    def __init__(self, hpp: Hidpp):
        self.hpp = hpp
        self.tabla = hpp.features()

    def tiene(self, fid: int) -> bool:
        return fid in self.tabla

    def llamar(self, fid: int, func: int, params: bytes = b"") -> bytes | None:
        """Devuelve el payload, o None si falló (imprimiendo el motivo)."""
        if fid not in self.tabla:
            return None
        try:
            return self.hpp.call(self.tabla[fid].index, func, params)
        except (HidppError, NoResponse, OSError):
            return None

    def mostrar(self, etiqueta: str, fid: int, func: int,
                params: bytes = b"") -> bytes | None:
        """Llama e imprime la línea del volcado. Devuelve el payload o None."""
        if fid not in self.tabla:
            print(f"  {etiqueta:44} — feature ausente")
            return None
        try:
            r = self.hpp.call(self.tabla[fid].index, func, params)
        except (HidppError, NoResponse, OSError) as e:
            print(f"  {etiqueta:44} ⚠ {e}")
            return None
        print(f"  {etiqueta:44} {hx(r)}")
        return r


# ---------------------------------------------------------------------------
# Descubrimiento
# ---------------------------------------------------------------------------

def encontrar(nodo_forzado: str | None):
    """Devuelve (nodo, canal, hpp) del primer ratón que conteste, o None."""
    for node in enumerate_nodes():
        if nodo_forzado and node.path != nodo_forzado:
            continue
        if not (node.hidpp and node.is_logitech):
            continue
        ch = RawChannel(node.path)
        for idx in [IDX_DIRECT, *IDX_RECEIVER]:
            try:
                ver = Hidpp(ch, idx).ping(timeout=0.4)
            except PermissionError:
                print(f"  {node.path}: sin permiso (¿falta sudo o la regla udev?)")
                break
            except Exception:
                continue
            if ver:
                print(f"  {node.path} · índice 0x{idx:02X} · HID++ {ver[0]}.{ver[1]}")
                return node, ch, Hidpp(ch, idx)
        ch.close()
    return None


# ---------------------------------------------------------------------------
# Bloques de diagnóstico
# ---------------------------------------------------------------------------

def bloque_bateria(s: Sonda) -> None:
    titulo("BATERÍA (0x1004 UnifiedBattery)")
    cap = s.mostrar("getCapabilities  f0", 0x1004, 0x00)
    est = s.mostrar("getStatus        f1", 0x1004, 0x01)
    if cap:
        # [0]=nº de niveles admitidos, [1]=flags; bit0 = informa porcentaje real
        print(f"    niveles admitidos: {cap[0]}   flags: 0x{cap[1]:02X}"
              f"   ¿porcentaje real?: {'sí' if cap[1] & 0x01 else 'no (sólo niveles)'}")
    if est:
        # [0]=carga %, [1]=nivel, [2]=estado de carga, [3]=alimentación externa
        niveles = {1: "crítico", 2: "bajo", 4: "bueno", 8: "lleno"}
        print(f"    carga: {est[0]}%   nivel: {niveles.get(est[1], est[1])}"
              f"   cargando: {'sí' if est[2] else 'no'}")


def bloque_modo(s: Sonda, escribir: bool) -> None:
    titulo("MODO ONBOARD / HOST")
    print("  -- 0x8090 ModeStatus --")
    s.mostrar("getModeStatus    f0", 0x8090, 0x00)

    print("  -- 0x8100 OnboardProfiles (el que usa Solaar) --")
    info = s.mostrar("getOnboardProfilesInfo f0", 0x8100, 0x00)
    if info:
        print(f"    modelo de memoria: 0x{info[0]:02X}   formato de perfil: "
              f"0x{info[1]:02X}   perfiles: {info[3]}")
    modo = s.mostrar("getOnboardMode         f2", 0x8100, 0x02)
    if modo:
        nombres = {0x01: "onboard (manda el ratón)", 0x02: "host (manda el PC)"}
        print(f"    modo actual: {nombres.get(modo[0], f'desconocido (0x{modo[0]:02X})')}")

    if not escribir:
        print("\n  (para probar el cambio a modo host, pasa --escribir)")
        return

    if modo and modo[0] == 0x02:
        print("\n  Ya está en modo host, no hace falta cambiarlo.")
        return

    print("\n  Probando setOnboardMode(host) — 0x8100 f1 con 0x02:")
    s.mostrar("setOnboardMode(0x02)   f1", 0x8100, 0x01, b"\x02")
    despues = s.mostrar("getOnboardMode         f2", 0x8100, 0x02)
    if despues and despues[0] == 0x02:
        print("    ✓ el ratón está ahora en modo host")
    else:
        print("    ✗ no cambió; el DPI seguirá mandándolo el perfil onboard")


def bloque_rangos(s: Sonda) -> list[int]:
    """getSensorDpiRanges es un flujo de bytes repartido en páginas.

    Cada página aporta 13 bytes (los 3 primeros son eco de la petición) al
    MISMO flujo, así que un valor puede quedar partido entre dos páginas. Se
    piden páginas consecutivas hasta que el flujo termina en 0x0000.
    """
    titulo("RANGOS DE DPI (0x2202 f2, flujo paginado)")
    datos = b""
    for pagina in range(8):
        r = s.mostrar(f"f2  getSensorDpiRanges(pág {pagina})", 0x2202, 0x02,
                      bytes([0x00, 0x00, pagina]))
        if not r:
            break
        datos += r[3:]
        if datos[-2:] == b"\x00\x00":
            break

    print(f"\n    flujo completo ({len(datos)} bytes): {hx(datos)}")

    valores: list[int] = []
    tramos: list[str] = []
    i = 0
    while i + 1 < len(datos):
        v = u16(datos, i)
        if v == 0:
            break
        if (v >> 13) == 0b111:
            paso = v & 0x1FFF
            hasta = u16(datos, i + 2)
            if valores and paso and hasta > valores[-1]:
                tramos.append(f"de {valores[-1]} a {hasta} en pasos de {paso}")
                valores += list(range(valores[-1] + paso, hasta + 1, paso))
            i += 4
        else:
            valores.append(v)
            tramos.append(f"valor suelto {v}")
            i += 2

    print("\n    tramos declarados:")
    for t in tramos:
        print(f"      · {t}")
    if valores:
        print(f"\n    → {len(valores)} DPIs válidos, de {min(valores)} "
              f"a {max(valores)}")
    return valores


def bloque_dpi(s: Sonda) -> dict:
    """Lee el DPI con los números de función que usa Solaar (5 = leer)."""
    titulo("DPI (0x2202)")
    ver = s.tabla[0x2202].version if s.tiene(0x2202) else None
    print(f"  versión de la feature en este ratón: v{ver}\n")

    s.mostrar("f0  getSensorCount", 0x2202, 0x00)
    cap = s.mostrar("f1  getSensorCapabilities(0)", 0x2202, 0x01, b"\x00")
    tiene_y = tiene_lod = False
    if cap:
        tiene_y, tiene_lod = bool(cap[2] & 0x01), bool(cap[2] & 0x02)
        print(f"      → eje Y independiente: {'sí' if tiene_y else 'no'}"
              f"   ·   distancia de despegue: {'sí' if tiene_lod else 'no'}")

    print()
    leer = s.mostrar("f5  getSensorDpi  ← el getter de verdad", 0x2202, 0x05,
                     b"\x00")
    actual = defecto = lod = None
    if leer and len(leer) >= 10:
        # [0]=sensor [1:3]=X [3:5]=X por defecto [5:7]=Y [7:9]=Y por defecto [9]=LOD
        actual = u16(leer, 1) or u16(leer, 3)
        defecto = u16(leer, 3)
        lod = leer[9]
        print(f"      → DPI actual: {actual}   ·   de fábrica: {defecto}"
              f"   ·   eje Y: {u16(leer, 5)}   ·   despegue: {lod}")

    print("\n  Las funciones que usábamos antes, para dejar constancia:")
    s.mostrar("f3  (era lo que creíamos 'DPI actual')", 0x2202, 0x03, b"\x00")
    s.mostrar("f4", 0x2202, 0x04, b"\x00")

    return {"actual": actual, "defecto": defecto, "lod": lod,
            "tiene_y": tiene_y, "tiene_lod": tiene_lod}


def bloque_escritura_dpi(s: Sonda, estado: dict, validos: list[int],
                         objetivo: int) -> None:
    """Escribe el DPI con f6 (el formato de Solaar) y comprueba leyendo."""
    titulo(f"PRUEBA DE ESCRITURA DE DPI → {objetivo}")

    if validos and objetivo not in validos:
        objetivo = min(validos, key=lambda v: abs(v - objetivo))
        print(f"  (ajustado al valor válido más cercano: {objetivo})")

    antes = s.llamar(0x2202, 0x05, b"\x00")
    print(f"  antes:  f5 = {hx(antes) if antes else '—'}")

    dpi = objetivo.to_bytes(2, "big")
    lod = bytes([estado.get("lod") or 0]) if estado.get("tiene_lod") else b"\x00"
    eje_y = dpi if estado.get("tiene_y") else b"\x00\x00"
    params = b"\x00" + dpi + eje_y + lod

    print(f"\n  → f6  setSensorDpi   params: {hx(params)}")
    print("     ([sensor, DPI X, DPI Y, distancia de despegue])")
    try:
        r = s.hpp.call(s.tabla[0x2202].index, 0x06, params)
        print(f"     respuesta: {hx(r)}")
    except (HidppError, NoResponse, OSError) as e:
        print(f"     ⚠ {e}")
        return

    despues = s.llamar(0x2202, 0x05, b"\x00")
    print(f"\n  después: f5 = {hx(despues) if despues else '—'}")
    if despues and antes and despues != antes:
        leido = u16(despues, 1) or u16(despues, 3)
        print(f"\n     *** FUNCIONA: el ratón dice ahora {leido} DPI ***")
        print("     Mueve el ratón: la velocidad tiene que haber cambiado.")
    else:
        print("\n     ✗ el ratón no cambió. Casi seguro que el perfil onboard "
              "lo está reimponiendo:\n"
              "       vuelve a lanzarlo con --escribir para pasar a modo host.")


# ---------------------------------------------------------------------------
# Medición real de la tasa de reporte
# ---------------------------------------------------------------------------

# struct input_event del kernel en 64 bits: timeval (2 x long) + type + code
# + value. Son 24 bytes.
FORMATO_EVENTO = "llHHi"
TAM_EVENTO = struct.calcsize(FORMATO_EVENTO)
EV_SYN, SYN_REPORT = 0x00, 0x00


def punteros_del_sistema() -> list[tuple[str, str, str]]:
    """Nodos /dev/input/event* que informan de movimiento relativo.

    Un ratón declara ejes relativos; un teclado no. Así se descartan sin tener
    que abrirlos.
    """
    salida = []
    for ruta in sorted(glob("/sys/class/input/event*")):
        try:
            rel = open(f"{ruta}/device/capabilities/rel").read().strip()
            if not rel or int(rel, 16) == 0:
                continue
            nombre = open(f"{ruta}/device/name").read().strip()
            vid = open(f"{ruta}/device/id/vendor").read().strip()
            pid = open(f"{ruta}/device/id/product").read().strip()
        except (OSError, ValueError):
            continue
        salida.append((f"/dev/input/{os.path.basename(ruta)}", nombre,
                       f"{vid}:{pid}"))
    return salida


def medir_tasa(dispositivo: str, segundos: float = 5.0) -> None:
    """Cuenta los informes que llegan de verdad y calcula los Hz.

    Es la única medida que no depende de lo que el ratón *diga*: los sellos de
    tiempo los pone el kernel al recibir cada informe. Hace falta mover el
    ratón, porque parado no manda nada.
    """
    print(f"\n  Midiendo en {dispositivo} durante {segundos:.0f} s.")
    print("  *** MUEVE EL RATÓN EN CÍRCULOS, SIN PARAR, HASTA QUE TERMINE ***\n")

    try:
        fd = os.open(dispositivo, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as e:
        print(f"     no se pudo abrir: {e}")
        return

    sellos: list[float] = []
    fin = time.monotonic() + segundos
    try:
        while time.monotonic() < fin:
            resto = fin - time.monotonic()
            if not select.select([fd], [], [], min(0.2, max(0.0, resto)))[0]:
                continue
            try:
                datos = os.read(fd, TAM_EVENTO * 256)
            except BlockingIOError:
                continue
            for i in range(0, len(datos) - TAM_EVENTO + 1, TAM_EVENTO):
                seg, useg, tipo, codigo, _ = struct.unpack(
                    FORMATO_EVENTO, datos[i:i + TAM_EVENTO])
                # Un informe del ratón termina siempre en SYN_REPORT: contarlo
                # a él y no los ejes evita multiplicar por dos o por tres.
                if tipo == EV_SYN and codigo == SYN_REPORT:
                    sellos.append(seg + useg / 1_000_000)
    finally:
        os.close(fd)

    if len(sellos) < 20:
        print(f"     sólo llegaron {len(sellos)} informes: ¿moviste el ratón?")
        return

    huecos = [b - a for a, b in zip(sellos, sellos[1:]) if b > a]
    # Los huecos grandes son pausas al mover, no la tasa: se descartan.
    activos = sorted(h for h in huecos if h < 0.05)
    if not activos:
        print("     no hubo movimiento seguido; repítelo moviendo sin parar")
        return

    mediana = statistics.median(activos)
    rapido = activos[len(activos) // 20]        # percentil 5: lo más rápido
    print(f"     informes contados: {len(sellos)}   ·   intervalos útiles: "
          f"{len(activos)}")
    print(f"     intervalo típico:  {mediana * 1000:.3f} ms  ->  "
          f"{1 / mediana:>7.0f} Hz")
    print(f"     el más corto (p5): {rapido * 1000:.3f} ms  ->  "
          f"{1 / rapido:>7.0f} Hz")

    conocidas = [125, 250, 500, 1000, 2000, 4000, 8000]
    cerca = min(conocidas, key=lambda v: abs(v - 1 / mediana))
    print(f"\n     → la tasa real es {cerca} Hz")


# Códigos de botón del kernel (linux/input-event-codes.h).
EV_KEY = 0x01
BOTONES_KERNEL = {
    0x110: "BTN_LEFT (clic izquierdo)", 0x111: "BTN_RIGHT (clic derecho)",
    0x112: "BTN_MIDDLE (clic central)", 0x113: "BTN_SIDE (lateral trasero)",
    0x114: "BTN_EXTRA (lateral delantero)", 0x115: "BTN_FORWARD",
    0x116: "BTN_BACK", 0x117: "BTN_TASK",
}


def escuchar_botones(dispositivo: str, segundos: float = 20.0) -> None:
    """Enseña qué botones llegan al kernel, tal cual los manda el ratón.

    Es la forma de separar tres cosas que se confunden: que el ratón no mande
    nada, que mande un botón distinto del que crees, o que lo mande bien y sea
    el escritorio quien hace algo raro con él.
    """
    print(f"\n  Escuchando {dispositivo} durante {segundos:.0f} s.")
    print("  *** PULSA LOS BOTONES DEL RATÓN, UNO A UNO ***\n")
    try:
        fd = os.open(dispositivo, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as e:
        print(f"     no se pudo abrir: {e}")
        return

    cuenta: dict[int, int] = {}
    eventos: list[tuple[float, int, int]] = []
    fin = time.monotonic() + segundos
    try:
        while time.monotonic() < fin:
            resto = fin - time.monotonic()
            if not select.select([fd], [], [], min(0.3, max(0.0, resto)))[0]:
                continue
            try:
                datos = os.read(fd, TAM_EVENTO * 64)
            except BlockingIOError:
                continue
            for i in range(0, len(datos) - TAM_EVENTO + 1, TAM_EVENTO):
                seg, useg, tipo, codigo, valor = struct.unpack(
                    FORMATO_EVENTO, datos[i:i + TAM_EVENTO])
                if tipo != EV_KEY or valor not in (0, 1):
                    continue
                t = seg + useg / 1_000_000
                eventos.append((t, codigo, valor))
                if valor == 1:
                    cuenta[codigo] = cuenta.get(codigo, 0) + 1
                nombre = BOTONES_KERNEL.get(codigo, f"código 0x{codigo:03X}")
                desde = f"  (+{(t - eventos[0][0]) * 1000:7.1f} ms)" if eventos else ""
                print(f"     {'PULSA ' if valor else 'suelta'} {nombre}{desde}")
    finally:
        os.close(fd)

    if not cuenta:
        print("\n     No llegó ninguna pulsación.")
        print("     Si estabas pulsando, el ratón no las está mandando por aquí.")
        return

    print("\n     Resumen de pulsaciones:")
    for codigo, veces in sorted(cuenta.items()):
        print(f"       {BOTONES_KERNEL.get(codigo, hex(codigo)):32} x{veces}")

    # Dos pulsaciones del mismo botón muy seguidas no las hace un dedo: o es
    # rebote del interruptor, o el ratón las está duplicando.
    rebotes = []
    ultima: dict[int, float] = {}
    for t, codigo, valor in eventos:
        if valor != 1:
            continue
        if codigo in ultima and (t - ultima[codigo]) < 0.08:
            rebotes.append((codigo, (t - ultima[codigo]) * 1000))
        ultima[codigo] = t
    if rebotes:
        print("\n     *** PULSACIONES DUPLICADAS, demasiado seguidas para ser "
              "tuyas: ***")
        for codigo, ms in rebotes:
            print(f"       {BOTONES_KERNEL.get(codigo, hex(codigo))}  a {ms:.1f} ms "
                  "de la anterior")
        print("     Un dedo no baja de unos 80 ms. Esto es rebote del "
              "interruptor o\n     el ratón mandando el clic dos veces.")
    else:
        print("\n     Sin pulsaciones duplicadas: cada clic llegó una sola vez.")


def bloque_escuchar(segundos: float) -> None:
    titulo("QUÉ BOTONES LLEGAN AL KERNEL")
    punteros = punteros_del_sistema()
    if not punteros:
        print("  No se encontró ningún puntero en /dev/input.")
        return
    elegido = next((p for p in punteros if p[2].startswith("046d")), punteros[0])
    print(f"  Escuchando: {elegido[1]}  ({elegido[0]})")
    escuchar_botones(elegido[0], segundos)


def mapa_de_botones(dispositivos: list[str], espera: float = 25.0) -> None:
    """Pregunta por cada botón y anota qué llega. Sin ambigüedades.

    Escuchar y contar deja siempre la duda de qué botón se pulsó de verdad.
    Aquí se pide uno concreto y se mira qué aparece, así que el resultado es
    una tabla de "pulsaste esto, llegó aquello".

    Escucha TODOS los nodos del ratón a la vez: si en algún modo los eventos
    salieran por otro sitio, se vería.
    """
    fds = {}
    for dev in dispositivos:
        try:
            fds[os.open(dev, os.O_RDONLY | os.O_NONBLOCK)] = dev
        except OSError as e:
            print(f"  no se pudo abrir {dev}: {e}")
    if not fds:
        return

    pedidos = [
        ("CLIC IZQUIERDO", 0x110),
        ("CLIC DERECHO", 0x111),
        ("CLIC CENTRAL (la rueda)", 0x112),
        ("LATERAL TRASERO (atrás)", 0x113),
        ("LATERAL DELANTERO (adelante)", 0x114),
    ]
    def vaciar() -> None:
        for fd in fds:
            try:
                while os.read(fd, TAM_EVENTO * 256):
                    pass
            except (BlockingIOError, OSError):
                pass

    print("\n  Se te pedirá un botón cada vez. Entre uno y otro hay una pausa\n"
          "  para descartar clics sueltos: no pulses nada hasta que lo pida.\n"
          "  Si el clic central te pega texto en la terminal, da igual: la\n"
          "  medición no se entera.")

    resultados = []
    try:
        for etiqueta, esperado in pedidos:
            # Un par de segundos en blanco: si acabas de pulsar algo para
            # recuperar el foco de la terminal, ese clic no cuenta.
            print(f"\n  ── prepárate para el {etiqueta} ──")
            time.sleep(2.0)
            vaciar()
            print(f"  ► Pulsa AHORA el {etiqueta}"
                  f"  (hasta {espera:.0f} s; si no, se salta)")
            recibido, nodo = None, None
            fin = time.monotonic() + espera
            while time.monotonic() < fin and recibido is None:
                listos, _, _ = select.select(list(fds), [], [],
                                             max(0.0, fin - time.monotonic()))
                for fd in listos:
                    try:
                        datos = os.read(fd, TAM_EVENTO * 64)
                    except BlockingIOError:
                        continue
                    for i in range(0, len(datos) - TAM_EVENTO + 1, TAM_EVENTO):
                        _, _, tipo, codigo, valor = struct.unpack(
                            FORMATO_EVENTO, datos[i:i + TAM_EVENTO])
                        if tipo == EV_KEY and valor == 1 and recibido is None:
                            recibido, nodo = codigo, fds[fd]
            if recibido is None:
                print("     (nada)")
            else:
                nombre = BOTONES_KERNEL.get(recibido, f"0x{recibido:03X}")
                marca = "OK" if recibido == esperado else "← NO COINCIDE"
                print(f"     llegó: {nombre}   por {nodo}   {marca}")
            resultados.append((etiqueta, esperado, recibido))
    finally:
        for fd in fds:
            os.close(fd)

    print("\n  Resumen:")
    fallos = 0
    for etiqueta, esperado, recibido in resultados:
        if recibido is None:
            estado = "sin pulsar"
        elif recibido == esperado:
            estado = "correcto"
        else:
            estado = f"llega como {BOTONES_KERNEL.get(recibido, hex(recibido))}"
            fallos += 1
        print(f"     {etiqueta:32} {estado}")
    if fallos:
        print(f"\n     *** {fallos} botón(es) mandan un código que no es el suyo ***")
    else:
        print("\n     Todos los botones mandan lo que les toca.")


def bloque_mapa(espera: float) -> None:
    titulo("MAPA DE BOTONES: qué pulsas y qué llega")
    punteros = punteros_del_sistema()
    logitech = [p[0] for p in punteros if p[2].startswith("046d")]
    if not logitech:
        print("  No se encontró ningún puntero de Logitech.")
        return
    print(f"  Escuchando: {', '.join(logitech)}")
    mapa_de_botones(logitech, espera)


def bloque_registros(nodo_forzado: str | None, todos: bool = False) -> None:
    """Barre los registros del receptor y enseña los que contestan.

    No hay forma de preguntarle a un receptor qué registros tiene: se prueban
    y se mira. "Dirección inválida" significa que no existe; cualquier otra
    respuesta es algo que está ahí. Sólo lee.
    """
    titulo("REGISTROS DEL RECEPTOR (HID++ 1.0)")

    # El receptor es el nodo que responde en el índice 0xFF con HID++ 1.0.
    candidatos = [n for n in enumerate_nodes()
                  if n.hidpp and n.is_logitech
                  and (not nodo_forzado or n.path == nodo_forzado)]
    if not candidatos:
        print("  No se encontró ningún nodo Logitech con canal HID++.")
        return

    for nodo in candidatos:
        canal = RawChannel(nodo.path)
        hpp1 = Hidpp10(canal, 0xFF)
        # Un receptor contesta al registro de firmware; un ratón detrás del
        # receptor, no: así se distingue sin depender del nombre.
        try:
            hpp1.leer(0xF1, b"\x01\x00\x00", timeout=0.3)
        except (HidppError, NoResponse, OSError):
            canal.close()
            continue

        print(f"\n  == {nodo.path}  ({nodo.id_str})  {nodo.name} ==")
        rango = range(0x00, 0x100) if todos else sorted(REGISTROS)
        encontrados = 0
        for direccion in rango:
            for etiqueta, leer in (("corto", hpp1.leer),
                                   ("largo", hpp1.leer_largo)):
                try:
                    r = leer(direccion, timeout=0.25)
                except HidppError as e:
                    # "Dirección inválida" es la respuesta normal de un
                    # registro que no existe: no se enseña, sería ruido.
                    if e.code != 0x02:
                        print(f"     0x{direccion:02X} {etiqueta:5} "
                              f"⚠ {ERRORES_1_0.get(e.code, hex(e.code))}"
                              f"   {REGISTROS.get(direccion, '')}")
                        encontrados += 1
                    continue
                except (NoResponse, OSError):
                    continue
                print(f"     0x{direccion:02X} {etiqueta:5} {hx(r[:16])}"
                      f"   {REGISTROS.get(direccion, '')}")
                encontrados += 1
        print(f"\n     {encontrados} registro(s) respondieron")
        canal.close()


def bloque_un_registro(nodo_forzado: str | None, direccion: int) -> None:
    """Barre el primer parámetro de un registro concreto, de 0 a 255.

    Varios registros contestan "parámetro no admitido" o "error de recursos"
    cuando se les pregunta en seco: existen, pero llevan un subregistro. La
    única forma de saber cuáles acepta es probarlos. Sólo lee.
    """
    titulo(f"REGISTRO 0x{direccion:02X} — barrido de parámetros")

    candidatos = [n for n in enumerate_nodes()
                  if n.hidpp and n.is_logitech
                  and (not nodo_forzado or n.path == nodo_forzado)]
    for nodo in candidatos:
        canal = RawChannel(nodo.path)
        hpp1 = Hidpp10(canal, 0xFF)
        try:
            hpp1.leer(0x00, timeout=0.3)
        except (HidppError, NoResponse, OSError):
            canal.close()
            continue

        print(f"  == {nodo.path}  ({nodo.id_str}) ==")
        print(f"  {REGISTROS.get(direccion, 'sin documentar')}\n")
        vistos = 0
        for etiqueta, leer in (("corto", hpp1.leer), ("largo", hpp1.leer_largo)):
            respuestas: dict[bytes, list[int]] = {}
            for p in range(0x100):
                try:
                    r = leer(direccion, bytes([p, 0, 0]), timeout=0.2)
                except (HidppError, NoResponse, OSError):
                    continue
                respuestas.setdefault(bytes(r[:16]), []).append(p)
            for datos, params in respuestas.items():
                # Los parámetros que dan lo mismo se agrupan: si un registro
                # ignora el subregistro, se vería como 256 líneas idénticas.
                if len(params) > 8:
                    cual = f"{len(params)} valores (0x{params[0]:02X}…0x{params[-1]:02X})"
                else:
                    cual = ", ".join(f"0x{p:02X}" for p in params)
                print(f"     {etiqueta:5} param {cual:34} -> {hx(datos)}")
                vistos += 1
        if not vistos:
            print("     ningún parámetro dio respuesta")
        canal.close()


def poner_tasa(s: Sonda, hz: int) -> bool:
    """Cambia la tasa de reporte de verdad, abriendo antes las features ocultas.

    Éste es el hallazgo de la sesión: `0x8061` función 3 no aplica nada por
    receptor salvo que antes se desbloquee `0x1E00`. Con eso abierto, el
    enlace cambia de verdad — medido: de 1,000 ms a 0,250 ms de intervalo.

    Y hay que saber que **la función 2 miente**: después de cambiar la tasa
    sigue devolviendo el índice anterior. La única forma de comprobarlo es
    cronometrar los informes que llegan al kernel.
    """
    MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]
    if hz not in MAPEO_HZ:
        print(f"  {hz} Hz no está en la tabla: {MAPEO_HZ}")
        return False
    idx = MAPEO_HZ.index(hz)

    abierto_antes = False
    if s.tiene(0x1E00):
        r = s.llamar(0x1E00, 0x00)
        abierto_antes = bool(r and r[0])
        if not abierto_antes:
            s.llamar(0x1E00, 0x01, b"\x01")
            r = s.llamar(0x1E00, 0x00)
            if not (r and r[0]):
                print("  No se pudieron abrir las features ocultas.")
                return False
    try:
        s.hpp.call(s.tabla[0x8061].index, 0x03, bytes([idx]))
    except (HidppError, NoResponse, OSError) as e:
        print(f"  la escritura falló: {e}")
        return False
    finally:
        if s.tiene(0x1E00) and not abierto_antes:
            try:
                s.hpp.call(s.tabla[0x1E00].index, 0x01, b"\x00")
            except (HidppError, NoResponse, OSError):
                pass
    return True


def bloque_poner_tasa(s: Sonda, hz: int, segundos: float) -> None:
    titulo(f"PONER LA TASA A {hz} Hz")
    print("  Se abren las features ocultas (0x1E00), se escribe, y se vuelven")
    print("  a cerrar. Después se mide, porque la función 2 no es de fiar.\n")

    if not poner_tasa(s, hz):
        return
    print(f"  Escrito. La función 2 dice ahora: "
          f"{(s.llamar(0x8061, 0x02) or [b'?'])[0]}  (no te fíes)")

    punteros = punteros_del_sistema()
    logitech = [p[0] for p in punteros if p[2].startswith("046d")]
    if not logitech:
        print("\n  No se encontró el puntero para medir.")
        return
    medir_tasa(logitech[0], segundos)


def bloque_features_ocultas(s: Sonda, objetivo_hz: int = 4000) -> None:
    """Desbloquea las features internas y reintenta escribir la tasa.

    La 0x1E00 es el mecanismo de Logitech para abrir las features marcadas
    como internas u ocultas; este ratón declara doce. Solaar sólo define la
    constante y no la usa, así que es terreno sin explorar. La hipótesis: que
    la escritura de la tasa esté detrás de esa puerta.

    Se deja el ratón como estaba al terminar.
    """
    titulo("FEATURES OCULTAS (0x1E00) — ¿abren la escritura de la tasa?")

    if not s.tiene(0x1E00):
        print("  Este ratón no expone 0x1E00.")
        return
    MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]

    antes = s.mostrar("f0  ¿están abiertas?", 0x1E00, 0x00)
    estado_previo = antes[0] if antes else 0

    print("\n  Abriendo…")
    s.mostrar("f1  abrir (0x01)", 0x1E00, 0x01, b"\x01")
    ahora = s.mostrar("f0  ¿y ahora?", 0x1E00, 0x00)
    if not ahora or not ahora[0]:
        print("     no se abrieron; se deja como estaba")
        return
    print("     ✓ abiertas")

    try:
        # ¿Cambia lo que declara la tasa de reporte con las features abiertas?
        print("\n  Lo que dice ahora 0x8061:")
        for etiqueta, fid, func, params in (
                ("f0 cable", 0x8061, 0x00, b"\x00"),
                ("f0 inalámbrico", 0x8061, 0x00, b"\x01"),
                ("f1 lista", 0x8061, 0x01, b""),
                ("f2 actual", 0x8061, 0x02, b"")):
            r = s.mostrar(f"     {etiqueta}", fid, func, params)
            if r and func in (0x00, 0x01):
                bm = int.from_bytes(r[0:2], "big")
                print(f"        -> {[MAPEO_HZ[n] for n in range(7) if bm & (1 << n)]}")

        idx = MAPEO_HZ.index(objetivo_hz)
        actual = s.llamar(0x8061, 0x02)
        print(f"\n  Escribiendo el índice {idx} ({objetivo_hz} Hz), "
              f"estando ahora en {actual[0] if actual else '?'}:")
        for etiqueta, params in (("f3 [idx]", bytes([idx])),
                                 ("f3 [idx, 0, 0]", bytes([idx, 0, 0]))):
            try:
                r = s.hpp.call(s.tabla[0x8061].index, 0x03, params)
                leido = s.llamar(0x8061, 0x02)
                marca = ("← CAMBIÓ" if leido and leido[0] == idx
                         else f"(sigue en {leido[0] if leido else '?'})")
                print(f"     {etiqueta:16} resp {hx(r[:4])}  {marca}")
                if leido and leido[0] == idx:
                    print("\n     *** FUNCIONA con las features ocultas abiertas ***")
                    print("     Mide la tasa real para confirmarlo:")
                    print("        python3 depurar.py --medir")
                    return
            except (HidppError, NoResponse, OSError) as e:
                print(f"     {etiqueta:16} ⚠ {e}")
        print("\n     Tampoco por aquí.")
    finally:
        # Dejarlo abierto sería dejar el ratón en un estado que nadie espera.
        if not estado_previo:
            print("\n  Cerrando las features ocultas…")
            try:
                s.hpp.call(s.tabla[0x1E00].index, 0x01, b"\x00")
                fin = s.llamar(0x1E00, 0x00)
                print(f"     estado final: {fin[0] if fin else '?'}")
            except (HidppError, NoResponse, OSError) as e:
                print(f"     ⚠ no se pudieron cerrar: {e}")


def bloque_dpi_clasico(s: Sonda) -> None:
    """DPI por 0x2201, la feature anterior a 0x2202.

    Los ratones que no llevan 0x2202 —el G203, por ejemplo— usan ésta: un solo
    eje, sin distancia de despegue, y la lista de valores admitidos viene
    entera en una respuesta en vez de en un flujo paginado.
    """
    titulo("DPI (0x2201, la feature clásica)")
    print(f"  versión de la feature en este ratón: v{s.tabla[0x2201].version}\n")

    s.mostrar("f0  getSensorCount", 0x2201, 0x00)
    lista = s.mostrar("f1  getSensorDpiList(0)", 0x2201, 0x01, b"\x00")
    if lista:
        # El flujo son u16: un valor suelto es un DPI admitido, y un valor con
        # el bit alto puesto abre un tramo "desde-hasta-cada".
        valores = [int.from_bytes(lista[i:i + 2], "big")
                   for i in range(1, len(lista) - 1, 2)]
        valores = [v for v in valores if v]
        if valores:
            print(f"      → valores declarados: {valores}")

    actual = s.mostrar("f2  getSensorDpi(0)  ← el DPI de ahora", 0x2201, 0x02,
                       b"\x00")
    if actual and len(actual) >= 5:
        print(f"      → DPI actual: {int.from_bytes(actual[1:3], 'big')}"
              f"   ·   por defecto: {int.from_bytes(actual[3:5], 'big')}")


def bloque_tasa_clasica(s: Sonda) -> None:
    """Tasa de reporte por 0x8060, la feature anterior a 0x8061.

    Aquí la tasa es el periodo en milisegundos, no un índice: 1 ms son 1000 Hz.
    Es el tope de esta feature, y por eso los ratones que pasan de ahí llevan
    la 0x8061.
    """
    titulo("TASA DE REPORTE (0x8060, la feature clásica)")

    r = s.mostrar("f0  getReportRateList", 0x8060, 0x00)
    if r:
        admitidas = [1000 // ms for ms in range(1, 9)
                     if r[0] & (1 << (ms - 1)) and 1000 % ms == 0]
        print(f"      → admite: {sorted(admitidas, reverse=True)} Hz")

    r = s.mostrar("f1  getReportRate  ← la tasa de ahora", 0x8060, 0x01)
    if r and r[0]:
        print(f"      → {r[0]} ms = {1000 // r[0]} Hz")


def bloque_leds(s: Sonda) -> None:
    """Vuelca lo que el ratón diga de sus luces. Sólo lee.

    Aún no está decodificado: la idea es justo ésa, recoger volcados de ratones
    con iluminación para deducirlo desde bytes reales, que es como se sacó el
    formato de perfil 0x07.

    Sólo se piden funciones de consulta. Probar números de función a ciegas
    puede escribir algo, y un volcado que va a ejecutar gente con otro hardware
    no es sitio para arriesgarse.
    """
    titulo("ILUMINACIÓN — volcado para decodificar")

    tiene_alguna = False

    # 0x8071 se consulta con la función 0, pero hay que decirle QUÉ se pregunta:
    # 0xFF significa "háblame de ti". Con ceros contesta ceros, que fue lo que
    # despistó en el primer informe que llegó.
    if s.tiene(0x8071):
        tiene_alguna = True
        print(f"\n  0x8071 efectos RGB  (v{s.tabla[0x8071].version})")
        general = s.mostrar("     f0  info general (FF FF 00)", 0x8071, 0x00,
                            b"\xff\xff\x00")
        n_zonas = general[0] if general else 0
        if general:
            print(f"      → zonas de luz declaradas: {n_zonas}")

        for zona in range(max(n_zonas, 1) if n_zonas else 0):
            info = s.mostrar(f"     f0  zona {zona} ({zona:02X} FF 00)",
                             0x8071, 0x00, bytes([zona, 0xFF, 0x00]))
            if not info:
                continue
            n_efectos = info[2] if len(info) > 2 else 0
            print(f"      → efectos que admite la zona {zona}: {n_efectos}")
            for efecto in range(min(n_efectos, 12)):
                r = s.mostrar(f"     f0  zona {zona} efecto {efecto}",
                              0x8071, 0x00, bytes([zona, efecto, 0x00]))
                if r and len(r) > 3:
                    print(f"      → id de efecto 0x{int.from_bytes(r[2:4], 'big'):04X}")
    else:
        print("  0x8071 efectos RGB: no lo expone este ratón")

    for fid, nombre in ((0x8070, "efectos LED"), (0x1300, "control de LEDs")):
        if not s.tiene(fid):
            print(f"  0x{fid:04X} {nombre}: no lo expone este ratón")
            continue
        tiene_alguna = True
        print(f"\n  0x{fid:04X} {nombre}  (v{s.tabla[fid].version})")
        for func in (0x00, 0x01):
            for params in (b"", b"\x00", b"\xff\xff\x00"):
                s.mostrar(f"     f{func} params {hx(params) or '(ninguno)'}",
                          fid, func, params)

    # Los efectos guardados en el perfil onboard. En la disposición clásica son
    # dos bloques de 11 bytes desde el byte 208; el 0x07 reserva sitio para más.
    if s.tiene(0x8100):
        info = s.llamar(0x8100, 0x00)
        if info:
            clasico = info[1] < 0x07
            cuantos = 2 if clasico else 4
            tam = int.from_bytes(info[7:9], "big")
            crudo = leer_sector(s, 1, tam)
            if crudo and len(crudo) >= 208 + cuantos * 11:
                print(f"\n  Efectos guardados en el perfil, desde el byte 208 "
                      f"({cuantos} bloques de 11 bytes):")
                for i in range(cuantos):
                    trozo = crudo[208 + i * 11:219 + i * 11]
                    print(f"     efecto {i}: {hx(trozo)}   {describir_efecto(trozo)}")
                tiene_alguna = True

    if not tiene_alguna:
        print("\n  Este ratón no parece tener iluminación.")


def describir_efecto(b: bytes) -> str:
    """Interpretación PROVISIONAL de un bloque de efecto de 11 bytes.

    El primer byte es el tipo; el resto depende del tipo y aún no está
    confirmado. Se marca como hipótesis a propósito: hasta que no haya dos
    volcados del mismo ratón con efectos distintos, esto son conjeturas y no
    debe tratarse de otra forma.
    """
    if not b or len(b) < 11:
        return ""
    if all(x == 0xFF for x in b):
        return "(sin usar)"
    tipo = b[0]
    if tipo == 0x00:
        return "apagado"
    rgb = f"#{b[1]:02X}{b[2]:02X}{b[3]:02X}"
    nombres = {0x01: "color fijo", 0x02: "respiración", 0x03: "ciclo de color",
               0x04: "¿onda de color?", 0x05: "¿starlight?", 0x0A: "¿respiración?"}
    hipotesis = nombres.get(tipo, f"tipo 0x{tipo:02X} desconocido")
    if tipo == 0x01:
        return f"{hipotesis} {rgb}"
    return f"{hipotesis}  (color {rgb}, resto sin descifrar)"


def bloque_informe(s: Sonda, ruta: str, nodo, segundos: float = 0.0) -> None:
    """Recoge todo lo que se puede leer, en un fichero para compartir.

    Sirve para pedir ayuda: alguien con otro ratón lo ejecuta y manda el
    fichero, y con eso se puede añadir soporte sin tener el aparato delante.
    Es lo que hicimos aquí con los volcados del PRO X 2.

    No escribe nada en el ratón. El fichero lleva el modelo y las respuestas
    del protocolo; no hay nada personal en él.
    """
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"gpx2 — informe de dispositivo")
        print(f"{nodo.id_str} · {nodo.name} · {nodo.path}")
        print(f"{len(s.tabla)} features\n")
        print("Features declaradas:")
        for f in sorted(s.tabla.values(), key=lambda x: x.index):
            marcas = [m for m, v in (("oculta", f.hidden), ("interna", f.internal),
                                     ("obsoleta", f.obsolete)) if v]
            print(f"  idx {f.index:>2}  0x{f.fid:04X} v{f.version}  {f.name}"
                  + (f"  [{', '.join(marcas)}]" if marcas else ""))
        bloque_bateria(s)
        if s.tiene(0x8100):
            bloque_perfiles_onboard(s)
        if s.tiene(0x2202):
            bloque_dpi(s)
            bloque_rangos(s)
        elif s.tiene(0x2201):
            bloque_dpi_clasico(s)
        if s.tiene(0x8061):
            bloque_tasa(s)
        elif s.tiene(0x8060):
            bloque_tasa_clasica(s)
        bloque_leds(s)

    texto = buf.getvalue()
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(texto)
    print(texto)
    print(f"\n{'=' * 72}")
    print(f"  Informe guardado en {ruta}")
    print("  Puedes mandarlo tal cual: no lleva nada personal, sólo el modelo")
    print("  del ratón y lo que contesta al protocolo.")


def bloque_medir(segundos: float) -> None:
    titulo("TASA REAL MEDIDA (no lo que el ratón dice, lo que hace)")
    punteros = punteros_del_sistema()
    if not punteros:
        print("  No se encontró ningún puntero en /dev/input.")
        return
    print("  Punteros del sistema:")
    for i, (dev, nombre, ids) in enumerate(punteros):
        print(f"    [{i}] {dev:20} {ids}  {nombre}")

    # El del ratón Logitech, si lo hay; si no, el primero.
    elegido = next((p for p in punteros if p[2].startswith("046d")), punteros[0])
    print(f"\n  Elegido: {elegido[1]}  ({elegido[0]})")
    medir_tasa(elegido[0], segundos)


def crc16_ccitt(datos: bytes) -> int:
    """CRC-16/CCITT-FALSE: polinomio 0x1021, inicio 0xFFFF, sin reflejar.

    Es el que cierra cada sector de perfil. Calcularlo bien es el requisito
    para poder escribir: un sector con el CRC mal lo rechaza el ratón, o peor,
    lo acepta y queda corrupto.
    """
    crc = 0xFFFF
    for byte in datos:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# Un botón ocupa 4 bytes. El nibble alto del primero es el comportamiento.
COMPORTAMIENTOS = {0x0: "ejecutar macro", 0x1: "parar macro",
                   0x2: "parar todas las macros", 0x8: "enviar", 0x9: "función"}
TIPOS_ENVIO = {0x0: "nada", 0x1: "botón", 0x2: "modificador+tecla",
               0x3: "tecla multimedia"}
BOTONES_RATON = {0x0001: "clic izquierdo", 0x0002: "clic derecho",
                 0x0004: "clic central", 0x0008: "atrás", 0x0010: "adelante"}
FUNCIONES = {0x00: "ninguna", 0x01: "inclinar izquierda", 0x02: "inclinar derecha",
             0x03: "DPI siguiente", 0x04: "DPI anterior", 0x05: "ciclar DPI",
             0x06: "DPI por defecto", 0x07: "DPI temporal", 0x08: "perfil siguiente",
             0x09: "perfil anterior", 0x0A: "ciclar perfil", 0x0B: "G-Shift",
             0x0C: "estado de batería", 0x0D: "elegir perfil",
             0x0E: "cambiar de modo", 0x0F: "cambiar de host",
             0x10: "rueda abajo", 0x11: "rueda arriba"}


def describir_boton(b: bytes) -> str:
    """Traduce los 4 bytes de un botón a algo legible."""
    comportamiento = b[0] >> 4
    nombre = COMPORTAMIENTOS.get(comportamiento, f"0x{comportamiento:X}?")
    if comportamiento == 0x8:                       # enviar
        tipo = TIPOS_ENVIO.get(b[1], f"0x{b[1]:02X}?")
        valor = (b[2] << 8) | b[3]
        if b[1] == 0x01:
            return f"{nombre} · {tipo}: {BOTONES_RATON.get(valor, f'0x{valor:04X}')}"
        return f"{nombre} · {tipo}: 0x{valor:04X}"
    if comportamiento == 0x9:                       # función interna
        return f"{nombre}: {FUNCIONES.get(b[1], f'0x{b[1]:02X}?')}"
    return nombre


def buscar_botones(sector: bytes, cuantos: int) -> int | None:
    """Localiza dónde empieza el bloque de botones dentro del sector.

    En el formato 0x06 empiezan en el byte 32, pero el 0x07 mete cinco bytes
    por nivel de DPI en vez de dos, así que la posición no tiene por qué ser la
    misma. En vez de suponerla, se busca: un botón válido empieza por un nibble
    de comportamiento conocido, y tiene que haber varios seguidos.
    """
    def plausible(b: bytes) -> bool:
        """Un botón de verdad, no cuatro bytes que casualmente encajan.

        Con aceptar cualquier nibble conocido, el bloque de niveles de DPI daba
        un falso positivo: sus bytes también empiezan por 0x0 y 0x8.
        """
        comportamiento = b[0] >> 4
        if comportamiento == 0x8:               # enviar: el tipo acota mucho
            return b[1] in TIPOS_ENVIO
        if comportamiento == 0x9:               # función: tiene que existir
            return b[1] in FUNCIONES
        return False

    for inicio in range(0, len(sector) - cuantos * 4 + 1):
        if all(plausible(sector[inicio + i * 4:inicio + i * 4 + 4])
               for i in range(cuantos)):
            return inicio
    return None


def leer_sector(s: Sonda, sector: int, tam: int) -> bytes | None:
    """Lee un sector entero de la memoria de perfiles (0x8100 función 5).

    Cada petición devuelve 16 bytes y el tamaño de sector no es múltiplo de 16,
    así que el último bloque se pide solapado desde el final: pedirlo en su
    sitio se saldría del sector y la petición falla en silencio.
    """
    datos = b""
    desp = 0
    while desp <= tam - 16:
        trozo = s.llamar(0x8100, 0x05,
                         bytes([sector >> 8, sector & 0xFF,
                                desp >> 8, desp & 0xFF]))
        if trozo is None:
            return None
        datos += trozo
        desp += 16
    if len(datos) < tam and tam % 16:
        cola = s.llamar(0x8100, 0x05,
                        bytes([sector >> 8, sector & 0xFF,
                               (tam - 16) >> 8, (tam - 16) & 0xFF]))
        if cola is None:
            return None
        datos += cola[16 - tam % 16:]
    return datos[:tam]


def escribir_sector(s: Sonda, sector: int, datos: bytes) -> None:
    """Escribe un sector completo. Función 6 abre, 7 manda trozos, 8 cierra.

    Los dos últimos bytes deben ser el CRC-16/CCITT del resto; el ratón lo
    comprueba. Quien llame a esto ya debe haberlo calculado.
    """
    idx = s.tabla[0x8100].index
    tam = len(datos)
    s.hpp.call(idx, 0x06, bytes([sector >> 8, sector & 0xFF, 0, 0,
                                 tam >> 8, tam & 0xFF]))
    for desp in range(0, tam, 16):
        s.hpp.call(idx, 0x07, datos[desp:desp + 16])
    s.hpp.call(idx, 0x08)


def bloque_prueba_escritura(s: Sonda, sector: int, ruta_copia: str) -> None:
    """Reescribe un sector con lo mismo que ya tenía. Prueba en seco.

    La idea es ejercitar el mecanismo entero —abrir, mandar, cerrar y el CRC—
    sin cambiar ningún valor, para saber si funciona antes de tocar nada que
    importe. Y se hace sobre un perfil DESHABILITADO: si algo saliera mal, el
    ratón no lo usa para nada.
    """
    titulo(f"PRUEBA EN SECO: reescribir el sector 0x{sector:04X} sin cambios")

    info = s.llamar(0x8100, 0x00)
    if not info:
        print("  No se pudo leer la información de perfiles.")
        return
    tam = int.from_bytes(info[7:9], "big")

    original = leer_sector(s, sector, tam)
    if original is None or len(original) != tam:
        print(f"  No se pudo leer el sector entero ({tam} bytes).")
        return

    with open(ruta_copia, "wb") as fh:
        fh.write(original)
    print(f"  Copia de seguridad guardada en {ruta_copia} ({tam} bytes).")

    esperado = int.from_bytes(original[tam - 2:tam], "big")
    calculado = crc16_ccitt(original[:tam - 2])
    if esperado != calculado:
        print(f"  El CRC no cuadra (dice 0x{esperado:04X}, calculamos "
              f"0x{calculado:04X}). No se escribe nada.")
        return
    print(f"  CRC comprobado: 0x{esperado:04X}. Se reescribe lo mismo.")

    try:
        escribir_sector(s, sector, original)
    except (HidppError, NoResponse, OSError) as e:
        print(f"  ⚠ la escritura falló: {e}")
        print(f"  El sector puede haber quedado a medias. Para restaurarlo:")
        print(f"     sudo python3 depurar.py --restaurar {ruta_copia} "
              f"--sector {sector}")
        return

    despues = leer_sector(s, sector, tam)
    if despues is None:
        print("  No se pudo releer el sector.")
        return
    if despues == original:
        print("\n     *** FUNCIONA: el sector volvió idéntico ***")
        print("     El mecanismo de escritura y el CRC son correctos.")
    else:
        print("\n     ✗ el sector cambió al reescribirlo:")
        for i in range(0, tam, 16):
            a, b = original[i:i + 16], despues[i:i + 16]
            if a != b:
                print(f"       +{i:03d} antes  {hx(a)}")
                print(f"       +{i:03d} ahora  {hx(b)}")
        print(f"\n     Para restaurarlo: sudo python3 depurar.py "
              f"--restaurar {ruta_copia} --sector {sector}")


def bloque_restaurar(s: Sonda, ruta: str, sector: int) -> None:
    """Devuelve un sector a como estaba, desde una copia guardada."""
    titulo(f"RESTAURAR el sector 0x{sector:04X} desde {ruta}")
    try:
        with open(ruta, "rb") as fh:
            datos = fh.read()
    except OSError as e:
        print(f"  no se pudo leer la copia: {e}")
        return
    print(f"  {len(datos)} bytes. CRC guardado: "
          f"0x{int.from_bytes(datos[-2:], 'big'):04X}")
    try:
        escribir_sector(s, sector, datos)
    except (HidppError, NoResponse, OSError) as e:
        print(f"  ⚠ falló: {e}")
        return
    vuelta = leer_sector(s, sector, len(datos))
    print("  ✓ restaurado" if vuelta == datos else "  ✗ no coincide tras escribir")


# Acciones que se pueden poner en un botón, por nombre. Los cuatro bytes son
# los que el ratón guarda tal cual en su perfil.
ACCIONES = {
    "izquierdo":  bytes([0x80, 0x01, 0x00, 0x01]),
    "derecho":    bytes([0x80, 0x01, 0x00, 0x02]),
    "central":    bytes([0x80, 0x01, 0x00, 0x04]),
    "atras":      bytes([0x80, 0x01, 0x00, 0x08]),
    "adelante":   bytes([0x80, 0x01, 0x00, 0x10]),
    "ciclar-dpi": bytes([0x90, 0x05, 0x00, 0x00]),
    "dpi-mas":    bytes([0x90, 0x03, 0x00, 0x00]),
    "dpi-menos":  bytes([0x90, 0x04, 0x00, 0x00]),
    "bateria":    bytes([0x90, 0x0C, 0x00, 0x00]),
    "nada":       bytes([0x80, 0x00, 0x00, 0x00]),
}


def bloque_botones_de_fabrica(s: Sonda, sector: int, ruta_copia: str) -> None:
    """Deja los cinco botones como vienen de fábrica.

    Red de seguridad: si un botón queda mal configurado puede costar usar el
    ratón, y entonces no es momento de andar eligiendo acciones en una lista.
    """
    titulo(f"BOTONES DE FÁBRICA en el sector 0x{sector:04X}")
    DE_FABRICA = [ACCIONES["izquierdo"], ACCIONES["derecho"],
                  ACCIONES["central"], ACCIONES["atras"], ACCIONES["adelante"]]

    info = s.llamar(0x8100, 0x00)
    if not info:
        print("  No se pudo leer la información de perfiles.")
        return
    tam = int.from_bytes(info[7:9], "big")
    cuantos = info[5]

    original = leer_sector(s, sector, tam)
    if original is None or len(original) != tam:
        print("  No se pudo leer el sector.")
        return
    with open(ruta_copia, "wb") as fh:
        fh.write(original)
    print(f"  Copia de lo que había en {ruta_copia}")

    inicio = buscar_botones(original, cuantos)
    if inicio is None:
        print("  No se encontró el bloque de botones. No se toca nada.")
        return
    print(f"  Bloque en el byte {inicio}. Estado actual:")
    for i in range(cuantos):
        b = original[inicio + i * 4:inicio + i * 4 + 4]
        print(f"     botón {i}: {hx(b)}   {describir_boton(b)}")

    cuerpo = bytearray(original[:tam - 2])
    for i, valor in enumerate(DE_FABRICA[:cuantos]):
        cuerpo[inicio + i * 4:inicio + i * 4 + 4] = valor
    nuevo = bytes(cuerpo) + crc16_ccitt(bytes(cuerpo)).to_bytes(2, "big")

    try:
        escribir_sector(s, sector, nuevo)
    except (HidppError, NoResponse, OSError) as e:
        print(f"  ⚠ falló: {e}")
        return
    despues = leer_sector(s, sector, tam)
    if despues == nuevo:
        print("\n     ✓ los cinco botones vuelven a ser los de fábrica")
    else:
        print("\n     ✗ no quedó como se pidió")


def bloque_cambiar_boton(s: Sonda, sector: int, numero: int, accion: str,
                         ruta_copia: str, forzar: bool) -> None:
    """Cambia un botón del perfil onboard. Escribe en el ratón.

    Guarda antes el sector entero, para poder deshacerlo con --restaurar.
    """
    titulo(f"CAMBIAR EL BOTÓN {numero} A «{accion}» "
           f"(sector 0x{sector:04X})")

    if accion not in ACCIONES:
        print(f"  «{accion}» no está. Disponibles: {', '.join(ACCIONES)}")
        return
    if numero in (0, 1) and not forzar:
        print("  Los botones 0 y 1 son el clic izquierdo y el derecho. "
              "Cambiarlos\n  puede dejarte sin poder pulsar nada mientras el "
              "perfil esté activo.\n  Si de verdad quieres, añade --forzar.")
        return

    info = s.llamar(0x8100, 0x00)
    if not info:
        print("  No se pudo leer la información de perfiles.")
        return
    tam = int.from_bytes(info[7:9], "big")
    cuantos = info[5]

    original = leer_sector(s, sector, tam)
    if original is None or len(original) != tam:
        print("  No se pudo leer el sector entero.")
        return
    if crc16_ccitt(original[:tam - 2]) != int.from_bytes(original[tam - 2:], "big"):
        print("  El CRC del sector no cuadra. No se toca nada.")
        return

    with open(ruta_copia, "wb") as fh:
        fh.write(original)
    print(f"  Copia guardada en {ruta_copia}")

    inicio = buscar_botones(original, cuantos)
    if inicio is None:
        print("  No se encontró el bloque de botones.")
        return
    if not 0 <= numero < cuantos:
        print(f"  Este perfil sólo tiene {cuantos} botones (0..{cuantos - 1}).")
        return

    pos = inicio + numero * 4
    antes = original[pos:pos + 4]
    nuevo_valor = ACCIONES[accion]
    print(f"  Botón {numero}, en el byte {pos}:")
    print(f"     antes: {hx(antes)}   {describir_boton(antes)}")
    print(f"     ahora: {hx(nuevo_valor)}   {describir_boton(nuevo_valor)}")
    if antes == nuevo_valor:
        print("\n  Ya estaba así. No se escribe nada.")
        return

    # El CRC cubre todo el sector menos sus dos últimos bytes.
    cuerpo = bytearray(original[:tam - 2])
    cuerpo[pos:pos + 4] = nuevo_valor
    modificado = bytes(cuerpo) + crc16_ccitt(bytes(cuerpo)).to_bytes(2, "big")
    print(f"  CRC nuevo: 0x{int.from_bytes(modificado[-2:], 'big'):04X}")

    try:
        escribir_sector(s, sector, modificado)
    except (HidppError, NoResponse, OSError) as e:
        print(f"  ⚠ la escritura falló: {e}")
        print(f"  Restaura con: sudo python3 depurar.py --restaurar "
              f"{ruta_copia} --sector {sector}")
        return

    despues = leer_sector(s, sector, tam)
    if despues == modificado:
        print("\n     *** ESCRITO: el sector quedó como queríamos ***")
    else:
        print("\n     ✗ el sector no quedó como se pidió.")
        print(f"     Restaura con: sudo python3 depurar.py --restaurar "
              f"{ruta_copia} --sector {sector}")
        return

    modo = s.llamar(0x8100, 0x02)
    if modo and modo[0] != 0x01:
        print("\n  OJO: el ratón está en modo host, y en ese modo NO usa su")
        print("  perfil interno, así que el botón seguirá haciendo lo de antes.")
        print("  Para probarlo hay que pasarlo a onboard:")
        print("     sudo python3 depurar.py --modo onboard")
        print("  y para volver:")
        print("     sudo python3 depurar.py --modo host")
    print(f"\n  Para deshacer el cambio: sudo python3 depurar.py --restaurar "
          f"{ruta_copia} --sector {sector}")


def bloque_cambiar_modo(s2: Sonda, modo: str) -> None:
    """Cambia entre onboard y host desde la línea de órdenes."""
    titulo(f"MODO -> {modo}")
    valor = 0x01 if modo == "onboard" else 0x02
    s2.llamar(0x8100, 0x01, bytes([valor]))
    ahora = s2.llamar(0x8100, 0x02)
    if ahora:
        nombres = {0x01: "onboard (manda el ratón)", 0x02: "host (manda el PC)"}
        print(f"  modo actual: {nombres.get(ahora[0], hex(ahora[0]))}")


def bloque_perfiles_onboard(s: Sonda) -> None:
    """Vuelca la memoria de perfiles del ratón. Sólo lee, no escribe nada.

    El primer byte de cada perfil es la tasa de reporte en milisegundos, y ahí
    está la sospecha: puede que el enlace inalámbrico coja de aquí su tasa al
    conectarse, y por eso escribir por 0x8061 no sirva de nada.

    Leer memoria es la función 5: [sector(2), desplazamiento(2)] -> 16 bytes.
    """
    titulo("PERFILES ONBOARD (0x8100) — volcado de memoria")

    info = s.llamar(0x8100, 0x00)
    if not info:
        print("  No se pudo leer la información de perfiles.")
        return
    # [0]=memoria [1]=formato de perfil [2]=formato de macro
    # [3]=nº perfiles [4]=fuera de caja [5]=botones [6]=sectores
    # [7:9]=tamaño de sector [9]=desplazamiento
    n_perfiles, botones = info[3], info[5]
    sectores = info[6]
    tam = int.from_bytes(info[7:9], "big")
    print(f"  formato de perfil: 0x{info[1]:02X}   ·   perfiles: {n_perfiles}"
          f"   ·   botones: {botones}")
    print(f"  sectores: {sectores}   ·   tamaño de sector: {tam} bytes")
    formato = info[1]
    # El 0x07 del PRO X 2 cambió la disposición de la cabecera: la tasa pasó de
    # milisegundos a un índice de la tabla de 0x8061, y cada nivel de DPI ganó
    # su segundo eje y su distancia de despegue. Los formatos anteriores llevan
    # la disposición clásica. Los botones, en cambio, son iguales en ambos.
    clasico = formato < 0x07
    print(f"  disposición: {'clásica (tasa en ms, DPI de un solo eje)' if clasico else 'nueva del 0x07 (tasa por índice, DPI con dos ejes)'}")

    def leer(sector: int, desp: int) -> bytes | None:
        return s.llamar(0x8100, 0x05,
                        bytes([sector >> 8, sector & 0xFF,
                               desp >> 8, desp & 0xFF]))

    print("\n  -- directorio (sector 0) --")
    dir0 = leer(0, 0)
    if not dir0:
        print("     no se pudo leer")
        return
    print(f"     {hx(dir0)}")

    cabeceras = []
    for i in range(0, 16, 4):
        sector = int.from_bytes(dir0[i:i + 2], "big")
        if sector in (0xFFFF, 0x0000):
            break
        cabeceras.append((sector, dir0[i + 2]))
    if not cabeceras:
        print("     el directorio está en ROM o vacío; se prueba el sector 1")
        dir0 = leer(1, 0)
        if dir0:
            print(f"     {hx(dir0)}")
            for i in range(0, 16, 4):
                sector = int.from_bytes(dir0[i:i + 2], "big")
                if sector in (0xFFFF, 0x0000):
                    break
                cabeceras.append((sector, dir0[i + 2]))

    activo = s.llamar(0x8100, 0x04)
    if activo:
        print(f"\n  perfil activo (f4): {hx(activo[:4])}")

    for n, (sector, habilitado) in enumerate(cabeceras, start=1):
        print(f"\n  -- perfil {n}: sector 0x{sector:04X}"
              f"   {'activo' if habilitado else 'deshabilitado'} --")

        # Del activo se lee el sector entero; de los demás basta la cabecera.
        cuanto = tam if habilitado else 32
        crudo = b""
        # Cada lectura devuelve 16 bytes, y el tamaño de sector no es múltiplo
        # de 16: pedir el último bloque en su sitio se sale del sector. Se lee
        # solapado desde el final y se descarta lo repetido.
        desp = 0
        while desp <= cuanto - 16:
            trozo = leer(sector, desp)
            if trozo is None:
                break
            crudo += trozo
            desp += 16
        if len(crudo) < cuanto and cuanto % 16:
            cola = leer(sector, cuanto - 16)
            if cola is not None:
                crudo += cola[16 - cuanto % 16:]
        crudo = crudo[:cuanto]
        if len(crudo) < 16:
            print("     no se pudo leer")
            continue

        if habilitado:
            for desp in range(0, len(crudo), 16):
                print(f"     +{desp:03d}  {hx(crudo[desp:desp + 16])}")
        else:
            print(f"     +000  {hx(crudo[:16])}")
            print(f"     +016  {hx(crudo[16:32])}")

        # Disposición del formato 0x07, deducida del volcado del PRO X 2. NO es
        # la del 0x06 que parsea Solaar: allí la tasa va en milisegundos y cada
        # nivel de DPI ocupa un u16; aquí la tasa es un ÍNDICE de la misma tabla
        # que usa 0x8061, y cada nivel lleva sus dos ejes y su distancia de
        # despegue.
        MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]

        if clasico:
            # El primer byte es el periodo en milisegundos, no un índice: 1 ms
            # son 1000 Hz. Después van el nivel por defecto, el nivel al que
            # salta el botón de DPI, y cinco niveles de un solo eje.
            ms = crudo[0]
            print(f"\n     tasa guardada:      {ms} ms"
                  + (f" = {1000 // ms} Hz" if ms else " (sin fijar)"))
            print(f"     nivel de DPI por defecto: {crudo[1]}"
                  f"   ·   nivel del botón de DPI: {crudo[2]}")
            for i in range(5):
                o = 3 + i * 2
                if o + 1 >= len(crudo):
                    break
                dpi = int.from_bytes(crudo[o:o + 2], "little")
                if dpi in (0, 0xFFFF):
                    continue
                marca = "  ← por defecto" if i == crudo[1] else ""
                print(f"     nivel {i}: {dpi:>5} DPI{marca}")
        else:
            def hz(i: int) -> str:
                return f"{MAPEO_HZ[i]} Hz" if i < len(MAPEO_HZ) else f"índice {i}?"

            print(f"\n     tasa guardada:      índice {crudo[0]} = {hz(crudo[0])}")
            print(f"     segunda tasa:       índice {crudo[1]} = {hz(crudo[1])}"
                  "   (¿la de la otra vía?)")
            print(f"     nivel de DPI por defecto: {crudo[2]}   ·   b[3]: {crudo[3]}")
            for i in range(5):
                o = 4 + i * 5
                if o + 4 >= len(crudo):
                    break
                x = int.from_bytes(crudo[o:o + 2], "little")
                y = int.from_bytes(crudo[o + 2:o + 4], "little")
                marca = "  ← por defecto" if i == crudo[2] else ""
                print(f"     nivel {i}: X={x:>5}  Y={y:>5}  despegue={crudo[o + 4]}{marca}")

        if not habilitado:
            continue

        # --- CRC: la prueba de que podríamos escribir bien -------------------
        esperado = int.from_bytes(crudo[tam - 2:tam], "big")
        calculado = crc16_ccitt(crudo[:tam - 2])
        igual = esperado == calculado
        print(f"\n     CRC del sector: el ratón dice 0x{esperado:04X}, "
              f"nosotros calculamos 0x{calculado:04X}")
        print(f"     → {'COINCIDE: sabríamos reescribir el sector' if igual else 'NO coincide: aún no sabemos calcularlo'}")

        # --- botones ---------------------------------------------------------
        inicio = buscar_botones(crudo, botones)
        if inicio is None:
            print("\n     no se ha encontrado un bloque de botones reconocible")
            continue
        print(f"\n     bloque de botones en el byte {inicio}:")
        for i in range(botones):
            b = crudo[inicio + i * 4:inicio + i * 4 + 4]
            print(f"       botón {i}: {hx(b)}   {describir_boton(b)}")

        # El resto del sector: nombre y efectos de LED, como en el formato 0x06.
        nombre = crudo[160:208].decode("utf-16le", "replace").rstrip("\x00\uffff")
        if nombre.strip():
            print(f"\n     nombre del perfil: {nombre!r}")

        # Tras los botones normales suelen ir los de G-Shift, otros tantos.
        segundo = inicio + botones * 4
        if segundo + botones * 4 <= len(crudo):
            grupo = crudo[segundo:segundo + botones * 4]
            if any(grupo):
                print(f"\n     ¿botones de G-Shift? en el byte {segundo}:")
                for i in range(botones):
                    b = grupo[i * 4:i * 4 + 4]
                    print(f"       botón {i}: {hx(b)}   {describir_boton(b)}")


def bloque_tasa(s: Sonda) -> None:
    """Números de función según Solaar: 1 = lista, 2 = leer, 3 = escribir."""
    titulo("TASA DE REPORTE (0x8061)")
    MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]

    for etiqueta, params in (("por cable", b"\x00"), ("inalámbrico", b"\x01")):
        r = s.mostrar(f"f0  capacidades ({etiqueta})", 0x8061, 0x00, params)
        if r:
            bitmap = int.from_bytes(r[0:2], "big")
            hz = [MAPEO_HZ[n] for n in range(7) if bitmap & (1 << n)]
            print(f"      → {sorted(hz, reverse=True)} Hz")

    r = s.mostrar("f1  getReportRateList", 0x8061, 0x01)
    if r:
        bitmap = int.from_bytes(r[0:2], "big")
        hz = [MAPEO_HZ[n] for n in range(7) if bitmap & (1 << n)]
        print(f"      → lista global: {sorted(hz, reverse=True)} Hz")

    r = s.mostrar("f2  getReportRate  ← la tasa actual", 0x8061, 0x02)
    if r:
        idx = r[0]
        actual = MAPEO_HZ[idx] if idx < len(MAPEO_HZ) else "?"
        print(f"      → índice {idx} = {actual} Hz")


def bloque_escritura_tasa(s: Sonda, objetivo_hz: int | None = None,
                          restaurar: bool = True,
                          en_onboard: bool = False) -> None:
    """Escribe la tasa de reporte con f3 y verifica leyendo con f2.

    Prueba varios formatos y comprueba el resultado DESPUÉS DE CADA UNO: en
    este ratón la escritura contesta "sin error" aunque no haya hecho nada, así
    que no basta con mirar si hubo excepción. La tasa original se restaura al
    final pase lo que pase.
    """
    titulo("PRUEBA DE ESCRITURA DE TASA DE REPORTE (0x8061 f3)")
    MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]

    # 0 = cable, 1 = inalámbrico (comprobado en el PRO X 2 por las dos vías).
    conexion = 0x00 if s.hpp.index == IDX_DIRECT else 0x01
    print(f"  conexión actual: {'receptor' if conexion else 'cable'}")

    # La lista que manda es la de la función 1: es la de la conexión actual y
    # la que decide qué acepta la escritura.
    caps = s.llamar(0x8061, 0x01)
    if not caps:
        print("  No se pudo leer la lista de tasas; se aborta.")
        return
    bitmap = int.from_bytes(caps[0:2], "big")
    permitidos = [n for n in range(7) if bitmap & (1 << n)]
    print(f"  índices permitidos: {permitidos} "
          f"= {[MAPEO_HZ[n] for n in permitidos]} Hz")

    antes = s.llamar(0x8061, 0x02)
    if not antes:
        print("  No se pudo leer la tasa actual; se aborta.")
        return
    idx_original = antes[0]
    print(f"  tasa actual: índice {idx_original} = "
          f"{MAPEO_HZ[idx_original] if idx_original < 7 else '?'} Hz")

    if objetivo_hz is not None and objetivo_hz in MAPEO_HZ:
        idx_destino = MAPEO_HZ.index(objetivo_hz)
    else:
        candidatos = [n for n in permitidos if n != idx_original]
        if not candidatos:
            print("  El ratón sólo admite una tasa; no hay nada que probar.")
            return
        idx_destino = candidatos[-1]

    print(f"\n  Objetivo: índice {idx_destino} = {MAPEO_HZ[idx_destino]} Hz\n")

    # El perfil onboard guarda la tasa como índice en su primer byte, así que
    # puede que 0x8061 sólo escriba ahí cuando manda el perfil. Es reversible:
    # al final se vuelve al modo en el que estaba.
    modo_previo = None
    if en_onboard:
        m = s.llamar(0x8100, 0x02)
        modo_previo = m[0] if m else None
        print("  Pasando a modo onboard para probar si la tasa entra por ahí…")
        s.llamar(0x8100, 0x01, b"\x01")
        ahora = s.llamar(0x8100, 0x02)
        print(f"     modo: 0x{ahora[0]:02X}" if ahora else "     no se pudo leer")

        # Lo que declara el ratón puede depender del modo: si en onboard la
        # lista se encoge, sabremos que el perfil la está limitando.
        print("\n  Lo que declara ahora, en onboard:")
        for et, par in (("f0 cable", b"\x00"), ("f0 inalámbrico", b"\x01")):
            r = s.llamar(0x8061, 0x00, par)
            if r:
                bm = int.from_bytes(r[0:2], "big")
                print(f"     {et:16} {hx(r[:2])}  -> "
                      f"{[MAPEO_HZ[n] for n in range(7) if bm & (1 << n)]}")
        r = s.llamar(0x8061, 0x01)
        if r:
            bm = int.from_bytes(r[0:2], "big")
            print(f"     {'f1 lista':16} {hx(r[:2])}  -> "
                  f"{[MAPEO_HZ[n] for n in range(7) if bm & (1 << n)]}")
        r = s.llamar(0x8061, 0x02)
        if r:
            print(f"     {'f2 actual':16} índice {r[0]}")

        # ¿Acepta al menos un índice que seguro está permitido?
        print("\n  Probando un índice bajo (2 = 500 Hz), que admiten las dos vías:")
        try:
            s.hpp.call(s.tabla[0x8061].index, 0x03, bytes([2]))
            r = s.llamar(0x8061, 0x02)
            print(f"     f3 [02] -> f2 dice índice {r[0] if r else '?'}"
                  + ("  ← ENTRA" if r and r[0] == 2 else "  (no entra)"))
        except (HidppError, NoResponse, OSError) as e:
            print(f"     f3 [02] -> ⚠ {e}")
        print()

    def probar(etiqueta: str, params: bytes) -> bool:
        """Escribe y comprueba leyendo. Devuelve si la tasa cambió de verdad."""
        try:
            r = s.hpp.call(s.tabla[0x8061].index, 0x03, params)
            resp = hx(r)
        except (HidppError, NoResponse, OSError) as e:
            print(f"  → {etiqueta:34} {hx(params):17} ⚠ {e}")
            return False
        leido = s.llamar(0x8061, 0x02)
        idx = leido[0] if leido else None
        # Ojo: "no llegó al objetivo" no es lo mismo que "no hizo nada". Un
        # formato puede escribir un índice distinto del que pretendíamos, y eso
        # es justo lo que revela cuál es el formato bueno.
        if idx == idx_destino:
            marca = "← CAMBIÓ, es el objetivo"
        elif idx != idx_original:
            hz = MAPEO_HZ[idx] if idx is not None and idx < 7 else "?"
            marca = f"← CAMBIÓ a {idx} ({hz} Hz), NO al objetivo"
        else:
            marca = f"(sigue en {idx})"
        print(f"  → {etiqueta:34} {hx(params):17} resp {resp[:11]}…  {marca}")
        return idx == idx_destino

    d = idx_destino
    variantes = [
        ("f3 [idx]  (lo que hace Solaar)", bytes([d])),
        ("f3 [conexión, idx]",             bytes([conexion, d])),
        ("f3 [idx, 0, 0]",                 bytes([d, 0, 0])),
        # Con 4+ parámetros el paquete pasa a ser un informe largo (0x11).
        ("f3 [idx] en informe largo",      bytes([d, 0, 0, 0])),
        ("f3 [conexión, idx] largo",       bytes([conexion, d, 0, 0])),
    ]

    funciono = False
    for etiqueta, params in variantes:
        if probar(etiqueta, params):
            print(f"\n     *** FUNCIONA con {etiqueta}: {MAPEO_HZ[d]} Hz ***")
            funciono = True
            break

    if not funciono:
        print("\n     ✗ ningún formato cambió la tasa.")
        modo = s.llamar(0x8100, 0x02)
        if modo:
            print(f"       modo onboard/host en este momento: 0x{modo[0]:02X} "
                  f"({'onboard' if modo[0] == 0x01 else 'host'})")
        print("       Si está en host y aun así no cambia, lo más probable es "
              "que\n       la tasa la fije el enlace inalámbrico y no se pueda "
              "tocar por\n       receptor. Contrástalo con Solaar (ver más abajo).")

    if en_onboard:
        perfil = s.llamar(0x8100, 0x05, b"\x00\x01\x00\x00")
        if perfil:
            print(f"\n  primer byte del perfil 1 ahora: {perfil[0]} "
                  f"({MAPEO_HZ[perfil[0]] if perfil[0] < 7 else '?'} Hz)")
            print(f"  sector completo: {hx(perfil)}")
        if modo_previo is not None:
            print(f"  Volviendo al modo anterior (0x{modo_previo:02X})…")
            s.llamar(0x8100, 0x01, bytes([modo_previo]))

    if not restaurar:
        print("\n  --sin-restaurar: la tasa se queda escrita.")
        print("  Apaga el ratón, enciéndelo, y vuelve a lanzar esto SIN")
        print("  --escribir. Si entonces f2 dice algo distinto de la tasa de")
        print("  partida, la escritura sí valía y sólo faltaba rehacer el enlace.")
        return

    print(f"\n  Restaurando la tasa original (índice {idx_original} = "
          f"{MAPEO_HZ[idx_original] if idx_original < 7 else '?'} Hz)…")
    try:
        s.hpp.call(s.tabla[0x8061].index, 0x03, bytes([idx_original]))
    except (HidppError, NoResponse, OSError) as e:
        print(f"     ⚠ {e}")
    final = s.llamar(0x8061, 0x02)
    if final and final[0] == idx_original:
        print("     ✓ restaurada")
    else:
        print(f"     ⚠ quedó en el índice {final[0] if final else '?'}")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nodo", help="forzar un /dev/hidrawN concreto")
    ap.add_argument("--escribir", action="store_true",
                    help="además de leer, prueba escrituras (DPI y modo)")
    ap.add_argument("--dpi", type=int, default=3200,
                    help="DPI objetivo para la prueba de escritura")
    ap.add_argument("--hz", type=int,
                    help="Hz objetivo para la prueba de tasa de reporte")
    ap.add_argument("--botones-de-fabrica", action="store_true",
                    help="deja los cinco botones como vienen de fábrica")
    ap.add_argument("--cambiar-boton", metavar="N=ACCION",
                    help="cambia un botón del perfil onboard, p. ej. 3=central. "
                         "Acciones: izquierdo, derecho, central, atras, "
                         "adelante, ciclar-dpi, dpi-mas, dpi-menos, bateria, nada")
    ap.add_argument("--forzar", action="store_true",
                    help="permite cambiar el clic izquierdo o el derecho")
    ap.add_argument("--modo", choices=("onboard", "host"),
                    help="cambia el modo del ratón y sale")
    ap.add_argument("--probar-escritura", action="store_true",
                    help="reescribe un perfil DESHABILITADO con lo mismo que "
                         "tenía, para comprobar el mecanismo sin arriesgar nada")
    ap.add_argument("--sector-perfil", type=int, default=1,
                    help="sector del perfil a modificar (por defecto 1, el activo)")
    ap.add_argument("--sector", type=int, default=2,
                    help="sector sobre el que probar o restaurar (por defecto 2, "
                         "que está deshabilitado)")
    ap.add_argument("--restaurar", metavar="FICHERO",
                    help="devuelve un sector a como estaba desde una copia")
    ap.add_argument("--copia", default="/tmp/gpx2-sector.bin",
                    help="dónde guardar la copia de seguridad del sector")
    ap.add_argument("--leds", action="store_true",
                    help="vuelca lo que el ratón diga de su iluminación")
    ap.add_argument("--informe", nargs="?", const="gpx2-informe.txt",
                    metavar="FICHERO",
                    help="recoge todo lo legible en un fichero para compartir")
    ap.add_argument("--poner-tasa", type=int, metavar="HZ",
                    help="cambia la tasa de reporte de verdad y la mide")
    ap.add_argument("--features-ocultas", action="store_true",
                    help="abre las features internas (0x1E00) y reintenta "
                         "escribir la tasa; lo deja como estaba al salir")
    ap.add_argument("--registro", metavar="0xNN",
                    help="barre los parámetros de un registro concreto")
    ap.add_argument("--registros", action="store_true",
                    help="barre los registros HID++ 1.0 del receptor (sólo lee)")
    ap.add_argument("--todos-los-registros", action="store_true",
                    help="prueba los 256, no sólo los conocidos. Tarda más")
    ap.add_argument("--mapa-botones", nargs="?", const=25.0, type=float,
                    metavar="SEGUNDOS",
                    help="te pide cada botón y anota qué código llega")
    ap.add_argument("--botones-en-vivo", nargs="?", const=20.0, type=float,
                    metavar="SEGUNDOS",
                    help="enseña qué botones recibe el kernel al pulsarlos")
    ap.add_argument("--medir", nargs="?", const=5.0, type=float,
                    metavar="SEGUNDOS",
                    help="mide la tasa de reporte real moviendo el ratón")
    ap.add_argument("--en-onboard", action="store_true",
                    help="prueba la escritura de la tasa con el ratón en modo "
                         "onboard, por si la tasa la manda su perfil interno")
    ap.add_argument("--sin-restaurar", action="store_true",
                    help="deja la tasa escrita, para comprobar si surte efecto "
                         "tras apagar y encender el ratón")
    ap.add_argument("--solo-tasa", action="store_true",
                    help="prueba únicamente la escritura de la tasa de reporte")
    args = ap.parse_args()

    if args.registro:
        bloque_un_registro(args.nodo, int(args.registro, 0))
        return 0

    if args.registros or args.todos_los_registros:
        bloque_registros(args.nodo, args.todos_los_registros)
        return 0

    if args.mapa_botones:
        bloque_mapa(args.mapa_botones)
        return 0

    if args.botones_en_vivo:
        bloque_escuchar(args.botones_en_vivo)
        return 0

    if args.medir:
        bloque_medir(args.medir)
        return 0

    titulo("DISPOSITIVO")
    hallazgo = encontrar(args.nodo)
    if not hallazgo:
        print("  No se encontró ningún ratón HID++. ¿Hace falta sudo?")
        return 1
    node, ch, hpp = hallazgo

    try:
        s = Sonda(hpp)
    except Exception as e:
        print(f"  No se pudo leer la tabla de features: {e}")
        return 1

    print(f"  {node.id_str} · {node.name} · {len(s.tabla)} features")

    if args.leds:
        bloque_leds(s)
        ch.close()
        return 0

    if args.informe:
        bloque_informe(s, args.informe, node)
        ch.close()
        return 0

    if args.poner_tasa:
        bloque_poner_tasa(s, args.poner_tasa, args.medir or 5.0)
        ch.close()
        return 0

    if args.features_ocultas:
        bloque_features_ocultas(s, args.hz or 4000)
        ch.close()
        return 0

    if args.modo:
        bloque_cambiar_modo(s, args.modo)
        ch.close()
        return 0

    if args.botones_de_fabrica:
        bloque_botones_de_fabrica(s, args.sector_perfil, args.copia)
        ch.close()
        return 0

    if args.cambiar_boton:
        try:
            n, _, accion = args.cambiar_boton.partition("=")
            numero = int(n)
        except ValueError:
            print("  Formato: --cambiar-boton 3=central")
            ch.close()
            return 1
        bloque_cambiar_boton(s, args.sector_perfil, numero, accion,
                             args.copia, args.forzar)
        ch.close()
        return 0

    if args.restaurar or args.probar_escritura:
        if args.restaurar:
            bloque_restaurar(s, args.restaurar, args.sector)
        else:
            bloque_prueba_escritura(s, args.sector, args.copia)
        ch.close()
        return 0

    bloque_bateria(s)
    bloque_modo(s, args.escribir)
    estado, validos = {}, []
    if s.tiene(0x2202):
        estado = bloque_dpi(s)
        validos = bloque_rangos(s)
    bloque_tasa(s)
    if s.tiene(0x8100):
        bloque_perfiles_onboard(s)

    if args.escribir and s.tiene(0x2202) and not args.solo_tasa:
        bloque_escritura_dpi(s, estado, validos, args.dpi)

    if args.escribir and s.tiene(0x8061):
        bloque_escritura_tasa(s, args.hz, not args.sin_restaurar,
                              args.en_onboard)

    if args.restaurar and s.tiene(0x8100):
        bloque_restaurar(s, args.restaurar, args.sector)
    elif args.probar_escritura and s.tiene(0x8100):
        bloque_prueba_escritura(s, args.sector, args.copia)

    print("\n")
    ch.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
