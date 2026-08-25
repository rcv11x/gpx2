#!/usr/bin/env python3
"""Lanzador de la interfaz gráfica de gpx2.

    ./run_gui.py           usa los ratones reales del sistema
    ./run_gui.py --demo         añade un G Pro X Superlight 2 simulado
    ./run_gui.py --demo=g203    o un G203 LIGHTSYNC, con luces y seis botones
"""
import sys
from gpx2.gui.main_window import main

if __name__ == "__main__":
    # --demo o --demo=<modelo>; sin modelo, el PRO X 2.
    demo = next((a.split("=", 1)[1] if "=" in a else True
                 for a in sys.argv if a.startswith("--demo")), False)
    sys.exit(main(demo=demo))
