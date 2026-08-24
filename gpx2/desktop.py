# -*- coding: utf-8 -*-
"""
Capa 3c — Ajustes del escritorio (KDE Plasma / KWin).

Esto NO es HID++. Es la sensibilidad "de software": la aceleración del puntero
que aplica el compositor, la misma que se toca en Ajustes del sistema > Ratón.
Sirve para dos cosas:

  * dar algo útil con ratones que NO hablan HID++ (cualquier ratón genérico);
  * complementar el DPI del hardware: DPI = cuánto mide el sensor,
    aceleración = qué hace el escritorio con esa medida.

KWin expone cada puntero en D-Bus con propiedades escribibles que se aplican
al instante, sin tocar ficheros de configuración ni reiniciar nada.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    DISPONIBLE = True
except ImportError:                                   # pragma: no cover
    DISPONIBLE = False

SERVICIO = "org.kde.KWin"
RUTA_MANAGER = "/org/kde/KWin/InputDevice"
IFACE_MANAGER = "org.kde.KWin.InputDeviceManager"
IFACE_DEVICE = "org.kde.KWin.InputDevice"


@dataclass
class PointerInfo:
    sysname: str
    nombre: str
    vid: int
    pid: int
    aceleracion: float
    perfil_plano: bool
    scroll_natural: bool
    zurdo: bool
    emulacion_central: bool
    soporta_aceleracion: bool
    es_de_teclado: bool = False

    @property
    def id_str(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"


class KdePointer:
    """Un puntero visto por KWin. Leer y escribir se aplica en caliente."""

    def __init__(self, sysname: str, es_de_teclado: bool = False):
        self.sysname = sysname
        self.es_de_teclado = es_de_teclado
        self.iface = QDBusInterface(SERVICIO, f"{RUTA_MANAGER}/{sysname}",
                                    IFACE_DEVICE, QDBusConnection.sessionBus())

    @property
    def valido(self) -> bool:
        return self.iface.isValid()

    def _get(self, prop: str, por_defecto=None):
        v = self.iface.property(prop)
        return por_defecto if v is None else v

    def _set(self, prop: str, valor) -> bool:
        return bool(self.iface.setProperty(prop, valor))

    def info(self) -> PointerInfo:
        return PointerInfo(
            sysname=self.sysname,
            nombre=self._get("name", self.sysname),
            vid=int(self._get("vendor", 0) or 0),
            pid=int(self._get("product", 0) or 0),
            aceleracion=float(self._get("pointerAcceleration", 0.0) or 0.0),
            perfil_plano=bool(self._get("pointerAccelerationProfileFlat", False)),
            scroll_natural=bool(self._get("naturalScroll", False)),
            zurdo=bool(self._get("leftHanded", False)),
            emulacion_central=bool(self._get("middleEmulation", False)),
            soporta_aceleracion=bool(self._get("supportsPointerAcceleration", False)),
            es_de_teclado=self.es_de_teclado,
        )

    # -- escritura (efecto inmediato) ----------------------------------------

    def set_aceleracion(self, valor: float) -> bool:
        """valor entre -1.0 (muy lento) y 1.0 (muy rápido). 0 = por defecto."""
        return self._set("pointerAcceleration", max(-1.0, min(1.0, float(valor))))

    def set_perfil_plano(self, plano: bool) -> bool:
        """Plano = sin aceleración: la distancia depende sólo del movimiento
        físico. Es lo que suele querer un jugador. Adaptativo = el escritorio
        acelera si mueves rápido."""
        clave = "pointerAccelerationProfileFlat" if plano else "pointerAccelerationProfileAdaptive"
        return self._set(clave, True)

    def set_scroll_natural(self, v: bool) -> bool:
        return self._set("naturalScroll", v)

    def set_zurdo(self, v: bool) -> bool:
        return self._set("leftHanded", v)

    def set_emulacion_central(self, v: bool) -> bool:
        return self._set("middleEmulation", v)


def _lista(manager, metodo: str) -> list[str]:
    respuesta = manager.call(metodo)
    args = respuesta.arguments()
    return list(args[0]) if args else []


def _ids(sysname: str) -> tuple[int, int]:
    iface = QDBusInterface(SERVICIO, f"{RUTA_MANAGER}/{sysname}", IFACE_DEVICE,
                           QDBusConnection.sessionBus())
    return (int(iface.property("vendor") or 0), int(iface.property("product") or 0))


def listar_punteros() -> list[KdePointer]:
    """Todos los punteros que ve KWin. Lista vacía si no estamos en KDE.

    Marca los que en realidad pertenecen a un teclado. Muchos teclados
    mecánicos (los de firmware QMK, por ejemplo) declaran además un endpoint
    de ratón para la función de mover el cursor con el teclado. El sistema lo
    ve como un ratón de pleno derecho — porque lo es — pero al usuario le
    confunde verlo en una lista de ratones.
    """
    if not DISPONIBLE:
        return []
    manager = QDBusInterface(SERVICIO, RUTA_MANAGER, IFACE_MANAGER,
                             QDBusConnection.sessionBus())
    if not manager.isValid():
        return []

    # Un mismo aparato físico se reparte en varios nodos. Si ALGUNO de los
    # nodos de ese VID:PID es un teclado, el aparato es un teclado.
    ids_teclado = {_ids(n) for n in _lista(manager, "ListKeyboards")}

    punteros = []
    for nombre in _lista(manager, "ListPointers"):
        p = KdePointer(nombre, es_de_teclado=_ids(nombre) in ids_teclado)
        if p.valido:
            punteros.append(p)
    return punteros


def buscar_puntero(vid: int, pid: int) -> KdePointer | None:
    """Empareja un ratón HID++ con su puntero en KWin por VID:PID."""
    for p in listar_punteros():
        info = p.info()
        if info.vid == vid and info.pid == pid:
            return p
    return None
