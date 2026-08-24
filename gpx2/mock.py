# -*- coding: utf-8 -*-
"""
Ratón simulado.

Implementa el mismo contrato que `RawChannel`, pero contestando lo que
contestaría un ratón de verdad. Sirve para dos cosas:

  * desarrollar la interfaz sin tener el ratón delante;
  * tener un banco de pruebas donde comprobar el decodificador de cada feature
    contra una respuesta conocida.

Lo que responde no está aquí: sale de `modelos.py`, donde cada ratón es un
`Modelo` copiado de su volcado. Este fichero sólo sabe de protocolo. Así,
añadir un ratón nuevo —de alguien que mande su informe— no toca este código.

Los ratones simulados reproducen también **las mentiras del hardware**. El
PRO X 2 contesta "sin error" a escrituras que ignora, y su función 2 de 0x8061
devuelve siempre el índice con el que arrancó. Un simulador que se portara
mejor que el aparato serviría para confirmar nuestros errores, no para
encontrarlos.
"""

from __future__ import annotations

from contextlib import contextmanager

from .device import Mouse
from .modelos import SL2, Modelo
from .transport import HidrawNode


class CanalSimulado:
    """Habla el mismo protocolo que un /dev/hidraw real, pero de mentira."""

    def __init__(self, modelo: Modelo = SL2):
        self.m = modelo
        self.cola: list[bytes] = []
        self.dpi = modelo.dpi_actual
        self.lod = modelo.lod
        self.hz_idx = modelo.hz_indice
        self.ms = modelo.ms_actual
        self.indices = {fid: i for i, fid in enumerate(modelo.tabla)}
        self.remapeos: dict[int, int] = {}
        self.modo_onboard = 0x01        # arranca en onboard, como el real
        self.ocultas = False            # 0x1E00, cerradas de fábrica
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
        m = self.m
        fid = m.tabla[fidx] if fidx < len(m.tabla) else None

        if fid == 0x0000:                                   # IRoot
            if func == 0x00:                                # getFeature
                pedido = int.from_bytes(params[0:2], "big")
                if pedido not in self.indices:
                    return b"\x00\x00\x00"
                return bytes([self.indices[pedido], m.tipos.get(pedido, 0),
                              m.versiones.get(pedido, 0)])
            if func == 0x01:                                # ping
                return bytes([4, 2, params[2] if len(params) > 2 else 0])

        if fid == 0x0001:                                   # IFeatureSet
            if func == 0x00:
                return bytes([len(m.tabla) - 1])
            if func == 0x01:
                f = m.tabla[params[0]]
                return f.to_bytes(2, "big") + bytes([m.tipos.get(f, 0),
                                                     m.versiones.get(f, 0)])

        if fid == 0x0005:                                   # nombre
            if func == 0x00:
                return bytes([len(m.nombre)])
            if func == 0x01:
                return m.nombre.encode()[params[0]:params[0] + 16].ljust(16, b"\x00")

        if fid == 0x1004 and func == 0x01:                  # batería
            if m.bateria is None:
                raise KeyError((fid, func))
            return bytes(m.bateria)

        if fid == 0x2201:                                   # DPI clásico
            if func == 0x00:                                # getSensorCount
                return b"\x01"
            if func == 0x01:                                # getSensorDpiList
                return m.dpi_lista
            if func == 0x02:                                # getSensorDpi
                return (bytes([0x00]) + self.dpi.to_bytes(2, "big")
                        + m.dpi_defecto.to_bytes(2, "big"))
            if func == 0x03:                                # setSensorDpi
                self.dpi = int.from_bytes(params[1:3], "big")
                return bytes([0x00]) + self.dpi.to_bytes(2, "big")

        if fid == 0x2202:                                   # DPI extendido
            # Números de función según Solaar: 5 = leer, 6 = escribir.
            if func == 0x00:                                # getSensorCount
                return b"\x01"
            if func == 0x01:                                # getSensorCapabilities
                # 0x0f -> tiene eje Y independiente y distancia de despegue
                return bytes([0x00, 0x05, 0x0f, 0x00])
            if func == 0x02:                                # getSensorDpiRanges
                pagina = params[2]
                cuerpo = (m.rangos_paginas[pagina]
                          if pagina < len(m.rangos_paginas) else b"\x00" * 13)
                return bytes([params[0], params[1], pagina]) + cuerpo
            if func == 0x03:                                # getSensorDpiList
                # Los cinco DPI que guarda el perfil onboard.
                payload = bytes([0x00, 0x00])
                for v in m.dpi_niveles:
                    payload += v.to_bytes(2, "big")
                return payload
            if func == 0x04:                                # getSensorLodList
                return bytes([0x00]) + bytes([self.lod] * len(m.dpi_niveles))
            if func == 0x05:                                # getSensorDpi
                return (bytes([0x00])
                        + self.dpi.to_bytes(2, "big")
                        + m.dpi_defecto.to_bytes(2, "big")
                        + self.dpi.to_bytes(2, "big")
                        + m.dpi_defecto.to_bytes(2, "big")
                        + bytes([self.lod]))
            if func == 0x06:                                # setSensorDpi
                # params: [sensor, dpiX(2), dpiY(2), lod(1)]
                self.dpi = int.from_bytes(params[1:3], "big")
                if len(params) > 5:
                    self.lod = params[5]
                return (bytes([0x00]) + self.dpi.to_bytes(2, "big")
                        + self.dpi.to_bytes(2, "big") + bytes([self.lod]))

        if fid == 0x8060:                                   # tasa clásica
            if func == 0x00:                                # getReportRateList
                return bytes([m.ms_bitmap])
            if func == 0x01:                                # getReportRate
                return bytes([self.ms])
            if func == 0x02:                                # setReportRate
                self.ms = params[0]
                return b"\x00"

        if fid == 0x8061:                                   # tasa extendida
            # Volcado real: por cable sólo hasta 1000 Hz, por receptor hasta
            # 8000. La vía va en el parámetro de f0, y al revés de lo que
            # parece: 0 es cable, 1 inalámbrico.
            if func == 0x00:                                # capacidades por vía
                return b"\x00" + bytes([m.hz_cable if params[0] == 0
                                        else m.hz_receptor])
            if func == 0x01:                                # lista global
                return b"\x00" + bytes([m.hz_global])
            if func == 0x02:                                # tasa actual
                # MIENTE, igual que el hardware: devuelve el índice con el que
                # arrancó aunque el enlace ya vaya a otra cosa. Es lo que hizo
                # que diéramos por fallido el cambio durante toda una sesión.
                return bytes([m.hz_indice])
            if func == 0x03:                                # fijar tasa
                # Comportamiento real del PRO X 2: por receptor sólo entra si
                # antes se han desbloqueado las features ocultas (0x1E00).
                # Sin eso contesta "sin error" y no cambia nada.
                if self.ocultas:
                    self.hz_idx = params[0]
                return b"\x00"

        if fid == 0x0003:                                   # info y firmware
            if func == 0x00:
                # entidades, unitId(4), transporte(2), modelId(6), ext
                return bytes([2, 0xA1, 0xB2, 0xC3, 0xD4, 0x00, 0x07]) + b"\x00" * 7
            if func == 0x01:
                if params[0] == 0:                          # firmware principal
                    return bytes([0]) + b"MPM" + bytes([0x25, 0x01]) + (0x0043).to_bytes(2, "big")
                return bytes([1]) + b"BOT" + bytes([0x11, 0x00]) + (0x0009).to_bytes(2, "big")

        if fid == 0x1B04:                                   # botones
            if func == 0x00:
                return bytes([len(m.botones)])
            if func == 0x01:
                cid, tid, flags, pos, grupo, gmask = m.botones[params[0]]
                return (cid.to_bytes(2, "big") + tid.to_bytes(2, "big")
                        + bytes([flags, pos, grupo, gmask, 0]))
            if func == 0x02:
                cid = int.from_bytes(params[0:2], "big")
                return (cid.to_bytes(2, "big") + b"\x00"
                        + self.remapeos.get(cid, 0).to_bytes(2, "big"))
            if func == 0x03:
                cid = int.from_bytes(params[0:2], "big")
                destino = int.from_bytes(params[3:5], "big")
                if destino:
                    self.remapeos[cid] = destino
                else:
                    self.remapeos.pop(cid, None)
                return params[0:5]

        if fid == 0x8071:                                   # efectos RGB
            # Sin decodificar del todo: se sirven los volcados que hay, tal
            # cual, y lo que no se preguntó se responde con "parámetro
            # inválido", que es lo que contesta el ratón de verdad.
            if func == 0x00:
                clave = bytes(params[:3])
                if clave in m.rgb:
                    return m.rgb[clave]
                if not any(clave):
                    return bytes(16)        # con ceros contesta ceros
            raise KeyError((fid, func))

        if fid == 0x8090 and func == 0x00:                  # modo
            return b"\x00\x00"                              # arranca en onboard

        if fid == 0x1E00:                                   # features ocultas
            if func == 0x00:
                return bytes([1 if self.ocultas else 0])
            if func == 0x01:
                self.ocultas = bool(params[0])
                return b"\x00"

        if fid == 0x8100:                                   # perfiles onboard
            if func == 0x00:                                # getOnboardProfilesInfo
                return m.info_onboard
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
                    origen = m.directorio.ljust(255, b"\x00")
                else:
                    origen = self.sectores.get(sector, m.sector_perfil)
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
                self._escribiendo = (0, b"")
                if len(buf) >= 2 and crc16_ccitt(buf[:-2]) == int.from_bytes(buf[-2:], "big"):
                    self.sectores[sector] = bytes(buf)
                    return b"\x00"
                raise KeyError((fid, func))     # error: CRC incorrecto

        raise KeyError((fid, func))


def raton_simulado(modelo: Modelo = SL2) -> Mouse:
    """Un `Mouse` conectado a un canal simulado. Por defecto, el PRO X 2."""
    node = HidrawNode(path="/dev/hidraw-simulado",
                      vid=modelo.vid, pid=modelo.pid, name=modelo.nodo,
                      hidpp=True, usage_page=0xFF00, report_ids=[0x10, 0x11])
    raton = Mouse(node, CanalSimulado(modelo), modelo.indice, (4, 2))

    # Un ratón simulado es siempre modo demo, y se marca aquí y no en quien lo
    # pide: el simulado comparte identificador con el real —mismo vid:pid— y la
    # tasa se recuerda en disco por identificador, así que sin esto las pruebas
    # leían y escribían la tasa del ratón de verdad. Salía un fallo suelto y
    # difícil de reproducir, según lo que hubiera guardado el demonio.
    if raton.rate is not None and hasattr(raton.rate, "demo"):
        raton.rate.demo = True
    return raton
