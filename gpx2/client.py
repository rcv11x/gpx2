# -*- coding: utf-8 -*-
"""
Cliente D-Bus del demonio, para la interfaz.

Usa QtDBus porque la interfaz ya carga Qt: así no añadimos una dependencia
sólo para hablar con nuestro propio demonio. El demonio, que no tiene Qt, usa
dbus-next; son dos librerías distintas hablando el mismo protocolo, que es
justo la gracia de D-Bus.
"""

from __future__ import annotations

import json

try:
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    DISPONIBLE = True
except ImportError:                                   # pragma: no cover
    DISPONIBLE = False

NOMBRE_BUS = "io.github.rcv11x.gpx2"
RUTA_BUS = "/io/github/rcv11x/gpx2"
IFACE = "io.github.rcv11x.gpx2.Manager"


class ClienteDemonio:
    def __init__(self):
        self.iface = None
        if DISPONIBLE:
            self.iface = QDBusInterface(NOMBRE_BUS, RUTA_BUS, IFACE,
                                        QDBusConnection.sessionBus())

    @property
    def activo(self) -> bool:
        """False también cuando el demonio no está arrancado: no lo activamos
        por sorpresa, es el usuario quien decide si lo quiere en marcha."""
        return bool(self.iface is not None and self.iface.isValid())

    def _llamar(self, metodo: str, *args):
        if not self.activo:
            return None
        respuesta = self.iface.call(metodo, *args)
        argumentos = respuesta.arguments()
        return argumentos[0] if argumentos else None

    # -- consultas ------------------------------------------------------------

    def perfiles(self) -> list[dict]:
        return self._json("ListProfiles", por_defecto=[])

    def perfil_activo(self) -> str:
        return str(self._llamar("ActiveProfile") or "")

    def estado(self) -> dict:
        return self._json("DeviceState", por_defecto={})

    def _json(self, metodo: str, *args, por_defecto):
        crudo = self._llamar(metodo, *args)
        if not crudo:
            return por_defecto
        try:
            return json.loads(crudo)
        except (ValueError, TypeError):
            return por_defecto

    # -- acciones -------------------------------------------------------------

    def aplicar(self, perfil_id: str) -> dict:
        """{'ok': bool, 'cambios': [...]} o {'ok': False, 'error': '…'}"""
        return self._json("ApplyProfile", perfil_id, por_defecto={"ok": False})

    def recargar(self) -> list[str]:
        return self._json("Reload", por_defecto={}).get("errores", [])
