# Red Team — tests reproductibles et répétition du clip

Cible autorisée : **https://app.slabreze.fr/**, par Internet → NPM → WAF →
application. Ne pas viser l'IP interne du WAF et ne pas ouvrir VPN → DMZ.
Le VPN « PC admin compromis » sert à une démonstration de segmentation
distincte ; il n'est pas nécessaire pour le trajet public.

Python 3.10+, sans dépendance pour les tests publics. Sans `--execute`,
le script affiche le plan **sans connexion réseau**.

## 1. Installer

```powershell
git clone --branch CYBER https://github.com/brikodepo/M2-EPSI-Workshop.git
cd M2-EPSI-Workshop/redteam
python --version
Copy-Item scope.example.json scope.json
```

Linux : `python3` et `cp scope.example.json scope.json`. Windows : `py -3` peut
remplacer `python`. Pour une copie existante : `git pull --ff-only`, puis
adapter le scope local, sans écraser une configuration déjà personnalisée.

Le scope exemple contient déjà l'origine publique exacte dans `allowed_origins`
et `default_origin`. `ca_file: null` utilise les autorités du système, sans
certificat interne à copier. TLS et le nom du certificat sont vérifiés ; les
redirections sont refusées et les proxys d'environnement sont ignorés. Une
autre origine, un autre port ou une URL avec identifiants/chemin est refusé.

**Avant tout test offensif :** PC attaquant distinct, sur une **autre IP publique
de sortie** que le PC de présentation, par exemple la 4G. Deux profils VPN ne
garantissent pas deux sorties différentes. Si le VPN impose une sortie par le
laboratoire, vérifier avec l'administrateur. Un ban pourrait sinon couper aussi
l'application du présentateur.

## 2. Contrôle normal et tests WAF/SOC

```powershell
# Plan seulement, aucun trafic.
python run.py --scenario waf
# Une requête normale, HTTP 200 attendu.
python run.py --scenario preflight --execute
# Filtrage SQL/XSS et contrôles normaux.
python run.py --scenario waf --execute
# Bannissement : attendre sa fin avant un nouvel essai.
python run.py --scenario soc --execute
```

Windows : `Lancer-RedTeam.cmd` joue `waf`.
`./run-waf.ps1 -Scenario waf -Execute` est aussi disponible.

| Scénario | Budget | Attendu |
| --- | --- | --- |
| `preflight` | 1 requête | 200 |
| `waf` | 12, 1 req/s par défaut | 3 normales 200, 6 injections 403, 3 normales 200 |
| `soc` | 26, 1 req/s et attente de 20 s | normales 200, injections 403, contrôles de confinement 403 |
| `all` | 38 | WAF puis SOC, hors clip de 60 s |
| `ml` | 102, au plus 5 req/s | lectures 200/401, sans garantie de détection |
| `ml-auth` | 102, au plus 5 req/s | TEST confirmé, montants négatifs refusés en 422 |
| `burst` | 752 par défaut, fenêtre de 25 s | stimulus de charge ; résultat ML à observer séparément |

WAF : plafonds 40 requêtes et 2 req/s. ML historique : 110 requêtes et 5 req/s.
Le faible débit des anciens scénarios n'a pas déclenché le modèle en recette
interne. Les lectures `/api/health` et `/api/status` sont en outre exclues du
débit applicatif dans le code actuel. Utiliser `burst` pour la répétition.
Un statut inattendu arrête les tests WAF ; ne pas les lancer depuis une IP déjà
bannie. Les délais des alertes restent ceux de la configuration déployée.

## 3. Charge bornée pour la répétition ML

```powershell
# Préparer seulement : 25 s, 30 req/s, 8 connexions, au plus 752 requêtes.
python run.py --scenario burst
# Lors du créneau convenu, sur la sortie attaquante séparée uniquement.
python run.py --scenario burst --execute
```

Prérequis automatiques : `/api/health` doit annoncer `mode=test`, puis un POST
à `/api/payment_intents` contenant **amount=-1** doit être refusé. Sans session,
le refus attendu est 401 ; avec session client TEST, 422. Sinon la charge est
annulée. Le script ne soumet aucun montant valide et ne vise pas directement
Stripe/PayPal. Un 5xx pendant la charge est enregistré, sans prouver un verdict ML.

