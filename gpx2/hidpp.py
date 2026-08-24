# -*- coding: utf-8 -*-
"""
Capa 2 — Protocolo HID++ 2.0.

Traduce "llama a la función N de la feature 0xXXXX con estos parámetros" a
bytes, y espera *su* respuesta. Los tres problemas que resuelve esta capa:

  1. sw_id  — cada petición va firmada con un nibble para reconocer nuestra
              respuesta entre el tráfico ajeno.
  2. notificaciones — el ratón envía avisos espontáneos (batería, botón) en
              cualquier momento, mezclados con las respuestas. Hay que filtrarlos.
  3. errores — existen dos formatos incompatibles, el de HID++ 1.0 y el de 2.0.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .transport import RawChannel

SHORT, LONG, VERY_LONG = 0x10, 0x11, 0x12
LEN = {SHORT: 7, LONG: 20, VERY_LONG: 64}

# Índices de dispositivo: a quién le hablamos por el mismo cable.
IDX_DIRECT = 0xFF          # el propio ratón (USB, o expuesto por el kernel)
IDX_RECEIVER = range(1, 7)  # ratones emparejados detrás de un receptor

ERRORS = {
    0x00: "sin error", 0x01: "parámetro inválido", 0x02: "fuera de rango",
    0x03: "batería crítica", 0x04: "función inválida", 0x05: "feature inválida",
    0x06: "sin permiso", 0x07: "índice de feature inválido",
    0x08: "solicitud inválida", 0x09: "no soportado",
}

# Catálogo de features. Sirve para poner nombre a lo que el ratón reporte;
# NO se usa para decidir qué sabe hacer (eso lo dice el propio dispositivo).
FEATURE_NAMES = {
    0x0000: "IRoot", 0x0001: "IFeatureSet", 0x0002: "IFeatureInfo",
    0x0003: "Información del dispositivo", 0x0005: "Nombre y tipo",
    0x0007: "Nombre personalizado", 0x0008: "Keep-alive",
    0x0020: "Cambio de configuración", 0x0021: "Identificador único",
    0x00C2: "Actualización de firmware",
    0x1000: "Batería (nivel)", 0x1001: "Batería (voltaje)",
    0x1004: "Batería unificada", 0x1300: "Control de LEDs",
    0x1802: "Reinicio", 0x1814: "Cambio de host", 0x1815: "Info de hosts",
    0x1B04: "Botones reprogramables", 0x2100: "Scroll vertical",
    0x2110: "SmartShift", 0x2201: "DPI ajustable",
    0x2202: "DPI ajustable (extendido)", 0x2205: "Escalado del puntero",
    0x2250: "Telemetría de uso", 0x8060: "Tasa de reporte",
    0x8061: "Tasa de reporte (extendida)", 0x8070: "Efectos LED",
    0x8071: "Efectos RGB", 0x8090: "Modo onboard/host",
    0x8100: "Perfiles onboard", 0x8110: "Espía de botones",
    0x8111: "Monitor de latencia", 0x8123: "Botón de fuerza",
}


class HidppError(Exception):
    def __init__(self, code: int, legacy: bool = False):
        self.code = code
        self.legacy = legacy
        familia = "HID++ 1.0" if legacy else "HID++ 2.0"
        super().__init__(f"{familia}: error 0x{code:02X} ({ERRORS.get(code, 'desconocido')})")


class NoResponse(Exception):
    pass


@dataclass(frozen=True)
class FeatureInfo:
    index: int          # índice local en ESTE dispositivo
    fid: int            # identificador universal, p.ej. 0x2202
    type_flags: int
    version: int

    @property
    def name(self) -> str:
        return FEATURE_NAMES.get(self.fid, "(sin catalogar)")

    @property
    def obsolete(self) -> bool:
        return bool(self.type_flags & 0x80)

    @property
    def hidden(self) -> bool:
        return bool(self.type_flags & 0x40)

    @property
    def internal(self) -> bool:
        return bool(self.type_flags & 0x20)


class Hidpp:
    """Conversación HID++ 2.0 con un dispositivo concreto de un canal."""

    SW_ID = 0x0A        # 1..15; nuestra firma

    def __init__(self, channel: RawChannel, index: int = IDX_DIRECT):
        self.ch = channel
        self.index = index
        self._features: dict[int, FeatureInfo] | None = None

    # -- núcleo ---------------------------------------------------------------

    def call(self, feature_index: int, function: int, params: bytes = b"",
             timeout: float = 1.0) -> bytes:
        """Envía una petición y devuelve los bytes de datos de su respuesta.

        Paquete: [report_id][idx_dispositivo][idx_feature][función<<4 | sw_id][params…]
        """
        params = bytes(params)
        report_id = SHORT if len(params) <= 3 else LONG
        head = bytes([report_id, self.index, feature_index,
                      (function << 4) | self.SW_ID])
        with self.ch.sesion():
            return self._intercambio(head, params, report_id, feature_index, timeout)

    def _intercambio(self, head: bytes, params: bytes, report_id: int,
                     feature_index: int, timeout: float) -> bytes:
        self.ch.drain()
        self.ch.write((head + params).ljust(LEN[report_id], b"\x00"))

        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise NoResponse(
                    f"feature idx {feature_index}, función {function}: sin respuesta")
            data = self.ch.read(left)
            if data is None or len(data) < 6 or data[1] != self.index:
                continue
            if data[2] == 0xFF and data[3] == feature_index and data[4] == head[3]:
                raise HidppError(data[5])                   # error HID++ 2.0
            if data[2] == 0x8F:
                raise HidppError(data[5], legacy=True)      # error HID++ 1.0
            if data[2] == feature_index and data[3] == head[3]:
                return data[4:]
            # cualquier otra cosa es una notificación espontánea: se ignora

    # -- IRoot / IFeatureSet --------------------------------------------------

    def ping(self, timeout: float = 0.5) -> tuple[int, int] | None:
        """IRoot.getProtocolVersion -> (mayor, menor), o None si no es HID++ 2.0."""
        r = self.call(0x00, 0x01, b"\x00\x00\x5A", timeout=timeout)
        return (r[0], r[1]) if r[2] == 0x5A else None

    def feature_index(self, fid: int) -> int:
        """IRoot.getFeature -> índice local (0 significa 'no la tengo')."""
        return self.call(0x00, 0x00, fid.to_bytes(2, "big"))[0]

    def features(self, refresh: bool = False) -> dict[int, FeatureInfo]:
        """Tabla completa {fid: FeatureInfo}, cacheada."""
        if self._features is not None and not refresh:
            return self._features
        table = {0x0000: FeatureInfo(0, 0x0000, 0, 0)}
        fs = self.feature_index(0x0001)
        if fs:
            count = self.call(fs, 0x00)[0]
            for i in range(1, count + 1):
                r = self.call(fs, 0x01, bytes([i]))
                fid = int.from_bytes(r[0:2], "big")
                table[fid] = FeatureInfo(i, fid, r[2], r[3])
        self._features = table
        return table

    def has(self, fid: int) -> bool:
        return fid in self.features()

    def of(self, fid: int) -> int:
        """Índice local de una feature; lanza KeyError si no está."""
        return self.features()[fid].index


def probe_channel(node_path: str, timeout: float = 0.4) -> list[tuple[int, tuple[int, int]]]:
    """Prueba todos los índices de un nodo. Devuelve [(índice, versión), …].

    Con receptor Lightspeed pueden convivir varios dispositivos en el mismo
    nodo; por USB directo sólo responde 0xFF.
    """
    encontrados = []
    with RawChannel(node_path) as ch:
        for idx in [IDX_DIRECT, *IDX_RECEIVER]:
            try:
                ver = Hidpp(ch, idx).ping(timeout=timeout)
            except (NoResponse, HidppError, OSError):
                continue
            if ver:
                encontrados.append((idx, ver))
    return encontrados
