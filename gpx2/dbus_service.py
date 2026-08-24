# -*- coding: utf-8 -*-
"""
La cara pública del demonio en D-Bus.

Todo lo que la interfaz puede pedirle al demonio pasa por aquí. Al ser D-Bus
estándar, cualquier cosa vale como cliente: la GUI, un script tuyo en Python,
o directamente `busctl` desde la terminal.

    busctl --user call io.github.rcv11x.gpx2 /io/github/rcv11x/gpx2 \
        io.github.rcv11x.gpx2.Manager ApplyProfile s valorant

Nota de diseño: lo que devuelve estructura (lista de perfiles, estado del
dispositivo) va como **JSON dentro de una cadena**, no como tipos D-Bus
compuestos. Motivo práctico: QtDBus, que es lo que usa la interfaz, entrega los
tipos anidados como un `QDBusArgument` que hay que desmontar a mano, campo por
campo, y cualquier cambio en el esquema obliga a tocar ese desmontaje. Con JSON
las dos partes son una línea, el esquema puede crecer sin romper clientes
viejos, y desde la terminal se lee con `| jq`. Los valores sueltos (un nombre,
un número) sí van con su tipo D-Bus normal.
"""

from __future__ import annotations

import json

from dbus_next.service import ServiceInterface, method, signal

IFACE = "io.github.rcv11x.gpx2.Manager"


class ServicioGpx2(ServiceInterface):
    def __init__(self, demonio):
        super().__init__(IFACE)
        self.d = demonio

    # -- consultas ------------------------------------------------------------

    @method()
    def ListProfiles(self) -> "s":
        """JSON: [{id, nombre, por_defecto, ajustes, ejecutables}, …]"""
        return json.dumps([
            {"id": p.id,
             "nombre": p.nombre,
             "por_defecto": p.por_defecto,
             "ajustes": p.ajustes.campos(),
             "ejecutables": p.activacion.ejecutables,
             "steam_appids": p.activacion.steam_appids}
            for p in self.d.almacen.lista()])

    @method()
    def ActiveProfile(self) -> "s":
        return (self.d.motor.perfil_activo or "") if self.d.motor else ""

    @method()
    def DeviceState(self) -> "s":
        """JSON con el estado del ratón. `conectado: false` si no hay ninguno."""
        if self.d.raton is None or self.d.motor is None:
            return json.dumps({"conectado": False})
        estado = {
            "conectado": True,
            "nombre": self.d.raton.nombre,
            "id": self.d.raton.id_str,
            "conexion": self.d.raton.conexion,
            "perfil_activo": self.d.motor.perfil_activo or "",
        }
        estado.update(self.d.motor.estado().campos())
        try:
            if self.d.raton.battery is not None:
                bateria = self.d.raton.battery.get()
                estado["bateria_pct"] = bateria.percent or 0
                estado["cargando"] = bateria.charging
        except Exception:
            pass
        return json.dumps(estado)

    @method()
    def ActiveGames(self) -> "s":
        return json.dumps([{"pid": pid, "perfil": perfil}
                           for pid, perfil in self.d.jugando.items()])

    # -- acciones -------------------------------------------------------------

    @method()
    def ApplyProfile(self, perfil_id: "s") -> "s":
        """Aplica un perfil. JSON con los cambios (lista vacía si ya estaba)."""
        perfil = self.d.almacen.obtener(perfil_id)
        if perfil is None:
            return json.dumps({"ok": False,
                               "error": f"no existe el perfil '{perfil_id}'"})
        return json.dumps({"ok": True,
                           "cambios": self.d.aplicar(perfil, "petición manual")})

    @method()
    def Reload(self) -> "s":
        """Relee los perfiles del disco. JSON con los errores encontrados."""
        return json.dumps({"errores": self.d.recargar()})

    @method()
    def SetDpi(self, dpi: "i") -> "s":
        return self._ajuste_suelto("dpi", dpi)

    @method()
    def SetReportRate(self, hz: "i") -> "s":
        return self._ajuste_suelto("report_rate_hz", hz)

    def _ajuste_suelto(self, ajuste: str, valor: int) -> str:
        """Cambio puntual sin perfil, para trastear desde la terminal."""
        if self.d.motor is None:
            return "no hay ningún ratón conectado"
        try:
            self.d.motor._escribir(ajuste, valor)
            return ""
        except Exception as e:
            return str(e)

    # -- señales --------------------------------------------------------------

    @signal()
    def ProfileSwitched(self, perfil_id) -> "s":
        return perfil_id

    @signal()
    def GameEvent(self, empezado, descripcion) -> "bs":
        return [empezado, descripcion]

    @signal()
    def DeviceChanged(self, conectado) -> "b":
        return conectado

    # atajos que usa el demonio (los decoradores emiten al llamarlos)
    def emitir_perfil(self, perfil_id: str) -> None:
        self.ProfileSwitched(perfil_id)

    def emitir_juego(self, empezado: bool, descripcion: str) -> None:
        self.GameEvent(empezado, descripcion)

    def emitir_dispositivo(self, conectado: bool) -> None:
        self.DeviceChanged(conectado)
