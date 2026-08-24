# -*- coding: utf-8 -*-
"""
Ratón simulado.

Implementa el mismo contrato que `RawChannel` pero respondiendo como lo haría
un G Pro X Superlight 2. Sirve para dos cosas:

  * desarrollar la interfaz sin tener el ratón delante;
  * tener un banco de pruebas donde comprobar el decodificador de cada feature
    contra una respuesta conocida.

Cuando tengamos volcados reales del ratón, se pegan aquí y el simulador pasa a
ser una réplica fiel: a partir de ese momento cualquier fallo de decodificación
se reproduce sin hardware.
"""

from __future__ import annotations

from contextlib import contextmanager

from .device import Mouse
from .transport import HidrawNode

NOMBRE = "PRO X SUPERLIGHT 2"

# Tabla de features que declararía el ratón, en orden de índice.
TABLA = [
    0x0000, 0x0001, 0x0003, 0x0005, 0x0020, 0x1004, 0x1B04,
    0x2202, 0x8061, 0x8090, 0x8100, 0x00C2, 0x1802, 0x1814, 0x8111,
]
TIPOS = {0x0001: 0x00, 0x0003: 0x00, 0x00C2: 0x20, 0x1802: 0x20, 0x8111: 0x20}
VERSIONES = {0x0005: 1, 0x1004: 0, 0x1B04: 5, 0x2202: 2, 0x8061: 0, 0x8100: 1}

DPI_ACTUAL, DPI_DEFECTO, LOD = 800, 800, 0x02

# Páginas de getSensorDpiRanges (0x2202 f2), copiadas literalmente del
# PRO X 2 (volcado 2026-08-24). Cada página aporta 13 bytes al MISMO flujo:
# un valor puede quedar partido entre dos, por eso la página 0 acaba en 0x03
# y la 1 empieza en 0xe8 (juntos, 0x03E8 = 1000).
# El flujo describe: 100 · paso 1 →200 · paso 2 →500 · paso 5 →1000 ·
# paso 10 →2000 · paso 20 →5000 · paso 50 →10000 · paso 100 →20000 ·
# paso 125 →32000 · paso 200 →44000.
RANGOS_PAGINAS = [
    bytes.fromhex("0064 e001 00c8 e002 01f4 e005 03".replace(" ", "")),
    bytes.fromhex("e8 e00a 07d0 e014 1388 e032 2710".replace(" ", "")),
    bytes.fromhex("e064 4e20 e07d 7d00 e0c8 abe0 00".replace(" ", "")),
    bytes(13),
]

