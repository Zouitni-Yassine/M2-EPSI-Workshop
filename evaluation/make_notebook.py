import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

cells.append(nbf.v4.new_markdown_cell(
"""# Évaluation du détecteur d'anomalies — RESILIENCE-ALPHA

**Domaine IA — validation de la détection d'anomalies**

Ce notebook évalue le détecteur d'anomalies (IsolationForest + distance robuste) sur un **scénario réel** :
trafic normal, puis attaque intense (surcharge + requêtes en erreur) contre l'API de paiement, puis retour au calme.

On compare les scores produits par le détecteur à la **vérité terrain** (la fenêtre d'attaque réelle)
et on calcule Precision, Recall, F1, AUC-ROC, le délai de détection et la matrice de confusion.
"""))

cells.append(nbf.v4.new_code_cell(
"""import pandas as pd
import numpy as np
from sklearn.metrics import (precision_score, recall_score, f1_score,
                             roc_auc_score, confusion_matrix)
import matplotlib.pyplot as plt

ATTACK_START = 1792500720.7
ATTACK_END   = 1792500767.4
THRESHOLD = 0.55

df = pd.read_csv("capture_scores.csv")
df["attaque_reelle"] = ((df["t"] >= ATTACK_START) & (df["t"] <= ATTACK_END)).astype(int)
df.head()"""))

cells.append(nbf.v4.new_markdown_cell(
"""## Métriques de performance"""))

cells.append(nbf.v4.new_code_cell(
"""y_true = df["attaque_reelle"].values
y_pred = df["over"].values
scores = df["score"].values

precision = precision_score(y_true, y_pred, zero_division=0)
recall    = recall_score(y_true, y_pred, zero_division=0)
f1        = f1_score(y_true, y_pred, zero_division=0)
auc       = roc_auc_score(y_true, scores)

print(f"Precision : {precision:.3f}")
print(f"Recall    : {recall:.3f}")
print(f"F1-score  : {f1:.3f}")
print(f"AUC-ROC   : {auc:.3f}")"""))

cells.append(nbf.v4.new_markdown_cell("""## Matrice de confusion et délai de détection"""))

cells.append(nbf.v4.new_code_cell(
"""tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
print("Matrice de confusion :")
print(f"  Vrais negatifs (normal OK)     : {tn}")
print(f"  Faux positifs  (fausse alerte) : {fp}")
print(f"  Faux negatifs  (attaque ratee) : {fn}")
print(f"  Vrais positifs (attaque vue)   : {tp}")

sous_attaque = df[df["attaque_reelle"] == 1]
detectees = sous_attaque[sous_attaque["over"] == 1]
if len(detectees):
    delai = detectees["t"].iloc[0] - ATTACK_START
    print(f"\\nDelai de detection : {delai:.0f} secondes")"""))

cells.append(nbf.v4.new_markdown_cell(
"""## Visualisation : score au cours du temps

Zone rouge = attaque réelle ; ligne pointillée = seuil de décision (0.55)."""))

cells.append(nbf.v4.new_code_cell(
"""t0 = df["t"].iloc[0]
temps = df["t"] - t0

plt.figure(figsize=(12, 5))
plt.plot(temps, df["score"], label="Score d'anomalie", color="#2563eb", linewidth=1.5)
plt.axhline(THRESHOLD, color="#dc2626", linestyle="--", label=f"Seuil ({THRESHOLD})")
plt.axvspan(ATTACK_START - t0, ATTACK_END - t0, alpha=0.15, color="red", label="Attaque reelle")
plt.xlabel("Temps (s)")
plt.ylabel("Score d'anomalie")
plt.title("Detection d'anomalie - score au cours du temps")
plt.legend()
plt.grid(alpha=0.3)
plt.tight_layout()
plt.show()"""))

cells.append(nbf.v4.new_markdown_cell(
"""## Interprétation et limites

- **Recall élevé** : le détecteur capte la quasi-totalité de l'attaque.
- **Faux positifs** : juste après l'attaque, le temps que le score redescende sous le seuil.
- **Faux négatifs** : les premières secondes, le temps que la persistance (3 points) se confirme — c'est le délai de détection.
- **Pistes** : ajuster le seuil/la persistance selon le compromis sensibilité/fausses alertes ; ajouter CPU/RAM (cAdvisor).
"""))

nb["cells"] = cells
with open("evaluation_detecteur.ipynb", "w") as f:
    nbf.write(nb, f)
print("Notebook cree -> evaluation_detecteur.ipynb")
