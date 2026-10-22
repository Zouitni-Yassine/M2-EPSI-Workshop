# Démonstration et clip chrono

Procédure de la démonstration devant le jury (10 min : 5 min de présentation et de démo, puis
5 min de questions) et du **Clip Chrono** (60 s au plus, une seule séquence continue, sans
coupe). Elle s'appuie sur les mesures déjà obtenues (sources en fin de document) ; les temps
notés « estimé » restent à confirmer pendant les répétitions.

> **Règle absolue** : une fois la séquence lancée, **personne ne touche à la plateforme** jusqu'à
> la reprise affichée. Une intervention humaine corrective pendant le live met l'axe remédiation à
> **0/5**. On ne redémarre rien, on ne débannit rien, on ne réinitialise pas le détecteur, on ne
> relance aucun playbook. Si un élément ne réagit pas, on l'explique à l'oral et on bascule sur le
> clip enregistré (§5).

---

## 1. Le scénario de résilience

Le propos de la démonstration est **défensif** : montrer que la plateforme détecte, répare et
contient seule. L'injection de charge sert uniquement de stimulus ; les outils employés font
déjà partie du dépôt, personne n'écrit de nouvelle charge offensive pour la démo.

Deux stimuli possibles, mesurés séparément :

**(a) Rafale sur l'API** — le détecteur voit l'anomalie, le moteur répare.

| Étape | Qui | Délai mesuré | Source |
|---|---|---|---|
| Anomalie confirmée (score ≥ 0,55 pendant 3 s) | détecteur ML | **+4 s** (score 0,88) | test `burst`, 20/10 |
| Redémarrage de `payment-api` par la passerelle `remediate` | moteur | **13,8 s** | test `burst`, 20/10 |
| Paiements de la sonde pendant la rafale | sonde | **0 s** de panne | test `burst`, 20/10 |
| « Service rétabli — 0 intervention humaine » | moteur | estimé +30 à +45 s | à confirmer |

**(b) Tentatives de connexion répétées** — le WAF bannit la source.

| Étape | Qui | Délai mesuré | Source |
|---|---|---|---|
| Règle `WafSourceBruteForce` (≥ 10 échecs `/auth/login` en 2 min) | Loki → Alertmanager → `waf-ban` | — | `waf.md` §5 |
| IP source bannie 15 min (403 sur tout sauf `/healthz`) | `waf-ban` sur le WAF | **27 s** du 1er échec au 1er 403 | `waf.md` §5, 21/10 |

Le scénario (a) illustre l'axe **détection + remédiation** (le plus noté) ; (b) illustre l'axe
**contention au WAF**. Pour un seul clip de 60 s, le scénario (a) est le plus sûr : panne nulle,
reprise visible, chiffres déjà mesurés. Le (b) peut être présenté en complément si le temps le
permet.

Récit pour le jury : *la plateforme détecte seule l'anomalie (IA), répare seule le service
(remédiation), peut bloquer seule la source (WAF), et prouve la reprise par un vrai paiement de
contrôle (sonde).*

**Limites connues, à dire à l'oral** :
- La rafale **par l'URL publique** (NPM → WAF) n'a pas encore été jouée de bout en bout ; le test
  `burst` visait l'adresse virtuelle directement. La première répétition (§6) sert à la valider.
- Le bannissement automatique a été mesuré sur la force brute, pas sur la rafale.

### Disposition des écrans et des postes

Le bannissement frappe **l'adresse IP source**. Le PC attaquant et le PC de présentation ne
doivent donc **pas partager la même IP publique de sortie** : sinon le poste de présentation est
banni lui aussi et l'application publique y répond 403. Idéalement, le PC attaquant sort par un
autre lien (partage de connexion mobile).

Écrans à ouvrir avant de commencer :

| Écran | Contenu |
|---|---|
| Projection principale | Dashboard Grafana **Démo / Remédiation** en plein écran (mode kiosque), rafraîchi toutes les 5 s, fenêtre 15 min |
| Second écran (ou onglet) | L'application publique `https://app.slabreze.fr`, onglet Supervision si l'on est connecté en opérateur |
| PC attaquant | Terminal prêt, commande saisie **mais pas lancée** |

