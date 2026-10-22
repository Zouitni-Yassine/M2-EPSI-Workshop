# Évaluation du détecteur d'anomalies — Domaine IA

Validation du détecteur (`detector/`) sur un scénario réel : trafic normal,
attaque intense contre l'API de paiement, puis retour au calme.

## Contenu
- `capture.py` — capture le score du détecteur chaque seconde dans un CSV
- `attaque.py` — génère le scénario de trafic + l'attaque (surcharge + requêtes en erreur)
- `capture_scores.csv` — scores capturés pendant le scénario
- `evaluate.py` / `evaluation_detecteur.ipynb` — calcul des métriques + graphique
- `evaluation_courbe.png` — score au cours du temps

## Résultats (données réelles, warmup 120 s)
| Métrique | Valeur |
| --- | --- |
| Precision | 0.811 |
| Recall | 0.915 |
| F1-score | 0.860 |
| AUC-ROC | 0.922 |
| Délai de détection | 4 s |

En démonstration, le warmup est réglé à 60 s via Docker Compose (arbitrage rapidité/robustesse).
