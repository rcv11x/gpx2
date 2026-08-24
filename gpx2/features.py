# -*- coding: utf-8 -*-
"""
Capa 3a — Capacidades (features).

Cada clase envuelve UNA feature HID++ y ofrece una interfaz limpia y agnóstica
(`dpi.get()`, `dpi.set(1600)`), para que las capas de arriba no sepan nunca qué
es un byte.

Sobre el campo CONFIANZA de cada clase:
  "verificada"  -> formato bien documentado por Solaar/libratbag y estable.
  "por validar" -> implementación razonada pero SIN probar contra hardware.
                   La pestaña de Diagnóstico vuelca la respuesta en crudo para
                   poder corregir el decodificador con el ratón delante.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hidpp import Hidpp, HidppError, NoResponse


class Capability:
    """Base de todas las capacidades."""
    FID: int = 0
    TITULO: str = ""
    CONFIANZA: str = "por validar"

    def __init__(self, hpp: Hidpp):
        self.hpp = hpp
        self.idx = hpp.of(self.FID)

    def call(self, function: int, params: bytes = b"") -> bytes:
        return self.hpp.call(self.idx, function, params)


# ---------------------------------------------------------------------------
# Identidad
# ---------------------------------------------------------------------------

class DeviceName(Capability):
    FID, TITULO, CONFIANZA = 0x0005, "Nombre del dispositivo", "verificada"

    def get(self) -> str:
        total = self.call(0x00)[0]
        buf = b""
        while len(buf) < total:
            buf += self.call(0x01, bytes([len(buf)]))
        return buf[:total].decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------------
# Batería
# ---------------------------------------------------------------------------

@dataclass
class BatteryState:
    percent: int | None
    charging: bool
    texto: str


class UnifiedBattery(Capability):
    FID, TITULO, CONFIANZA = 0x1004, "Batería", "verificada"
    _ESTADOS = {0: "descargando", 1: "cargando", 2: "carga lenta",
                3: "carga completa", 4: "error de carga"}

    def get(self) -> BatteryState:
        r = self.call(0x01)
        estado = r[2]
        return BatteryState(percent=r[0], charging=estado in (1, 2),
                            texto=self._ESTADOS.get(estado, "?"))


class LegacyBattery(Capability):
    FID, TITULO, CONFIANZA = 0x1000, "Batería", "verificada"
    _ESTADOS = {0: "descargando", 1: "cargando", 2: "carga completa",
                3: "carga lenta", 4: "error"}

    def get(self) -> BatteryState:
        r = self.call(0x00)
        return BatteryState(percent=r[0], charging=r[2] in (1, 3),
                            texto=self._ESTADOS.get(r[2], "?"))


# ---------------------------------------------------------------------------
# DPI  (sensibilidad del sensor)
# ---------------------------------------------------------------------------

@dataclass
class DpiInfo:
    actual: int
    por_defecto: int
    minimo: int
    maximo: int
    paso: int
    valores: list[int]     # vacío si el sensor usa rango continuo


class AdjustableDpi(Capability):
    """Feature 0x2201: el modelo clásico. Muy bien documentado."""
    FID, TITULO, CONFIANZA = 0x2201, "DPI", "verificada"

    def sensor_count(self) -> int:
        return self.call(0x00)[0]

    def _lista(self, sensor: int = 0) -> tuple[list[int], int]:
        """Decodifica la lista de DPIs.

        Es una secuencia de u16 big-endian terminada en 0. Un valor con los tres
        bits altos a 1 (máscara 0xE000) no es un DPI: codifica el *paso* entre el
        valor anterior y el siguiente. Así el ratón describe tanto listas
        discretas como rangos continuos.
        """
        raw = self.call(0x01, bytes([sensor]))
        valores, paso = [], 0
        for i in range(1, len(raw) - 1, 2):
            v = int.from_bytes(raw[i:i + 2], "big")
            if v == 0:
                break
            if (v & 0xE000) == 0xE000:
                paso = v & 0x1FFF
            else:
                valores.append(v)
        return valores, paso

    def get(self, sensor: int = 0) -> DpiInfo:
        r = self.call(0x02, bytes([sensor]))
        actual = int.from_bytes(r[1:3], "big")
        defecto = int.from_bytes(r[3:5], "big")
        valores, paso = self._lista(sensor)
        if paso and len(valores) >= 2:
            # rango continuo: [mínimo, máximo] con el paso indicado
            return DpiInfo(actual, defecto, min(valores), max(valores), paso, [])
        return DpiInfo(actual, defecto,
                       min(valores) if valores else actual,
                       max(valores) if valores else actual,
                       paso or 50, valores)

    def set(self, dpi: int, sensor: int = 0) -> int:
        r = self.call(0x03, bytes([sensor]) + dpi.to_bytes(2, "big"))
        return int.from_bytes(r[1:3], "big")


class ExtendedDpi(Capability):
    """Feature 0x2202: el modelo nuevo (el que probablemente use el SL2).

    OJO: el decodificador está razonado a partir de la documentación pero SIN
    validar contra hardware. La pestaña Diagnóstico vuelca la respuesta cruda
    para poder ajustarlo.
    """
    FID, TITULO, CONFIANZA = 0x2202, "DPI", "por validar"
    DIR_X = 0

    def sensor_count(self) -> int:
        return self.call(0x00)[0]

    def raw_ranges(self, sensor: int = 0) -> bytes:
        return self.call(0x02, bytes([sensor, self.DIR_X, 0]))

    def raw_current(self, sensor: int = 0) -> bytes:
        return self.call(0x03, bytes([sensor]))

    def get(self, sensor: int = 0) -> DpiInfo:
        r = self.raw_current(sensor)
        actual = int.from_bytes(r[1:3], "big")
        defecto = actual
        # La lista de rangos usa el mismo truco 0xE000 que 0x2201.
        raw = self.raw_ranges(sensor)
        valores, paso = [], 0
        for i in range(3, len(raw) - 1, 2):
            v = int.from_bytes(raw[i:i + 2], "big")
            if v == 0:
                break
            if (v & 0xE000) == 0xE000:
                paso = v & 0x1FFF
            else:
                valores.append(v)
        if paso and len(valores) >= 2:
            return DpiInfo(actual, defecto, min(valores), max(valores), paso, [])
        return DpiInfo(actual, defecto,
                       min(valores) if valores else actual,
                       max(valores) if valores else actual,
                       paso or 50, valores)

    def set(self, dpi: int, sensor: int = 0) -> int:
        self.call(0x04, bytes([sensor, self.DIR_X]) + dpi.to_bytes(2, "big") + b"\x00")
        return self.get(sensor).actual


# ---------------------------------------------------------------------------
# Tasa de reporte  (Hz de sondeo)
# ---------------------------------------------------------------------------

@dataclass
class RateInfo:
    actual_hz: int
    disponibles: list[int]


class ReportRate(Capability):
    """Feature 0x8060: el ratón contesta con un bitmap de periodos en ms."""
    FID, TITULO, CONFIANZA = 0x8060, "Tasa de reporte", "verificada"

    def get(self) -> RateInfo:
        bitmap = self.call(0x00)[0]
        # bit n activo -> soporta un periodo de (n+1) ms  ->  1000/(n+1) Hz
        hz = [1000 // (n + 1) for n in range(8) if bitmap & (1 << n)]
        actual_ms = self.call(0x01)[0] or 1
        return RateInfo(1000 // actual_ms, sorted(hz, reverse=True))

    def set(self, hz: int) -> None:
        self.call(0x02, bytes([max(1, round(1000 / hz))]))


class ExtendedReportRate(Capability):
    """Feature 0x8061: el modelo nuevo, necesario para 2K/4K/8K.

    Igual que 0x2202: implementado a partir de la documentación, pendiente de
    validar con el ratón real. El mapeo de bits a Hz es la parte a confirmar.
    """
    FID, TITULO, CONFIANZA = 0x8061, "Tasa de reporte", "por validar"
    WIRELESS, WIRED = 0, 1
    # Hipótesis de mapeo: bit n -> este Hz. Se corrige en cuanto veamos el
    # bitmap real junto a lo que muestra G HUB.
    MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]

    def raw_capabilities(self, conexion: int = WIRELESS) -> bytes:
        return self.call(0x00, bytes([conexion]))

    def get(self, conexion: int = WIRELESS) -> RateInfo:
        raw = self.raw_capabilities(conexion)
        bitmap = int.from_bytes(raw[0:2], "big")
        hz = [self.MAPEO_HZ[n] for n in range(len(self.MAPEO_HZ))
              if bitmap & (1 << n)]
        idx = self.call(0x01)[0]
        actual = self.MAPEO_HZ[idx] if idx < len(self.MAPEO_HZ) else 0
        return RateInfo(actual, sorted(hz, reverse=True))

    def set(self, hz: int, conexion: int = WIRELESS) -> None:
        idx = self.MAPEO_HZ.index(hz)
        self.call(0x02, bytes([conexion, idx]))


# ---------------------------------------------------------------------------
# Modo onboard / host
# ---------------------------------------------------------------------------

class ModeStatus(Capability):
    """Feature 0x8090. Dice si manda la memoria del ratón o manda el PC."""
    FID, TITULO, CONFIANZA = 0x8090, "Modo de funcionamiento", "por validar"

    def get(self) -> str:
        r = self.call(0x00)
        return "host (manda el PC)" if r[0] & 0x01 else "onboard (manda el ratón)"


# ---------------------------------------------------------------------------
# Registro: qué clase usar para cada feature, en orden de preferencia
# ---------------------------------------------------------------------------

DPI_CLASSES = [ExtendedDpi, AdjustableDpi]        # 0x2202 gana a 0x2201
RATE_CLASSES = [ExtendedReportRate, ReportRate]   # 0x8061 gana a 0x8060
BATTERY_CLASSES = [UnifiedBattery, LegacyBattery]