Cette route est comptabilisée dans le débit du code actuel de l'API. Confirmer
sa réception et les métriques sur la version déployée : une interception en
amont peut empêcher le détecteur de la voir. Le script ne contourne pas le WAF.

Garde-fous par défaut : fenêtre d'émission **25 s**, cadence de soumission
**30 req/s**, **8 appels simultanés** au plus, **752 requêtes** avec les deux
prérequis, timeout réseau **3 s**. Les appels déjà partis se terminent après
la fenêtre. Aucun rattrapage des créneaux perdus, nouvelle tentative ni
escalade automatique. 403/429, redirection, succès inattendu du paiement ou
trois échecs de transport consécutifs arrêtent les nouvelles émissions.
**Ctrl+C** interrompt les émissions et conserve les observations déjà écrites.

Options `--rate`, `--duration`, `--concurrency` pour réduire la charge. Plafonds
absolus : 40 req/s, 30 s, 10 connexions, 1200 requêtes ; le scope exemple impose
un budget plus bas de **800**. Une combinaison dépassant le budget est refusée.
Ne pas augmenter ces paramètres en cours de prise pour obtenir un score.

Session client TEST facultative, demandée en masqué :

```powershell
python run.py --scenario burst --session-cookie --execute
```

Utiliser un cookie client de test obtenu dans l'application, sous la forme
`nom=valeur`. Ne pas l'afficher dans une commande, une capture ou Git. Il peut
aussi être fourni en mémoire par `REDTEAM_SESSION_COOKIE`. Aucun compte admin
n'est requis. `--ssh-relay` est refusé pour `app.slabreze.fr`, afin de conserver
le trajet public sans contournement de la segmentation.

## 4. Répétition et clip continu de 60 s

**État au 22 octobre :** contrôle normal public réussi en 200 avec TLS vérifié.
La charge publique et la chaîne complète restent **à valider** sur une sortie
séparée. Les valeurs d'environ 4 s de détection et 13 s de remédiation viennent
d'une autre recette sur l'adresse virtuelle interne ; elles ne sont pas garanties
sur le trajet public. La recette WAF/SOC précédente utilisait un relais interne.

Avant de filmer, l'opérateur infra suit `infra/demo/demo-check.sh` de la branche
INFRA : détecteur prêt, moteur en veille, quota disponible, sonde active, absence
de sauvegarde proche et d'alerte parasite. Entre répétitions, attendre le retour
nominal et la reconstitution des quotas. Ne pas réinitialiser le modèle pour
forcer une réussite.

| Phase continue | Preuve à montrer et conserver |
| --- | --- |
| Avant | service nominal, horloge UTC, score bas, moteur en veille |
| Attaque | commande `burst --execute` et UUID du run |
| Détection | vrai verdict ML, heure, score et métriques |
| Réaction | décision et action automatiques, cible et résultat |
| Reprise | **nouvelle transaction fictive réussie après l'action**, identifiant, cohérence en base et retour nominal |

Après le lancement, laisser agir la plateforme : aucun redémarrage, relancement
de playbook ou débannissement pendant la prise. Filmer une seule séquence de
60 s maximum après une répétition réussie. WAF/SOC peut être montré à part ;
`all` n'est pas conçu pour tenir dans le clip.

Une sonde interne prouve une transaction interne. Pour prouver aussi le trajet
public, prévoir une sonde de paiement via l'entrée publique depuis une source
saine. Un GET 200, une ancienne transaction ou un simple redémarrage ne prouve
pas la reprise métier. Ne pas afficher de cookie, carte ou secret.

Si le WAF bloque avant le verdict ML, conserver le résultat comme preuve de
confinement, **sans annoncer la chaîne ML/remédiation validée**. Si le modèle
ne réagit pas, garder aussi cet échec et analyser les métriques hors clip.

## 5. Grafana et preuves

