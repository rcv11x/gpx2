# -*- coding: utf-8 -*-
"""
Capa 4 — Perfiles.

Un perfil es un fichero TOML que dice qué ajustes quieres y cuándo. Se guarda
en ~/.config/gpx2/profiles/ y está pensado para poder editarse a mano con
cualquier editor: si la interfaz falla, tus perfiles siguen siendo legibles.

De momento los perfiles sólo llevan ajustes de *hardware* (DPI y tasa de
reporte). La aceleración de Plasma es un ajuste por dispositivo, no por juego,
y vive fuera de aquí.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path


def directorio_perfiles(demo: bool = False) -> Path:
    """Dónde viven los perfiles.

    El modo demo usa una carpeta aparte a propósito: el ratón simulado no debe
    ensuciar la configuración real con ajustes que no ha dado ningún
    dispositivo tuyo.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "gpx2" / ("profiles-demo" if demo else "profiles")


def ruta_modo(demo: bool = False) -> Path:
    return directorio_perfiles(demo).parent / "modo"


def leer_modo_preferido(demo: bool = False) -> str | None:
    """Qué modo ha elegido el usuario: "host", "onboard", o nada aún.

    Hace falta porque el demonio no puede distinguir "el ratón se ha reiniciado
    y ha vuelto a onboard" de "el usuario ha pedido onboard a propósito". Sin
    esto, le deshacía la elección cada cinco segundos.

    Un fichero de una línea y no un TOML: es un solo dato y así se puede mirar
    y cambiar con `cat` y `echo`.
    """
    try:
        valor = ruta_modo(demo).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return valor if valor in ("host", "onboard") else None