---

## 2. Check-list d'avant passage

Dans l'ordre, 10 min avant la démonstration :

1. **`infra/demo/demo-check.sh`** doit afficher **PRÊT**. Il vérifie en lecture seule : créneaux de
   sauvegarde, quorum Proxmox, HA, Ceph, Vault descellé, 6 nœuds Swarm, réplicas des stacks
   `paiement` et `probe`, adresse virtuelle, API et base, chaîne NPM → WAF (page 200, injection SQL
   403), détecteur prêt, moteur en veille, quota de la passerelle, sonde, aucune alerte active.
2. **Pas de créneau de sauvegarde** dans les 20 min (elles gèlent les VM ~45 s et fausseraient la
   mesure) : **13h00** et **21h00** (PBS), **15h36** (hôte parent). `demo-check.sh` avertit si l'un
   approche. Une sauvegarde sur ceph01 vers 15h36 (heure de Paris) est aussi à éviter.
3. **Quota de la passerelle plein** : `demo-check.sh` signale `aucune action dans les 10 dernières
   minutes`. Sinon, attendre : 10 actions au plus par 10 min et par manager, 60 s entre deux
   actions sur un même service. Après une répétition, patienter 10 min.
4. **Aucune IP bannie** qui gênerait : sur le WAF, `sudo waf-ban list` doit être vide (ou ne
   contenir que des IP sans rapport). Vérifier en particulier que l'IP du PC de présentation n'y
   est pas.
5. **Détecteur prêt** : `detector_ready = 1`. Après un redémarrage, il réapprend la normale
   pendant 60 s ; ne pas démarrer pendant ce temps.
6. **Écrans** ouverts comme au §1.

---

## 3. Clip Chrono : minutage (scénario a)

Objectif : une seule prise, moins de 60 s, sans coupe, qui montre l'attaque, l'anomalie, la
réaction et la reprise. La caméra (ou la capture d'écran) filme la projection du dashboard, avec un
insert du terminal attaquant. Les temps sont indicatifs : la première répétition les cale.

| t (s) | Au PC attaquant | À l'écran (dashboard Démo) |
|---|---|---|
| 0–3 | On lance la rafale (commande du §4) | Bandeau **Paiements OK** (vert), score bas, moteur **EN VEILLE** |
| 3–8 | La rafale tourne | Les couloirs « Avant / pendant / après » passent au trafic élevé ; score qui monte |
| ~8 | — | **Annotation rouge « Incident détecté »** ; score franchit 0,55 ; tuile **Score d'anomalie** au rouge (0,88) |
| 8–12 | — | Moteur **EN ACTION** ; **annotation orange « Action du moteur »** ; chronologie : « Anomalie confirmée », « redémarrage de paiement_payment-api » |
| 12–25 | On arrête la rafale | Panneau payment-api : réplica qui se recrée ; **annotation bleue « Vérification »** |
| 25–40 | — | **Annotation verte « Service rétabli »** ; tuile **Dernier temps de reprise** affiche N s ; `humanActions = 0` |
| 40–55 | — | Une barre verte « Transaction de test réussie » (sonde) ; bandeau repassé **OK** ; chronologie complète |
| 55–60 | — | Plan large : tout est vert, « 0 intervention humaine » |

Si le scénario (b) est filmé à la place : au lieu de la rafale, répéter des connexions erronées ;
l'écran montre l'**annotation « IP bannie au WAF »** et les requêtes de l'attaquant qui passent en
403, le service restant disponible pour les autres.

Tuiles du dashboard à connaître (bandeau haut) : **Paiements** (OK / EN PANNE / SONDE MUETTE),
**Depuis la dernière transaction réussie**, **Score d'anomalie**, **Moteur de remédiation** (EN
VEILLE / EN ACTION), **Dernier temps de reprise** (sonde et moteur). En dessous : couloirs avant /
pendant / après, score et transactions de test, métriques de payment-api, chronologie en clair et
alertes actives.

