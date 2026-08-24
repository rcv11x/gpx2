# -*- coding: utf-8 -*-
"""
Capa 1 — Transporte.

Encuentra los nodos /dev/hidraw* que exponen el canal HID++ de Logitech y
los abre para leer/escribir bytes. Esta capa NO entiende el contenido de esos
bytes: sólo los mueve.
"""

from __future__ import annotations

import fcntl
import os
import select
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from glob import glob

LOGITECH = 0x046D

# IDs conocidos del G Pro X Superlight 2 (informativo: la detección real se
# hace mirando el descriptor, no una lista de modelos).
SL2_IDS = {0xC09B: "G Pro X Superlight 2 (cable)",
           0xC54D: "Receptor Lightspeed del SL2"}


def parse_descriptor(desc: bytes) -> dict[int, set[int]]:
    """Recorre un HID report descriptor -> {usage_page: {report_ids}}.

    El descriptor es una lista de items TLV. Sólo nos interesan dos etiquetas
    globales: 'Usage Page' (0x04) y 'Report ID' (0x84). Asociamos cada Report ID
    a la Usage Page vigente en ese punto; es una heurística, pero cubre de sobra
    los descriptores de Logitech.
    """
    out: dict[int, set[int]] = {}
    usage_page = 0
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:                      # item largo (poco habitual)
            i += 3 + desc[i + 1]
            continue
        size = prefix & 0x03
        size = 4 if size == 3 else size
        data = int.from_bytes(desc[i + 1:i + 1 + size], "little") if size else 0
        tag = prefix & 0xFC
        if tag == 0x04:
            usage_page = data
        elif tag == 0x84:
            out.setdefault(usage_page, set()).add(data)
        i += 1 + size
    return out


@dataclass
class HidrawNode:
    """Un /dev/hidrawN y lo que sabemos de él sin abrirlo."""
    path: str
    vid: int = 0
    pid: int = 0
    name: str = "?"
    phys: str = ""
    hidpp: bool = False                 # ¿expone el canal HID++?
    usage_page: int = 0
    report_ids: list[int] = field(default_factory=list)

    @property
    def is_logitech(self) -> bool:
        return self.vid == LOGITECH

    @property
    def id_str(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"

    def readable(self) -> bool:
        return os.access(self.path, os.R_OK | os.W_OK)


def enumerate_nodes() -> list[HidrawNode]:
    """Lista todos los /dev/hidraw* leyendo sólo /sys (no abre ningún fichero)."""
    nodes: list[HidrawNode] = []
    def _numero(ruta: str) -> int:
        try:
            return int(ruta.rsplit("hidraw", 1)[1])
        except ValueError:
            return 1 << 30          # los raros, al final; sin reventar

    for sysdir in sorted(glob("/sys/class/hidraw/hidraw*"), key=_numero):
        node = HidrawNode(path=f"/dev/{os.path.basename(sysdir)}")
        try:
            with open(f"{sysdir}/device/uevent") as fh:
                for line in fh:
                    key, _, val = line.strip().partition("=")
                    if key == "HID_NAME":
                        node.name = val
                    elif key == "HID_PHYS":
                        node.phys = val
                    elif key == "HID_ID":
                        parts = val.split(":")
                        node.vid = int(parts[1], 16)
                        node.pid = int(parts[2], 16)
            with open(f"{sysdir}/device/report_descriptor", "rb") as fh:
                pages = parse_descriptor(fh.read())
            # El canal HID++ vive en una usage page de fabricante (>= 0xFF00)
            # con los report id 0x10 (corto) y/o 0x11 (largo).
            for page, rids in pages.items():
                if page >= 0xFF00 and (0x10 in rids or 0x11 in rids):
                    node.hidpp = True
                    node.usage_page = page
                    node.report_ids = sorted(rids)
                    break
        except (OSError, ValueError, IndexError):
            # Un nodo ilegible o con el uevent en un formato inesperado no
            # puede llevarse por delante la lista entera: se anota lo que se
            # haya podido leer y se sigue. Además desaparecen a media lectura
            # cuando alguien desenchufa algo, que es justo cuando escaneamos.
            pass
        nodes.append(node)
    return nodes


def hidpp_candidates() -> list[HidrawNode]:
    """Los nodos que merece la pena interrogar: Logitech + canal HID++."""
    return [n for n in enumerate_nodes() if n.hidpp and n.is_logitech]


class DispositivoOcupado(OSError):
    """Otro proceso (normalmente el demonio) está hablando con el ratón."""


class RawChannel:
    """Un /dev/hidraw. Se abre sólo mientras dura una conversación.

    Por qué no se deja abierto: HID++ es pregunta-respuesta sobre un canal
    compartido. Si dos procesos leen a la vez, cada uno se lleva respuestas del
    otro y el protocolo se corrompe en silencio — es el error más difícil de
    diagnosticar de todo este proyecto.

    La solución es abrir el nodo sólo durante cada petición y cerrarlo al
    terminar, protegido con `flock`. Así la interfaz y el demonio pueden
    coexistir sin coordinarse: el que llega segundo espera unos milisegundos.
    Abrir un hidraw es barato, así que no compensa optimizarlo.
    """

    def __init__(self, path: str, espera: float = 2.0):
        self.path = path
        self.espera = espera
        self.fd: int | None = None
        self._nivel = 0            # permite anidar sesiones sin cerrar de más

    # -- gestión de la sesión -------------------------------------------------

    @contextmanager
    def sesion(self):
        """Abre el nodo (con cerrojo) mientras dure el bloque."""
        self._entrar()
        try:
            yield self
        finally:
            self._salir()

    def _entrar(self) -> None:
        self._nivel += 1
        if self.fd is not None:
            return
        fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        limite = time.monotonic() + self.espera
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= limite:
                    os.close(fd)
                    self._nivel -= 1
                    raise DispositivoOcupado(
                        f"{self.path} está ocupado por otro proceso")
                time.sleep(0.02)
        self.fd = fd

    def _salir(self) -> None:
        self._nivel = max(0, self._nivel - 1)
        if self._nivel == 0 and self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    # -- entrada/salida (sólo válido dentro de una sesión) --------------------

    def write(self, data: bytes) -> None:
        os.write(self._activo(), data)

    def read(self, timeout: float) -> bytes | None:
        fd = self._activo()
        if not select.select([fd], [], [], timeout)[0]:
            return None
        try:
            return os.read(fd, 64)
        except BlockingIOError:
            return None

    def drain(self) -> None:
        fd = self._activo()
        while select.select([fd], [], [], 0)[0]:
            try:
                os.read(fd, 64)
            except OSError:
                return

    def _activo(self) -> int:
        if self.fd is None:
            raise RuntimeError("uso fuera de una sesión: falta 'with canal.sesion()'")
        return self.fd

    def close(self) -> None:
        self._nivel = 0
        self._salir()

    def __enter__(self):
        self._entrar()
        return self

    def __exit__(self, *exc):
        self._salir()
