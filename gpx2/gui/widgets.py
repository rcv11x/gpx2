# -*- coding: utf-8 -*-
"""Piezas reutilizables de la interfaz."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QIcon, QPainter,
                           QPainterPath, QPalette, QPen)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QSizePolicy, QSlider, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem,
                               QVBoxLayout, QWidget)


def mezclar(a: QColor, b: QColor, factor: float) -> QColor:
    """Interpola dos colores. Sirve para derivar tonos del tema del sistema
    en vez de fijar colores a mano (así funciona en claro y en oscuro)."""
    f = max(0.0, min(1.0, factor))
    return QColor(round(a.red() * (1 - f) + b.red() * f),
                  round(a.green() * (1 - f) + b.green() * f),
                  round(a.blue() * (1 - f) + b.blue() * f))


def hoja_de_estilo(pal: QPalette) -> str:
    """QSS derivada de la paleta activa de Qt, para integrarse con Breeze."""
    ventana = pal.color(QPalette.ColorRole.Window)
    base = pal.color(QPalette.ColorRole.Base)
    texto = pal.color(QPalette.ColorRole.WindowText)
    realce = pal.color(QPalette.ColorRole.Highlight)
    borde_col = mezclar(ventana, texto, 0.18)
    borde = borde_col.name()
    tarjeta_col = mezclar(base, ventana, 0.35)
    tarjeta = tarjeta_col.name()
    lateral = mezclar(ventana, base, 0.45).name()
    suave = mezclar(ventana, texto, 0.45).name()

    return f"""
    QWidget#Lateral {{ background: {lateral}; }}
    QFrame#Tarjeta {{
        background: {tarjeta};
        border: 1px solid {borde};
        border-radius: 10px;
    }}
    QLabel#TituloTarjeta {{ font-weight: 600; }}
    QLabel#Suave {{ color: {suave}; }}
    QLabel#Titulo {{ font-size: 20pt; font-weight: 600; }}
    QLabel#Pastilla {{
        background: {mezclar(ventana, realce, 0.25).name()};
        border: 1px solid {mezclar(borde_col, realce, 0.35).name()};
        border-radius: 9px;
        padding: 2px 10px;
    }}
    /* El perfil que manda: una pastilla ajustada, no un bloque. */
    QLabel#PastillaPerfil {{
        background: {mezclar(ventana, realce, 0.22).name()};
        border: 1px solid {mezclar(borde_col, realce, 0.45).name()};
        border-radius: 11px;
        padding: 3px 12px;
        font-weight: 600;
    }}
    /* La batería es un dato, no algo que se pulse: sin caja y algo mayor. */
    QLabel#Bateria {{
        font-size: 12pt;
        color: {mezclar(ventana, texto, 0.85).name()};
    }}
    /* Sólo la lista de dispositivos: es la que lleva el delegado con dos
       líneas por entrada. Las demás listas del programa se quedan con el
       estilo nativo, que para una lista normal se ve mejor. */
    QListWidget#ListaDispositivos {{ background: transparent; border: none; }}
    QListWidget#ListaDispositivos::item {{
        padding: 9px 12px; border-radius: 8px; margin: 2px 6px;
    }}
    QListWidget#ListaDispositivos::item:selected {{
        background: {realce.name()};
        color: {pal.color(QPalette.ColorRole.HighlightedText).name()};
    }}
    QTabWidget::pane {{ border: none; }}
    /* Los 18px son los mismos que el margen de las tarjetas y la cabecera:
       sin esto la primera pestaña queda desalineada con todo lo de abajo.
       Tiene que ser `QTabWidget::tab-bar` con `left`: un margin sobre QTabBar
       lo ignora Qt, porque a la barra la coloca el QTabWidget. */
    QTabWidget::tab-bar {{ left: 18px; }}
    QTabBar::tab {{ padding: 7px 16px; margin-right: 4px; border-radius: 7px; }}
    QTabBar::tab:selected {{ background: {mezclar(ventana, realce, 0.30).name()}; }}
    /* Perfiles: la selección se marca en suave, porque el color de realce
       está reservado al perfil que manda. Marcar los dos igual hacía que se
       leyeran como lo mismo. */
    QListWidget#ListaPerfiles {{ background: transparent; border: none; }}
    QListWidget#ListaPerfiles::item {{
        padding: 7px 10px; border-radius: 7px; margin: 1px 2px;
    }}
    QListWidget#ListaPerfiles::item:selected {{
        background: {mezclar(tarjeta_col, texto, 0.14).name()};
        color: {texto.name()};
    }}
    QListWidget#ListaPerfiles::item:hover {{
        background: {mezclar(tarjeta_col, texto, 0.07).name()};
    }}

    /* Atajos de DPI. Hay que dar geometría también al estado normal: en
       cuanto se estila :checked, ese botón pasa a dibujarse por QSS y los
       demás siguen con el estilo nativo, y quedan de distinto tamaño. */
    QPushButton#Nivel {{
        background: {mezclar(tarjeta_col, texto, 0.10).name()};
        border: 1px solid {borde};
        border-radius: 7px;
        padding: 6px 14px;
        min-width: 44px;
    }}
    QPushButton#Nivel:hover {{
        border-color: {mezclar(borde_col, realce, 0.55).name()};
    }}
    QPushButton#Nivel:checked {{
        background: {realce.name()};
        color: {pal.color(QPalette.ColorRole.HighlightedText).name()};
        border-color: {realce.name()};
        font-weight: 600;
    }}
    """


class Tarjeta(QFrame):
    """Un bloque con título y contenido. La unidad visual de toda la app."""

    def __init__(self, titulo: str, subtitulo: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Tarjeta")
        self.setFrameShape(QFrame.Shape.NoFrame)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 16)
        raiz.setSpacing(4)

        if titulo:
            lbl = QLabel(titulo)
            lbl.setObjectName("TituloTarjeta")
            raiz.addWidget(lbl)

        if subtitulo:
            sub = QLabel(subtitulo)
            sub.setObjectName("Suave")
            sub.setWordWrap(True)
            raiz.addWidget(sub)

        raiz.addSpacing(8)
        self.cuerpo = QVBoxLayout()
        self.cuerpo.setSpacing(10)
        raiz.addLayout(self.cuerpo)

    def añadir(self, w: QWidget) -> None:
        # Cualquier etiqueta que entre en una tarjeta se ajusta sola. Si no, un
        # texto largo ensancha la tarjeta y aparece scroll horizontal en toda
        # la ventana.
        if isinstance(w, QLabel):
            w.setWordWrap(True)
        self.cuerpo.addWidget(w)

    def añadir_layout(self, layout) -> None:
        self.cuerpo.addLayout(layout)


class FilaSlider(QWidget):
    """Etiqueta + slider + valor. Emite el valor ya convertido."""

    cambiado = Signal(float)

    def __init__(self, etiqueta: str, minimo: float, maximo: float,
                 paso: float, sufijo: str = "", decimales: int = 0, parent=None):
        super().__init__(parent)
        self._min, self._paso, self._dec = minimo, paso, decimales
        self._sufijo = sufijo

        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(12)

        self.lbl = QLabel(etiqueta)
        self.lbl.setMinimumWidth(150)
        fila.addWidget(self.lbl)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(1, round((maximo - minimo) / paso)))
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        fila.addWidget(self.slider, 1)

        self.valor = QLabel("—")
        self.valor.setMinimumWidth(84)
        self.valor.setAlignment(Qt.AlignmentFlag.AlignRight |
                                Qt.AlignmentFlag.AlignVCenter)
        fuente = QFont(self.valor.font())
        fuente.setStyleHint(QFont.StyleHint.Monospace)
        self.valor.setFont(fuente)
        fila.addWidget(self.valor)

        self.slider.valueChanged.connect(self._al_mover)

    def _real(self, pasos: int) -> float:
        return self._min + pasos * self._paso

    def _al_mover(self, pasos: int) -> None:
        v = self._real(pasos)
        self.valor.setText(f"{v:.{self._dec}f}{self._sufijo}")
        self.cambiado.emit(v)

    def poner(self, valor: float) -> None:
        """Fija el valor sin emitir la señal (para cargar el estado inicial)."""
        self.slider.blockSignals(True)
        self.slider.setValue(round((valor - self._min) / self._paso))
        self.slider.blockSignals(False)
        self.valor.setText(f"{valor:.{self._dec}f}{self._sufijo}")


class FilaSliderLista(QWidget):
    """Etiqueta + slider + valor, pero recorriendo una lista de valores válidos.

    Un paso del deslizador es un valor que el dispositivo admite de verdad, no
    una fracción de un rango lineal. Importa porque los sensores describen su
    resolución en tramos de paso creciente: de 100 a 200 van de uno en uno y de
    32000 a 44000 de 200 en 200. Recorriendo la lista, la precisión cae donde
    deja de notarse y el recorrido entero sigue siendo manejable.
    """

    cambiado = Signal(int)

    def __init__(self, etiqueta: str, valores: list[int], sufijo: str = "",
                 parent=None):
        super().__init__(parent)
        self._valores = list(valores)
        self._sufijo = sufijo

        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(12)

        self.lbl = QLabel(etiqueta)
        self.lbl.setMinimumWidth(150)
        fila.addWidget(self.lbl)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(0, len(self._valores) - 1))
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        fila.addWidget(self.slider, 1)

        self.valor = QLabel("—")
        self.valor.setMinimumWidth(84)
        self.valor.setAlignment(Qt.AlignmentFlag.AlignRight |
                                Qt.AlignmentFlag.AlignVCenter)
        fuente = QFont(self.valor.font())
        fuente.setStyleHint(QFont.StyleHint.Monospace)
        self.valor.setFont(fuente)
        fila.addWidget(self.valor)

        self.slider.valueChanged.connect(self._al_mover)

    def _indice_de(self, valor: int) -> int:
        """El índice del valor válido más cercano al pedido."""
        if not self._valores:
            return 0
        return min(range(len(self._valores)),
                   key=lambda i: abs(self._valores[i] - valor))

    def _al_mover(self, i: int) -> None:
        if not self._valores:
            return
        v = self._valores[i]
        self.valor.setText(f"{v}{self._sufijo}")
        self.cambiado.emit(v)

    def poner(self, valor: int) -> None:
        """Fija el valor sin emitir la señal (para cargar el estado inicial)."""
        if not self._valores:
            return
        i = self._indice_de(valor)
        self.slider.blockSignals(True)
        self.slider.setValue(i)
        self.slider.blockSignals(False)
        self.valor.setText(f"{self._valores[i]}{self._sufijo}")


class DiagramaRaton(QWidget):
    """Esquema de un ratón con lo que hace cada botón, y una guía a su etiqueta.

    Es un dibujo nuestro y genérico, no una foto: no tenemos derechos sobre las
    imágenes de ningún fabricante, y un esquema vale para cualquier modelo y se
    adapta al tema del escritorio. Las posiciones son las de un ratón de cinco
    botones diestro, que es la disposición de casi todos.
    """

    pulsado = Signal(int)

    # Para cada botón: dónde está sobre el cuerpo (x, y), a qué altura va su
    # etiqueta y de qué lado. La etiqueta no va a la altura del punto a
    # propósito: el clic derecho y la rueda están casi juntos y sus textos se
    # pisarían. La línea guía se encarga de unirlos.
    #             x     y   etiqueta  lado
    SITIOS = [
        (0.28, 0.15, 0.10, "izquierda"),    # clic izquierdo
        (0.72, 0.15, 0.10, "derecha"),      # clic derecho
        (0.50, 0.20, 0.32, "derecha"),      # central / rueda
        (0.05, 0.34, 0.36, "izquierda"),    # lateral trasero
        (0.05, 0.45, 0.56, "izquierda"),    # lateral delantero
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.acciones: list[str] = []
        self.resaltado: int | None = None
        self.setMinimumHeight(360)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def poner(self, acciones: list[str]) -> None:
        self.acciones = list(acciones)
        self.update()

    # -- geometría ------------------------------------------------------------

    def _cuerpo(self) -> QRectF:
        """El contorno del ratón, centrado y dejando sitio a las etiquetas."""
        alto = self.height() - 24
        ancho = alto * 0.62
        return QRectF((self.width() - ancho) / 2, 12, ancho, alto)

    def _punto(self, i: int) -> QPointF:
        c = self._cuerpo()
        x, y = self.SITIOS[i][0], self.SITIOS[i][1]
        return QPointF(c.left() + c.width() * x, c.top() + c.height() * y)

    def _zona_etiqueta(self, i: int) -> QRectF:
        c = self._cuerpo()
        y, lado = self.SITIOS[i][2], self.SITIOS[i][3]
        alto = 26
        cy = c.top() + c.height() * y - alto / 2
        margen = 12
        if lado == "izquierda":
            return QRectF(margen, cy, c.left() - margen * 2, alto)
        return QRectF(c.right() + margen, cy,
                      self.width() - c.right() - margen * 2, alto)

    # -- pintado --------------------------------------------------------------

    def paintEvent(self, evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        texto = pal.color(QPalette.ColorRole.WindowText)
        realce = pal.color(QPalette.ColorRole.Highlight)
        linea = mezclar(pal.color(QPalette.ColorRole.Window), texto, 0.35)

        c = self._cuerpo()

        # Cuerpo: un óvalo alargado con la parte de abajo más recta, que es la
        # silueta de un ratón visto desde arriba.
        camino = QPainterPath()
        camino.moveTo(c.center().x(), c.top())
        camino.cubicTo(c.right(), c.top() + c.height() * 0.02,
                       c.right(), c.top() + c.height() * 0.45,
                       c.right() - c.width() * 0.03, c.top() + c.height() * 0.72)
        camino.cubicTo(c.right() - c.width() * 0.06, c.bottom(),
                       c.left() + c.width() * 0.06, c.bottom(),
                       c.left() + c.width() * 0.03, c.top() + c.height() * 0.72)
        camino.cubicTo(c.left(), c.top() + c.height() * 0.45,
                       c.left(), c.top() + c.height() * 0.02,
                       c.center().x(), c.top())
        p.setPen(QPen(linea, 1.6))
        p.setBrush(mezclar(pal.color(QPalette.ColorRole.Window), texto, 0.06))
        p.drawPath(camino)

        # La raya que separa los dos clics principales, y la rueda.
        p.setPen(QPen(linea, 1.2))
        p.drawLine(QPointF(c.center().x(), c.top() + c.height() * 0.02),
                   QPointF(c.center().x(), c.top() + c.height() * 0.34))
        rueda = QRectF(c.center().x() - c.width() * 0.055,
                       c.top() + c.height() * 0.11,
                       c.width() * 0.11, c.height() * 0.13)
        p.setBrush(mezclar(pal.color(QPalette.ColorRole.Window), texto, 0.18))
        p.drawRoundedRect(rueda, rueda.width() / 2, rueda.width() / 2)

        # Los dos laterales.
        for i in (3, 4):
            if i >= len(self.acciones):
                continue
            pt = self._punto(i)
            lateral = QRectF(pt.x() - c.width() * 0.015, pt.y() - c.height() * 0.035,
                             c.width() * 0.07, c.height() * 0.07)
            p.setBrush(mezclar(pal.color(QPalette.ColorRole.Window), texto, 0.18))
            p.drawRoundedRect(lateral, 3, 3)

        # Guías y etiquetas.
        fuente = QFont(self.font())
        fuente.setPointSizeF(max(8.0, fuente.pointSizeF() - 0.5))
        p.setFont(fuente)
        for i, accion in enumerate(self.acciones[:len(self.SITIOS)]):
            activo = i == self.resaltado
            color = realce if activo else linea
            pt = self._punto(i)
            zona = self._zona_etiqueta(i)
            lado = self.SITIOS[i][3]
            # La guía sale del texto HACIA el ratón, con un hueco para no
            # tocarlo: un tramo recto y luego la diagonal hasta el botón.
            hacia = 1 if lado == "izquierda" else -1
            borde = zona.right() if lado == "izquierda" else zona.left()
            anclaje = QPointF(borde + 8 * hacia, zona.center().y())
            codo = QPointF(anclaje.x() + 16 * hacia, anclaje.y())

            p.setPen(QPen(color, 2.0 if activo else 1.2))
            p.drawLine(anclaje, codo)
            p.drawLine(codo, pt)
            p.setBrush(color)
            p.drawEllipse(pt, 3.5, 3.5)

            p.setPen(realce if activo else texto)
            alineacion = (Qt.AlignmentFlag.AlignRight if lado == "izquierda"
                          else Qt.AlignmentFlag.AlignLeft)
            p.drawText(zona, int(alineacion | Qt.AlignmentFlag.AlignVCenter),
                       f"{i + 1}. {accion}")
        p.end()

    # -- interacción ----------------------------------------------------------

    def _cerca_de(self, pos) -> int | None:
        for i in range(min(len(self.acciones), len(self.SITIOS))):
            if self._zona_etiqueta(i).adjusted(-8, -6, 8, 6).contains(pos):
                return i
            pt = self._punto(i)
            if (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 < 18 ** 2:
                return i
        return None

    def mouseMoveEvent(self, evento) -> None:
        i = self._cerca_de(evento.position())
        if i != self.resaltado:
            self.resaltado = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i is not None
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, evento) -> None:
        self.resaltado = None
        self.update()

    def mousePressEvent(self, evento) -> None:
        i = self._cerca_de(evento.position())
        if i is not None:
            self.pulsado.emit(i)


def icono(*nombres: str) -> QIcon:
    """El primer icono del tema que exista, o ninguno.

    Los nombres son los estándar de freedesktop, así que en Plasma salen los
    de Breeze y en otro escritorio los suyos. Se prueban varios porque no
    todos los temas traen los mismos, y si no hay ninguno se devuelve un icono
    vacío: un botón sin icono se ve bien, uno con un hueco no.
    """
    for nombre in nombres:
        ico = QIcon.fromTheme(nombre)
        if not ico.isNull():
            return ico
    return QIcon()


def pastilla(texto: str) -> QLabel:
    lbl = QLabel(texto)
    lbl.setObjectName("Pastilla")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


# ---------------------------------------------------------------------------
# Lista lateral de dispositivos
# ---------------------------------------------------------------------------

ROL_SUB = Qt.ItemDataRole.UserRole + 1
ROL_ENCABEZADO = Qt.ItemDataRole.UserRole + 2


class DelegadoDispositivo(QStyledItemDelegate):
    """Pinta cada entrada como nombre + identificador atenuado, y las
    cabeceras de sección como una etiqueta pequeña."""

    ALTO_ITEM = 50
    ALTO_ENCABEZADO = 30

    def paint(self, painter, option, index):
        opciones = QStyleOptionViewItem(option)
        self.initStyleOption(opciones, index)
        opciones.text = ""
        widget = opciones.widget
        estilo = widget.style() if widget else QApplication.style()
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, opciones,
                           painter, widget)

        texto = index.data(Qt.ItemDataRole.DisplayRole) or ""
        sub = index.data(ROL_SUB)
        es_cabecera = bool(index.data(ROL_ENCABEZADO))
        seleccionado = bool(opciones.state & QStyle.StateFlag.State_Selected)

        base = (opciones.palette.highlightedText().color() if seleccionado
                else opciones.palette.text().color())
        painter.save()

        if es_cabecera:
            f = QFont(opciones.font)
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1.0))
            f.setBold(True)
            atenuado = QColor(base)
            atenuado.setAlphaF(0.55)
            painter.setFont(f)
            painter.setPen(atenuado)
            zona = opciones.rect.adjusted(14, 0, -12, -4)
            fm = painter.fontMetrics()
            painter.drawText(zona,
                             Qt.AlignmentFlag.AlignLeft |
                             Qt.AlignmentFlag.AlignBottom,
                             fm.elidedText(texto.upper(),
                                           Qt.TextElideMode.ElideRight,
                                           zona.width()))
            painter.restore()
            return

        rect = opciones.rect.adjusted(14, 7, -12, -7)
        metrica_ancho = rect.width()

        f = QFont(opciones.font)
        painter.setFont(f)
        painter.setPen(base)
        fm = painter.fontMetrics()
        painter.drawText(QRect(rect.x(), rect.y(), metrica_ancho, fm.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(texto, Qt.TextElideMode.ElideRight, metrica_ancho))

        if sub:
            f2 = QFont(f)
            f2.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
            atenuado = QColor(base)
            atenuado.setAlphaF(0.6)
            painter.setFont(f2)
            painter.setPen(atenuado)
            fm2 = painter.fontMetrics()
            painter.drawText(
                QRect(rect.x(), rect.y() + fm.height() + 1, metrica_ancho, fm2.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                fm2.elidedText(sub, Qt.TextElideMode.ElideRight, metrica_ancho))
        painter.restore()

    def sizeHint(self, option, index):
        alto = (self.ALTO_ENCABEZADO if index.data(ROL_ENCABEZADO)
                else self.ALTO_ITEM)
        return QSize(0, alto)


class ColumnaCentrada(QWidget):
    """Contenedor de ancho fijo y centrado. Evita que los QLabel con ajuste de
    línea calculen mal su altura dentro de un layout centrado."""

    def __init__(self, ancho: int = 540, parent=None):
        super().__init__(parent)
        externo = QHBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.addStretch(1)
        interno = QWidget()
        interno.setFixedWidth(ancho)
        externo.addWidget(interno)
        externo.addStretch(1)
        self.contenido = QVBoxLayout(interno)
        self.contenido.setContentsMargins(0, 0, 0, 0)
        self.contenido.setSpacing(8)
