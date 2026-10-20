"""Préparation des tests : le module démarre sa boucle à l'import, on la fait parler
à un détecteur injoignable pour qu'elle ne déclenche rien pendant les tests."""

import os
import sys

os.environ.setdefault("DETECTOR_URL", "http://127.0.0.1:9")
os.environ.setdefault("API_URL", "http://127.0.0.1:9/api")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
