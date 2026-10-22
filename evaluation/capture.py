"""Capture le score du détecteur chaque seconde dans un CSV, avec un horodatage."""
import time, csv, requests

DUREE = 150  # secondes de capture
URL = "http://localhost:8001/score"

with open("capture_scores.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["t", "score", "over"])
    print("Capture démarrée (Ctrl+C pour arrêter)...")
    for i in range(DUREE):
        try:
            d = requests.get(URL, timeout=2).json()
            score = d.get("current")
            over = 1 if d.get("over") else 0
            w.writerow([round(time.time(), 1), score, over])
            f.flush()
            print(f"t={i:3d}s  score={score}  over={over}")
        except Exception as e:
            print("erreur:", e)
        time.sleep(1)
print("Capture terminée -> capture_scores.csv")
