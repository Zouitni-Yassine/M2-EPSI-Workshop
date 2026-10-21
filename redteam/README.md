# Red Team - démarrer en 5 minutes

Ce dossier permet de rejouer les tests de RESILIENCE-ALPHA depuis un **PC
attaquant distinct du serveur**. Commencer par le scénario `waf` ; le scénario
`soc` peut bannir l'adresse source pendant la durée configurée par l'équipe.

Les scripts envoient de vraies requêtes vers le laboratoire. Sans `--execute`,
ils affichent seulement le plan et n'établissent aucune connexion.

## 1. Préparer le poste

- Windows ou Linux, Python 3.10 ou plus récent.
- Un profil VPN propre à ce poste et un accès réseau autorisé au WAF.
- L'adresse HTTPS du WAF et son certificat d'autorité public, fournis par
  l'équipe. Aucune clé privée, aucun mot de passe administrateur n'est requis
  pour les tests WAF directs.
- Un membre de l'équipe observe Grafana pendant le test.

```powershell
git clone --branch CYBER https://github.com/brikodepo/M2-EPSI-Workshop.git
cd M2-EPSI-Workshop/redteam
python --version
Copy-Item scope.example.json scope.json
```

Sous Linux : remplacer la dernière commande par `cp scope.example.json scope.json`
et utiliser `python3` si nécessaire. Sous Windows, `py -3` peut remplacer `python`.
Les scénarios directs utilisent uniquement la bibliothèque standard de Python.

## 2. Renseigner la cible autorisée

Éditer **scope.json** : remplacer l'origine HTTPS dans `allowed_origins` ET
`default_origin` par l'adresse exacte donnée par l'équipe. Conserver le bon port.
Les IP de `scope.example.json` sont fictives et ne désignent pas le laboratoire.

Copier le certificat public reçu dans `ca-interne.crt`, à côté du script.
Vérifier son empreinte avec l'administrateur via le canal d'équipe. Le programme
contrôle TLS et le nom/IP du certificat ; ne pas désactiver cette vérification.

Les routes du VPN et le pare-feu doivent autoriser le poste vers ce port du WAF.
Chaque poste doit utiliser ses propres clés et sa propre adresse VPN.

**scope.json, certificats, clés d'hôte SSH et preuves restent locaux** : ils
sont ignorés par Git. Les mots de passe, profils VPN et cookies ne doivent pas
être ajoutés au dépôt.

## 3. Vérifier, puis lancer

```powershell
# Préparer : aucun trafic émis.
python run.py --scenario waf

# Une requête normale : HTTPS valide et HTTP 200 attendus.
python run.py --scenario preflight --execute

# Test WAF : 12 requêtes, environ 12 secondes à 1 requête/s.
python run.py --scenario waf --execute
```

Sous Windows, **Lancer-RedTeam.cmd** lance le scénario WAF après la configuration.
Le wrapper PowerShell est également disponible :

```powershell
./run-waf.ps1 -Scenario waf -Execute
```

### Résultats attendus

| Scénario | Stimulus | Attendu |
| --- | --- | --- |
| `preflight` | 1 requête normale | HTTP 200 |
| `waf` | 3 normales, 6 essais SQL/XSS, 3 normales | 200, puis 403, puis 200 |
| `soc` | 3 normales, 20 essais XSS, attente de 20 s, 3 contrôles | source bannie, contrôles finaux en 403 |
| `all` | WAF puis SOC : 38 requêtes | filtrage et bannissement de la source |
| `ml` | 102 lectures, au plus 5 req/s | mode TEST confirmé ; réponses 200/401 et service disponible |
| `ml-auth` | mode TEST, 100 demandes de montant négatif, contrôle final | demandes refusées en 422 ; disponibilité finale |

Les scénarios WAF sont limités à 2 requêtes/s et 40 requêtes ; les stimuli ML
à 5 requêtes/s et 110 requêtes. Aucun parallélisme ni augmentation automatique
du débit. Un statut inattendu arrête la séquence. **Ctrl+C** arrête l'émetteur
et conserve les observations déjà écrites.

**Code de sortie 0** : les réponses HTTP attendues ont été observées.
**Code 2** : contrôle échoué, interruption ou prérequis manquant. Le détail
figure dans le terminal et dans le bilan. Un code 0 ne valide pas à lui seul
la détection ML, une alerte SOC ou une nouvelle transaction.

## 4. Observer Grafana et conserver les preuves

Ouvrir le dashboard Cyber du laboratoire sur les 5 ou 15 dernières minutes.
Dans Explore, sélectionner Loki et utiliser :

```logql
{host="waf01",container="resilience-waf"}
  | json | __error__="" | event_type="http_access"
```

Adapter les labels si la configuration de l'équipe a changé. Pour corréler une
requête, recopier son `request_id` depuis `requests.jsonl` :

```logql
{host="waf01",container="resilience-waf"} |= "IDENTIFIANT_REQUETE"
```

