# REARM — Raccordement de la reprise et preuve métier

Correctif du 21 octobre 2026, préparé sur REARM-source(3).zip. La version précédente appelait `/internal/incidents` et `/internal/business-probe` sans implémentation backend. Elle pouvait redémarrer le backend mais ne permettait pas de conclure honnêtement à une récupération métier. Le présent correctif raccorde ces échanges et distingue explicitement les niveaux de preuve.

## Ce qui est ajouté

- Registre PostgreSQL persistant pour les tentatives de reprise, avec référence technique INC-…, dates et commande de preuve.
- Routes internes protégées par le jeton de remédiation existant. Aucun nouveau secret à saisir et aucune publication de port backend.
- Sonde catalogue + écriture sur une ligne dédiée, immédiatement annulée. Aucun stock, client, commande, compteur de séquence ou paiement n'est modifié par cette sonde.
- Transmission du résultat technique par la remédiation, puis attente d'une nouvelle commande créée après le rétablissement technique et réellement réglée en mode Stripe TEST.
- Rapprochement automatique par le détecteur avec l'état de paiement confirmé côté serveur. Un paramètre de retour navigateur ou une réponse HTTP 200 ne suffisent jamais à valider le paiement.
- File de rapports du détecteur persistée dans un volume dédié, sans secret. Les rapports non acceptés ne sont plus supprimés silencieusement.
- Tableau Grafana **REARM — Reprise et preuve métier**, métriques agrégées sans identifiant client et événements filtrés.
- Scripts de contrôle, recette de panne bornée et retour arrière.

Le domaine d'action reste **le backend de ce projet**, via le docker-guard existant. Le périmètre Docker autorisé n'est pas élargi. Le détecteur existant conserve IsolationForest, sa calibration de 20 observations, les confirmations de panne et ses temporisations. Aucun nouveau LLM ni mécanisme de correction générale des vulnérabilités n'est ajouté. La caméra, les droits du personnel, le firmware ESP8266, les photos et le parcours Stripe existant sont conservés.

## Installation guidée, une commande à la fois

Conserver l'agent caméra et le listener Stripe ouverts. Ne pas laisser un paiement en cours pendant la reconstruction du backend.

1. Extraire le ZIP à côté du projet ; exécuter son `install.py` depuis la racine du projet. L'installateur vérifie les fichiers, sauvegarde les anciennes versions et ne lance aucun service.
2. `docker compose config --quiet`
3. `python scripts/backup_db.py` — conserver le dump localement, il contient des données sensibles.
4. `python scripts/recovery_migrate.py` — ajoute uniquement deux tables et un index. Aucun rejeu des anciennes migrations boutique, aucune remise à zéro des stocks et aucune révocation des sessions.
5. `docker compose up -d --build --no-deps backend remediation ai-engine log-gateway` — brève indisponibilité possible de la boutique. Le gateway de journaux est reconstruit uniquement pour reconnaître les nouveaux événements ; le correctif anti-double-comptage du WAF est préservé.
6. `docker compose restart grafana` — conserve le compte, le mot de passe et les anciens tableaux.
7. `python scripts/recovery_check.py` — n'affiche aucune clé. Vérifie que la sonde exige une autorisation, effectue l'essai technique annulé et lit le registre. Ce contrôle ne provoque aucune panne et ne crée aucune commande.
8. Attendre la calibration du détecteur après sa reconstruction : environ 3 à 4 minutes avec un intervalle de 10 secondes, davantage si des observations ne sont pas saines. `docker compose logs --since=1m --tail=8 ai-engine` doit montrer une observation récente avec `healthy:true` et `ml_ready:true` avant le test de panne.

L'authentification caméra reste dans son service séparé. Le backend reçoit le jeton de remédiation existant pour contrôler les routes internes ; il n'est pas transmis au frontend ni à Grafana.

## Recette de reprise technique

Quand aucun paiement n'est en cours et que le détecteur est prêt :

`python scripts/recovery_demo.py --stop-backend`

Cette commande est une **injection volontaire de panne dans le laboratoire**. Elle arrête seulement le backend via Docker Compose, laisse le détecteur et la remédiation agir, vérifie le retour du catalogue à travers le WAF puis exige un nouveau dossier de reprise au stade technique. La base n'est pas arrêtée, aucun volume n'est supprimé et aucune commande commerciale n'est créée par le script.