def guardar_modo_preferido(modo: str, demo: bool = False) -> None:
    ruta = ruta_modo(demo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(modo + "\n", encoding="utf-8")


def ruta_tasas(demo: bool = False) -> Path:
    return directorio_perfiles(demo).parent / "tasas"


def leer_tasa_recordada(id_dispositivo: str, demo: bool = False) -> int | None:
    """La última tasa que le escribimos a este ratón.

    Hace falta porque el ratón NO informa de la suya: su función de lectura
    sigue devolviendo la que tenía al arrancar aunque el enlace haya cambiado.
    Sin recordarlo, cada vez que se abre el programa enseñaría un valor que
    sabemos falso.
    """
    try:
        for linea in ruta_tasas(demo).read_text(encoding="utf-8").splitlines():
            ident, _, hz = linea.partition(" ")
            if ident == id_dispositivo and hz.strip().isdigit():
                return int(hz)
    except OSError:
        pass
    return None


def guardar_tasa_recordada(id_dispositivo: str, hz: int,
                           demo: bool = False) -> None:
    ruta = ruta_tasas(demo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = []
    try:
        lineas = [l for l in ruta.read_text(encoding="utf-8").splitlines()
                  if not l.startswith(f"{id_dispositivo} ")]
    except OSError:
        pass
    lineas.append(f"{id_dispositivo} {hz}")
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


@dataclass
class Ajustes:
    """Lo que un perfil cambia. None = 'no lo toques'."""
    dpi: int | None = None
    report_rate_hz: int | None = None

    def campos(self) -> dict:
        return {k: v for k, v in vars(self).items() if v is not None}


@dataclass
class Activacion:
    """Cuándo se activa el perfil solo."""
    ejecutables: list[str] = field(default_factory=list)
    steam_appids: list[int] = field(default_factory=list)

    def coincide(self, juego) -> bool:
        if juego.steam_appid and juego.steam_appid in self.steam_appids:
            return True
        nombre = (juego.nombre or "").lower()
        ruta = (juego.exe or "").lower()
        for patron in self.ejecutables:
            p = patron.lower()
            if p and (p == nombre or p in ruta):
                return True
        return False


@dataclass
class Perfil:
    nombre: str
    ajustes: Ajustes = field(default_factory=Ajustes)
    activacion: Activacion = field(default_factory=Activacion)
    por_defecto: bool = False
    ruta: Path | None = None

    @property
    def id(self) -> str:
        return _slug(self.nombre)


def _slug(texto: str) -> str:
    limpio = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return limpio or "perfil"


# ---------------------------------------------------------------------------
# Lectura y escritura
# ---------------------------------------------------------------------------

def _valor_toml(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_valor_toml(x) for x in v) + "]"
    raise TypeError(f"no sé escribir {type(v).__name__} en TOML")


def a_toml(p: Perfil) -> str:
    """Genera el TOML a mano. El esquema es tan simple que no compensa una
    dependencia externa sólo para escribirlo."""
    lineas = [
        "# Perfil de gpx2. Puedes editarlo a mano.",
        f"nombre = {_valor_toml(p.nombre)}",
        f"por_defecto = {_valor_toml(p.por_defecto)}",
        "",
        "[ajustes]",
        "# Quita o comenta una línea para que el perfil no toque ese ajuste.",
    ]
    for clave, valor in vars(p.ajustes).items():
        if valor is None:
            lineas.append(f"# {clave} =")
        else:
            lineas.append(f"{clave} = {_valor_toml(valor)}")
    lineas += [
        "",
        "[activacion]",
        "# Se activa si el ejecutable del juego coincide con alguno de estos",
        "# (nombre exacto, o texto contenido en la ruta completa).",
        f"ejecutables = {_valor_toml(p.activacion.ejecutables)}",
        f"steam_appids = {_valor_toml(p.activacion.steam_appids)}",
        "",
    ]
    return "\n".join(lineas)


def desde_toml(datos: dict, ruta: Path | None = None) -> Perfil:
    ajustes_raw = datos.get("ajustes", {}) or {}
    act_raw = datos.get("activacion", {}) or {}
    return Perfil(
        nombre=str(datos.get("nombre") or (ruta.stem if ruta else "sin nombre")),
        por_defecto=bool(datos.get("por_defecto", False)),
        ajustes=Ajustes(
            dpi=ajustes_raw.get("dpi"),
            report_rate_hz=ajustes_raw.get("report_rate_hz"),
        ),
        activacion=Activacion(
            ejecutables=[str(x) for x in act_raw.get("ejecutables", [])],
            steam_appids=[int(x) for x in act_raw.get("steam_appids", [])],
        ),
        ruta=ruta,
    )


class Almacen:
    """La colección de perfiles en disco."""

    def __init__(self, directorio: Path | None = None, demo: bool = False):
        self.dir = Path(directorio) if directorio else directorio_perfiles(demo)
        self.perfiles: dict[str, Perfil] = {}

    def cargar(self) -> list[str]:
        """Lee todos los .toml. Devuelve los errores encontrados, sin lanzar:
        un perfil roto no debe impedir que funcionen los demás."""
        self.perfiles.clear()
        errores: list[str] = []
        if not self.dir.is_dir():
            return errores
        for ruta in sorted(self.dir.glob("*.toml")):
            try:
                with open(ruta, "rb") as fh:
                    perfil = desde_toml(tomllib.load(fh), ruta)
                self.perfiles[perfil.id] = perfil
            except Exception as e:
                errores.append(f"{ruta.name}: {e}")
        return errores

    def guardar(self, perfil: Perfil) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        ruta = perfil.ruta or (self.dir / f"{perfil.id}.toml")
        # Escritura atómica: si algo falla a medias, el fichero viejo sigue bien.
        temporal = ruta.with_suffix(".toml.tmp")
        temporal.write_text(a_toml(perfil), encoding="utf-8")
        os.replace(temporal, ruta)
        perfil.ruta = ruta
        self.perfiles[perfil.id] = perfil
        return ruta

    def borrar(self, perfil_id: str) -> bool:
        perfil = self.perfiles.pop(perfil_id, None)
        if perfil and perfil.ruta and perfil.ruta.exists():
            perfil.ruta.unlink()
            return True
        return False

    # -- consulta -------------------------------------------------------------

    def lista(self) -> list[Perfil]:
        return sorted(self.perfiles.values(),
                      key=lambda p: (not p.por_defecto, p.nombre.lower()))

    def obtener(self, perfil_id: str) -> Perfil | None:
        return self.perfiles.get(perfil_id)

    def por_defecto(self) -> Perfil | None:
        for p in self.lista():
            if p.por_defecto:
                return p
        return None

    def buscar_para(self, juego) -> Perfil | None:
        """El primer perfil cuya regla de activación case con este juego."""
        for p in self.lista():
            if not p.por_defecto and p.activacion.coincide(juego):
                return p
        return None

    def marcar_por_defecto(self, perfil_id: str) -> None:
        """Sólo puede haber uno; los demás se desmarcan y se reescriben."""
        for pid, p in self.perfiles.items():
            deseado = (pid == perfil_id)
            if p.por_defecto != deseado:
                self.guardar(replace(p, por_defecto=deseado))

    def crear_por_defecto_si_falta(self, ajustes: Ajustes) -> Perfil | None:
        """En el primer arranque deja algo con lo que empezar."""
        if self.lista():
            return None
        perfil = Perfil(nombre="Escritorio", ajustes=ajustes, por_defecto=True)
        self.guardar(perfil)
        return perfil