---

## 4. La commande de stimulus

On réutilise **ce qui existe déjà** dans le dépôt, sans rédiger de nouvelle charge :

- **Le plus simple et le plus sûr** : `infra/chaos/chaos.sh burst`. Il joue la rafale (40 requêtes
  parallèles, 45 s), pose les annotations « Tests de chaos » sur le dashboard, mesure la reprise
  par la sonde et écrit le résultat dans `/root/chaos/resultats.tsv`. C'est l'outil validé le
  20/10. Il vise l'adresse virtuelle depuis le poste de contrôle (pas la chaîne publique).
- **Depuis un PC externe, par l'URL publique** (plus spectaculaire, à valider en répétition) : une
  boucle de requêtes parallèles vers `POST https://app.slabreze.fr/api/payment_intents` avec un
  corps JSON minimal. La charge de référence de l'équipe IA, `evaluation/attaque.py`
  (branche `origin/IA`), fait cela contre une base locale ; pour la démo, il suffit d'en pointer
  l'URL de base sur `https://app.slabreze.fr`. Exemple reproductible, sans secret (les requêtes
  sont refusées en 401 faute de session, mais comptent dans le trafic vu par le détecteur) :

  ```bash
  # PC attaquant, sortant par une autre IP publique que le poste de présentation
  URL=https://app.slabreze.fr/api/payment_intents
  end=$(( $(date +%s) + 25 ))
  while [ "$(date +%s)" -lt "$end" ]; do
    seq 1 200 | xargs -P 40 -I{} curl -s -o /dev/null --max-time 3 \
      -X POST -H 'Content-Type: application/json' -d '{"amount":100}' "$URL"
  done
  ```

  Aucun identifiant, aucune carte, aucun secret : ce n'est qu'un volume de requêtes. Pour le
  scénario (b), remplacer par des `POST /auth/login` avec un identifiant quelconque et un mauvais
  mot de passe ; au-delà de 10 échecs en 2 min, le WAF bannit l'IP.

Garder la durée courte (20–25 s) pour tenir dans les 60 s du clip et ne pas épuiser le quota de la
passerelle.

---

## 5. Démonstration live (5 min)

Déroulé proposé, dashboard projeté en permanence :

1. **Contexte** (45 s) : « Plateforme de paiement qui doit encaisser une attaque et se rétablir
   seule. Trois boucles : détection par IA, remédiation automatique, bannissement au WAF. Tout est
   supervisé en direct sur ce tableau de bord. » Montrer l'état nominal (tout vert, score bas,
   moteur en veille) et faire un paiement réel à la main sur `app.slabreze.fr` (carte de test
   `4242 4242 4242 4242`) pour prouver que le service marche : il apparaît dans le journal.
2. **Attaque** (15 s) : lancer la commande du §4 sur le PC attaquant. « À partir de maintenant,
   nous ne touchons plus à rien. »
3. **Réaction** (1 min) : commenter en direct ce que le dashboard affiche — montée du score,
   annotation « Incident détecté », moteur « EN ACTION », redémarrage, vérification, « Service
   rétabli en N s ». Insister sur `humanActions = 0`.
4. **Preuve** (30 s) : la sonde rejoue une transaction qui réussit ; refaire aussi un paiement
   manuel sur le site pour montrer que le client peut payer. Si le scénario (b) est inclus, montrer
   l'annotation « IP bannie au WAF » et un 403 depuis le PC attaquant.
5. **Explication technique** (1 min 30) : schéma de l'archive (README §2) — NPM, WAF, adresse
   virtuelle, Swarm, le détecteur qui lit l'API chaque seconde, le moteur qui agit par une
   passerelle SSH à droits réduits (jamais le socket Docker), la supervision VictoriaMetrics / Loki
   / Grafana. Citer un chiffre : « reprise mesurée en 10 à 19 s selon le type de panne,
   13 tests de résilience documentés ».
