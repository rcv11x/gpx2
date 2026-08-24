# -*- coding: utf-8 -*-
"""Ventana principal de gpx2."""

from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt, QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QSplitter, QStackedWidget,
                               QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import desktop, firmware
from ..client import ClienteDemonio
from ..device import Discovery, Mouse, discover
from ..hidpp import IDX_DIRECT
from ..engine import Motor
from ..profiles import Almacen, Perfil
from .widgets import (ColumnaCentrada, DelegadoDispositivo,
                      DiagramaRaton, FilaSlider, FilaSliderLista,
                      icono,
                      ROL_ENCABEZADO, ROL_SUB, Tarjeta, hoja_de_estilo,
                      pastilla)

ROL_DATOS = Qt.ItemDataRole.UserRole


@contextmanager
def _ocupado(widget: QWidget, texto: str):
    """Cursor de espera y mensaje mientras algo tarda.

    Escanear el bus o escribir en la memoria del ratón bloquea la interfaz
    medio segundo largo. Sin señal alguna parece que se ha colgado, y la gente
    vuelve a pulsar.
    """
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    _avisar(widget, texto, 0)
    QApplication.processEvents()
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def _suelto(*widgets: QWidget) -> QWidget:
    """Botones a su ancho natural, no estirados de lado a lado.

    Un botón que ocupa toda la tarjeta parece un banner y no invita a
    pulsarlo; además su tamaño deja de decir nada de su importancia.
    """
    caja = QWidget()
    fila = QHBoxLayout(caja)
    fila.setContentsMargins(0, 0, 0, 0)
    fila.setSpacing(8)
    for w in widgets:
        fila.addWidget(w)
    fila.addStretch(1)
    return caja


def _avisar(widget: QWidget, texto: str, ms: int = 5000) -> None:
    """Mensaje en la barra de estado, si la hay.

    Las páginas también se usan sueltas (snapshot.py las renderiza fuera de la
    ventana principal), y ahí no existe barra de estado: un aviso no puede ser
    motivo de que reviente nada.
    """
    ventana = widget.window()
    barra = getattr(ventana, "statusBar", None)
    if callable(barra):
        barra().showMessage(texto, ms)


