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

DPI_ACTUAL = 1600
DPI_MIN, DPI_MAX, DPI_PASO = 100, 32000, 50
HZ_INDICE = 4                      # posición en ExtendedReportRate.MAPEO_HZ
BATERIA = (78, 3, 0, 0)            # porcentaje, nivel, estado, alimentación

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
        self.hz_idx = HZ_INDICE
        self.indices = {fid: i for i, fid in enumerate(TABLA)}
        self.remapeos: dict[int, int] = {}

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
            if func == 0x00:
                return b"\x01"                              # un sensor
            if func == 0x02:                                # rangos
                return (bytes([0, 0, 0])
                        + DPI_MIN.to_bytes(2, "big")
                        + (0xE000 | DPI_PASO).to_bytes(2, "big")
                        + DPI_MAX.to_bytes(2, "big")
                        + b"\x00\x00")
            if func == 0x03:                                # DPI actual
                return bytes([0]) + self.dpi.to_bytes(2, "big")
            if func == 0x04:                                # fijar DPI
                self.dpi = int.from_bytes(params[2:4], "big")
                return bytes([0]) + self.dpi.to_bytes(2, "big")

        if fid == 0x8061:                                   # tasa de reporte
            if func == 0x00:
                return b"\x00\x7F"                          # bits 0..6 activos
            if func == 0x01:
                return bytes([self.hz_idx])
            if func == 0x02:
                self.hz_idx = params[1]
                return bytes([self.hz_idx])

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

        if fid == 0x8100 and func == 0x00:                  # perfiles onboard
            return bytes([0x01, 0x06, 0x05, 0x00])          # layout 0x06

        raise KeyError((fid, func))


def raton_simulado() -> Mouse:
    node = HidrawNode(path="/dev/hidraw-simulado", vid=0x046D, pid=0xC54D,
                      name="Logitech Lightspeed Receiver", hidpp=True,
                      usage_page=0xFF00, report_ids=[0x10, 0x11])
    return Mouse(node, CanalSimulado(), 0x01, (4, 2))
