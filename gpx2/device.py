# -*- coding: utf-8 -*-
"""
Capa 3b — Modelo de dispositivo.

Un `Mouse` se construye preguntándole al ratón qué sabe hacer, no consultando
una lista de modelos. Si mañana enchufas otro Logitech, funcionará solo: si
tiene la feature, aparece el panel; si no, no aparece.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import features as feat
from .hidpp import Hidpp, HidppError, NoResponse, IDX_DIRECT, IDX_RECEIVER
from .transport import (DispositivoOcupado, HidrawNode, RawChannel,
                        enumerate_nodes)


class Mouse:
    """Un dispositivo HID++ vivo, con el canal abierto."""

    def __init__(self, node: HidrawNode, channel: RawChannel, index: int,
                 protocolo: tuple[int, int]):
        self.node = node
        self.ch = channel
        self.index = index
        self.protocolo = protocolo
        self.hpp = Hidpp(channel, index)
        self.nombre = node.name
        self.errores: list[str] = []

        # capacidades (None = el dispositivo no la tiene)
        self.dpi = None
        self.rate = None
        self.battery = None
        self.mode = None
        self.onboard = None
        self.buttons = None
        self.info = None

        self._construir()

    # -- construcción ---------------------------------------------------------

    def _primera(self, clases):
        """Instancia la primera clase cuya feature exista en este ratón."""
        for cls in clases:
            if self.hpp.has(cls.FID):
                try:
                    return cls(self.hpp)
                except (HidppError, NoResponse, OSError) as e:
                    self.errores.append(f"{cls.TITULO} (0x{cls.FID:04X}): {e}")
        return None

    def _construir(self) -> None:
        try:
            self.hpp.features()
        except (HidppError, NoResponse, OSError) as e:
            self.errores.append(f"no se pudo leer la tabla de features: {e}")
            return

        if self.hpp.has(feat.DeviceName.FID):
            try:
                self.nombre = feat.DeviceName(self.hpp).get() or self.nombre
            except Exception as e:
                self.errores.append(f"nombre: {e}")

        self.dpi = self._primera(feat.DPI_CLASSES)
        self.rate = self._primera(feat.RATE_CLASSES)
        self.battery = self._primera(feat.BATTERY_CLASSES)
        self.mode = self._primera([feat.ModeStatus])
        self.onboard = self._primera([feat.OnboardProfiles])
        self.buttons = self._primera([feat.ReprogrammableControls])
        self.info = self._primera([feat.DeviceInfo])

    # -- consulta -------------------------------------------------------------

    @property
    def feature_table(self):
        return sorted(self.hpp.features().values(), key=lambda f: f.index)

    @property
    def conexion(self) -> str:
        return "cable USB" if self.index == IDX_DIRECT else f"inalámbrica (índice {self.index})"

    @property
    def id_str(self) -> str:
        return self.node.id_str

    def asegurar_host(self) -> bool | None:
        """Pone el ratón en modo host si aún no lo está.

        True si manda el PC, False si no se pudo, None si el ratón no tiene la
        feature. Hay que llamarlo **antes de cada escritura**, no una vez al
        arrancar: el modo host no persiste — el ratón vuelve a onboard al
        apagarse o al reconectar el receptor — y en ese estado rechaza los
        cambios con un error interno (0x05), que no dice nada de la causa.
        """
        if self.onboard is None:
            return None
        try:
            return True if self.onboard.es_host() else self.onboard.set_host(True)
        except Exception:
            return False

    def leer_todo(self) -> dict:
        """Snapshot del estado, tolerante a fallos (para pintar la GUI)."""
        estado: dict = {"nombre": self.nombre, "errores": list(self.errores)}
        for clave, cap, metodo in (("dpi", self.dpi, "get"),
                                   ("rate", self.rate, "get"),
                                   ("battery", self.battery, "get"),
                                   ("mode", self.mode, "get"),
                                   ("onboard", self.onboard, "get")):
            if cap is None:
                estado[clave] = None
                continue
            try:
                estado[clave] = getattr(cap, metodo)()
            except Exception as e:
                estado[clave] = None
                estado.setdefault("fallos", {})[clave] = str(e)
        return estado

    def close(self) -> None:
        self.ch.close()


# ---------------------------------------------------------------------------
# Descubrimiento
# ---------------------------------------------------------------------------

@dataclass
class Discovery:
    ratones: list[Mouse] = field(default_factory=list)
    sin_permiso: list[HidrawNode] = field(default_factory=list)   # falta regla udev
    ocupados: list[HidrawNode] = field(default_factory=list)      # otro proceso lo tiene
    otros: list[HidrawNode] = field(default_factory=list)         # HID sin HID++

    @property
    def hay_algo(self) -> bool:
        return bool(self.ratones)


def discover(timeout: float = 0.4) -> Discovery:
    """Recorre el sistema y devuelve los ratones HID++ con los que se puede hablar."""
    res = Discovery()
    # (nombre, device_index) de los ratones ya añadidos, para deduplicar cuando
    # el mismo dispositivo físico aparece en varios nodos hidraw (p.ej. receptor Bolt).
    vistos: set[tuple[str, int]] = set()

    for node in enumerate_nodes():
        if not (node.hidpp and node.is_logitech):
            if node.vid and not node.hidpp:
                res.otros.append(node)
            continue
        ch = RawChannel(node.path)
        encontrado = False
        for idx in [IDX_DIRECT, *IDX_RECEIVER]:
            try:
                ver = Hidpp(ch, idx).ping(timeout=timeout)
            except PermissionError:
                res.sin_permiso.append(node)
                break
            except DispositivoOcupado:
                res.ocupados.append(node)
                break
            except (NoResponse, HidppError, OSError):
                continue
            if not ver:
                continue
            raton = Mouse(node, ch, idx, ver)
            clave = (raton.nombre, idx)
            if clave in vistos:
                raton.close()
            else:
                vistos.add(clave)
                res.ratones.append(raton)
            encontrado = True
            break
        if not encontrado:
            ch.close()
    return res