Le script mesure depuis la demande d'arrêt jusqu'à l'observation du catalogue revenu et du dossier technique enregistré. Il indique si l'objectif technique de moins de 60 secondes est atteint pour cette exécution. Ce délai n'est pas une garantie : cadence des sondes, délais de connexion, calibration et charge influencent le résultat. Le repli de disponibilité à six sondes en échec peut dépasser une minute. Si la récupération n'est pas confirmée sous 120 secondes, le script remet explicitement le backend en route et marque la recette **non validée**. Cette commande de secours ne compte pas comme récupération autonome. Une interruption clavier appelle également le secours.

Préconditions : les trois services ai-engine, remediation et docker-guard doivent tourner, le catalogue doit être disponible, une observation récente doit confirmer le modèle prêt, et aucun dossier précédent ne doit déjà attendre sa preuve métier. Le script ne lance pas de panne si ces conditions ne sont pas réunies. Il refuse un lancement sans le drapeau explicite `--stop-backend`.

## Recette métier, distincte

Après le message de réussite technique :

1. Dans la boutique, créer une **nouvelle commande après la reprise** et la payer avec la carte Stripe de test, jamais une vraie carte. Le listener Stripe doit rester ouvert. Une ancienne commande déjà payée ou une commande réservée avant la reprise ne suffit pas.
2. Vérifier dans la boutique que le paiement est confirmé.
3. Attendre un ou deux cycles du détecteur, puis `python scripts/recovery_check.py`.
4. Le dossier INC-… doit passer à `business_verified`, avec le numéro RA-… de la nouvelle commande servant de preuve.
5. Dans Grafana, ouvrir REARM → **REARM — Reprise et preuve métier**. Les mesures peuvent attendre le prochain scrape de 15 secondes. L'événement `recovery_reported` indique le résultat technique ; `recovery_business_verified` indique le rapprochement métier confirmé par le backend.

Le **rapprochement et le changement d'état sont automatiques**. Le paiement de recette est effectué par un utilisateur dans Checkout ; cette étape n'automatise ni une saisie de carte ni un paiement. Elle ne constitue donc pas une sonde de paiement autonome intégrale. Le test d'une nouvelle commande payé après panne reste nécessaire pour démontrer le retour métier ; une sonde SQL annulée ne le remplace pas.

## Contrats et sécurité

`GET /internal/business-probe`, `GET /internal/recovery-status`, `POST /internal/incidents` et `POST /internal/recovery/reconcile` exigent tous `Authorization: Bearer <jeton existant>`. L'absence de jeton ou un mauvais jeton renvoie 401. Seuls les deux POST internes exacts bénéficient de l'exception au contrôle d'origine, et leur jeton est vérifié avant traitement ; les POST publics conservent leur contrôle Origin. Ces routes ne sont pas servies par la documentation HTTP (désactivée volontairement), ni publiées par le routage frontend `/api/…`. Aucun accès anonyme n'est ajouté.

Le registre n'accepte du détecteur que les états `remediation`, `echec` et `attente_metier`, des raisons/actions fixes, une référence validée et une date bornée. Il ne stocke pas les dictionnaires libres `detail`/`result`, même s'ils sont présents dans le message. Un client ne peut pas envoyer `resolu` ou `business_verified=true` pour s'attribuer un succès métier. Les dates de rétablissement et de clôture sont fixées par le serveur. Un rejeu tardif ne peut pas effacer une preuve déjà vérifiée.

La preuve métier est dérivée des tables existantes : commande créée après `technical_at`, état de commande compatible, paiement `paid`, identifiant de session de test et référence de paiement présents. Ces tables sont alimentées par le parcours Stripe qui relit et vérifie la session auprès du fournisseur avant de confirmer le paiement. Le rapprochement ne fait pas un nouveau prélèvement et ne se contente pas d'une URL de succès. Il s'applique en mode `stripe_test`, dans les 24 heures suivant la reprise technique. Une annulation/remboursement déjà présent au moment du contrôle n'est pas accepté. Une annulation ultérieure ne réécrit pas la preuve historique d'un paiement qui avait effectivement réussi.