6. **Transition questions** : renvoyer vers `infra/docs/tests-resilience.md` et
   `infra/docs/pca-pra-technique.md`.

Phrases clés : « zéro intervention humaine », « le détecteur n'a aucune règle codée en dur : il
connaît la normale et mesure l'écart », « la source est bloquée au WAF pendant que le moteur
rétablit le service », « tout est en code, rien n'est configuré à la main ».

---

## 6. Plan B

| Situation | Signe | Conduite à tenir |
|---|---|---|
| L'attaque ne déclenche rien | score reste bas, aucune annotation après 15 s | Ne pas réparer ni relancer en boucle. Expliquer que la fenêtre de trafic est de 10 s et que le détecteur exige 3 s au-dessus du seuil ; prolonger un peu la rafale **une fois**. Si rien ne vient, passer au clip enregistré |
| Le WAF bannit l'IP du PC attaquant avant la fin | les requêtes passent en 403, l'attaque s'arrête d'elle-même | C'est un **succès défensif** : le dire. Pour relancer une démo, débannir depuis le WAF `sudo waf-ban unban <ip>` (expiration sinon 15 min) — **hors séquence filmée** |
| Le poste de présentation est banni | l'application publique y répond 403 | Vérifier que les deux PC sortent par des IP différentes (§1). Débannir l'IP du poste `sudo waf-ban unban <ip>` **avant** la démo |
| Une sauvegarde gèle les VM | `demo-check.sh` avertit, dashboard figé ~45 s | Attendre la fin du créneau (§2) ; ne jamais démarrer dans ces 45 s |
| Vault est scellé | `demo-check.sh` : `Vault scellé` | L'application **tourne quand même** ; seul un redéploiement serait impossible. Lancer `vault-unseal` sur le poste de contrôle **avant** la démo, pas pendant |
| Quota de la passerelle épuisé | `demo-check.sh` : quota presque épuisé | Attendre 10 min. La passerelle refuse (code 4, `RateLimited`) : le moteur réessaie, mais la reprise serait lente. Ne pas forcer |
| Le détecteur réapprend | `detector_ready = 0` | Attendre la fin des 60 s d'échauffement |
| N'importe quel imprévu pendant le live | — | **Ne jamais réparer à la main.** Basculer sur le clip de 60 s enregistré à l'avance |

**Clip de secours** : enregistrer à l'avance, lors d'une répétition réussie, une prise complète de
60 s. La projeter si le live échoue. C'est l'assurance que la note de remédiation ne dépend pas
d'un aléa en direct.

---

## 7. Remise à zéro après une répétition

1. Attendre **10 min** que le quota de la passerelle se reconstitue (`demo-check.sh` :
   `aucune action dans les 10 dernières minutes`).
2. Vérifier qu'aucune IP n'est bannie : sur le WAF, `sudo waf-ban list`. Débannir si besoin
   (`sudo waf-ban unban <ip>` ou `--all`).
3. Relancer **`infra/demo/demo-check.sh`** : il doit afficher **PRÊT**.
4. Vérifier que le détecteur n'est pas en apprentissage (`detector_ready = 1`) et que la sonde a
   une transaction réussie récente.

---

## Sources des chiffres

- Test `burst` (rafale 45 s) : panne 0 s, anomalie +4 s (score 0,88), redémarrage 13,8 s —
  `/root/chaos/resultats.tsv` et `infra/docs/tests-resilience.md`.
- Test `api-stop` : reprise 10 s (détection +4 s, restart 12,6 s) ; test de reprise de bout en
  bout : 16 s — `infra/docs/application.md`, `infra/docs/tests-resilience.md`.
- Bannissement au WAF : 27 s du premier échec au premier 403 (force brute, 21/10) —
  `infra/docs/waf.md` §5.
- Seuils des règles de bannissement : `infra/monitoring/loki/rules/waf-ban.yml`.
- Dashboard et tuiles : `infra/monitoring/grafana/dashboards/Démo/demo-remediation.json`.