Ouvrir les dashboards Cyber et Démo / Remédiation sur 5 ou 15 minutes.
Dans Explore / Loki, adapter les labels à la version déployée :

```logql
{host="waf01",container="resilience-waf"} | json | __error__="" | event_type="http_access"
{host="waf01",container="resilience-waf"} |= "IDENTIFIANT_REQUETE"
{host="waf01",identifier="waf-ban"}
{stack="probe",service="probe_transactions"} |= "type=etat"
{stack="probe",service="probe_transactions"} |= "type=evenement"
{stack="probe",service="probe_transactions"} |= "type=transaction" |= "result=ok"
```

Relever l'IP source **réellement journalisée au WAF**, le `request_id` et la
fenêtre UTC du run. Ne pas simuler l'IP avec un en-tête client. NPM et WAF doivent
préserver la source avec une chaîne de proxies de confiance correcte : si le
WAF voit seulement NPM, suspendre le test de ban et faire corriger avant la démo.

Chaque exécution écrit `evidence/<date-UTC>-<UUID>/` :

- `requests.jsonl` : heures, cas, chemins, statuts, durées et request IDs ;
- `summary.json` : budgets, trajet, résultats HTTP et limites ;
- `SHA256SUMS.txt` : empreintes des deux fichiers précédents.

Les corps sont remplacés par une empreinte des 4096 premiers octets. Aucun
cookie ou mot de passe n'est exporté. Les preuves techniques restent privées.

Code **0** : stimulus terminé selon les contraintes et attentes HTTP.
Code **2** : prérequis, arrêt de protection, interruption ou contrôle échoué.
Un 5xx ne vaut pas un verdict ML. Les champs détection/remédiation/transaction
restent `not_verified` et `full_subject_sequence_passed` reste `false` :
rapprocher les preuves externes avant de déclarer la séquence complète réussie.

## 6. Nettoyer après la prise

Le ban expire normalement après **15 min**. Depuis un accès admin autorisé
sur `waf01`, retirer uniquement l'IP concernée si nécessaire :

```bash
sudo waf-ban unban <ip-publique-de-l-attaquant>
```

Conserver les preuves avant nettoyage. Ce débannissement manuel a lieu **hors
prise** et ne constitue pas une reprise automatique. Préserver les autres bans.
Vérifier l'accès à l'application depuis une source saine.

## 7. Versionnement et Code.zip

Sources versionnées dans `CYBER` du fork `brikodepo` et intégrées à `main` du
dépôt d'équipe par la [PR nº 6](https://github.com/Zouitni-Yassine/M2-EPSI-Workshop/pull/6),
fusionnée le 22 octobre. Vérifier que la version retenue pour l'archive globale
contient bien le dossier. Pour reprendre toute la partie cyber/gouvernance,
voir la [passation](../cyber/README.md), l'[exploitation](../cyber/EXPLOITATION.md)
et le [guide jury](../cyber/JURY.md).

Paquet partageable des seules sources Red Team :

```powershell
python package.py --output Code-RedTeam.zip
```

Inclut le dossier `redteam/`, le scope **exemple** et un manifeste d'empreintes.
Exclut configuration locale, preuves, pycache, cookies, clés, certificats et VPN.
Intégrer ce dossier au **Code.zip global du projet**, avec les autres sources
demandées ; le paquet Red Team seul ne remplace pas le rendu complet.
Le destinataire reprend les étapes 1–3 depuis le dossier extrait.

La suite fournit les scripts d'attaque, le périmètre, le mode d'emploi et les
observations reproductibles. Pour répondre entièrement au sujet, ajouter la
recette réelle attaque → détection → réaction → nouvelle transaction et le
clip continu. Ne pas les annoncer réussis avant observation.

## 8. Tests locaux

```powershell
python -m unittest discover -s tests -v
```

Scope exact, TLS public, redirections, absence de trafic sans `--execute`,
budgets, cadence de soumission, parallélisme et arrêts sont couverts localement.
Ils ne remplacent pas la répétition réseau. Les autres équipes, le campus et
les services tiers sont hors périmètre.
