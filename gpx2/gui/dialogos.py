# -*- coding: utf-8 -*-
"""Diálogos que no caben en la ventana principal."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from ..procesos import (caratula, juegos_instalados,
                        listar_candidatos, nombres_de_steam)
from .widgets import icono

ROL_VALOR = Qt.ItemDataRole.UserRole


def _a_la_derecha(widget: QWidget) -> QHBoxLayout:
    """Un botón suelto ocupando todo el ancho parece un banner, no un botón."""
    fila = QHBoxLayout()
    fila.addStretch(1)
    fila.addWidget(widget)
    return fila


class DialogoJuegos(QDialog):
    """Elegir qué juegos activan un perfil, sin tener que saberse su nombre.

    La idea es que abras el juego, abras esto y lo elijas de la lista. Saberse
    de memoria que el ejecutable se llama `hl2_linux` no es razonable, y
    escribirlo mal significa que el perfil no salta nunca y no hay forma de
    saber por qué.
    """

    def __init__(self, nombre_perfil: str, ejecutables: list[str],
                 appids: list[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Juegos de «{nombre_perfil}»")
        self.resize(620, 620)

        raiz = QVBoxLayout(self)
        raiz.setSpacing(10)

        intro = QLabel("Cuando arranque cualquiera de estos, se aplicará el "
                       "perfil. Al cerrarlo se vuelve al perfil por defecto.")
        intro.setWordWrap(True)
        raiz.addWidget(intro)

        # -- lo que ya está puesto --------------------------------------------
        raiz.addWidget(QLabel("Activan este perfil:"))
        self.lista_activadores = QListWidget()
        self.lista_activadores.setMaximumHeight(150)
        # El AppID a secas no le dice nada a nadie: se enseña el nombre.
        self._nombres_steam = nombres_de_steam()
        for e in ejecutables:
            self._añadir_activador(e, ("exe", e))
        for a in appids:
            self._añadir_activador(self._nombre_steam(a), ("steam", a))
        raiz.addWidget(self.lista_activadores)

        quitar = QPushButton(icono("list-remove", "edit-delete"),
                             "Quitar el seleccionado")
        quitar.clicked.connect(self._quitar)
        raiz.addLayout(_a_la_derecha(quitar))

        # -- lo que está corriendo ahora --------------------------------------
        raiz.addWidget(QLabel("Elige de aquí — los juegos abiertos salen arriba:"))

        fila_busq = QWidget()
        lay_busq = QHBoxLayout(fila_busq)
        lay_busq.setContentsMargins(0, 0, 0, 0)
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar…")
        self.busqueda.textChanged.connect(self._filtrar)
        lay_busq.addWidget(self.busqueda, 1)
        refrescar = QPushButton(icono("view-refresh"), "Actualizar")
        refrescar.clicked.connect(self._cargar)
        lay_busq.addWidget(refrescar)
        raiz.addWidget(fila_busq)

        self.lista_procesos = QListWidget()
        # Steam guarda las carátulas en local: se reconoce el juego de un
        # vistazo, sin leer. Apaisado porque es como vienen los cabeceros.
        self.lista_procesos.setIconSize(QSize(72, 34))
        self._icono_vacio: QIcon | None = None
        self.lista_procesos.itemDoubleClicked.connect(lambda _: self._añadir())
        raiz.addWidget(self.lista_procesos, 1)

        añadir = QPushButton(icono("list-add"), "Añadir el seleccionado")
        añadir.clicked.connect(self._añadir)
        raiz.addLayout(_a_la_derecha(añadir))

        # -- a mano, por si no está abierto ------------------------------------
        fila_man = QWidget()
        lay_man = QHBoxLayout(fila_man)
        lay_man.setContentsMargins(0, 0, 0, 0)
        self.manual = QLineEdit()
        self.manual.setPlaceholderText(
            "…o escríbelo a mano: nombre del ejecutable, o «steam:730»")
        self.manual.returnPressed.connect(self._añadir_manual)
        lay_man.addWidget(self.manual, 1)
        btn_man = QPushButton(icono("list-add"), "Añadir")
        btn_man.clicked.connect(self._añadir_manual)
        lay_man.addWidget(btn_man)
        raiz.addWidget(fila_man)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        raiz.addWidget(botones)

        self._cargar()

    # -- activadores ----------------------------------------------------------

    def _nombre_steam(self, appid: int) -> str:
        nombre = self._nombres_steam.get(appid)
        return f"{nombre}  ·  Steam {appid}" if nombre else f"Steam {appid}"

    def _añadir_activador(self, texto: str, valor) -> bool:
        for i in range(self.lista_activadores.count()):
            if self.lista_activadores.item(i).data(ROL_VALOR) == valor:
                return False            # ya estaba
        item = QListWidgetItem(texto)
        item.setData(ROL_VALOR, valor)
        self.lista_activadores.addItem(item)
        return True

    def _quitar(self) -> None:
        fila = self.lista_activadores.currentRow()
        if fila >= 0:
            self.lista_activadores.takeItem(fila)

    # -- procesos -------------------------------------------------------------

    def _hueco(self, juego: bool) -> QIcon:
        """Qué poner cuando Steam no tiene la carátula descargada.

        Un rectángulo vacío parece que algo ha fallado. Para un juego se usa
        el icono de juegos del propio tema, que se lee como "no hay imagen" y
        no como "error"; para lo que no es un juego, un hueco transparente,
        que si no el texto de unas filas empieza más a la izquierda que el de
        otras y el borde queda irregular.
        """
        if juego:
            icono = QIcon.fromTheme("applications-games")
            if not icono.isNull():
                return icono
        if self._icono_vacio is None:
            pm = QPixmap(self.lista_procesos.iconSize())
            pm.fill(Qt.GlobalColor.transparent)
            self._icono_vacio = QIcon(pm)
        return self._icono_vacio

    def _cargar(self) -> None:
        self.lista_procesos.clear()
        corriendo = listar_candidatos()
        ya = {c.steam_appid for c in corriendo if c.steam_appid}
        # Los instalados pero cerrados van después: sirven para preparar un
        # perfil sin tener que lanzar el juego primero.
        instalados = [c for c in juegos_instalados() if c.steam_appid not in ya]

        # Orden: primero lo que está abierto y parece un juego, después los
        # instalados, y al final el resto de programas. Enterrar los juegos
        # debajo de cuarenta procesos del sistema sería justo lo que queremos
        # evitar.
        abiertos = [c for c in corriendo if c.probable]
        resto = [c for c in corriendo if not c.probable]
        for c in abiertos + instalados + resto:
            # Los que traen una pista fuerte van marcados: Steam los identifica
            # en su entorno, y Proton o Wine dejan huella en la ruta.
            if not c.corriendo:
                marca = ""
                sufijo = "   (instalado)"
            else:
                # Que esté abierto se dice, no se deja deducir por la posición.
                marca = ""
                sufijo = "   (abierto)" if c.probable else ""
            item = QListWidgetItem(marca + c.etiqueta + sufijo)
            imagen = caratula(c.steam_appid) if c.steam_appid else None
            item.setIcon(QIcon(imagen) if imagen
                         else self._hueco(bool(c.steam_appid)))
            item.setToolTip(c.exe or f"Steam {c.steam_appid}")
            item.setData(ROL_VALOR,
                         ("steam", c.steam_appid) if c.steam_appid
                         else ("exe", c.nombre))
            self.lista_procesos.addItem(item)
        if not abiertos and not instalados and not resto:
            self.lista_procesos.addItem("No se ha podido leer /proc")
        self._filtrar(self.busqueda.text())

    def _filtrar(self, texto: str) -> None:
        t = texto.strip().lower()
        for i in range(self.lista_procesos.count()):
            item = self.lista_procesos.item(i)
            visible = not t or t in item.text().lower() or t in item.toolTip().lower()
            item.setHidden(not visible)

    def _añadir(self) -> None:
        item = self.lista_procesos.currentItem()
        if item is None or item.data(ROL_VALOR) is None:
            return
        tipo, valor = item.data(ROL_VALOR)
        self._añadir_activador(self._nombre_steam(valor) if tipo == "steam"
                               else valor, (tipo, valor))

    def _añadir_manual(self) -> None:
        texto = self.manual.text().strip()
        if not texto:
            return
        if texto.lower().startswith("steam:") and texto[6:].strip().isdigit():
            appid = int(texto[6:].strip())
            self._añadir_activador(self._nombre_steam(appid), ("steam", appid))
        else:
            self._añadir_activador(texto, ("exe", texto))
        self.manual.clear()

    # -- resultado ------------------------------------------------------------

    def resultado(self) -> tuple[list[str], list[int]]:
        ejecutables, appids = [], []
        for i in range(self.lista_activadores.count()):
            tipo, valor = self.lista_activadores.item(i).data(ROL_VALOR)
            (appids if tipo == "steam" else ejecutables).append(valor)
        return ejecutables, appids