Le registre suppose l'intégrité de la base et de ce parcours de règlement. Un administrateur de base compromis pourrait falsifier les états : cette étape ne prétend pas résoudre ce risque. Le moindre privilège SQL, le chiffrement des secrets et les exercices de restauration restent des travaux de durcissement distincts.

## Stockage et limites de reprise

Nouvelles tables : `rearm_recovery_incidents` et `rearm_recovery_probe`. Le marqueur de sonde est écrit puis annulé, avec délais SQL/attente de verrou bornés. Le registre persiste avec PostgreSQL et est inclus dans les dumps existants. Aucun effacement automatique de son historique n'est ajouté ; surveiller l'espace disque.

Nouveau volume du détecteur : `rearm_recovery_detector_v1`, contenant uniquement les rapports en attente. Le processus tourne désormais sans privilège (UID/GID 65532). La file est écrite atomiquement avant transmission et réécrite après acceptation. Elle ne contient ni jeton, ni mot de passe, ni en-têtes de requête. Un fichier corrompu ou une capacité maximale de 1000 rapports provoque une erreur explicite plutôt qu'un écrasement silencieux. Conserver le volume pour diagnostic ; ne pas le supprimer pour masquer l'erreur.

Le modèle et la temporisation locale repartent à leur état initial après redémarrage du détecteur ; la file, elle, persiste. Le cooldown du service de remédiation reste en mémoire. Une interruption entre l'exécution d'une action et l'enregistrement de son résultat peut laisser une demande `remediation` sans résultat final : elle nécessite un examen, jamais une résolution inventée. Aucun engagement d'exécution « exactement une fois » n'est ajouté.

Les dossiers de reprise INC-… et les incidents de corrélation SOC numérotés (waf_burst, etc.) restent deux registres distincts. Le tableau de corrélation peut résoudre une panne HTTP lorsque la sonde redevient verte ; le dossier de reprise attend toujours une nouvelle commande payée pour sa validation métier. Les mots « résolu » n'ont donc pas le même périmètre dans les deux tableaux.

Cette boucle ne sait pas démarrer si Windows, Docker Desktop ou le PC est entièrement arrêté. Un mécanisme extérieur est nécessaire pour une panne de l'hôte. Elle ne répare pas une base corrompue, ne corrige pas arbitrairement du code et ne remplace pas PCA/PRA, Ansible ou le futur assistant RAG local.

## Retour arrière

`python scripts/recovery_rollback.py`

Le script vérifie que les fichiers n'ont pas été modifiés depuis l'installation, puis restaure les fichiers précédents et retire les fichiers ajoutés par ce patch. Il ne supprime ni table, ni preuve, ni volume, ni secret. Reconstruire ensuite les anciens services :

`docker compose up -d --build --no-deps backend remediation ai-engine log-gateway`

Le tableau Grafana peut rester provisionné à cause du réglage `disableDeletion` : ne pas interpréter ses anciennes valeurs après retrait du correctif. Ne jamais utiliser `docker compose down -v` pour ce retour arrière. Si d'autres modifications ont été faites après ce patch, adapter le retour arrière avant toute restauration automatique.

## Validation avant livraison

Tests du token et de l'Origin, rollback de la sonde et préservation du stock, rejets de fausses preuves, commandes anciennes/non payées/remboursées/live, rapprochement idempotent, conservation de preuve, migration rejouable, file persistante et absence de jeton, gating ML et cooldown, remédiation authentifiée et distinction HTTP/technique/métier. Tests des anciens parcours d'authentification, commande, stock, paiement de test, WAF, journaux et corrélation.

Un test d'enchaînement utilise les vrais handlers Python et SQL PostgreSQL embarqué : panne de transport simulée, redémarrage Docker simulé, sonde technique, nouvelle commande via l'API boutique, règlement via le fournisseur simulé, puis confirmation métier par le détecteur. Le fournisseur Stripe et les actions Docker y sont remplacés par des doubles contrôlés. L'adaptateur SQL de test sérialise les connexions : ce n'est pas une preuve de comportement de verrous sous connexions PostgreSQL indépendantes.

Docker Desktop, les secrets Stripe, le matériel et une panne réelle sur le PC ne sont pas accessibles dans l'environnement de construction. La recette sur le poste reste à exécuter, à chronométrer et à compléter par un paiement Stripe TEST réel. Aucun résultat de recette hôte ni délai de reprise réel n'est annoncé avant ce test.
