"""
Évaluation du détecteur d'anomalies sur données réelles.
Compare les scores capturés à la vérité terrain (fenêtre d'attaque),
calcule Precision, Recall, F1, AUC-ROC, délai de détection, et trace la courbe.
"""
import pandas as pd
import numpy as np
from sklearn.metrics import (precision_score, recall_score, f1_score,
                             roc_auc_score, confusion_matrix)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- Vérité terrain (timestamps de l'attaque réelle) ---
ATTACK_START = 1792500720.7
ATTACK_END   = 1792500767.4
THRESHOLD = 0.55

df = pd.read_csv("capture_scores.csv")
# label réel : 1 si la seconde tombe dans la fenêtre d'attaque, 0 sinon
df["attaque_reelle"] = ((df["t"] >= ATTACK_START) & (df["t"] <= ATTACK_END)).astype(int)

y_true = df["attaque_reelle"].values
y_pred = df["over"].values          # le verdict du détecteur
scores = df["score"].values

# --- Métriques ---
precision = precision_score(y_true, y_pred, zero_division=0)
recall    = recall_score(y_true, y_pred, zero_division=0)
f1        = f1_score(y_true, y_pred, zero_division=0)
auc       = roc_auc_score(y_true, scores)

print("=== ÉVALUATION DU DÉTECTEUR (données réelles) ===\n")
print(f"Seuil de décision      : {THRESHOLD}")
print(f"Durée de l'attaque     : {ATTACK_END - ATTACK_START:.0f} s")
print(f"Secondes capturées     : {len(df)}")
print(f"  dont sous attaque    : {y_true.sum()}\n")
print(f"Precision              : {precision:.3f}")
print(f"Recall (sensibilité)   : {recall:.3f}")
print(f"F1-score               : {f1:.3f}")
print(f"AUC-ROC                : {auc:.3f}\n")

tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
print("Matrice de confusion :")
print(f"  Vrais négatifs (normal OK)      : {tn}")
print(f"  Faux positifs  (fausse alerte)  : {fp}")
print(f"  Faux négatifs  (attaque ratée)  : {fn}")
print(f"  Vrais positifs (attaque vue)    : {tp}\n")

# --- Délai de détection ---
sous_attaque = df[df["attaque_reelle"] == 1]
detectees = sous_attaque[sous_attaque["over"] == 1]
if len(detectees):
    delai = detectees["t"].iloc[0] - ATTACK_START
    print(f"Délai de détection     : {delai:.0f} secondes")
else:
    print("Attaque non détectée par le verdict 'over'.")

# --- Graphique ---
t0 = df["t"].iloc[0]
temps = df["t"] - t0
plt.figure(figsize=(12, 5))
plt.plot(temps, df["score"], label="Score d'anomalie", color="#2563eb", linewidth=1.5)
plt.axhline(THRESHOLD, color="#dc2626", linestyle="--", label=f"Seuil ({THRESHOLD})")
plt.axvspan(ATTACK_START - t0, ATTACK_END - t0, alpha=0.15, color="red", label="Attaque réelle")
plt.xlabel("Temps (s)")
plt.ylabel("Score d'anomalie")
plt.title("Détection d'anomalie — score au cours du temps")
plt.legend()
plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("evaluation_courbe.png", dpi=130)
print("\nGraphique enregistré -> evaluation_courbe.png")
