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
        self.buttons = None

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
        self.buttons = self._primera([feat.ReprogrammableControls])

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

    def leer_todo(self) -> dict:
        """Snapshot del estado, tolerante a fallos (para pintar la GUI)."""
        estado: dict = {"nombre": self.nombre, "errores": list(self.errores)}
        for clave, cap, metodo in (("dpi", self.dpi, "get"),
                                   ("rate", self.rate, "get"),
                                   ("battery", self.battery, "get"),
                                   ("mode", self.mode, "get")):
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
    for node in enumerate_nodes():
        if not (node.hidpp and node.is_logitech):
            if node.vid and not node.hidpp:
                res.otros.append(node)
            continue
        # RawChannel ya no abre nada al construirse: el nodo se abre dentro
        # de cada petición. Los errores de permiso salen en el primer ping.
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
            res.ratones.append(Mouse(node, ch, idx, ver))
            encontrado = True
            # Un receptor puede tener varios emparejados, pero comparten canal:
            # de momento nos quedamos con el primero que responde.
            break
        if not encontrado:
            ch.close()
    return res