Pour le bannissement, vérifier l'alerte active et le journal de décision :

```logql
{host="waf01",identifier="waf-ban"}
```

Le seuil et la période d'évaluation sont ceux des règles réellement déployées.
Une suite de 403 ne prouve pas à elle seule qu'un bannissement a eu lieu :
vérifier aussi la décision et l'accès d'un client sain utilisant une autre IP.

Chaque exécution crée `evidence/<date-UTC>-<UUID>/` :

- `requests.jsonl` : heure UTC, cas, statut, durée et identifiant de requête ;
- `summary.json` : résultat HTTP et limites de la vérification ;
- `SHA256SUMS.txt` : empreintes des deux fichiers précédents.

Les corps sont remplacés par une empreinte des 4096 premiers octets. Les cookies
et mots de passe ne sont pas exportés. Les preuves contiennent néanmoins des
adresses, un nom de poste et des identifiants techniques : les partager dans
l'espace privé de l'équipe, sans les publier sur un dépôt public.

## 5. Après le scénario SOC

Une requête normale de la **source attaquante bannie** doit rester en 403.
La disponibilité du service se teste depuis une autre source saine.

Pour répéter, attendre l'expiration du ban ou demander à l'administrateur de
retirer uniquement le ban de l'IP utilisée. Le nettoyage est manuel, effectué
**après conservation des preuves et hors séquence filmée**. Ne pas le présenter
comme une reprise autonome. Le programme ne modifie pas les règles du WAF.

## Relais SSH : réservé à un opérateur autorisé

Si le réseau direct n'est pas disponible, l'administrateur peut renseigner
`ssh_relay` dans scope.json et fournir une clé d'hôte vérifiée dans
`ssh-known-hosts`. Utiliser un compte dédié dont les droits de transfert sont
limités à la destination WAF ; ne pas distribuer un compte root aux participants.

```powershell
python -m pip install -r requirements-relay.txt
python run.py --scenario waf --execute --ssh-relay
```

Le mot de passe du relais est demandé en saisie masquée. Le relais écoute
uniquement sur la boucle locale, sur un port éphémère, et se ferme après le
test. TLS reste vérifié pour la vraie cible. **Le WAF voit l'IP du relais** :
ce trajet apparaît dans le bilan et doit être annoncé dans la démonstration.

## Stimulus applicatif authentifié

Pour `ml-auth`, utiliser une session d'un **compte client de test**, obtenue
dans l'application du laboratoire. Copier la valeur de l'en-tête Cookie de
cette session, sous la forme `nom=valeur`, puis la saisir en masqué :

```powershell
python run.py --scenario ml-auth --session-cookie --execute
```

Ne pas coller le cookie dans la commande, dans Git ou dans une capture vidéo.
Une session peut aussi être fournie en mémoire via REDTEAM_SESSION_COOKIE.
Le script exige `mode=test` et envoie `amount=-1` : une réponse autre que 422
arrête les demandes. Il ne crée aucun paiement avec un montant valide.

Ce stimulus peut **ne pas déclencher le modèle** : des routes exclues des
métriques, une session refusée ou la normale apprise influencent le résultat.
Vérifier le score, le verdict et la chronologie du moteur. Ne pas modifier le
seuil pendant la prise pour faire apparaître artificiellement une réussite.

## Correspondance avec le sujet et limites

La suite couvre le stimulus depuis un poste distinct, le WAF, l'observation SOC,
le confinement d'une source et la collecte de preuves reproductibles.

La recette de développement a observé 38/38 contrôles WAF/SOC réussis, un
bannissement automatique et des paiements de test réussis par la sonde interne.
Elle a également observé que le stimulus applicatif borné ne déclenchait pas
le verdict ML. Ces constats ne garantissent pas le même résultat sur une autre
configuration. Les preuves détaillées et les paramètres de ce laboratoire ne
sont pas publiés dans cette branche.

Pour la démonstration complète : montrer le service avant, l'incident, la
détection réelle, l'action automatique et une **nouvelle transaction fictive
réussie**, avec vérification des données. La sonde interne ne prouve pas le
chemin public WAF. Le clip doit rester continu, de 60 s maximum, sans correction
manuelle masquée. Un redémarrage de conteneur seul ne suffit pas.

La branche IA propose aussi `evaluation/attaque.py` (250 threads / 45 s, cible
locale) ; ce script n'est pas lancé automatiquement par cette suite. Les
scénarios actuels utilisent des budgets explicites adaptés au laboratoire.

## Vérifier les scripts sans attaquer de serveur

```powershell
python -m unittest discover -s tests -v
```

Les tests des garde-fous sont locaux. Ils ne remplacent pas la recette réseau.
Les redirections sont refusées, les proxys de l'environnement sont ignorés et
seules les IP privées HTTPS inscrites dans scope.json sont acceptées. Les autres
groupes, le réseau du campus et les services tiers sont hors périmètre.
