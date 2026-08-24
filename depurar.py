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
    for inicio in range(0, len(sector) - cuantos * 4):
        if all((sector[inicio + i * 4] >> 4) in COMPORTAMIENTOS
               for i in range(cuantos)):
            # Descartar rachas de ceros, que también encajarían.
            if any(sector[inicio + i * 4] for i in range(cuantos)):
                return inicio
    return None


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
    if info[1] != 0x06:
        print(f"  OJO: el formato 0x{info[1]:02X} es más nuevo que el 0x06 que")
        print("  parsea Solaar, así que la disposición puede no coincidir.")

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
        for desp in range(0, cuanto, 16):
            trozo = leer(sector, desp)
            if trozo is None:
                break
            crudo += trozo
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

    print("\n")
    ch.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