# El sector del perfil 1, copia literal del volcado del PRO X 2 (2026-08-24).
# El directorio (sector 0) apunta a cuatro perfiles; sólo el primero está
# habilitado, y los otros tres son copias suyas.
SECTOR_PERFIL = bytes.fromhex(
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
DIRECTORIO = bytes.fromhex("00010100" "00020000" "00030000" "00040000")

# Los cinco DPI del perfil onboard y su distancia de despegue (0x2202 f3 y f4).
DPI_NIVELES = [800, 1200, 1600, 2400, 3200]

HZ_INDICE = 3                      # índice 3 = 1000 Hz (tope por receptor)
BATERIA = (78, 8, 0, 0)            # volcado real: 78%, nivel 8 (lleno)

# Botones que declararía el ratón: (cid, task_id, flags, pos, group, gmask)
#   flags 0x01 botón de ratón | 0x10 reprogramable | 0x20 divertible
# El clic izquierdo y el derecho tienen gmask 0: el firmware no deja moverlos.
BOTONES = [
    (0x0050, 0x0038, 0x11, 0, 1, 0x00),
    (0x0051, 0x0039, 0x11, 0, 2, 0x00),
    (0x0052, 0x003A, 0x31, 0, 3, 0x07),
    (0x0053, 0x003C, 0x31, 0, 3, 0x07),
    (0x0056, 0x003E, 0x31, 0, 3, 0x07),
    (0x00C3, 0x00C3, 0x31, 0, 3, 0x07),
]


class CanalSimulado:
    """Habla el mismo protocolo que un /dev/hidraw real, pero de mentira."""

    def __init__(self):
        self.cola: list[bytes] = []
        self.dpi = DPI_ACTUAL
        self.lod = LOD
        self.hz_idx = HZ_INDICE
        self.indices = {fid: i for i, fid in enumerate(TABLA)}
        self.remapeos: dict[int, int] = {}
        self.modo_onboard = 0x01        # arranca en onboard, como el real
        self.sectores: dict[int, bytes] = {}
        self._escribiendo: tuple[int, bytes] = (0, b"")

    # -- contrato de RawChannel ----------------------------------------------

    @contextmanager
    def sesion(self):
        yield self

    def drain(self) -> None:
        self.cola.clear()

    def close(self) -> None:
        pass

    def read(self, timeout: float):
        return self.cola.pop(0) if self.cola else None

    def write(self, pkt: bytes) -> None:
        idx, fidx, funcswid = pkt[1], pkt[2], pkt[3]
        func, params = funcswid >> 4, pkt[4:]
        try:
            payload = self._responder(fidx, func, params)
        except KeyError:
            self.cola.append(bytes([0x10, idx, 0xFF, fidx, funcswid, 0x09, 0]))
            return
        self.cola.append((bytes([0x11, idx, fidx, funcswid]) + payload).ljust(20, b"\x00"))

    # -- lógica del dispositivo ----------------------------------------------

    def _responder(self, fidx: int, func: int, params: bytes) -> bytes:
        fid = TABLA[fidx] if fidx < len(TABLA) else None

        if fid == 0x0000:                                   # IRoot
            if func == 0x00:                                # getFeature
                pedido = int.from_bytes(params[0:2], "big")
                if pedido not in self.indices:
                    return b"\x00\x00\x00"
                return bytes([self.indices[pedido], TIPOS.get(pedido, 0),
                              VERSIONES.get(pedido, 0)])
            if func == 0x01:                                # ping
                return bytes([4, 2, params[2] if len(params) > 2 else 0])

        if fid == 0x0001:                                   # IFeatureSet
            if func == 0x00:
                return bytes([len(TABLA) - 1])
            if func == 0x01:
                i = params[0]
                f = TABLA[i]
                return f.to_bytes(2, "big") + bytes([TIPOS.get(f, 0),
                                                     VERSIONES.get(f, 0)])

        if fid == 0x0005:                                   # nombre
            if func == 0x00:
                return bytes([len(NOMBRE)])
            if func == 0x01:
                trozo = NOMBRE.encode()[params[0]:params[0] + 16]
                return trozo.ljust(16, b"\x00")

        if fid == 0x1004 and func == 0x01:                  # batería
            return bytes(BATERIA)

        if fid == 0x2202:                                   # DPI extendido
            # Números de función según Solaar: 5 = leer, 6 = escribir.
            if func == 0x00:                                # getSensorCount
                return b"\x01"
            if func == 0x01:                                # getSensorCapabilities
                # 0x0f -> tiene eje Y independiente y distancia de despegue
                return bytes([0x00, 0x05, 0x0f, 0x00])
            if func == 0x02:                                # getSensorDpiRanges
                pagina = params[2]
                cuerpo = (RANGOS_PAGINAS[pagina] if pagina < len(RANGOS_PAGINAS)
                          else b"\x00" * 13)
                return bytes([params[0], params[1], pagina]) + cuerpo
            if func == 0x03:                                # getSensorDpiList
                # Los cinco DPI que guarda el perfil onboard.
                payload = bytes([0x00, 0x00])
                for v in DPI_NIVELES:
                    payload += v.to_bytes(2, "big")
                return payload
            if func == 0x04:                                # getSensorLodList
                # Distancia de despegue de cada uno de los cinco niveles.
                return bytes([0x00]) + bytes([self.lod] * len(DPI_NIVELES))
            if func == 0x05:                                # getSensorDpi
                return (bytes([0x00])
                        + self.dpi.to_bytes(2, "big")
                        + DPI_DEFECTO.to_bytes(2, "big")
                        + self.dpi.to_bytes(2, "big")
                        + DPI_DEFECTO.to_bytes(2, "big")
                        + bytes([self.lod]))
            if func == 0x06:                                # setSensorDpi
                # params: [sensor, dpiX(2), dpiY(2), lod(1)]
                self.dpi = int.from_bytes(params[1:3], "big")
                if len(params) > 5:
                    self.lod = params[5]
                # El ratón devuelve el eco de lo que se le pidió.
                return (bytes([0x00]) + self.dpi.to_bytes(2, "big")
                        + self.dpi.to_bytes(2, "big") + bytes([self.lod]))

        if fid == 0x8061:                                   # tasa de reporte
            # Volcado real: por receptor sólo hasta 1000 Hz (0x0f),
            # por cable hasta 8000 Hz (0x7f).
            if func == 0x00:                                # capacidades por conexión
                return b"\x00\x0F" if params[0] == 0 else b"\x00\x7F"
            if func == 0x01:                                # lista global
                return b"\x00\x7F"
            if func == 0x02:                                # tasa actual
                return bytes([self.hz_idx])
            if func == 0x03:                                # fijar tasa
                # Comportamiento real del PRO X 2 por receptor: contesta "sin
                # error" y NO cambia nada. Solaar tropieza con lo mismo. Se
                # reproduce aquí para que el caso quede cubierto sin hardware.
                return b"\x00"

        if fid == 0x0003:                                   # info y firmware
            if func == 0x00:
                # entidades, unitId(4), transporte(2), modelId(6), ext
                return bytes([2, 0xA1, 0xB2, 0xC3, 0xD4, 0x00, 0x07]) + b"\x00" * 7
            if func == 0x01:
                entidad = params[0]
                if entidad == 0:                            # firmware principal
                    return bytes([0]) + b"MPM" + bytes([0x25, 0x01]) + (0x0043).to_bytes(2, "big")
                return bytes([1]) + b"BOT" + bytes([0x11, 0x00]) + (0x0009).to_bytes(2, "big")

        if fid == 0x1B04:                                   # botones
            if func == 0x00:
                return bytes([len(BOTONES)])
            if func == 0x01:
                cid, tid, flags, pos, grupo, gmask = BOTONES[params[0]]
                return (cid.to_bytes(2, "big") + tid.to_bytes(2, "big")
                        + bytes([flags, pos, grupo, gmask, 0]))
            if func == 0x02:
                cid = int.from_bytes(params[0:2], "big")
                destino = self.remapeos.get(cid, 0)
                return (cid.to_bytes(2, "big") + b"\x00"
                        + destino.to_bytes(2, "big"))
            if func == 0x03:
                cid = int.from_bytes(params[0:2], "big")
                destino = int.from_bytes(params[3:5], "big")
                if destino:
                    self.remapeos[cid] = destino
                else:
                    self.remapeos.pop(cid, None)
                return params[0:5]

        if fid == 0x8090 and func == 0x00:                  # modo
            return b"\x00\x00"                              # arranca en onboard

        if fid == 0x8100:                                   # perfiles onboard
            if func == 0x00:                                # getOnboardProfilesInfo
                return bytes([0x01, 0x07, 0x01, 0x05, 0x01, 0x05, 0x10, 0x00,
                              0xff, 0x0a, 0x04, 0x00])      # volcado del PRO X 2
            if func == 0x01:                                # setOnboardMode
                self.modo_onboard = params[0]
                return b"\x00"
            if func == 0x02:                                # getOnboardMode
                return bytes([self.modo_onboard])
            if func == 0x04:                                # getActiveProfile
                return b"\x00\x00\x00\x00"
            if func == 0x05:                                # leer memoria
                sector = int.from_bytes(params[0:2], "big")
                desp = int.from_bytes(params[2:4], "big")
                if sector == 0:
                    origen = DIRECTORIO.ljust(255, b"\x00")
                else:
                    origen = self.sectores.get(sector, SECTOR_PERFIL)
                return origen[desp:desp + 16].ljust(16, b"\x00")
            if func == 0x06:                                # abrir escritura
                self._escribiendo = (int.from_bytes(params[0:2], "big"), b"")
                return b"\x00"
            if func == 0x07:                                # trozo
                sector, buf = self._escribiendo
                self._escribiendo = (sector, buf + params)
                return b"\x00"
            if func == 0x08:                                # cerrar
                sector, buf = self._escribiendo
                # El ratón comprueba el CRC: un sector mal cerrado se rechaza.
                from .onboard import crc16_ccitt
                if len(buf) >= 2 and crc16_ccitt(buf[:-2]) == int.from_bytes(buf[-2:], "big"):
                    self.sectores[sector] = bytes(buf)
                    self._escribiendo = (0, b"")
                    return b"\x00"
                self._escribiendo = (0, b"")
                raise KeyError((fid, func))     # error: CRC incorrecto

        raise KeyError((fid, func))


def raton_simulado() -> Mouse:
    node = HidrawNode(path="/dev/hidraw-simulado", vid=0x046D, pid=0xC54D,
                      name="Logitech Lightspeed Receiver", hidpp=True,
                      usage_page=0xFF00, report_ids=[0x10, 0x11])
    return Mouse(node, CanalSimulado(), 0x01, (4, 2))
