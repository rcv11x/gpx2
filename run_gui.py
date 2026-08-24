#!/usr/bin/env python3
"""Lanzador de la interfaz gráfica de gpx2.

    ./run_gui.py           usa los ratones reales del sistema
    ./run_gui.py --demo    añade un G Pro X Superlight 2 simulado
"""
import sys
from gpx2.gui.main_window import main

if __name__ == "__main__":
    sys.exit(main(demo="--demo" in sys.argv))
