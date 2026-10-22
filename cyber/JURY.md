# Présenter la partie cyber au jury

À lire avec [l'état réel et les preuves](README.md). Le texte ci-dessous est
une proposition orale ; adapter les dernières phrases après la répétition.

## 1. Discours de deux minutes

> « La partie cybersécurité protège le chemin d'accès au paiement et permet
> de comprendre ce qui se passe pendant un incident.
>
> L'utilisateur passe par l'URL publique, puis NPM, notre WAF dédié en DMZ et
> enfin le frontal applicatif. Le WAF utilise ModSecurity et les règles OWASP CRS.
> Il peut refuser des requêtes comme nos essais d'injection SQL et de XSS avant
> leur arrivée dans l'application. L'accès direct depuis le VPN n'est pas ouvert
> pour faciliter les attaques : nous conservons la segmentation.
>
> Chaque requête produit des traces. Alloy les envoie à Loki ; Grafana permet
> de voir les codes HTTP, les sources et l'audit, avec des identifiants pour
> corréler une requête et un événement. Nous avons également une règle de
> détection de blocages répétés.
>
> L'intégration avec l'infrastructure ajoute le confinement : certaines alertes
> déclenchent un bannissement temporaire de la source au WAF, pendant quinze
> minutes. Nous vérifions la décision dans les logs et le maintien de l'accès
> depuis un client sain. Ce mécanisme est distinct de l'IA : le modèle détecte
> une anomalie de comportement et le moteur peut agir sur le service via une
> passerelle aux droits limités.
>
> Notre recette WAF/SOC a passé 38 contrôles sur 38 par un relais interne.
> Nous en précisons le trajet, sans l'assimiler à une attaque publique. Les
> scripts sont versionnés, bornés et documentés pour être rejoués par une
> autre personne. Le nouveau scénario de charge publique est préparé ; la
> séquence complète ML, action et nouvelle transaction reste à valider lors
> d'une répétition dédiée.
>
> Enfin, le PCA/PRA distingue continuer le paiement, rétablir la disponibilité
> et restaurer des données fiables. Nous ne confondons pas un redémarrage
> technique avec une reprise métier ni avec l'éradication d'une compromission. »

Après une répétition réellement réussie, remplacer la réserve finale par le
résultat **mesuré**, son trajet et la preuve de transaction. Ne pas annoncer
les délais de la recette interne comme ceux d'une démonstration publique.

## 2. Ce qu'il faut montrer

| Écran / preuve | Commentaire utile | Ce que cela ne prouve pas seul |
| --- | --- | --- |
| Schéma et URL publique | une entrée contrôlée, une DMZ, des flux limités | résistance à toutes les attaques |
| Requête normale puis SQL/XSS | 200 pour le normal, 403 sur le cas de test, règle d'audit correspondante | absence de vulnérabilité dans le code |
| Dashboard Cyber | événements récents et identifiants corrélables | collecte complète si des panneaux sont sans données |
| Décision `waf-ban` + client sain | source confinée et maintien du service pour les autres | réparation d'une API tombée |
| Verdict ML + action moteur | anomalie réelle puis action autonome horodatée | paiement rétabli tant qu'aucune transaction n'a réussi |
| Nouvelle transaction de test après l'action | reprise métier, ID et cohérence vérifiables | trajet public si la sonde utilise seulement le réseau interne |
| PCA/PRA et tests de restauration | objectifs, décisions, preuves et limites | continuité d'un sinistre de site si aucun second site n'existe |

Les scripts WAF/SOC et le scénario ML peuvent être montrés séparément. Le clip
complet doit suivre une seule chaîne réelle, en une prise continue ≤ 60 s.

## 3. Préparer la démonstration

Avant la prise :

1. Sortie publique de l'attaquant différente de celle du présentateur ; vérifier
   le routage réel du VPN, pas seulement le nom du profil.
2. Plateforme nominale, modèle prêt, moteur en veille, quota disponible,
   sauvegardes éloignées ; validation par le référent infra.
3. Dashboard Démo / Remédiation, application et terminal prêts ; horloges
   cohérentes et commandes saisies sans secret visible.
4. Transaction de contrôle et destination de la sonde connues ; preuve à relier
   à l'action, pas à une transaction datant d'avant l'incident.

Pendant : annoncer le lancement, laisser agir automatiquement, montrer verdict,
action et nouvelle transaction. **Aucune correction humaine de plateforme.**
Ne pas débannir, redémarrer à la main, réinitialiser le modèle ou relancer un
playbook dans la prise. Si le WAF contient la source sans réaction ML, expliquer
ce résultat ; ne pas le convertir verbalement en réussite de la chaîne complète.

Après : conserver résultats et logs, puis nettoyer seulement si nécessaire.
Le débannissement manuel se fait hors prise. Le [guide Red Team](../redteam/README.md)
contient les commandes et plafonds ; ne pas improviser un outil de charge.

## 4. Questions probables

**« Votre WAF, c'est l'IA ? »**

Non. ModSecurity/CRS applique des règles de protection HTTP. Les alertes Loki
utilisent des seuils explicites. Le détecteur ML apprend un comportement normal
et fournit un verdict au moteur ; il appartient à un autre pilier.

**« Pourquoi un WAF si le code est sécurisé ? »**

Il ajoute un contrôle indépendant à l'entrée, des traces et un moyen de
confinement. Il complète les validations, l'authentification et les correctifs
du code ; il ne les remplace pas.

**« Comment savez-vous que ce 403 est une attaque ? »**

Le statut seul ne suffit pas. Nous corrélons l'accès et l'audit ModSecurity
avec le request ID, la règle et le cas de test. Nos règles de seuil peuvent
aussi compter certains refus applicatifs : c'est une limite connue.

**« Bannissez-vous le proxy NPM à la place du client ? »**

La configuration décrite fait confiance à NPM pour l'adresse réelle, pas aux
en-têtes arbitraires du client. Nous vérifions la source dans les journaux et
la décision. Le ban se fait au niveau nginx, où cette IP est connue.

**« Pourquoi deux connexions Internet ? »**

Le ban concerne une IP. Deux PC derrière le même NAT partagent cette identité
réseau ; l'attaque pourrait aussi couper la présentation. Une sortie séparée
permet de montrer le confinement de l'attaquant et l'accès du client sain.

**« Comment prouvez-vous la reprise ? »**

Avec une nouvelle transaction fictive réussie après l'action, son identifiant,
son horodatage et sa cohérence en base. Une page 200 ou un conteneur recréé ne
suffit pas. Nous précisons si la sonde passe par le public ou par l'interne.

**« Le moteur a-t-il root ou le socket Docker ? »**

Le moteur utilise une passerelle d'infrastructure à commandes restreintes,
avec périmètre, quotas et traçabilité. Il n'a pas un shell général ni un socket
Docker monté directement. Les permissions effectives et leurs limites sont
dans `infra/docs/remediation.md` ; la passerelle privilégiée reste un composant
sensible à protéger.

**« Et les données personnelles ou les secrets dans les logs ? »**

Les accès évitent les corps/cookies et les preuves utilisent des données
fictives ; l'audit peut conserver des fragments utiles à la détection. Accès,
rétention et export doivent être maîtrisés. Les secrets ne sont pas dans les
scripts publics ; ils passent par les mécanismes de coffre et de déploiement
de l'équipe.

**« Est-ce un SIEM/SOC complet et conforme ? »**

C'est une fonction SOC de démonstration : collecte, recherche, corrélation,
alertes et réponse ciblée. Cela ne démontre ni un SOC exploité 24/7, ni une
conformité réglementaire complète. Le dossier de gouvernance expose exigences,
hypothèses et écarts ; la conformité ne se déduit pas d'une liste d'outils.

**« Quelle différence entre sauvegarde et réplication ? »**

La réplication maintient une autre copie courante pour la disponibilité ; une
erreur peut se propager. La sauvegarde permet de revenir à un état antérieur,
à condition qu'elle soit saine et qu'une restauration ait été testée.

**« Quelles limites assumez-vous ? »**

Une VM WAF unique, un site unique, les IP partagées, les attaques distribuées,
les faux positifs et les dépendances externes. La HA de VM n'assure pas une
continuité instantanée du WAF. La source INFRA indique aussi que NPM ne vérifie
pas par défaut le certificat du lien interne vers le WAF : le lien est chiffré,
mais son authentification mérite un durcissement. La charge publique et le clip
restent à valider tant que nous n'avons pas leurs preuves.

## 5. Formulations à garder exactes

| Éviter | Dire |
| --- | --- |
| « Tout est validé » | « Voici les recettes réussies et les réserves restantes » |
| « Le ML bloque les injections » | « CRS bloque les requêtes ; Loki peut déclencher le ban ; le ML traite l'anomalie de comportement » |
| « Grafana sécurise l'application » | « Grafana permet d'observer les événements et les décisions » |
| « 38/38 prouve le clip complet » | « 38/38 valide nos attentes WAF/SOC sur le trajet de cette recette » |
| « Le service est revenu, j'ai un 200 » | « Une nouvelle transaction après l'action confirme la reprise métier » |
| « Nous garantissons 4 s / 13 s » | « Ces temps viennent d'une recette interne précise, à distinguer du trajet public » |
| « RPO zéro pour tout » | « Le RPO dépend des données, du scénario et de la dernière copie utilisable » |
| « DORA/NIS2 : conforme » | « Le dossier analyse les exigences et les écarts ; ce prototype ne certifie pas la conformité » |

## 6. Répartir la parole

- Cyber : chemin public, WAF, journaux, règles, confinement, scripts et limites.
- IA/application : variables et modèle, verdict, choix de l'action, nouvelle transaction.
- Infra : réseau, HA, stockage, sauvegardes, passerelle et droits.
- Gouvernance : criticité métier, risques, objectifs, arbitrages et décisions humaines.

Pour un chiffre ou une question dépassant son périmètre, donner la source et
passer au responsable concerné. Présenter une réalisation collective avec des
preuves distinctes est plus solide qu'attribuer tous les résultats à un seul pilier.
