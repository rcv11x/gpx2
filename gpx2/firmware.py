# -*- coding: utf-8 -*-
"""
Firmware: leer sí, escribir no.

Este módulo **no actualiza firmware**, y es una decisión deliberada.

Grabar firmware es la única operación de todo el proyecto que puede dejar el
ratón inservible de verdad. Todo lo demás (DPI, Hz, botones, perfiles) es
reversible: si nos equivocamos, se vuelve a escribir el valor bueno. Un flasheo
a medias, no.

El protocolo existe y está a nuestro alcance — features 0x00C2 (DfuControl) y
0x00D0 (Dfu) de HID++, que ponen el dispositivo en modo bootloader y le mandan
la imagen en bloques. Podríamos implementarlo. Pero además de escribir el
protocolo haría falta:

  * conseguir las imágenes de firmware oficiales y verificar su firma,
  * distinguir la actualización del ratón de la del receptor (son dos
    dispositivos con dos firmwares distintos, y actualizar el receptor por
    radio mientras el ratón está conectado es justo el caso delicado),
  * y una ruta de recuperación probada para cuando algo se corta a medias.

Todo eso ya está hecho, auditado y mantenido: se llama **fwupd**, lo trae toda
distribución de Linux, y descarga firmware firmado desde LVFS. Lo sensato es
apoyarse en él y no escribir un flasheador paralelo.

Lo que sí hace este módulo: mirar qué versión tienes y si fwupd conoce tu
dispositivo.
"""

from __future__ import annotations

import json
import shutil
import subprocess


def disponible() -> bool:
    return shutil.which("fwupdmgr") is not None


def _ejecutar(args: list[str], timeout: float = 15.0) -> dict | None:
    try:
        r = subprocess.run(["fwupdmgr", *args, "--json"],
                           capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout) if r.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def dispositivos_logitech() -> list[dict]:
    """Los dispositivos Logitech que fwupd reconoce. Sólo consulta local,
    no descarga nada de internet."""
    datos = _ejecutar(["get-devices"]) or {}
    salida = []
    for d in datos.get("Devices", []):
        vendor = str(d.get("VendorId", "")).upper()
        nombre = str(d.get("Name", ""))
        if "046D" in vendor or "logitech" in nombre.lower():
            salida.append({
                "nombre": nombre,
                "version": d.get("Version", "?"),
                "actualizable": "updatable" in (d.get("Flags") or []),
                "plugin": d.get("Plugin", ""),
            })
    return salida


def resumen() -> dict:
    """Estado en una sola llamada, para pintar la pestaña."""
    if not disponible():
        return {"fwupd": False,
                "mensaje": "fwupd no está instalado. Es la herramienta estándar "
                           "de Linux para actualizar firmware; instálala con el "
                           "gestor de paquetes de tu distribución."}
    dispositivos = dispositivos_logitech()
    if not dispositivos:
        return {"fwupd": True, "dispositivos": [],
                "mensaje": "fwupd está instalado pero no reconoce ningún "
                           "dispositivo Logitech ahora mismo. Puede ser que no "
                           "esté conectado, o que este modelo aún no tenga "
                           "soporte en fwupd/LVFS."}
    return {"fwupd": True, "dispositivos": dispositivos,
            "mensaje": f"fwupd reconoce {len(dispositivos)} dispositivo(s) Logitech."}
