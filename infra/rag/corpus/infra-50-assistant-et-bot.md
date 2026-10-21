# Fiche infra : l'assistant opérateur et le bot Discord

## Que sait faire l'assistant (bot Discord « Qwen ») ?

L'assistant répond aux questions des opérateurs dans le salon #assistance-rag du serveur Discord
de l'équipe, quand on le mentionne (ou qu'on répond à l'un de ses messages). Il combine :

- la **documentation** et les procédures du projet (que faire si..., comment...) ;
- l'**état réel du système**, lu dans la supervision : alertes récentes, état de la plateforme
  (services, base PostgreSQL, détecteur d'anomalies, sonde de transaction, Vault, Ceph,
  hyperviseurs, Swarm), IP bannies au WAF, événements du moteur de remédiation, requête PromQL.

Il est en **lecture seule** : il ne redémarre rien, ne bannit personne, ne modifie rien et ne lit
aucun secret. Pour agir, suivre la procédure qu'il indique (ou laisser le moteur de remédiation
faire son travail).

## Exemples de questions

- « quelles alertes ont eu lieu ces 2 dernières heures ? »
- « la base de données est-elle en bonne santé ? »
- « quelles IP ont été bannies au WAF aujourd'hui ? »
- « qu'a fait le moteur de remédiation depuis une heure ? »
- « que faire si Vault est scellé ? »

## Limites

- Une question à la fois pour toute l'équipe, 10 par minute au plus ; 20 à 80 s par réponse.
- Sans le GPU de délestage, le modèle de secours ne consulte pas la supervision : la réponse
  commence par « Mode dégradé » et ne reflète pas l'état réel du système.
- Si le bot ne répond plus : sur rag01, `systemctl status discord-bot rag-api rag-mcp` et les
  journaux `journalctl -u discord-bot` (procédure complète : docs/rag.md, section 10).