def _envolver(widget: QWidget) -> QScrollArea:
    """Mete un panel en un área con scroll, para ventanas pequeñas."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(widget)
    return area


# Una línea de texto de 2000 píxeles no se lee: el ojo pierde el renglón al
# volver. En una pantalla ancha las tarjetas se quedan a este ancho y el resto
# es margen.
ANCHO_MAXIMO = 1100


def _columna(*widgets, espaciado: int = 14, margen: int = 18) -> QWidget:
    contenido = QWidget()
    lay = QVBoxLayout(contenido)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(espaciado)
    for w in widgets:
        lay.addWidget(w)
    lay.addStretch(1)
    contenido.setMaximumWidth(ANCHO_MAXIMO)

    caja = QWidget()
    fuera = QHBoxLayout(caja)
    fuera.setContentsMargins(margen, margen, margen, margen)
    fuera.addWidget(contenido, 1)
    fuera.addStretch(0)
    return caja


# ---------------------------------------------------------------------------
# Página: nada que configurar
# ---------------------------------------------------------------------------

class PaginaVacia(QWidget):
    def __init__(self, al_reescanear, parent=None):
        super().__init__(parent)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 24, 24, 24)
        raiz.addStretch(1)

        columna = ColumnaCentrada(540)

        icono = QLabel("\U0001F5B1")
        f = QFont(icono.font())
        f.setPointSize(44)
        icono.setFont(f)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulo = QLabel("No se ha detectado ningún ratón compatible")
        titulo.setObjectName("Titulo")
        titulo.setWordWrap(True)
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.detalle = QLabel()
        self.detalle.setObjectName("Suave")
        self.detalle.setWordWrap(True)
        self.detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detalle.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        boton = QPushButton("Buscar de nuevo")
        boton.clicked.connect(al_reescanear)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(boton)
        fila.addStretch(1)

        columna.contenido.addWidget(icono)
        columna.contenido.addWidget(titulo)
        columna.contenido.addSpacing(4)
        columna.contenido.addWidget(self.detalle)
        columna.contenido.addSpacing(10)
        columna.contenido.addLayout(fila)

        raiz.addWidget(columna)
        raiz.addStretch(1)

    def poner_detalle(self, texto: str) -> None:
        self.detalle.setText(texto)


# ---------------------------------------------------------------------------
# Página: ratón HID++
# ---------------------------------------------------------------------------

class PaginaRaton(QWidget):
    def __init__(self, raton: Mouse, demo: bool = False, parent=None):
        super().__init__(parent)
        self.raton = raton
        self.demo = demo
        self.estado = raton.leer_todo()
        self.puntero_kde = desktop.buscar_puntero(raton.node.vid, raton.node.pid)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._cabecera())

        pestañas = QTabWidget()
        pestañas.addTab(_envolver(self._tab_sensibilidad()),
                        icono("input-mouse", "preferences-desktop-mouse"),
                        "Ajustes")
        pestañas.addTab(_envolver(self._tab_botones()),
                        icono("configure", "preferences-desktop-keyboard"),
                        "Botones")
        if self.raton.onboard is not None:
            pestañas.addTab(_envolver(self._tab_memoria()),
                            icono("media-flash", "drive-harddisk"),
                            "Memoria del ratón")
        pestañas.addTab(_envolver(self._tab_perfiles()),
                        icono("bookmarks", "user-identity"), "Perfiles")
        pestañas.addTab(_envolver(self._tab_firmware()),
                        icono("system-upgrade", "application-x-firmware"),
                        "Firmware")
        pestañas.addTab(_envolver(self._tab_diagnostico()),
                        icono("tools-report-bug", "utilities-terminal"),
                        "Diagnóstico")
        lay.addWidget(pestañas, 1)

    # -- cabecera -------------------------------------------------------------

    def _cabecera(self) -> QWidget:
        caja = QWidget()
        lay = QHBoxLayout(caja)
        lay.setContentsMargins(18, 16, 18, 10)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel(self.estado["nombre"])
        titulo.setObjectName("Titulo")
        # El identificador USB, el índice y el nodo son datos de depuración:
        # no ayudan a nadie a usar el programa y hacían la cabecera ilegible.
        # Siguen a mano en el tooltip y en la pestaña de Diagnóstico.
        from ..hidpp import IDX_DIRECT
        via = ("Conectado por cable" if self.raton.index == IDX_DIRECT
               else "Conectado sin cable")
        sub = QLabel(via)
        sub.setObjectName("Suave")
        sub.setToolTip(
            f"{self.raton.id_str} · {self.raton.conexion} · "
            f"HID++ {self.raton.protocolo[0]}.{self.raton.protocolo[1]} · "
            f"{self.raton.node.path}")
        textos.addWidget(titulo)
        textos.addWidget(sub)
        lay.addLayout(textos)
        lay.addStretch(1)

        # Con el cambio automático por juego, saber qué perfil manda es lo
        # primero que uno quiere ver, y estaba escondido en otra pestaña.
        # Va en pastilla porque es un estado que cambia solo; la batería no,
        # que es un dato y punto: en pastilla parecía un botón sin función.
        self.lbl_perfil = QLabel("Perfil:")
        self.lbl_perfil.setObjectName("Suave")
        self.lbl_perfil.setVisible(False)
        lay.addWidget(self.lbl_perfil, 0, Qt.AlignmentFlag.AlignVCenter)

        self.pastilla_perfil = pastilla("")
        self.pastilla_perfil.setObjectName("PastillaPerfil")
        self.pastilla_perfil.setVisible(False)
        # Sin alinear, el layout le da toda la altura de la cabecera y la
        # pastilla queda como un bloque en vez de ceñirse al texto.
        lay.addWidget(self.pastilla_perfil, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(14)

        bat = self.estado.get("battery")
        self.pastilla_bateria = QLabel()
        self.pastilla_bateria.setObjectName("Bateria")
        self.pastilla_bateria.setVisible(bool(bat and bat.percent is not None))
        if bat and bat.percent is not None:
            self.pastilla_bateria.setText(self._texto_bateria(bat))
        lay.addWidget(self.pastilla_bateria, 0, Qt.AlignmentFlag.AlignVCenter)
        self._refrescar_perfil_activo()
        return caja

    def _perfil_activo(self):
        """El perfil que manda ahora: lo dice el demonio, o el que hay marcado
        por defecto si no está en marcha."""
        try:
            almacen = Almacen(demo=self.demo)
            almacen.cargar()
        except Exception:
            return None
        try:
            cliente = ClienteDemonio()
            if cliente.activo:
                pid = cliente.estado().get("perfil_activo", "")
                # El demonio puede nombrar un perfil que este almacén no tiene
                # (le pasa al modo demo, que usa otra carpeta). Entonces vale
                # más el predeterminado que no enseñar nada.
                if pid and almacen.obtener(pid) is not None:
                    return almacen.obtener(pid)
        except Exception:
            pass
        return almacen.por_defecto()

    def _refrescar_perfil_activo(self) -> None:
        pastilla_ = getattr(self, "pastilla_perfil", None)
        if pastilla_ is None:
            return
        perfil = self._perfil_activo()
        etiqueta = getattr(self, "lbl_perfil", None)
        if perfil is None:
            pastilla_.setVisible(False)
            if etiqueta is not None:
                etiqueta.setVisible(False)
            return
        if etiqueta is not None:
            etiqueta.setVisible(True)
        pastilla_.setText(f"⬢ {perfil.nombre}")
        pastilla_.setToolTip(
            "Perfil que manda ahora mismo. Se cambia en la pestaña Perfiles.")
        pastilla_.setVisible(True)

    @staticmethod
    def _texto_bateria(bat) -> str:
        return f"{'⚡' if bat.charging else '🔋'} {bat.percent}% · {bat.texto}"

    def refrescar_bateria(self) -> bool:
        """Relee la batería y repinta la pastilla. Devuelve si el ratón contestó.

        Es la única lectura que se repite sola: el resto de ajustes no cambian
        si no los cambia alguien, pero la carga sí. Que devuelva False es la
        señal de que el ratón ha dejado de responder.
        """
        if self.raton.battery is None:
            return True
        try:
            bat = self.raton.battery.get()
        except Exception:
            return False
        self.estado["battery"] = bat
        if self.pastilla_bateria is not None:
            self.pastilla_bateria.setText(self._texto_bateria(bat))
        return True

    # -- pestañas -------------------------------------------------------------

    def _tab_sensibilidad(self) -> QWidget:
        tarjetas = []

        dpi = self.estado.get("dpi")
        if dpi:
            tarjetas.append(self._tarjeta_dpi(dpi))
        else:
            tarjetas.append(Tarjeta(
                "DPI del sensor",
                "Este ratón no permite ajustar el DPI desde el sistema."))

        # La tasa de reporte es lo mismo que el DPI: cómo se comporta el ratón
        # ahora. Tenerlas en pestañas distintas obligaba a saltar entre dos
        # pantallas para lo mismo.
        tarjetas.append(self._tarjeta_tasa())
        if self.raton.onboard is None:
            tarjetas.append(Tarjeta(
                "Modo de funcionamiento",
                self.estado.get("mode")
                or "Este ratón no informa de en qué modo está."))
        tarjetas.append(self._tarjeta_kde())
        return _columna(*tarjetas)

    def _tarjeta_dpi(self, dpi) -> Tarjeta:
        cap = self.raton.dpi
        t = Tarjeta("Sensibilidad del sensor",
                    "Cuántos puntos por pulgada mide el sensor. A más DPI, más "
                    "recorre el puntero con el mismo movimiento de la mano.")

        try:
            validos = cap.valores_validos()
        except Exception:
            validos = []
        try:
            niveles = cap.niveles()
        except Exception:
            niveles = []

        # Atajos: los DPI que el propio ratón guarda en su perfil interno. Son
        # los que recorre su botón de cambio de DPI, así que el usuario ya los
        # conoce; poner los nuestros sería inventar.
        self._botones_dpi = []
        if niveles:
            fila = QWidget()
            lay = QHBoxLayout(fila)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            for v in niveles:
                b = QPushButton(str(v))
                b.setObjectName("Nivel")
                b.setCheckable(True)
                b.setToolTip(f"{v} DPI — nivel guardado en el ratón")
                b.clicked.connect(lambda _=False, val=v: self._elegir_dpi(val))
                lay.addWidget(b)
                self._botones_dpi.append((v, b))
            lay.addStretch(1)
            etiqueta = QLabel("Niveles guardados en el ratón")
            etiqueta.setObjectName("Suave")
            t.añadir(etiqueta)
            t.añadir(fila)

        if validos:
            # Un paso del deslizador = un DPI que el sensor admite de verdad.
            self._slider_dpi = FilaSliderLista("Resolución", validos,
                                               sufijo=" DPI")
            self._slider_dpi.poner(dpi.actual)
            self._slider_dpi.cambiado.connect(self._set_dpi)
            t.añadir(self._slider_dpi)
        else:
            self._slider_dpi = FilaSlider("Resolución", dpi.minimo, dpi.maximo,
                                          dpi.paso, sufijo=" DPI")
            self._slider_dpi.poner(dpi.actual)
            self._slider_dpi.cambiado.connect(lambda v: self._set_dpi(int(v)))
            t.añadir(self._slider_dpi)

        pie = QLabel(f"De {dpi.minimo} a {dpi.maximo} DPI · "
                     f"{len(validos) or '?'} valores admitidos · "
                     f"de fábrica {dpi.por_defecto} DPI")
        pie.setObjectName("Suave")
        t.añadir(pie)

        # Lo que se toca aquí cambia el ratón al momento, pero NO el perfil.
        # Sin decirlo, uno mueve el deslizador, luego se aplica un perfil y no
        # entiende por qué se ha perdido su ajuste.
        self.lbl_desfase = QLabel()
        self.lbl_desfase.setObjectName("Suave")
        self.lbl_desfase.setWordWrap(True)
        t.añadir(self.lbl_desfase)
        self.btn_guardar_perfil = QPushButton()
        self.btn_guardar_perfil.setIcon(icono("document-save"))
        self.btn_guardar_perfil.clicked.connect(self._guardar_en_perfil)
        t.añadir(_suelto(self.btn_guardar_perfil))
        self._refrescar_desfase()
        self._marcar_nivel(dpi.actual)
        return t

    def refrescar_ajustes(self) -> None:
        """Vuelve a leer del ratón lo que se está mostrando.

        Los valores cambian sin que nadie toque estos controles: al aplicar un
        perfil desde otra pestaña, cuando el demonio cambia de perfil al
        arrancar un juego, o cuando el ratón se reconecta y vuelve a los suyos.
        """
        slider = getattr(self, "_slider_dpi", None)
        # No pelear con el usuario mientras arrastra.
        if slider is not None and slider.slider.isSliderDown():
            return

        if self.raton.dpi is not None:
            try:
                dpi = self.raton.dpi.get()
            except Exception:
                dpi = None
            if dpi is not None:
                self.estado["dpi"] = dpi
                if slider is not None:
                    slider.poner(dpi.actual)
                self._marcar_nivel(dpi.actual)

        self._resincronizar_rate()
        self._refrescar_perfil_activo()
        self._refrescar_desfase()

        if self.raton.onboard is not None and hasattr(self, "lbl_modo"):
            try:
                self.lbl_modo.setText(self.raton.onboard.get())
            except Exception:
                pass

    def _marcar_nivel(self, valor: int) -> None:
        """Deja marcado el atajo que coincide con el DPI puesto, si hay alguno."""
        for v, b in getattr(self, "_botones_dpi", []):
            b.setChecked(v == valor)

    def _elegir_dpi(self, valor: int) -> None:
        """Un atajo: mueve el deslizador y aplica."""
        if hasattr(self, "_slider_dpi"):
            self._slider_dpi.poner(valor)
        self._set_dpi(valor)

    def _tarjeta_kde(self) -> Tarjeta:
        t = Tarjeta("Velocidad del puntero en el escritorio",
                    "Este ajuste no es del ratón: es de Plasma, y se aplica "
                    "encima de lo que mida el sensor. Cambiarlo aquí es lo "
                    "mismo que hacerlo en los ajustes del sistema.\n\n"
                    "Para jugar conviene el perfil plano: sin aceleración, "
                    "recorres siempre la misma distancia con el mismo "
                    "movimiento de la mano, muevas rápido o despacio.")
        if self.puntero_kde is None:
            t.añadir(QLabel("KWin no expone este dispositivo como puntero."))
            return t
        info = self.puntero_kde.info()
        fila = FilaSlider("Velocidad", -1.0, 1.0, 0.05, decimales=2)
        fila.poner(info.aceleracion)
        fila.cambiado.connect(self.puntero_kde.set_aceleracion)
        t.añadir(fila)

        chk = QCheckBox("Perfil plano (sin aceleración)")
        chk.setChecked(info.perfil_plano)
        chk.toggled.connect(self.puntero_kde.set_perfil_plano)
        t.añadir(chk)
        return t

    def _tarjeta_tasa(self) -> Tarjeta:
        rate = self.estado.get("rate")
        if rate:
            cap = self.raton.rate
            t = Tarjeta("Tasa de reporte",
                        "Veces por segundo que el ratón informa de dónde está. "
                        "Más alta significa menos retraso, y algo menos de batería.")
            combo = QComboBox()
            for hz in rate.disponibles:
                combo.addItem(f"{hz} Hz", hz)
            if rate.actual_hz in rate.disponibles:
                combo.setCurrentIndex(rate.disponibles.index(rate.actual_hz))
            # Cada vía admite tasas distintas: por cable este ratón llega a
            # 1000 Hz y por Lightspeed a 8000. Decirlo evita que parezca que
            # el programa esconde opciones.
            otra = rate.otra_conexion
            if otra and max(otra) != max(rate.disponibles):
                via = "por cable" if self.raton.index != IDX_DIRECT else "sin cable"
                t.añadir(QLabel(
                    f"Por esta conexión tu ratón llega a {max(rate.disponibles)} Hz. "
                    f"{via.capitalize()} admitiría hasta {max(otra)} Hz."))
            # El ratón no informa de la tasa que tiene puesta: su función de
            # lectura sigue devolviendo la anterior. Se enseña lo último que
            # hemos escrito, y se dice cómo comprobarlo de verdad.
            nota = QLabel("El ratón no informa de la tasa que tiene puesta, así "
                          "que aquí se muestra la última que se le ha pedido. "
                          "Para medir la real: python3 depurar.py --medir")
            nota.setObjectName("Suave")
            nota.setWordWrap(True)
            t.añadir(nota)
            combo.currentIndexChanged.connect(
                lambda i, c=combo: self._set_rate(c.itemData(i)))
            self._combo_rate = combo
            t.añadir(combo)
        else:
            t = Tarjeta("Tasa de reporte",
                        "Este ratón no permite ajustar la tasa de reporte.")

        return t

    def _pintar_boton_modo(self, btn: QPushButton) -> None:
        try:
            en_host = self.raton.onboard.es_host()
        except Exception:
            btn.setText("Cambiar de modo")
            return
        btn.setText("Volver a modo onboard" if en_host else "Cambiar a modo host")

    # -- memoria del ratón ----------------------------------------------------

    def _tab_memoria(self) -> QWidget:
        """Lo que el ratón guarda por su cuenta, y que sobrevive a apagarlo."""
        from .. import onboard as ob_mod

        cap = self.raton.onboard
        self._perfil_ob = None
        self._combos_boton = []

        cabecera = Tarjeta(
            "Memoria del ratón",
            "Tu ratón guarda dentro sus propios ajustes: la sensibilidad, la "
            "tasa de reporte y lo que hace cada botón. Eso sobrevive a apagarlo "
            "y funciona en cualquier ordenador, sin este programa ni ningún otro.")

        try:
            crudo = cap.leer_sector(1)
            perfil = ob_mod.leer_perfil(crudo, cap.num_botones)
        except Exception as e:
            cabecera.añadir(QLabel(f"No se pudo leer: {e}"))
            return _columna(cabecera)
        if crudo is None:
            cabecera.añadir(QLabel("No se pudo leer la memoria de perfiles."))
            return _columna(cabecera)
        self._perfil_ob = perfil
        self._sector_ob = crudo

        cabecera.añadir(QLabel(
            f"Guardado ahora mismo: {perfil.tasa_hz} Hz, "
            f"{perfil.dpi_por_defecto} DPI al encender, y "
            f"{len(perfil.niveles)} niveles de sensibilidad "
            f"({', '.join(str(n.x) for n in perfil.niveles)})."))

        # -- modo ------------------------------------------------------------
        t_modo = Tarjeta(
            "Quién manda ahora mismo",
            "En modo onboard manda el ratón con lo que tiene guardado, y "
            "funciona igual en cualquier sitio. En modo host mandamos nosotros: "
            "se puede cambiar la sensibilidad al vuelo y los perfiles cambian "
            "solos al arrancar un juego, pero nada de eso sobrevive a apagarlo.")
        self.lbl_modo = QLabel(self.estado.get("onboard") or "?")
        t_modo.añadir(self.lbl_modo)
        self.lbl_modo_aviso = QLabel()
        self.lbl_modo_aviso.setObjectName("Suave")
        self.lbl_modo_aviso.setWordWrap(True)
        t_modo.añadir(self.lbl_modo_aviso)
        btn_modo = QPushButton()
        btn_modo.setIcon(icono("exchange-positions", "system-switch-user"))
        self._pintar_boton_modo(btn_modo)
        btn_modo.clicked.connect(lambda: self._toggle_mode(btn_modo))
        t_modo.añadir(_suelto(btn_modo))
        self._pintar_aviso_modo()

        # -- niveles de sensibilidad -------------------------------------------
        t_niv = Tarjeta(
            "Niveles de sensibilidad",
            "Los cinco escalones que guarda el ratón. Son por los que va pasando "
            "el botón de «Ciclar DPI», y el marcado como inicial es el que tiene "
            "al encenderse.")
        self._spins_nivel = []
        try:
            validos = self.raton.dpi.valores_validos() if self.raton.dpi else []
        except Exception:
            validos = []
        minimo = min(validos) if validos else 100
        maximo = max(validos) if validos else 32000
        for i, nivel in enumerate(perfil.niveles):
            fila = QWidget()
            lay = QHBoxLayout(fila)
            lay.setContentsMargins(0, 0, 0, 0)
            etiqueta = QLabel(f"Nivel {i + 1}")
            etiqueta.setMinimumWidth(90)
            lay.addWidget(etiqueta)
            spin = QSpinBox()
            spin.setRange(minimo, maximo)
            spin.setSingleStep(50)
            spin.setSuffix(" DPI")
            spin.setValue(nivel.x)
            lay.addWidget(spin, 1)
            t_niv.añadir(fila)
            self._spins_nivel.append(spin)

        fila_def = QWidget()
        lay_def = QHBoxLayout(fila_def)
        lay_def.setContentsMargins(0, 0, 0, 0)
        et_def = QLabel("Al encender")
        et_def.setMinimumWidth(90)
        lay_def.addWidget(et_def)
        self._combo_defecto = QComboBox()
        for i in range(len(perfil.niveles)):
            self._combo_defecto.addItem(f"Nivel {i + 1}", i)
        if 0 <= perfil.nivel_por_defecto < len(perfil.niveles):
            self._combo_defecto.setCurrentIndex(perfil.nivel_por_defecto)
        lay_def.addWidget(self._combo_defecto, 1)
        t_niv.añadir(fila_def)

        btn_niv = QPushButton(icono("document-save"),
                              "Guardar los niveles en el ratón")
        btn_niv.clicked.connect(self._guardar_niveles)
        t_niv.añadir(_suelto(btn_niv))

        # -- botones ----------------------------------------------------------
        t_bot = Tarjeta(
            "Botones",
            "Lo que hace cada botón, guardado en el ratón. Sólo tiene efecto en "
            "modo onboard: en modo host manda el firmware y estos ajustes no se "
            "aplican.")
        # El esquema es un dibujo genérico de ratón diestro de cinco botones,
        # que es la disposición de casi todos. Pulsar en uno lleva el foco a su
        # desplegable, para no tener que contar cuál es cuál.
        self._diagrama = DiagramaRaton()
        self._diagrama.pulsado.connect(self._enfocar_boton)
        t_bot.añadir(self._diagrama)
        for i, b in enumerate(perfil.botones):
            fila = QWidget()
            lay = QHBoxLayout(fila)
            lay.setContentsMargins(0, 0, 0, 0)
            etiqueta = QLabel(f"Botón {i + 1}")
            etiqueta.setMinimumWidth(90)
            lay.addWidget(etiqueta)
            combo = QComboBox()
            actual = ob_mod.describir_boton(b)
            for nombre in ob_mod.ACCIONES:
                combo.addItem(nombre, nombre)
            if actual not in ob_mod.ACCIONES:
                # Algo que sabemos leer pero no ofrecer: se enseña y no se pierde.
                combo.addItem(actual, None)
            combo.setCurrentText(actual)
            lay.addWidget(combo, 1)
            combo.currentIndexChanged.connect(self._refrescar_diagrama)
            t_bot.añadir(fila)
            self._combos_boton.append(combo)
        self._refrescar_diagrama()

        btn_bot = QPushButton(icono("document-save"),
                              "Guardar los botones en el ratón")
        btn_bot.clicked.connect(self._guardar_botones)
        t_bot.añadir(_suelto(btn_bot))

        # -- guardar los ajustes de ahora --------------------------------------
        dpi = self.estado.get("dpi")
        rate = self.estado.get("rate")
        t_guardar = Tarjeta(
            "Guardar los ajustes actuales",
            "Escribe en el ratón lo que tienes puesto ahora, para que lo "
            "conserve al apagarlo y lo lleve consigo a otro ordenador.")
        detalle = []
        if dpi:
            detalle.append(f"{dpi.actual} DPI")
        if rate:
            detalle.append(f"{rate.actual_hz} Hz")
        t_guardar.añadir(QLabel(
            "Se guardaría: " + (", ".join(detalle) if detalle else "nada") + "."))
        aviso = QLabel(
            "La memoria del ratón admite un número limitado de escrituras, así "
            "que conviene guardar cuando tengas los ajustes como los quieres, "
            "no en cada prueba.")
        aviso.setObjectName("Suave")
        aviso.setWordWrap(True)
        t_guardar.añadir(aviso)
        btn_guardar = QPushButton(icono("document-save"), "Guardar en el ratón")
        btn_guardar.clicked.connect(self._guardar_ajustes_ob)
        t_guardar.añadir(_suelto(btn_guardar))

        return _columna(cabecera, t_modo, t_niv, t_bot, t_guardar)

    def _refrescar_desfase(self) -> None:
        """Avisa si lo que tiene el ratón ya no es lo que dice el perfil."""
        etiqueta = getattr(self, "lbl_desfase", None)
        boton = getattr(self, "btn_guardar_perfil", None)
        if etiqueta is None or boton is None:
            return
        perfil = self._perfil_activo()
        dpi = self.estado.get("dpi")
        rate = self.estado.get("rate")
        if perfil is None or (dpi is None and rate is None):
            etiqueta.setVisible(False)
            boton.setVisible(False)
            return

        # Se comparan los dos ajustes, no sólo el DPI: cambiar la tasa y que no
        # apareciera el botón dejaba sin forma de guardarla en el perfil.
        difieren = []
        if dpi is not None and perfil.ajustes.dpi not in (None, dpi.actual):
            difieren.append(f"{perfil.ajustes.dpi} DPI")
        if rate is not None and perfil.ajustes.report_rate_hz not in (
                None, rate.actual_hz):
            difieren.append(f"{perfil.ajustes.report_rate_hz} Hz")

        if not difieren:
            etiqueta.setText(f"Coincide con el perfil «{perfil.nombre}».")
            boton.setVisible(False)
        else:
            etiqueta.setText(
                f"El perfil «{perfil.nombre}» tiene guardado "
                f"{' y '.join(difieren)}. Esto que has puesto vale hasta que se "
                "aplique un perfil.")
            boton.setText(f"Guardar esto en «{perfil.nombre}»")
            boton.setVisible(True)
        etiqueta.setVisible(True)

    def _guardar_en_perfil(self) -> None:
        perfil = self._perfil_activo()
        dpi = self.estado.get("dpi")
        if perfil is None or dpi is None:
            return
        # Se guardan los dos ajustes que el perfil ya llevaba. No se le añaden
        # campos nuevos: si un perfil sólo toca el DPI a propósito, meterle la
        # tasa cambiaría lo que hace sin que nadie lo haya pedido.
        if perfil.ajustes.dpi is not None:
            perfil.ajustes.dpi = dpi.actual
        rate = self.estado.get("rate")
        if rate and perfil.ajustes.report_rate_hz is not None:
            perfil.ajustes.report_rate_hz = rate.actual_hz
        try:
            almacen = Almacen(demo=self.demo)
            almacen.cargar()
            almacen.guardar(perfil)
        except Exception as e:
            QMessageBox.warning(self, "No se pudo guardar el perfil", str(e))
            return
        self._refrescar_desfase()
        _avisar(self, f"«{perfil.nombre}» guardado")

    def _pintar_aviso_modo(self) -> None:
        aviso = getattr(self, "lbl_modo_aviso", None)
        if aviso is None:
            return
        try:
            host = self.raton.onboard.es_host()
        except Exception:
            return
        aviso.setText(
            "Mientras esté así, los perfiles por juego no se aplican: el DPI lo "
            "manda la memoria del ratón." if not host else
            "Los perfiles por juego funcionan, pero lo que ajustes se pierde al "
            "apagar el ratón.")

    def _refrescar_diagrama(self) -> None:
        """El esquema enseña lo que hay elegido ahora, no lo que está guardado."""
        diagrama = getattr(self, "_diagrama", None)
        if diagrama is not None:
            diagrama.poner([c.currentText() for c in self._combos_boton])

    def _enfocar_boton(self, indice: int) -> None:
        if 0 <= indice < len(self._combos_boton):
            combo = self._combos_boton[indice]
            combo.setFocus()
            combo.showPopup()

    def _copia_sector(self) -> str:
        """Guarda el sector original antes de tocarlo, y devuelve la ruta."""
        from ..profiles import directorio_perfiles
        carpeta = directorio_perfiles(self.demo).parent / "respaldo"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"{self.raton.id_str}-sector1.bin"
        ruta.write_bytes(self._sector_ob)
        return str(ruta)

    def _escribir_perfil_ob(self, perfil, que: str) -> bool:
        from .. import onboard as ob_mod
        try:
            copia = self._copia_sector()
            with _ocupado(self, f"Guardando {que} en el ratón…"):
                self.raton.onboard.escribir_sector(
                    1, ob_mod.escribir_perfil(perfil))
            self._sector_ob = self.raton.onboard.leer_sector(1)
            self._perfil_ob = ob_mod.leer_perfil(self._sector_ob,
                                                 self.raton.onboard.num_botones)
            _avisar(self, f"{que.capitalize()} guardados en el ratón")
        except Exception as e:
            QMessageBox.warning(self, f"No se pudo guardar {que}", str(e))
            return False
        QMessageBox.information(
            self, "Guardado en el ratón",
            f"{que.capitalize()} ya están en la memoria del ratón.\n\n"
            f"Copia del estado anterior en:\n{copia}"
            + ("" if not self.raton.onboard.es_host() else
               "\n\nAhora mismo el ratón está en modo host, y en ese modo usa "
               "los botones del firmware, no los que acabas de guardar. Para "
               "probarlos, pulsa «Volver a modo onboard» aquí arriba."))
        return True

    def _guardar_niveles(self) -> None:
        perfil = self._perfil_ob
        if perfil is None:
            return
        try:
            validos = self.raton.dpi.valores_validos() if self.raton.dpi else []
        except Exception:
            validos = []
        for i, spin in enumerate(self._spins_nivel):
            if i >= len(perfil.niveles):
                break
            v = spin.value()
            # El sensor sólo admite ciertos valores: se ajusta al más cercano
            # antes de escribirlo, o el ratón guardaría algo que no puede usar.
            if validos:
                v = min(validos, key=lambda x: abs(x - v))
                spin.setValue(v)
            perfil.niveles[i].x = perfil.niveles[i].y = v
        perfil.nivel_por_defecto = self._combo_defecto.currentIndex()
        self._escribir_perfil_ob(perfil, "los niveles")

    def _guardar_botones(self) -> None:
        from .. import onboard as ob_mod
        perfil = self._perfil_ob
        if perfil is None:
            return
        for i, combo in enumerate(self._combos_boton):
            nombre = combo.currentData()
            if nombre is None:          # una acción que no sabemos componer
                continue
            perfil.botones[i] = ob_mod.ACCIONES[nombre]
        self._escribir_perfil_ob(perfil, "los botones")

    def _guardar_ajustes_ob(self) -> None:
        perfil = self._perfil_ob
        if perfil is None:
            return
        dpi = self.estado.get("dpi")
        rate = self.estado.get("rate")
        if rate and rate.actual_hz in [125, 250, 500, 1000, 2000, 4000, 8000]:
            perfil.tasa_hz = rate.actual_hz
        if dpi:
            # Si el DPI de ahora ya es uno de los niveles, basta apuntar a él;
            # si no, se escribe en el que arranca por defecto.
            valores = [n.x for n in perfil.niveles]
            if dpi.actual in valores:
                perfil.nivel_por_defecto = valores.index(dpi.actual)
            elif perfil.niveles:
                i = perfil.nivel_por_defecto
                i = i if 0 <= i < len(perfil.niveles) else 0
                perfil.niveles[i].x = perfil.niveles[i].y = dpi.actual
                perfil.nivel_por_defecto = i
        self._escribir_perfil_ob(perfil, "los ajustes")

    def _tab_botones(self) -> QWidget:
        cap = self.raton.buttons
        if cap is None:
            return _columna(Tarjeta(
                "Botones reprogramables",
                "Este ratón no permite reasignar sus botones desde el sistema. "
                "Los configura su propio perfil interno."))

        try:
            controles = cap.controls()
        except Exception as e:
            return _columna(Tarjeta("Botones reprogramables",
                                    f"No se pudo leer la lista de controles: {e}"))

        tarjeta = Tarjeta(
            "Botones reprogramables",
            "Cada botón sólo puede adoptar "
            "la función de otros que el firmware permita: por eso el clic "
            "izquierdo casi nunca se puede mover. No es una limitación de este "
            "programa, la impone el ratón.")

        self._combos_botones = {}
        movibles = 0
        for control in controles:
            destinos = [d for d in controles
                        if d.cid != control.cid and control.admite(d)]
            fila = QHBoxLayout()
            etiqueta = QLabel(control.nombre)
            etiqueta.setMinimumWidth(190)
            fila.addWidget(etiqueta)

            combo = QComboBox()
            combo.addItem("Función original", 0)
            for d in destinos:
                combo.addItem(f"Actuar como: {d.nombre}", d.cid)

            if not destinos:
                combo.setEnabled(False)
                combo.setToolTip("El firmware no permite reasignar este botón")
            else:
                movibles += 1
                try:
                    actual = cap.reporting(control.cid).remapeado_a
                    indice = combo.findData(actual)
                    combo.setCurrentIndex(max(0, indice))
                except Exception:
                    pass
                combo.currentIndexChanged.connect(
                    lambda i, c=combo, cid=control.cid: self._remapear(cid, c.itemData(i)))

            self._combos_botones[control.cid] = combo
            fila.addWidget(combo, 1)
            fila.addWidget(QLabel(f"grupo {control.group}"))
            tarjeta.añadir_layout(fila)

        restaurar = QPushButton("Restaurar todos los botones")
        restaurar.clicked.connect(lambda: self._restaurar_botones(controles))
        restaurar.setEnabled(movibles > 0)
        tarjeta.añadir(restaurar)

        aviso = Tarjeta(
            "Qué falta aquí",
            "De momento un botón sólo puede adoptar la función de otro botón "
            "del ratón. Asignar acciones del sistema (una tecla, una macro, un "
            "atajo) necesita además \"desviar\" el botón hacia el demonio y que "
            "sea él quien genere el evento — eso viene después, y usa el mismo "
            "0x1B04 con el bit de desvío.")
        return _columna(tarjeta, aviso)

    def _remapear(self, cid: int, destino: int) -> None:
        try:
            if destino:
                self.raton.buttons.remapear(cid, destino)
            else:
                self.raton.buttons.restaurar(cid)
        except Exception as e:
            QMessageBox.warning(self, "No se pudo reasignar el botón", str(e))

    def _restaurar_botones(self, controles) -> None:
        for control in controles:
            try:
                self.raton.buttons.restaurar(control.cid)
            except Exception:
                pass
        for cid, combo in self._combos_botones.items():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

    def _tab_perfiles(self) -> QWidget:
        return PanelPerfiles(self.raton, demo=self.demo)

    def _tab_firmware(self) -> QWidget:
        tarjetas = []

        t = Tarjeta("Versiones instaladas",
                    "Leído del propio ratón.")
        if self.raton.info is None:
            t.añadir(QLabel("Este ratón no informa de su versión de firmware."))
        else:
            try:
                for f in self.raton.info.firmwares():
                    fila = QHBoxLayout()
                    etiqueta = QLabel(f.nombre_tipo)
                    etiqueta.setMinimumWidth(190)
                    fila.addWidget(etiqueta)
                    valor = QLabel(f.version)
                    fuente = QFont(valor.font())
                    fuente.setStyleHint(QFont.StyleHint.Monospace)
                    valor.setFont(fuente)
                    valor.setTextInteractionFlags(
                        Qt.TextInteractionFlag.TextSelectableByMouse)
                    fila.addWidget(valor)
                    fila.addStretch(1)
                    t.añadir_layout(fila)
                t.añadir(QLabel(f"Identificador único: {self.raton.info.unit_id()}"))
            except Exception as e:
                t.añadir(QLabel(f"No se pudieron leer las versiones: {e}"))
        tarjetas.append(t)

        estado = firmware.resumen()
        t2 = Tarjeta("Actualizar: lo hace fwupd, no este programa",
                     "fwupd es la herramienta estándar de Linux para firmware. "
                     "Descarga imágenes firmadas desde LVFS, implementa el modo "
                     "DFU de HID++ y tiene ruta de recuperación si algo se "
                     "corta. Reimplementar eso aquí sería la única parte del "
                     "proyecto capaz de dejarte el ratón inservible, así que no "
                     "se hace.")
        t2.añadir(QLabel(estado["mensaje"]))
        for d in estado.get("dispositivos", []):
            marca = "actualizable" if d["actualizable"] else "sin actualizaciones disponibles"
            t2.añadir(QLabel(f"  • {d['nombre']} — versión {d['version']} ({marca})"))

        comprobar = QPushButton("Comprobar de nuevo")
        comprobar.clicked.connect(lambda: QMessageBox.information(
            self, "Comprobar actualizaciones",
            "Para buscar actualizaciones de verdad, en la terminal:\n\n"
            "    fwupdmgr refresh\n"
            "    fwupdmgr get-updates\n"
            "    fwupdmgr update\n\n"
            "Se hace desde fuera a propósito: así el proceso que escribe en el "
            "firmware es fwupd, que está preparado para ello, y no nosotros."))
        t2.añadir(comprobar)
        tarjetas.append(t2)

        if not estado.get("dispositivos"):
            tarjetas.append(Tarjeta(
                "Si fwupd no reconoce tu ratón",
                "Entonces hoy no se puede actualizar el firmware desde Linux de "
                "forma segura, y el camino útil no es escribir un flasheador "
                "propio: es añadir el dispositivo a fwupd, que es software libre "
                "y acepta contribuciones. Hace falta el identificador del "
                "dispositivo y alguien con el hardware para probar — o sea, tú. "
                "Mientras tanto queda la herramienta web oficial de Logitech, "
                "que funciona en Chrome sobre Linux con WebHID."))
        return _columna(*tarjetas)

    def _tab_diagnostico(self) -> QWidget:
        t = Tarjeta("Capacidades que declara el ratón",
                    "Esta tabla no está escrita a mano: la responde el propio "
                    "dispositivo. Es la base de todo lo demás.")
        tabla = QTableWidget()
        filas = self.raton.feature_table
        tabla.setRowCount(len(filas))
        tabla.setColumnCount(4)
        tabla.setHorizontalHeaderLabels(["Índice", "ID", "Versión", "Qué es"])
        tabla.verticalHeader().setVisible(False)
        tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for fila, info in enumerate(filas):
            marcas = [m for m, on in (("obsoleta", info.obsolete),
                                      ("oculta", info.hidden),
                                      ("interna", info.internal)) if on]
            nombre = info.name + (f"  [{', '.join(marcas)}]" if marcas else "")
            for col, txt in enumerate([str(info.index), f"0x{info.fid:04X}",
                                       f"v{info.version}", nombre]):
                tabla.setItem(fila, col, QTableWidgetItem(txt))
        tabla.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        tabla.setMinimumHeight(260)
        t.añadir(tabla)

        t2 = Tarjeta("Volcado en crudo",
                     "Para las features aún sin validar (0x2202, 0x8061), esto "
                     "muestra la respuesta byte a byte. Es la herramienta con la "
                     "que se corrige el decodificador sin adivinar nada.")
        salida = QPlainTextEdit()
        salida.setReadOnly(True)
        salida.setMinimumHeight(160)
        fuente = QFont("monospace")
        fuente.setStyleHint(QFont.StyleHint.Monospace)
        salida.setFont(fuente)
        boton = QPushButton("Volcar respuestas en crudo")
        boton.clicked.connect(lambda: salida.setPlainText(self._volcado()))
        t2.añadir(boton)
        t2.añadir(salida)

        if self.estado.get("errores") or self.estado.get("fallos"):
            t3 = Tarjeta("Incidencias durante la lectura")
            for e in self.estado.get("errores", []):
                t3.añadir(QLabel(f"• {e}"))
            for k, v in (self.estado.get("fallos") or {}).items():
                t3.añadir(QLabel(f"• {k}: {v}"))
            return _columna(t, t2, t3)
        return _columna(t, t2)

    # -- acciones -------------------------------------------------------------

    def _volcado(self) -> str:
        lineas = []
        pruebas = [
            ("0x2202 getSensorCount", 0x2202, 0x00, b""),
            ("0x2202 getSensorCapabilities", 0x2202, 0x01, b"\x00"),
            ("0x2202 getSensorDpiRanges (pág 0)", 0x2202, 0x02, b"\x00\x00\x00"),
            ("0x2202 getSensorDpiRanges (pág 1)", 0x2202, 0x02, b"\x00\x00\x01"),
            ("0x2202 getSensorDpiRanges (pág 2)", 0x2202, 0x02, b"\x00\x00\x02"),
            ("0x2202 getSensorDpi  f5", 0x2202, 0x05, b"\x00"),
            ("0x2201 getSensorDpiList", 0x2201, 0x01, b"\x00"),
            ("0x2201 getSensorDpi", 0x2201, 0x02, b"\x00"),
            ("0x8061 capacidades (receptor)", 0x8061, 0x00, b"\x00"),
            ("0x8061 capacidades (cable)", 0x8061, 0x00, b"\x01"),
            ("0x8061 getReportRateList  f1", 0x8061, 0x01, b""),
            ("0x8061 getReportRate  f2", 0x8061, 0x02, b""),
            ("0x8060 getReportRateList", 0x8060, 0x00, b""),
            ("0x8060 getReportRate", 0x8060, 0x01, b""),
            ("0x8090 getModeStatus", 0x8090, 0x00, b""),
            ("0x8100 getOnboardMode  f2", 0x8100, 0x02, b""),
            ("0x1004 getBatteryStatus", 0x1004, 0x01, b""),
            ("0x1004 getBatteryCapability", 0x1004, 0x00, b""),
            ("0x8100 getOnboardProfilesInfo", 0x8100, 0x00, b""),
            ("0x1B04 getCount", 0x1B04, 0x00, b""),
            ("0x1B04 getCidInfo(0)", 0x1B04, 0x01, b"\x00"),
            ("0x1B04 getCidInfo(1)", 0x1B04, 0x01, b"\x01"),
            ("0x1B04 getCidInfo(2)", 0x1B04, 0x01, b"\x02"),
            ("0x1B04 getCidInfo(3)", 0x1B04, 0x01, b"\x03"),
            ("0x1B04 getCidReporting(0x53)", 0x1B04, 0x02, b"\x00\x53"),
        ]
        tabla = self.raton.hpp.features()
        for etiqueta, fid, func, params in pruebas:
            if fid not in tabla:
                lineas.append(f"{etiqueta:38} — feature ausente")
                continue
            try:
                r = self.raton.hpp.call(tabla[fid].index, func, params)
                lineas.append(f"{etiqueta:38} {r.hex(' ')}")
            except Exception as e:
                lineas.append(f"{etiqueta:38} ⚠ {e}")
        return "\n".join(lineas)

    def _antes_de_escribir(self) -> None:
        """El ratón vuelve a onboard al reconectarse, y así rechaza todo."""
        if self.raton.asegurar_host() and hasattr(self, "lbl_modo"):
            try:
                self.lbl_modo.setText(self.raton.onboard.get())
            except Exception:
                pass

    def _explicar(self, e: Exception) -> str:
        """Traduce el error del ratón a algo accionable."""
        from gpx2.hidpp import HidppError
        if isinstance(e, HidppError) and e.code == 0x05:
            return ("El ratón rechazó el cambio. Suele pasar cuando mandan sus "
                    "perfiles internos: prueba «Cambiar a modo host» en la "
                    "pestaña Rendimiento.")
        return str(e)

    def _set_dpi(self, valor: int) -> None:
        try:
            self._antes_de_escribir()
            self.raton.dpi.set(int(valor))
            self._marcar_nivel(int(valor))
        except Exception as e:
            QMessageBox.warning(self, "No se pudo cambiar el DPI",
                                self._explicar(e))

    def _set_rate(self, hz: int) -> None:
        self._tras_cambiar_rate = True
        from gpx2.features import EscrituraIgnorada
        try:
            self._antes_de_escribir()
            self.raton.rate.set(int(hz))
        except EscrituraIgnorada as e:
            # El ratón no ha cambiado: dejar el desplegable donde estaba, o
            # estaríamos enseñando un valor que el dispositivo no tiene.
            QMessageBox.information(
                self, "El ratón no aplicó la tasa",
                f"{e}\n\nNo es un fallo de comunicación: la orden llegó y el "
                "ratón la aceptó, pero mantiene su tasa.")
            self._resincronizar_rate()
        except Exception as e:
            QMessageBox.warning(self, "No se pudo cambiar la tasa de reporte",
                                self._explicar(e))
            self._resincronizar_rate()
        self._refrescar_desfase()

    def _resincronizar_rate(self) -> None:
        """Devuelve el desplegable a lo que el ratón dice de verdad."""
        combo = getattr(self, "_combo_rate", None)
        if combo is None:
            return
        try:
            real = self.raton.rate.get().actual_hz
        except Exception:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == real:
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
                return

    def _toggle_mode(self, btn: QPushButton) -> None:
        from ..profiles import guardar_modo_preferido
        try:
            quiero_host = not self.raton.onboard.es_host()
            # Se anota la elección ANTES de hacerla: el demonio comprueba cada
            # pocos segundos si el ratón se ha reiniciado solo, y sin saber que
            # esto lo has pedido tú, te lo desharía.
            guardar_modo_preferido("host" if quiero_host else "onboard", self.demo)
            if not self.raton.onboard.set_host(quiero_host):
                QMessageBox.warning(
                    self, "El ratón no aceptó el cambio",
                    "El dispositivo sigue en el modo anterior.")
            self._pintar_boton_modo(btn)
            if hasattr(self, "lbl_modo"):
                self.lbl_modo.setText(self.raton.onboard.get())
            self._pintar_aviso_modo()
        except Exception as e:
            QMessageBox.warning(self, "No se pudo cambiar el modo", str(e))


# ---------------------------------------------------------------------------
# Página: puntero genérico (sin HID++)
# ---------------------------------------------------------------------------

class PaginaPuntero(QWidget):
    def __init__(self, puntero: desktop.KdePointer, parent=None):
        super().__init__(parent)
        self.p = puntero
        info = puntero.info()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        cab = QWidget()
        cl = QVBoxLayout(cab)
        cl.setContentsMargins(18, 16, 18, 10)
        cl.setSpacing(2)
        titulo = QLabel(info.nombre)
        titulo.setObjectName("Titulo")
        sub = QLabel(f"{info.id_str} · {info.sysname} · "
                     + ("endpoint de ratón de un teclado"
                        if info.es_de_teclado else "sin canal HID++"))
        sub.setObjectName("Suave")
        cl.addWidget(titulo)
        cl.addWidget(sub)
        lay.addWidget(cab)

        if info.es_de_teclado:
            aviso = Tarjeta(
                "Esto es un teclado, no un ratón",
                "Aparece aquí porque el teclado declara además un endpoint de "
                "ratón: es la función de mover el cursor con las teclas, típica "
                "del firmware QMK/VIA. El sistema lo trata como un ratón real, "
                "así que estos ajustes funcionan — pero sólo afectan al cursor "
                "movido desde el teclado, no a tu ratón.")
        else:
            aviso = Tarjeta(
                "Este ratón no es configurable por hardware",
                "No expone el canal HID++ de Logitech, así que no hay DPI ni tasa de "
                "reporte que tocar. Lo que sí se puede ajustar es cómo interpreta "
                "Plasma su movimiento, exactamente igual que en Ajustes del sistema.")

        sens = Tarjeta("Sensibilidad del puntero")
        fila = FilaSlider("Velocidad", -1.0, 1.0, 0.05, decimales=2)
        fila.poner(info.aceleracion)
        fila.cambiado.connect(self.p.set_aceleracion)
        fila.setEnabled(info.soporta_aceleracion)
        sens.añadir(fila)
        chk = QCheckBox("Perfil plano (sin aceleración)")
        chk.setChecked(info.perfil_plano)
        chk.toggled.connect(self.p.set_perfil_plano)
        sens.añadir(chk)

        comp = Tarjeta("Comportamiento")
        for texto, valor, setter in (
                ("Desplazamiento natural", info.scroll_natural, self.p.set_scroll_natural),
                ("Modo zurdo (invertir botones)", info.zurdo, self.p.set_zurdo),
                ("Emular botón central", info.emulacion_central, self.p.set_emulacion_central)):
            c = QCheckBox(texto)
            c.setChecked(valor)
            c.toggled.connect(setter)
            comp.añadir(c)

        lay.addWidget(_envolver(_columna(aviso, sens, comp)), 1)


# ---------------------------------------------------------------------------
# Ventana
# ---------------------------------------------------------------------------

class PanelPerfiles(QWidget):
    """Lista de perfiles, con o sin demonio.

    Si el demonio está en marcha, es él quien manda al ratón (y quien cambia de
    perfil solo al arrancar un juego). Si no lo está, la interfaz aplica los
    perfiles directamente. En ambos casos los perfiles son los mismos ficheros
    TOML del disco, así que no hay dos verdades.
    """

    def __init__(self, raton: Mouse, demo: bool = False, parent=None):
        super().__init__(parent)
        self.raton = raton
        self.motor = Motor(raton)
        self.cliente = ClienteDemonio()
        self.almacen = Almacen(demo=demo)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 18, 18, 18)
        raiz.setSpacing(14)

        self.aviso = Tarjeta("")
        self.aviso_texto = QLabel()
        self.aviso_texto.setWordWrap(True)
        self.aviso.añadir(self.aviso_texto)
        raiz.addWidget(self.aviso)

        tarjeta = Tarjeta("Perfiles",
                          "El que lleva ⬢ es el que manda ahora. "
                          "Selecciona uno y pulsa Aplicar, o haz doble clic. "
                          "Cada perfil es un fichero TOML en "
                          f"{self.almacen.dir}, editable a mano.")
        self.lista = QListWidget()
        # Nombre propio: el estilo de la lista lateral pinta la selección con
        # el color de realce a todo lo ancho, y aquí ese color tiene que ser
        # para el perfil que MANDA, no para el que está seleccionado.
        self.lista.setObjectName("ListaPerfiles")
        self.lista.setItemDelegate(DelegadoDispositivo(self.lista))
        self.lista.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setMinimumHeight(220)
        self.lista.itemDoubleClicked.connect(lambda _: self._aplicar())
        tarjeta.añadir(self.lista)

        botones = QHBoxLayout()
        for texto, nombres, accion in (
                ("Aplicar", ("dialog-ok-apply", "dialog-ok"), self._aplicar),
                ("Crear desde el estado actual", ("list-add", "document-new"),
                 self._crear),
                ("Juegos…", ("applications-games", "preferences-desktop-gaming"),
                 self._editar_juegos),
                ("Por defecto", ("emblem-favorite", "bookmarks"),
                 self._por_defecto),
                ("Borrar", ("edit-delete", "list-remove"), self._borrar)):
            b = QPushButton(icono(*nombres), texto)
            b.clicked.connect(accion)
            botones.addWidget(b)
        botones.addStretch(1)
        abrir = QPushButton(icono("folder-open", "document-open-folder"),
                            "Abrir carpeta")
        abrir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.almacen.dir))))
        botones.addWidget(abrir)
        tarjeta.añadir_layout(botones)
        raiz.addWidget(tarjeta)
        raiz.addStretch(1)

        self.refrescar()

    # -- estado ---------------------------------------------------------------

    def refrescar(self) -> None:
        errores = self.almacen.cargar()
        if self.cliente.activo:
            self.aviso.setToolTip("")
            self.aviso_texto.setText(
                "✅  El demonio está en marcha: los perfiles cambian solos cuando "
                "arranca un juego, y los cambios que hagas aquí los aplica él.")
            self.cliente.recargar()
            activo = self.cliente.estado().get("perfil_activo", "")
        else:
            self.aviso_texto.setText(
                "⚠  El demonio no está en marcha. Puedes aplicar perfiles a mano "
                "desde aquí, pero no cambiarán solos al arrancar un juego.\n\n"
                "Para activarlo:  systemctl --user enable --now gpx2d.service")
            activo = self.motor.perfil_activo or ""

        try:
            from ..procesos import nombres_de_steam
            nombres_steam = nombres_de_steam()
        except Exception:
            nombres_steam = {}

        self.lista.clear()
        for p in self.almacen.lista():
            # El azul de la lista es la SELECCIÓN, no el perfil que manda: son
            # dos cosas distintas y se leían como una. El que manda lleva el
            # mismo símbolo que la pastilla de la cabecera, para que se vea que
            # hablan de lo mismo.
            marcas = []
            if p.id == activo:
                marcas.append("manda ahora")
            if p.por_defecto:
                marcas.append("por defecto")
            ajustes = p.ajustes.campos()
            resumen = ", ".join(
                f"{'DPI' if k == 'dpi' else 'Hz'} {v}" for k, v in ajustes.items()) or "sin ajustes"
            # Los juegos de Steam se guardan por AppID, que no le dice nada a
            # nadie: aquí se enseña el nombre. Sin esto, añadir un juego de
            # Steam parecía no haber hecho nada.
            juegos = list(p.activacion.ejecutables)
            for appid in p.activacion.steam_appids:
                juegos.append(nombres_steam.get(appid, f"Steam {appid}"))
            detalle = resumen + (f"  ·  {', '.join(juegos)}" if juegos else "")
            if marcas:
                detalle += f"  ·  {' · '.join(marcas)}"
            item = QListWidgetItem(("⬢  " if p.id == activo else "     ") + p.nombre)
            item.setData(ROL_SUB, detalle)
            item.setData(ROL_DATOS, p.id)
            self.lista.addItem(item)

        for e in errores:
            self.lista.addItem(QListWidgetItem(f"⚠ perfil ilegible — {e}"))
        if self.lista.count():
            self.lista.setCurrentRow(0)

    def _seleccionado(self) -> Perfil | None:
        item = self.lista.currentItem()
        if item is None:
            return None
        return self.almacen.obtener(item.data(ROL_DATOS) or "")

    # -- acciones -------------------------------------------------------------

    def _pagina_raton(self):
        """La página de ratón que contiene este panel, si la hay."""
        w = self.parent()
        while w is not None and not isinstance(w, PaginaRaton):
            w = w.parent()
        return w

    def _exige_seleccion(self, accion: str):
        """El perfil elegido, o un aviso. Callarse deja al usuario pulsando un
        botón que no hace nada, sin forma de saber qué falta."""
        perfil = self._seleccionado()
        if perfil is None:
            QMessageBox.information(
                self, "Elige un perfil primero",
                f"Selecciona en la lista el perfil {accion}.")
        return perfil

    def _aplicar(self) -> None:
        self._aplicar_perfil(self._exige_seleccion("que quieres aplicar"))

    def _aplicar_perfil(self, perfil) -> None:
        if perfil is None:
            return
        if self.cliente.activo:
            resultado = self.cliente.aplicar(perfil.id)
            if not resultado.get("ok"):
                QMessageBox.warning(self, "No se pudo aplicar",
                                    resultado.get("error", "error desconocido"))
                return
            cambios = resultado.get("cambios", [])
        else:
            cambios = [str(c) for c in self.motor.aplicar(perfil)]
        self.refrescar()
        # Los controles de las otras pestañas siguen enseñando lo de antes.
        pagina = self._pagina_raton()
        if pagina is not None:
            pagina.refrescar_ajustes()
        _avisar(self, f"{perfil.nombre}: "
                + ("; ".join(cambios) if cambios else "ya estaba aplicado"), 6000)

    def _crear(self) -> None:
        nombre, ok = QInputDialog.getText(
            self, "Nuevo perfil",
            "Nombre del perfil (se guarda con el DPI y los Hz que tiene el "
            "ratón ahora mismo):")
        if not ok or not nombre.strip():
            return
        perfil = Perfil(nombre=nombre.strip(), ajustes=self.motor.estado())
        self.almacen.guardar(perfil)
        self.refrescar()

    def _editar_juegos(self) -> None:
        from .dialogos import DialogoJuegos
        perfil = self._exige_seleccion("cuyos juegos quieres elegir")
        if perfil is None:
            return
        dlg = DialogoJuegos(perfil.nombre,
                            list(perfil.activacion.ejecutables),
                            list(perfil.activacion.steam_appids), self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        perfil.activacion.ejecutables, perfil.activacion.steam_appids = dlg.resultado()
        self.almacen.guardar(perfil)
        self.refrescar()

    def _por_defecto(self) -> None:
        perfil = self._exige_seleccion("que quieres poner por defecto")
        if perfil is None:
            return
        self.almacen.marcar_por_defecto(perfil.id)
        # Marcarlo por defecto y que no pase nada desconcierta: el perfil por
        # defecto es "lo que quiero tener puesto", así que se aplica también.
        self._aplicar_perfil(perfil)

    def _borrar(self) -> None:
        perfil = self._exige_seleccion("que quieres borrar")
        if perfil is None:
            return
        if QMessageBox.question(
                self, "Borrar perfil",
                f"¿Borrar «{perfil.nombre}»? Se elimina el fichero del disco.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.almacen.borrar(perfil.id)
        self.refrescar()


class VentanaPrincipal(QMainWindow):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self.setWindowTitle("gpx2 — control de ratones Logitech"
                            + ("  ·  MODO DEMO" if demo else ""))
        self.resize(1220, 840)
        self.hallazgo: Discovery | None = None

        divisor = QSplitter(Qt.Orientation.Horizontal)

        lateral = QWidget()
        lateral.setObjectName("Lateral")
        # Sin esto el divisor deja arrastrar la barra hasta que desaparece y
        # no hay forma de recuperarla.
        lateral.setMinimumWidth(190)
        lateral.setMaximumWidth(420)
        lat = QVBoxLayout(lateral)
        lat.setContentsMargins(0, 14, 0, 10)
        lat.setSpacing(8)

        self.lista = QListWidget()
        self.lista.setObjectName("ListaDispositivos")
        self.lista.setItemDelegate(DelegadoDispositivo(self.lista))
        self.lista.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setUniformItemSizes(False)
        self.lista.setSizePolicy(QSizePolicy.Policy.Preferred,
                                 QSizePolicy.Policy.Maximum)
        self.lista.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.lista.currentItemChanged.connect(self._seleccion)
        lat.addWidget(self.lista)
        lat.addStretch(1)

        self.btn_rescan = QPushButton(icono("view-refresh"), "Volver a escanear")
        self.btn_rescan.clicked.connect(self.escanear)
        lat.addWidget(self.btn_rescan)

        self.pila = QStackedWidget()
        self.vacia = PaginaVacia(self.escanear)
        self.pila.addWidget(self.vacia)

        divisor.addWidget(lateral)
        divisor.addWidget(self.pila)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([230, 990])
        divisor.setChildrenCollapsible(False)
        self.lateral = lateral
        self.setCentralWidget(divisor)

        # Ocultar la barra sí, pero a propósito y con vuelta atrás.
        self.accion_lateral = QAction("Mostrar u ocultar los dispositivos", self)
        self.accion_lateral.setShortcut("Ctrl+B")
        self.accion_lateral.triggered.connect(self._alternar_lateral)
        self.addAction(self.accion_lateral)

        self.btn_lateral = QPushButton("◧  Dispositivos")
        self.btn_lateral.setFlat(True)
        self.btn_lateral.setToolTip("Mostrar u ocultar el panel lateral (Ctrl+B)")
        self.btn_lateral.clicked.connect(self._alternar_lateral)
        self.statusBar().addPermanentWidget(self.btn_lateral)
        self.statusBar().showMessage("Listo")

        # Vigilancia de conexiones. Sin dependencias añadidas: mirar qué nodos
        # /dev/hidraw* hay es un listado de directorio, y cambia en cuanto se
        # enciende o se apaga un dispositivo. Un udev real necesitaría pyudev.
        self._firma_nodos: tuple = ()
        self._ciclos = 0
        self._escaneando = False
        self._fallos = 0
        self._vigilante = QTimer(self)
        self._vigilante.setInterval(800)
        self._vigilante.timeout.connect(self._vigilar)
        self._vigilante.start()

        # Al enchufar el receptor, el nodo aparece antes de que el ratón
        # conteste por HID++. Si escaneáramos al instante, no lo veríamos como
        # ratón HID++ y acabaría en la lista de punteros genéricos. Esperar
        # también agrupa la ráfaga de nodos que crea un solo receptor.
        self._rescan = QTimer(self)
        self._rescan.setSingleShot(True)
        self._rescan.setInterval(700)
        self._rescan.timeout.connect(self.escanear)

        QTimer.singleShot(0, self.escanear)

    # -- vigilancia -----------------------------------------------------------

    @staticmethod
    def _firma() -> tuple:
        from glob import glob
        return tuple(sorted(glob("/dev/hidraw*")))

    def _vigilar(self) -> None:
        if self._escaneando:
            return
        firma = self._firma()
        if firma != self._firma_nodos:
            self._firma_nodos = firma
            # Esto sí lo ha provocado el usuario enchufando algo, así que
            # decirlo tiene sentido.
            self.statusBar().showMessage("Ha cambiado un dispositivo…", 4000)
            self._rescan.start()          # reinicia la espera si llegan más
            return

        # Cada 5 ciclos (4 s) se relee la batería del ratón que se está viendo.
        # Además de mantener el porcentaje al día, es la única forma de notar
        # que el ratón se ha apagado con su interruptor: eso no quita ningún
        # nodo del sistema, así que la vigilancia de arriba no lo ve. No se
        # puede escuchar la notificación que manda el ratón porque el canal se
        # abre sólo durante cada petición, y eso es a propósito.
        self._ciclos += 1
        if self._ciclos % 5:
            return
        pagina = self.pila.currentWidget()
        if isinstance(pagina, PaginaRaton):
            if not pagina.refrescar_bateria():
                # El demonio consulta el ratón cada cinco segundos y nosotros
                # cada cuatro: alguna petición se pierde de vez en cuando. Un
                # fallo suelto no significa que el ratón se haya ido, y
                # rescanear por él llenaba la barra de estado de mensajes.
                self._fallos += 1
                if self._fallos >= 2:
                    self._fallos = 0
                    self.escanear(silencioso=True)
                return
            self._fallos = 0
            # El demonio puede haber cambiado de perfil, o el ratón haber
            # vuelto a los suyos al despertarse: que se vea.
            pagina.refrescar_ajustes()
            return

        # Sin ningún ratón HID++ a la vista. Hay que seguir mirando: encender
        # el ratón con su interruptor no crea ningún nodo, y al enchufar el
        # receptor el nodo aparece antes de que el enlace esté listo, así que
        # el escaneo de hace un momento pudo llegar demasiado pronto. Sin este
        # reintento habría que pulsar "Volver a escanear" a mano.
        if not (self.hallazgo and self.hallazgo.ratones) and self._hay_logitech():
            self.escanear(silencioso=True)

    @staticmethod
    def _hay_logitech() -> bool:
        """¿Hay algún nodo Logitech con canal HID++? Mirar sysfs, sin hablar
        con el dispositivo: así el reintento no cuesta nada cuando no hay nada
        que encontrar."""
        from ..transport import enumerate_nodes
        try:
            return any(n.hidpp and n.is_logitech for n in enumerate_nodes())
        except Exception:
            return False

    # -- escaneo --------------------------------------------------------------

    def escanear(self, silencioso: bool = False) -> None:
        """Vuelve a mirar qué hay conectado.

        `processEvents` de más abajo deja correr el temporizador de vigilancia,
        que llamaría aquí otra vez y se llevaría por delante los objetos que
        este escaneo está construyendo.

        Los escaneos automáticos van en silencio: enseñar "Buscando
        dispositivos…" cada pocos segundos, sin que nadie lo haya pedido, hace
        pensar que el programa está haciendo algo raro.
        """
        if self._escaneando:
            return
        self._escaneando = True
        try:
            if silencioso:
                self._escanear()
            else:
                with _ocupado(self, "Buscando dispositivos…"):
                    self._escanear()
        finally:
            self._escaneando = False

    def _escanear(self) -> None:
        self.statusBar().showMessage("Buscando dispositivos…")

        # Tras un reescaneo hay páginas nuevas: sin esto, la selección salta al
        # primer dispositivo cada vez que alguien enciende un teclado.
        anterior = None
        item = self.lista.currentItem()
        if item is not None:
            anterior = item.data(ROL_SUB)
        ids_antes = {m.id_str for m in self.hallazgo.ratones} if self.hallazgo else set()
        self._firma_nodos = self._firma()
        QApplication.processEvents()

        if self.hallazgo:
            for r in self.hallazgo.ratones:
                r.close()

        # Escaneamos cada vez que cambia un nodo, o sea justo cuando alguien
        # está enchufando o desenchufando algo: los nodos desaparecen a media
        # lectura. Un fallo aquí no puede llevarse la ventana por delante.
        error = None
        try:
            self.hallazgo = discover()
        except Exception as e:
            self.hallazgo = Discovery()
            error = str(e)
        try:
            punteros = desktop.listar_punteros()
        except Exception:
            punteros = []

        if self.demo:
            # Ratón inventado, para trabajar en la interfaz sin hardware.
            from ..mock import raton_simulado
            self.hallazgo.ratones.append(raton_simulado())

        # Los ratones HID++ ya tienen su propia entrada; no los repetimos abajo.
        # Hace falta comparar también por nombre: por receptor, HID++ ve el
        # VID:PID del receptor y KWin el del ratón emparejado, y no coinciden.
        ids_hidpp = {(m.node.vid, m.node.pid) for m in self.hallazgo.ratones}
        nombres_hidpp = [m.nombre for m in self.hallazgo.ratones]

        def ya_esta_arriba(info) -> bool:
            if (info.vid, info.pid) in ids_hidpp:
                return True
            return any(desktop.mismo_aparato(n, info.nombre)
                       for n in nombres_hidpp)

        candidatos = [(p, p.info()) for p in punteros]
        otros = [p for p, i in candidatos
                 if not ya_esta_arriba(i)
                 and i.soporta_aceleracion and not i.es_de_teclado]
        teclados = [p for p, i in candidatos
                    if not ya_esta_arriba(i)
                    and i.soporta_aceleracion and i.es_de_teclado]

        self.lista.clear()
        while self.pila.count() > 1:
            w = self.pila.widget(1)
            self.pila.removeWidget(w)
            w.deleteLater()

        if self.hallazgo.ratones:
            self._encabezado("Compatibles")
            for raton in self.hallazgo.ratones:
                pagina = PaginaRaton(raton, demo=self.demo)
                self.pila.addWidget(pagina)
                self._entrada(raton.nombre, raton.id_str, pagina)

        if otros:
            self._encabezado("Otros punteros")
            for p in otros:
                info = p.info()
                pagina = PaginaPuntero(p)
                self.pila.addWidget(pagina)
                self._entrada(info.nombre, info.id_str, pagina)

        if teclados:
            self._encabezado("Teclados que emulan ratón")
            for p in teclados:
                info = p.info()
                pagina = PaginaPuntero(p)
                self.pila.addWidget(pagina)
                self._entrada(info.nombre, info.id_str, pagina)

        self._actualizar_vacio(error)
        if self.lista.count():
            # Volver al mismo dispositivo que estaba seleccionado; si ya no
            # está (lo han desconectado), al primero que sirva.
            fila = None
            for i in range(self.lista.count()):
                item = self.lista.item(i)
                if item.data(ROL_DATOS) is None:
                    continue
                if fila is None:
                    fila = i
                if anterior is not None and item.data(ROL_SUB) == anterior:
                    fila = i
                    break
            if fila is not None:
                self.lista.setCurrentRow(fila)
        self._ajustar_alto_lista()
        self._reaplicar_por_defecto(ids_antes)
        self.statusBar().showMessage(
            f"{len(self.hallazgo.ratones)} ratón(es) HID++ · "
            f"{len(otros)} puntero(s) genérico(s) · "
            f"{len(teclados)} teclado(s) con emulación · "
            f"{len(self.hallazgo.sin_permiso)} sin permiso")

    def _reaplicar_por_defecto(self, ids_antes: set[str]) -> None:
        """Reaplica el perfil por defecto a los ratones que acaban de volver.

        En modo host el ratón NO guarda nada: al apagarlo y encenderlo vuelve a
        los valores de su perfil interno. Es el mismo trabajo que hace el
        demonio cuando detecta una conexión; aquí sirve para quien use sólo la
        interfaz. Se hace también al arrancar: marcar un perfil "por defecto" es
        decir "esto es lo que quiero tener puesto", así que abrir el programa y
        encontrarse otra cosa desconcierta.
        """
        vuelven = [m for m in self.hallazgo.ratones if m.id_str not in ids_antes]
        if not vuelven:
            return
        try:
            almacen = Almacen(demo=self.demo)
            almacen.cargar()
            perfil = almacen.por_defecto()
        except Exception:
            return
        if perfil is None:
            return
        for raton in vuelven:
            try:
                if Motor(raton).aplicar(perfil):
                    self.statusBar().showMessage(
                        f"«{perfil.nombre}» reaplicado a {raton.nombre} "
                        "tras reconectarse")
                    QApplication.processEvents()
            except Exception:
                continue

    def _ajustar_alto_lista(self) -> None:
        """La lista ocupa lo que ocupan sus entradas, no todo el panel.

        Con dos dispositivos, una lista a pantalla completa deja un vacío
        enorme debajo y el panel parece roto.
        """
        alto = sum(self.lista.sizeHintForRow(i)
                   for i in range(self.lista.count())) + 8
        self.lista.setFixedHeight(min(alto, 460))

    def _encabezado(self, texto: str) -> None:
        item = QListWidgetItem(texto)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(ROL_ENCABEZADO, True)
        self.lista.addItem(item)

    def _entrada(self, titulo: str, sub: str, pagina: QWidget) -> None:
        item = QListWidgetItem(titulo)
        item.setData(ROL_SUB, sub)
        item.setData(ROL_DATOS, pagina)
        item.setToolTip(f"{titulo} — {sub}")
        self.lista.addItem(item)

    def _seleccion(self, actual: QListWidgetItem | None, _previo=None) -> None:
        if actual is None:
            return
        pagina = actual.data(ROL_DATOS)
        if pagina is not None:
            self.pila.setCurrentWidget(pagina)

    def _actualizar_vacio(self, error: str | None = None) -> None:
        h = self.hallazgo
        if error:
            self.vacia.poner_detalle(
                f"El escaneo falló: {error}\n\n"
                "Si acabas de conectar o desconectar algo, vuelve a intentarlo.")
            return
        if h and h.sin_permiso:
            rutas = ", ".join(n.path for n in h.sin_permiso)
            self.vacia.poner_detalle(
                f"Se han encontrado dispositivos Logitech con canal HID++ ({rutas}) "
                "pero no hay permiso para abrirlos.\n\n"
                "Hace falta la regla udev. Si instalaste gpx2 con un paquete, ya "
                "viene incluida y basta con reconectar el dispositivo. Si lo "
                "tienes desde el repositorio:\n\n"
                "sudo cp 99-logitech-hidpp.rules /etc/udev/rules.d/ && "
                "sudo udevadm control --reload-rules && sudo udevadm trigger")
        elif h and not h.ratones:
            self.vacia.poner_detalle(
                "No hay ningún dispositivo Logitech que exponga el canal HID++.\n\n"
                "Conecta el ratón por cable USB o enchufa su receptor Lightspeed "
                "y vuelve a escanear. Los ratones genéricos aparecen igualmente "
                "en la lista, pero sólo permiten ajustar la sensibilidad de Plasma.")
        if not self.lista.count():
            self.pila.setCurrentWidget(self.vacia)

    def _alternar_lateral(self) -> None:
        self.lateral.setVisible(not self.lateral.isVisible())

    def closeEvent(self, evento):
        if self.hallazgo:
            for r in self.hallazgo.ratones:
                r.close()
        super().closeEvent(evento)


APP_ID = "io.github.rcv11x.gpx2"


def _icono() -> QIcon:
    """El icono del proyecto. Primero el instalado en el sistema; si no, el
    del repositorio (para ejecutar sin instalar)."""
    from pathlib import Path
    icono = QIcon.fromTheme(APP_ID)
    if not icono.isNull():
        return icono
    local = Path(__file__).resolve().parents[2] / "data" / "gpx2.svg"
    return QIcon(str(local)) if local.exists() else QIcon()


def _qt_msg_handler(mode, _ctx, message):
    import sys
    # El splitter de XCB intenta capturar el ratón y Qt avisa; es inofensivo.
    if "grabbing the mouse only for popup" in message:
        return
    print(message, file=sys.stderr)

qInstallMessageHandler(_qt_msg_handler)


def main(demo: bool = False) -> int:
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("gpx2")
    app.setApplicationDisplayName("gpx2")
    # En Wayland el icono de la barra de tareas NO sale de la ventana: el
    # compositor lo busca en el .desktop cuyo nombre coincida con este app_id.
    # Sin esto sale el logo genérico de Wayland.
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(_icono())
    app.setStyleSheet(hoja_de_estilo(app.palette()))
    ventana = VentanaPrincipal(demo=demo)
    ventana.show()
    return app.exec()
