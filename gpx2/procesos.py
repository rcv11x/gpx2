# -*- coding: utf-8 -*-
"""
Qué hay corriendo ahora mismo, y cuáles de esas cosas parecen un juego.

Existe para que nadie tenga que saberse de memoria que el ejecutable de su
juego se llama `hl2_linux` o `Cyberpunk2077.exe`. Se abre el juego, se abre
esta lista y se elige.

No hay forma infalible de saber si un proceso es un juego, así que no se
inventa una: se separan los que traen una **pista fuerte** —Steam los marca en
su entorno, y Proton, Wine o Lutris dejan su huella en la ruta— del resto, que
se enseña igual por si acaso.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from pathlib import Path

from .watcher.base import identificar

# Huellas en la ruta del ejecutable que delatan un juego.
PISTAS = ("steamapps", "/proton", "/.wine", "wineprefix", "lutris",
          "heroic", "bottles", "/games/", "/juegos/", "/gog/", "/itch")

# Lo que Steam y compañía lanzan alrededor del juego: aparecen con las mismas
# huellas en la ruta pero no son el juego.
ANDAMIAJE = {
    "steam", "steamwebhelper", "steamerrorreporter", "reaper", "srt-logger",
    "pressure-vessel-wrap", "pv-bwrap", "proton", "python3", "sh", "bash",
    "wine", "wineserver", "wine64", "winedevice.exe", "services.exe",
    "explorer.exe", "rpcss.exe", "plugplay.exe", "svchost.exe", "tabtip.exe",
    "start.exe", "conhost.exe", "winemenubuilder.exe", "gamescope",
    "gamemoded", "gamemoderun", "mangohud", "lutris-wrapper",
}

# Cosas del sistema y del escritorio que nunca son un juego. No pretende ser
# exhaustiva: sólo quita el ruido más común de la lista de "otros".
DEL_SISTEMA = {
    "systemd", "dbus-daemon", "dbus-broker", "pipewire", "wireplumber",
    "pulseaudio", "kwin_wayland", "plasmashell", "kded6", "kglobalacceld",
    "xdg-desktop-portal", "xdg-document-portal", "xdg-permission-store",
    "polkitd", "udisksd", "upowerd", "NetworkManager", "wpa_supplicant",
    "gpg-agent", "ssh-agent", "at-spi-bus-launcher", "at-spi2-registryd",
    "gvfsd", "tracker-miner-fs-3", "packagekitd", "fwupd", "colord",
    "gpx2", "gpx2d", "python3.14",
}

# Trozos de nombre que delatan un proceso auxiliar. No son juegos y sólo
# ensucian la lista.
RUIDO = ("crashpad", "-booster", "-service", "-launch", "-agent", "-daemon",
         "-helper", "_helper", "-notifier", "runner")


def _bibliotecas_steam() -> list[Path]:
    """Dónde tiene Steam sus juegos. Pueden ser varios discos.

    `libraryfolders.vdf` es el índice; se lee con una expresión regular en vez
    de un parser de VDF porque sólo interesa una clave y no compensa la
    dependencia.
    """
    raices = [Path.home() / ".steam/steam", Path.home() / ".local/share/Steam"]
    carpetas: list[Path] = []
    for raiz in raices:
        apps = raiz / "steamapps"
        if apps.is_dir() and apps not in carpetas:
            carpetas.append(apps)
        indice = apps / "libraryfolders.vdf"
        try:
            texto = indice.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ruta in re.findall(r'"path"\s+"([^"]+)"', texto):
            otra = Path(ruta) / "steamapps"
            if otra.is_dir() and otra not in carpetas:
                carpetas.append(otra)
    return carpetas


def nombres_de_steam() -> dict[int, str]:
    """{appid: nombre} leído de los manifiestos que Steam deja instalados.

    Enseñar «SILENT HILL 2» en vez de «srt-bwrap» es la diferencia entre una
    lista que se entiende y una que no.
    """
    nombres: dict[int, str] = {}
    for carpeta in _bibliotecas_steam():
        try:
            manifiestos = list(carpeta.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifiesto in manifiestos:
            try:
                texto = manifiesto.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', texto)
            nombre = re.search(r'"name"\s+"([^"]*)"', texto)
            if appid and nombre:
                nombres[int(appid.group(1))] = nombre.group(1)
    return nombres


# Lo que Steam instala como dependencia y no es un juego.
NO_SON_JUEGOS = ("proton", "steam linux runtime", "steamworks common",
                 "steamworks shared", "steam runtime")


@dataclass
class Candidato:
    pid: int
    nombre: str
    exe: str
    steam_appid: int | None = None
    probable: bool = False       # ¿tiene una pista fuerte de ser un juego?
    corriendo: bool = True       # False = instalado pero sin abrir

    @property
    def etiqueta(self) -> str:
        if self.steam_appid:
            return f"{self.nombre}  ·  Steam {self.steam_appid}"
        return self.nombre


def _mio(pid: int) -> bool:
    """¿Es un proceso del usuario? Los de otros no los puede lanzar él."""
    try:
        return os.stat(f"/proc/{pid}").st_uid == os.getuid()
    except OSError:
        return False


def listar_candidatos() -> list[Candidato]:
    """Los procesos del usuario, con los que parecen juegos marcados.

    Ordenados con los probables delante: es lo que la gente busca, y hacerles
    recorrer doscientas líneas de demonios del sistema sería justo lo que
    queremos evitar.
    """
    de_steam = nombres_de_steam()
    por_appid: dict[int, Candidato] = {}
    sueltos: dict[str, Candidato] = {}

    for entrada in os.listdir("/proc"):
        if not entrada.isdigit():
            continue
        pid = int(entrada)
        if not _mio(pid):
            continue
        juego = identificar(pid)
        # Sin ruta de ejecutable son hilos del núcleo o procesos que ya no están.
        if juego is None or not juego.exe.startswith("/"):
            continue

        nombre = juego.nombre
        if nombre in DEL_SISTEMA or any(r in nombre.lower() for r in RUIDO):
            continue

        ruta = juego.exe.lower()
        pista = juego.steam_appid is not None or any(p in ruta for p in PISTAS)
        envoltorio = nombre.lower() in ANDAMIAJE

        if juego.steam_appid is not None:
            # Steam lanza media docena de envoltorios con el mismo AppID:
            # pv-adverb, srt-bwrap, wine-preloader… Es un solo juego, y lo que
            # de verdad identifica el perfil es el AppID, no el ejecutable.
            appid = juego.steam_appid
            visible = de_steam.get(appid) or (None if envoltorio else nombre)
            previo = por_appid.get(appid)
            if previo is None:
                por_appid[appid] = Candidato(
                    pid=pid, nombre=visible or f"Juego de Steam {appid}",
                    exe=juego.exe, steam_appid=appid, probable=True)
            elif visible and previo.nombre.startswith("Juego de Steam"):
                previo.nombre = visible
                previo.exe = juego.exe
            continue

        if envoltorio:
            continue
        if nombre not in sueltos:
            sueltos[nombre] = Candidato(pid=pid, nombre=nombre, exe=juego.exe,
                                        probable=pista)

    salida = list(por_appid.values()) + list(sueltos.values())
    salida.sort(key=lambda c: (not c.probable, c.nombre.lower()))
    return salida


def juegos_instalados() -> list[Candidato]:
    """Los juegos de Steam que hay instalados, estén abiertos o no.

    Así se puede preparar un perfil sin tener que lanzar el juego primero, que
    es lo cómodo cuando estás configurando varios de una sentada.
    """
    salida = []
    for appid, nombre in nombres_de_steam().items():
        if any(p in nombre.lower() for p in NO_SON_JUEGOS):
            continue
        salida.append(Candidato(pid=0, nombre=nombre, exe="",
                                steam_appid=appid, probable=True,
                                corriendo=False))
    salida.sort(key=lambda c: c.nombre.lower())
    return salida


# Steam guarda las carátulas en local, así que se pueden enseñar sin pedir
# nada a internet. Por orden de preferencia para una lista: el cabecero es
# apaisado y se reconoce de un vistazo.
IMAGENES = ("library_header.jpg", "header.jpg", "logo.png",
            "library_600x900.jpg")


def _cachés_steam() -> list[Path]:
    return [raiz / "appcache/librarycache"
            for raiz in (Path.home() / ".steam/steam",
                         Path.home() / ".local/share/Steam")]


def caratula(appid: int) -> str | None:
    """Ruta a la imagen del juego, si Steam la tiene descargada.

    Steam la guarda de dos formas según la versión: una carpeta por AppID, o
    ficheros sueltos con el AppID delante. Se prueban las dos.
    """
    for cache in _cachés_steam():
        carpeta = cache / str(appid)
        for nombre in IMAGENES:
            ruta = carpeta / nombre
            if ruta.is_file():
                return str(ruta)
            suelta = cache / f"{appid}_{nombre}"
            if suelta.is_file():
                return str(suelta)
    return None
