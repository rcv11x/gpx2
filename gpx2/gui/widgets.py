# -*- coding: utf-8 -*-
"""Piezas reutilizables de la interfaz."""

from __future__ import annotations

from PySide6.QtCore import (QEvent, QObject, QPointF, QRect, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QIcon, QPainter, QPixmap,
                           QPainterPath, QPalette, QPen)
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox,
                               QFrame, QHBoxLayout, QLabel,
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
        # Lo que ocupe el texto, no un ancho fijo: "Resolución" mide 61 px y
        # reservaba 150, así que quedaba un pasillo vacío entre el rótulo y la
        # barra. El mínimo es para que dos filas seguidas no bailen.
        self.lbl.setMinimumWidth(
            max(96, self.lbl.fontMetrics().horizontalAdvance(etiqueta) + 16))
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
        # Lo que ocupe el texto, no un ancho fijo: "Resolución" mide 61 px y
        # reservaba 150, así que quedaba un pasillo vacío entre el rótulo y la
        # barra. El mínimo es para que dos filas seguidas no bailen.
        self.lbl.setMinimumWidth(
            max(96, self.lbl.fontMetrics().horizontalAdvance(etiqueta) + 16))
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

    # Dónde está cada botón sobre el cuerpo (x, y) y de qué lado sale su
    # etiqueta. Los cinco primeros son la disposición de casi cualquier ratón
    # diestro; el sexto, el botón de DPI detrás de la rueda, que también es
    # donde lo pone casi todo el mundo.
    #             x     y    lado
    SITIOS = [
        (0.28, 0.15, "izquierda"),      # clic izquierdo
        (0.72, 0.15, "derecha"),        # clic derecho
        (0.50, 0.20, "derecha"),        # central / rueda
        (0.05, 0.34, "izquierda"),      # lateral trasero
        (0.05, 0.45, "izquierda"),      # lateral delantero
        (0.50, 0.31, "derecha"),        # detrás de la rueda: DPI
    ]

    # A partir del séptimo ya no sabemos dónde está cada uno: un G502 y un
    # ratón de MMO no los ponen en el mismo sitio, y el ratón no dice dónde
    # tiene nada. Se reparten por el lateral del pulgar, que es donde suelen
    # ir, y el dibujo no pretende ser un plano: es un esquema para saber qué
    # hace cada botón, no para reconocerlo a ciegas.
    EXTRA_X = 0.05
    EXTRA_DESDE, EXTRA_HASTA = 0.55, 0.80

    # Palabras que dicen dónde cae físicamente un botón del lateral. El orden
    # del perfil no lo dice: en el PRO X 2 el índice 3 es "Atrás" y el 4
    # "Adelante", y el dibujo los ponía en ese orden de arriba abajo, o sea
    # justo al revés de donde están en el ratón. Quien busca el botón de atrás
    # lo busca detrás.
    DELANTEROS = ("adelante", "avanzar", "forward")
    TRASEROS = ("atrás", "atras", "retroceder", "back")

    def _ordenar_laterales(self, sitios):
        """Coloca los botones del lateral donde caen de verdad en la mano."""
        laterales = [i for i, (x, _, _) in enumerate(sitios)
                     if x <= 0.10 and i < len(self.acciones)]
        if len(laterales) < 2:
            return sitios
        alturas = sorted(sitios[i][1] for i in laterales)

        def peso(i: int) -> int:
            accion = self.acciones[i].lower()
            if any(p in accion for p in self.DELANTEROS):
                return 0                      # los de avanzar, delante
            if any(p in accion for p in self.TRASEROS):
                return 2                      # los de retroceder, detrás
            return 1

        # A igualdad, se respeta el orden del perfil.
        orden = sorted(laterales, key=lambda i: (peso(i), i))
        sitios = list(sitios)
        for altura, i in zip(alturas, orden):
            x, _, lado = sitios[i]
            sitios[i] = (x, altura, lado)
        return sitios

    def _sitios(self) -> list[tuple[float, float, str]]:
        """Los sitios de los botones que haya, sean cinco o quince."""
        n = len(self.acciones)
        if n <= len(self.SITIOS):
            return self._ordenar_laterales(self.SITIOS[:n])
        sitios = list(self.SITIOS)
        sobran = n - len(self.SITIOS)
        for i in range(sobran):
            # Repartidos a lo largo del lateral, sin amontonarse aunque sean
            # muchos: con uno solo va en medio del tramo.
            t = (i + 1) / (sobran + 1)
            y = self.EXTRA_DESDE + (self.EXTRA_HASTA - self.EXTRA_DESDE) * t
            sitios.append((self.EXTRA_X, y, "izquierda"))
        return self._ordenar_laterales(sitios)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.acciones: list[str] = []
        self.resaltado: int | None = None
        self.imagen: QPixmap | None = None
        self.setMinimumHeight(360)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def poner_imagen(self, id_str: str) -> bool:
        """Usa la foto que el usuario haya dejado para este ratón, si la hay.

        El proyecto no trae fotos de fabricante —no son nuestras, y esto es
        MIT—, pero cada uno puede poner la suya en su máquina. Los puntos de
        los botones siguen siendo los del esquema genérico, así que sobre una
        foto quedan aproximados: se dibujan igual porque lo que importa es
        saber qué botón es cuál, y para eso basta con la guía y el número.
        """
        ruta = ruta_imagen_propia(id_str)
        if ruta is None:
            self.imagen = None
            return False
        px = QPixmap(str(ruta))
        self.imagen = None if px.isNull() else px
        self.update()
        return self.imagen is not None

    def poner(self, acciones: list[str]) -> None:
        self.acciones = list(acciones)
        # Con muchos botones las etiquetas piden más sitio del que ocupa el
        # dibujo: si no, se salen por abajo o se aprietan hasta tocarse. Manda
        # el lado más cargado, no la mitad del total: los que no caben en la
        # anatomía conocida van todos al lateral, así que los lados no se
        # reparten a partes iguales ni de lejos.
        sitios = self._sitios()
        peor = max((sum(1 for _, _, l in sitios if l == lado)
                    for lado in ("izquierda", "derecha")), default=1)
        self.setMinimumHeight(max(360, peor * (self.ALTO_ETIQUETA + 6) + 60))
        self.update()

    # -- geometría ------------------------------------------------------------

    ALTO_MAXIMO_CUERPO = 420

    def _cuerpo(self) -> QRectF:
        """El contorno del ratón, centrado y dejando sitio a las etiquetas.

        Con un tope: un ratón de doce botones necesita mucho alto para sus
        etiquetas, pero el dibujo tiene que seguir pareciendo un ratón. Sin
        esto se estiraba hasta llenar el widget y acababa siendo un óvalo
        gigante con los textos pegados a los lados.
        """
        alto = min(self.height() - 24, self.ALTO_MAXIMO_CUERPO)
        ancho = alto * 0.62
        arriba = max(12, (self.height() - alto) / 2)
        return QRectF((self.width() - ancho) / 2, arriba, ancho, alto)

    def _punto(self, i: int) -> QPointF:
        c = self._cuerpo()
        sitios = self._sitios()
        if i >= len(sitios):
            return QPointF(c.center().x(), c.center().y())
        x, y, _ = sitios[i]
        return QPointF(c.left() + c.width() * x, c.top() + c.height() * y)

    ALTO_ETIQUETA = 26

    def _alturas(self) -> dict[int, float]:
        """A qué altura va la etiqueta de cada botón, en píxeles.

        No se puede usar la del punto: el clic derecho y la rueda están casi
        juntos y sus textos se pisarían, y con muchos botones se pisarían casi
        todos. Se reparten por lado, en orden y equiespaciadas, y la línea
        guía se encarga de unir cada texto con su botón.
        """
        c = self._cuerpo()
        alturas: dict[int, float] = {}
        sitios = self._sitios()
        for lado in ("izquierda", "derecha"):
            # En orden de arriba abajo, para que las guías no se crucen.
            ids = [i for i, (_, _, l) in enumerate(sitios) if l == lado]
            ids.sort(key=lambda i: sitios[i][1])
            if not ids:
                continue
            hueco = self.ALTO_ETIQUETA + 6
            alto_total = hueco * len(ids)
            # Se reparten sobre el widget entero, no sobre el cuerpo: cuando
            # hay más etiquetas que sitio en el dibujo, el que sobra está
            # fuera de él.
            if alto_total <= c.height():
                arriba = c.top() + (c.height() - alto_total) * 0.28
            else:
                arriba = max(4, (self.height() - alto_total) / 2)
            for orden, i in enumerate(ids):
                alturas[i] = arriba + hueco * orden + hueco / 2
        return alturas

    def _zona_etiqueta(self, i: int) -> QRectF:
        c = self._cuerpo()
        sitios = self._sitios()
        if i >= len(sitios):
            return QRectF()
        lado = sitios[i][2]
        cy = self._alturas().get(i, c.center().y()) - self.ALTO_ETIQUETA / 2
        margen = 12
        if lado == "izquierda":
            return QRectF(margen, cy, c.left() - margen * 2, self.ALTO_ETIQUETA)
        return QRectF(c.right() + margen, cy,
                      self.width() - c.right() - margen * 2, self.ALTO_ETIQUETA)

    # -- pintado --------------------------------------------------------------

    def paintEvent(self, evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        texto = pal.color(QPalette.ColorRole.WindowText)
        realce = pal.color(QPalette.ColorRole.Highlight)
        linea = mezclar(pal.color(QPalette.ColorRole.Window), texto, 0.35)

        c = self._cuerpo()

        if self.imagen is not None:
            # La foto del usuario, encajada en el hueco del cuerpo y sin
            # deformarla. El resto —guías, puntos y etiquetas— se pinta encima
            # igual que sobre el dibujo.
            escalada = self.imagen.scaled(
                int(c.width()), int(c.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(c.center().x() - escalada.width() / 2),
                         int(c.center().y() - escalada.height() / 2),
                         escalada)
            self._pintar_guias(p, texto, realce, linea)
            p.end()
            return

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

        # Los botones del lateral: todos los que caen sobre el borde, sean los
        # dos de siempre o los siete de un ratón de MMO.
        sitios = self._sitios()
        p.setBrush(mezclar(pal.color(QPalette.ColorRole.Window), texto, 0.18))
        for i, (x, _, _) in enumerate(sitios[:len(self.acciones)]):
            if x > 0.10:
                continue
            pt = self._punto(i)
            lateral = QRectF(pt.x() - c.width() * 0.015, pt.y() - c.height() * 0.030,
                             c.width() * 0.07, c.height() * 0.06)
            p.drawRoundedRect(lateral, 3, 3)

        # Y el de detrás de la rueda, si el ratón lo tiene.
        if len(self.acciones) > 5:
            pt = self._punto(5)
            p.drawRoundedRect(QRectF(pt.x() - c.width() * 0.035,
                                     pt.y() - c.height() * 0.018,
                                     c.width() * 0.07, c.height() * 0.036), 3, 3)

        self._pintar_guias(p, texto, realce, linea)
        p.end()

    def _pintar_guias(self, p, texto, realce, linea) -> None:
        """Las líneas y los rótulos, iguales sobre el dibujo y sobre una foto."""
        c = self._cuerpo()
        sitios = self._sitios()
        fuente = QFont(self.font())
        fuente.setPointSizeF(max(8.0, fuente.pointSizeF() - 0.5))
        p.setFont(fuente)
        for i, accion in enumerate(self.acciones):
            activo = i == self.resaltado
            color = realce if activo else linea
            pt = self._punto(i)
            zona = self._zona_etiqueta(i)
            lado = sitios[i][2]
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

    # -- interacción ----------------------------------------------------------

    def _cerca_de(self, pos) -> int | None:
        for i in range(len(self.acciones)):
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


class RuedaSoloConFoco(QObject):
    """Impide que la rueda cambie un control por el que sólo estás pasando.

    Qt deja que la rueda mueva un desplegable, un contador o una barra aunque
    no tengan el foco. Dentro de una ventana con scroll eso es una trampa: vas
    a bajar por la página, el puntero cruza por encima de un desplegable y le
    cambias el DPI sin enterarte. Y como la rueda del ratón ES lo que estás
    configurando, es especialmente fácil de hacer.

    Con esto, esos controles sólo responden a la rueda si antes has hecho clic
    en ellos. El evento se deja pasar al padre, así que la página sigue
    haciendo scroll como si el control no estuviera.
    """

    VIGILADOS = (QComboBox, QAbstractSpinBox, QSlider)

    def eventFilter(self, obj, evento):
        if (evento.type() == QEvent.Type.Wheel
                and isinstance(obj, self.VIGILADOS)
                and not obj.hasFocus()):
            evento.ignore()
            return True
        return False


def proteger_de_la_rueda(app) -> RuedaSoloConFoco:
    """Instala el filtro y deja el foco de forma que no lo dé la rueda.

    Se devuelve para que quien lo llame lo guarde: si se lo lleva el recolector
    de basura, el filtro deja de aplicarse y el fallo vuelve en silencio.
    """
    filtro = RuedaSoloConFoco(app)
    app.installEventFilter(filtro)
    return filtro


def carpeta_imagenes():
    """Donde el usuario puede dejar la foto de su ratón.

    El proyecto no trae fotos de ningún fabricante: son suyas, y este
    repositorio es MIT. Pero cada uno puede poner en su propia máquina la que
    quiera, y eso es asunto suyo. Basta con dejar aquí un PNG llamado como el
    identificador del dispositivo, `046d_c54d.png`, y se usará en su lugar.
    """
    from pathlib import Path
    import os
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "gpx2" / "imagenes"


def ruta_imagen_propia(id_str: str):
    """El fichero que el usuario haya dejado para este dispositivo, si hay."""
    if not id_str:
        return None
    nombre = id_str.replace(":", "_").lower()
    for extension in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        ruta = carpeta_imagenes() / f"{nombre}{extension}"
        if ruta.is_file():
            return ruta
    return None


def imagen_propia(id_str: str) -> QIcon | None:
    """La imagen del usuario como icono, si la hay y se puede leer."""
    ruta = ruta_imagen_propia(id_str)
    if ruta is None:
        return None
    ico = QIcon(str(ruta))
    return ico if not ico.isNull() else None


def icono_dispositivo(id_str: str, tipo: str = "raton") -> QIcon:
    """El icono de una entrada de la lista lateral.

    Primero la imagen que haya puesto el usuario; si no, el icono del tema,
    que en Plasma sale de Breeze y en otro escritorio del suyo.
    """
    propia = imagen_propia(id_str)
    if propia is not None:
        return propia
    if tipo == "teclado":
        return icono("input-keyboard", "keyboard")
    if tipo == "puntero":
        return icono("input-mouse-symbolic", "input-mouse", "mouse")
    return icono("input-mouse", "preferences-desktop-mouse", "mouse")


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

    # Si la lista pinta su selección con el color de realce, el texto va del
    # color que le toca encima (blanco en un tema claro). La lista de perfiles
    # NO lo hace —ahí el realce está reservado al perfil que manda, y la
    # selección es un gris suave—, así que allí ese blanco quedaba encima de un
    # #dbdbdb y no se leía.
    usa_realce = True
    LADO_ICONO = 24

    def paint(self, painter, option, index):
        opciones = QStyleOptionViewItem(option)
        self.initStyleOption(opciones, index)
        opciones.text = ""
        opciones.icon = QIcon()     # lo pintamos nosotros, más abajo
        widget = opciones.widget
        estilo = widget.style() if widget else QApplication.style()
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, opciones,
                           painter, widget)

        texto = index.data(Qt.ItemDataRole.DisplayRole) or ""
        sub = index.data(ROL_SUB)
        es_cabecera = bool(index.data(ROL_ENCABEZADO))
        seleccionado = bool(opciones.state & QStyle.StateFlag.State_Selected)

        base = (opciones.palette.highlightedText().color()
                if seleccionado and self.usa_realce
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

        # El icono lo pinta el estilo nativo, pero el texto lo pintamos
        # nosotros: hay que apartarlo o se le echa encima.
        ico = index.data(Qt.ItemDataRole.DecorationRole)
        if ico is not None and not ico.isNull():
            lado = self.LADO_ICONO
            destino = QRect(rect.x(), rect.y() + (rect.height() - lado) // 2,
                            lado, lado)
            modo = (QIcon.Mode.Selected if seleccionado and self.usa_realce
                    else QIcon.Mode.Normal)
            ico.paint(painter, destino, Qt.AlignmentFlag.AlignCenter, modo)
            rect = rect.adjusted(lado + 10, 0, 0, 0)

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
