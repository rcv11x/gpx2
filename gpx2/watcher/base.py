# -*- coding: utf-8 -*-
"""
Qué es un "juego" para nosotros, y cómo se identifica un proceso.

En Wayland no se puede preguntar "¿qué ventana está activa?": el protocolo lo
prohíbe por seguridad, y hace bien. Así que no miramos ventanas, miramos
procesos — que además es más fiable, porque un juego puede tener varias
ventanas o ninguna.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Juego:
    pid: int
    exe: str = ""              # ruta completa del ejecutable
    nombre: str = ""           # sólo el nombre del fichero
    steam_appid: int | None = None
    origen: str = ""           # qué vigilante lo detectó

    def __str__(self) -> str:
        extra = f" (Steam {self.steam_appid})" if self.steam_appid else ""
        return f"{self.nombre or self.pid}{extra}"


def identificar(pid: int, origen: str = "") -> Juego | None:
    """Saca del sistema de ficheros todo lo que se sabe de un proceso."""
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        # Sin permiso o el proceso ya no existe. `comm` suele seguir accesible.
        try:
            exe = Path(f"/proc/{pid}/comm").read_text().strip()
        except OSError:
            return None

    juego = Juego(pid=pid, exe=exe, nombre=os.path.basename(exe), origen=origen)

    # Steam exporta el AppID en el entorno del proceso; es el identificador
    # más fiable que existe, mucho mejor que el nombre del ejecutable.
    try:
        entorno = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        for entrada in entorno:
            if entrada.startswith(b"SteamAppId="):
                valor = entrada.split(b"=", 1)[1].decode(errors="ignore")
                if valor.isdigit():
                    juego.steam_appid = int(valor)
                break
    except OSError:
        pass                    # /proc/PID/environ sólo lo lee su dueño

    return juego


class Vigilante:
    """Interfaz común. Cada implementación avisa cuando un juego entra o sale.

    Los vigilantes no deciden nada: sólo informan. Quién elige el perfil es el
    demonio, para que se pueda cambiar la política sin tocar la detección.
    """

    nombre = "base"

    async def iniciar(self, al_empezar, al_terminar) -> None:
        raise NotImplementedError

    async def parar(self) -> None:
        pass
