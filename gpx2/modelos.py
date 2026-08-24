# -*- coding: utf-8 -*-
"""
Ratones que el simulador sabe imitar.

Cada `Modelo` son las respuestas de un ratón real, copiadas de su volcado. El
simulador no tiene lógica propia de modelo: coge de aquí lo que contesta.

La regla es la de siempre en este proyecto: **lo que está aquí sale de un
volcado, no de suponer**. Cuando un dato no se ha medido todavía va marcado
como PROVISIONAL, para que nadie lo confunda con algo verificado. Esa marca es
lo que separa un simulador útil de uno que confirma nuestros propios errores.

Añadir un ratón es añadir un `Modelo`: no hay que tocar el simulador.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Modelo:
    """Las respuestas de un ratón concreto al protocolo."""

    nombre: str
    vid: int
    pid: int
    nodo: str                       # cómo se ve el nodo hidraw
    indice: int                     # índice de dispositivo HID++

    tabla: list[int]                # features declaradas, en orden de índice
    tipos: dict[int, int] = field(default_factory=dict)
    versiones: dict[int, int] = field(default_factory=dict)

    # DPI
    dpi_actual: int = 800
    dpi_defecto: int = 800
    dpi_niveles: list[int] = field(default_factory=list)
    lod: int = 0x02
    rangos_paginas: list[bytes] = field(default_factory=list)   # 0x2202 f2
    dpi_lista: bytes = b""                                      # 0x2201 f1

    # Tasa de reporte
    hz_indice: int = 3              # 0x8061: índice de la tabla de 7 valores
    # Bitmaps de 0x8061 f0. El parámetro de esa función es la vía y va al revés
    # de lo que parece: 0 es por cable, 1 inalámbrico. En el PRO X 2 el cable
    # topa en 1000 Hz (0x0F) y el receptor llega a 8000 (0x7F).
    hz_cable: int = 0x0F            # 0x8061 f0 con parámetro 0
    hz_receptor: int = 0x7F         # 0x8061 f0 con parámetro 1
    hz_global: int = 0x7F           # 0x8061 f1: la lista sin distinguir vía
    ms_bitmap: int = 0x0F           # 0x8060 f0: bitmap de periodos en ms
    ms_actual: int = 1              # 0x8060 f1: periodo actual

    bateria: tuple[int, int, int, int] | None = None

    # Perfiles onboard (0x8100)
    info_onboard: bytes = b""       # respuesta de la función 0
    directorio: bytes = b""         # sector 0
    sector_perfil: bytes = b""      # sector 1

    botones: list[tuple] = field(default_factory=list)   # 0x1B04

    @property
    def formato_perfil(self) -> int:
        return self.info_onboard[1] if len(self.info_onboard) > 1 else 0

    @property
    def num_botones(self) -> int:
        return self.info_onboard[5] if len(self.info_onboard) > 5 else 0


# ---------------------------------------------------------------------------
# G PRO X SUPERLIGHT 2 — volcado del 24-08-2026, por receptor Bolt
# ---------------------------------------------------------------------------

# Páginas de getSensorDpiRanges (0x2202 f2). Cada página aporta 13 bytes al
# MISMO flujo: un valor puede quedar partido entre dos, por eso la página 0
# acaba en 0x03 y la 1 empieza en 0xe8 (juntos, 0x03E8 = 1000).
# El flujo describe: 100 · paso 1 →200 · paso 2 →500 · paso 5 →1000 ·
# paso 10 →2000 · paso 20 →5000 · paso 50 →10000 · paso 100 →20000 ·
# paso 125 →32000 · paso 200 →44000.
_SL2_RANGOS = [
    bytes.fromhex("0064e00100c8e00201f4e00503"),
    bytes.fromhex("e8e00a07d0e0141388e0322710"),
    bytes.fromhex("e0644e20e07d7d00e0c8abe000"),
    bytes(13),
]

_SL2_SECTOR = bytes.fromhex(
    "030300002003200302b004b004024006"
    "4006026009600902800c800c02000000"
    "00ff00ffffffffffffffffff3c002c01"
    "80010001800100028001000480010008"
    "80010010ffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffff"
    "0300000000001f400000000300000000"
    "001f400000000300000000001f403200"
    "000300000000001f403200000384db"
)

SL2 = Modelo(
    nombre="PRO X SUPERLIGHT 2",
    vid=0x046D, pid=0xC54D,
    nodo="Logitech Lightspeed Receiver",
    indice=0x01,
    tabla=[0x0000, 0x0001, 0x0003, 0x0005, 0x0020, 0x1004, 0x1B04,
           0x2202, 0x8061, 0x8090, 0x8100, 0x00C2, 0x1802, 0x1814, 0x8111,
           0x1E00],
    tipos={0x0001: 0x00, 0x0003: 0x00, 0x00C2: 0x20, 0x1802: 0x20,
           0x8111: 0x20},
    versiones={0x0005: 1, 0x1004: 0, 0x1B04: 5, 0x2202: 2, 0x8061: 0,
               0x8100: 1},
    dpi_actual=800, dpi_defecto=800,
    dpi_niveles=[800, 1200, 1600, 2400, 3200],
    lod=0x02,
    rangos_paginas=_SL2_RANGOS,
    hz_indice=3,                    # índice 3 = 1000 Hz (tope por receptor)
    hz_cable=0x0F, hz_receptor=0x7F,
    bateria=(78, 8, 0, 0),          # 78 %, nivel 8 (lleno)
    info_onboard=bytes([0x01, 0x07, 0x01, 0x05, 0x01, 0x05, 0x10, 0x00,
                        0xFF, 0x0A, 0x04, 0x00]),
    directorio=bytes.fromhex("00010100" "00020000" "00030000" "00040000"),
    sector_perfil=_SL2_SECTOR,
    # (cid, task_id, flags, pos, grupo, gmask)
    #   flags 0x01 botón de ratón | 0x10 reprogramable | 0x20 divertible
    # El clic izquierdo y el derecho tienen gmask 0: el firmware no los mueve.
    botones=[(0x0050, 0x0038, 0x11, 0, 1, 0x00),
             (0x0051, 0x0039, 0x11, 0, 2, 0x00),
             (0x0052, 0x003A, 0x31, 0, 3, 0x07),
             (0x0053, 0x003C, 0x31, 0, 3, 0x07),
             (0x0056, 0x003E, 0x31, 0, 3, 0x07),
             (0x00C3, 0x00C3, 0x31, 0, 3, 0x07)],
)


# ---------------------------------------------------------------------------
# G203 LIGHTSYNC — primer informe recibido de la comunidad, 25-08-2026
# ---------------------------------------------------------------------------
#
# Es el contrapunto útil al PRO X 2: con cable, sin batería, con luces, con las
# features CLÁSICAS (0x2201 y 0x8060 en vez de 0x2202 y 0x8061) y con el perfil
# onboard en formato 0x04, cuya disposición no es la del 0x07.
#
# Copiado del volcado: la tabla de features con sus marcas, el sector de perfil
# entero —con su CRC, que nos cuadra— y la información de 0x8100.
#
# PROVISIONAL, a la espera del segundo informe: las respuestas de 0x2201 y
# 0x8060 (aquel informe aún no las pedía) y las de 0x8071 (se preguntaban con
# los parámetros a cero, y contestaba ceros). Los valores de abajo se han
# DEDUCIDO del perfil onboard, que sí es real: sus niveles son 400/800/1600/
# 3200 y su periodo es de 1 ms. Sirven para ejercitar el código; no valen como
# referencia de protocolo hasta que lleguen los bytes de verdad.

def _sector(lineas: dict[int, str], tam: int = 255) -> bytes:
    """Reconstruye un sector desde las líneas de un volcado.

    Se pega el volcado tal como lo imprime `depurar.py`, con su desplazamiento
    delante, y lo no volcado queda a 0xFF. Contar bytes a mano para pegarlos
    seguidos es justo la clase de error que este proyecto no puede permitirse:
    un sector con un byte de menos cambia el CRC y parece un fallo de código.
    """
    s = bytearray(b"\xff" * tam)
    for off, txt in lineas.items():
        b = bytes.fromhex(txt.replace(" ", ""))
        s[off:off + len(b)] = b
    return bytes(s)


# Volcado del sector 1, tal cual salió en el informe.
_G203_SECTOR = _sector({
      0: "01 01 00 90 01 20 03 40 06 80 0c 00 00 ff ff ff",
     16: "ff 00 ff ff ff ff ff ff ff ff ff ff ff ff ff ff",
     32: "80 01 00 01 80 01 00 02 80 01 00 04 80 01 00 08",
     48: "80 01 00 10 90 05 ff ff ff ff ff ff ff ff ff ff",
    208: "04 00 00 00 00 00 00 40 01 00 1f 04 00 00 00 00",
    224: "00 00 40 01 00 1f 00 ff ff ff ff ff ff ff ff ff",
    240: "ff ff ff ff ff ff ff ff ff ff ff ff ff 24 70",
})

G203 = Modelo(
    nombre="G203 LIGHTSYNC",
    vid=0x046D, pid=0xC092,
    nodo="Logitech G203 LIGHTSYNC Gaming Mouse",
    indice=0xFF,                    # por cable: el ratón responde directamente
    tabla=[0x0000, 0x0001, 0x0003, 0x0005, 0x1801, 0x1802, 0x1806, 0x1E00,
           0x1E22, 0x1EB0, 0x2201, 0x18B1, 0x00C2, 0x8060, 0x8071, 0x8100,
           0x8110, 0x18A1, 0x8081],
    # 0x40 oculta · 0x20 interna, tal como salieron marcadas en el informe
    tipos={0x1801: 0x60, 0x1802: 0x60, 0x1806: 0x60, 0x1E00: 0x40,
           0x1E22: 0x60, 0x1EB0: 0x60, 0x18B1: 0x60, 0x18A1: 0x60},
    versiones={0x0003: 2, 0x1806: 5, 0x2201: 1},
    dpi_actual=800, dpi_defecto=800,
    dpi_niveles=[400, 800, 1600, 3200],
    # PROVISIONAL: 0x2201 f1 declara un rango continuo. Los extremos salen de
    # la hoja del producto (200 a 8000, paso 50), no de un volcado.
    dpi_lista=bytes([0x00]) + b"\x00\xc8" + b"\xe0\x32" + b"\x1f\x40" + b"\x00\x00",
    # bits 0,1,3,7 = periodos de 1, 2, 4 y 8 ms = 1000/500/250/125 Hz, que es
    # la escalera de siempre. PROVISIONAL: el bitmap real no está volcado.
    ms_bitmap=0b10001011,
    ms_actual=1,                    # del perfil onboard: 1 ms = 1000 Hz
    bateria=None,                   # va por cable
    # [memoria, formato_perfil, formato_macro, nº perfiles, fuera de caja,
    #  botones, sectores, tamaño(2), desplazamiento, ...]
    # PROVISIONAL en los bytes 0, 2 y 4: el informe sólo imprimió los demás.
    info_onboard=bytes([0x01, 0x04, 0x01, 0x01, 0x01, 0x06, 0x10, 0x00,
                        0xFF, 0x00, 0x00, 0x00]),
    directorio=bytes.fromhex("00010100") + b"\xff" * 12,
    sector_perfil=_G203_SECTOR,
    botones=[],                     # no expone 0x1B04: se configuran por perfil
)


MODELOS = {"sl2": SL2, "g203": G203}
