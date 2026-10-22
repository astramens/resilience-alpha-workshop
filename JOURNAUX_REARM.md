# REARM — Centralisation des événements filtrés

Étape ajoutée le 21 octobre 2026. Cette étape apporte Loki, un collecteur et un tableau Grafana ; elle ne constitue pas un SIEM complet et ne déclenche aucune nouvelle réparation.

## Installation sur Windows

Conserver la fenêtre Stripe CLI et l'agent caméra ouverts. Depuis le dossier du projet :

1. Exécuter l'installateur extrait à côté du projet. Il vérifie les empreintes, sauvegarde les fichiers modifiés et ne redémarre rien.
2. `docker compose config --quiet`
3. `docker compose pull loki`
4. `docker compose up -d --build --no-deps loki log-gateway log-collector`
5. `docker compose up -d --no-deps --force-recreate grafana`
6. Attendre environ 60 secondes. Dans http://localhost:3001, conserver le compte `superviseur` et son mot de passe. Dashboards → REARM → **REARM — Journaux de sécurité**. L'ancien tableau de disponibilité reste présent.
7. `python scripts/logging_check.py` : saisir le mot de passe Grafana de façon masquée. Le contrôle génère seulement une lecture du catalogue, puis vérifie Loki, un battement récent, les huit sources lisibles et un événement WAF réel. Il ne passe aucune commande et ne simule aucune réparation.
8. `python scripts/waf_check.py` : les deux requêtes de test inertes doivent toujours être refusées. Après quelques secondes, elles alimentent le panneau « Refus WAF » et les journaux. Un refus seul n'est pas une preuve d'attaque réelle.
9. Vérifier à nouveau connexion personnel, parcours caméra puis mot de passe, paiement Stripe de test et ancien dashboard de disponibilité. Contrôler `docker stats --no-stream`.

Ne pas partager `.env`, les mots de passe, les dumps ni les paramètres de caméra/firmware.

## Périmètre et flux

`Docker → passerelle de lecture/filtrage → collecteur → Loki → Grafana`.

Sources autorisées uniquement : edge, waf, frontend, backend, auth, ai-engine, remediation, docker-guard, portant l'étiquette exacte du projet Compose courant. Aucun journal de base de données ni d'un autre projet n'est collecté. Un service qui n'émet pas de format reconnu peut être lisible sans produire d'événement.

La passerelle expose seulement `/health` et `/snapshot`, sans paramètres. Elle construit elle-même des GET Docker vers la liste des conteneurs filtrée et les journaux récents des seuls services autorisés. Aucune inspection des variables d'environnement ni commande de redémarrage, création, suppression, exécution ou écriture Docker n'est exposée. Les autres routes et verbes sont refusés.

**Limite de confiance importante :** cette petite passerelle monte le socket Docker et fait donc partie des composants de confiance de l'hôte, comme le docker-guard existant. Le montage `:ro` ne rend pas l'API Docker intrinsèquement accessible en lecture seule. Une compromission du processus de passerelle serait grave. La restriction vient de son code, de ses réseaux et de son absence d'accès public, pas du suffixe `:ro`. Ni le collecteur, ni Loki, ni Grafana ne montent le socket ; ils ne rejoignent pas le réseau du docker-guard de réparation. Les deux passerelles restent séparées.

Les nouveaux réseaux log_source et log_store sont internes. Loki n'a pas d'authentification applicative : son API n'est accessible que sur log_store, à Grafana et au collecteur. Aucune publication de port pour Loki, la passerelle ou le collecteur. Grafana garde exactement `127.0.0.1:3001:3000` et le réseau grafana_access qui a corrigé son accès Windows. Ne pas désactiver l'authentification Grafana et ne pas exposer Loki sur le LAN.

## Données retenues et données écartées

Le filtre utilise des listes fermées. Pour les accès HTTP : méthode autorisée, statut numérique et route prédéfinie (les autres routes sont regroupées). Les paramètres d'URL ne sont jamais conservés. Pour les événements structurés : nom connu et quelques mesures numériques/booléennes bornées. Les acteurs, noms clients, identifiants de commande/cible, raisons textuelles libres, adresses IP, cookies, en-têtes, corps, signatures, tokens, mots de passe et données faciales ne sont pas stockés dans Loki. Les messages inconnus et traces d'exception brutes sont abandonnés.

Les journaux Docker sources peuvent déjà contenir des données sensibles : ce patch filtre le flux envoyé à Loki, il ne purge pas les anciens journaux Docker. L'audit métier détaillé reste dans la base et l'espace atelier. Le nouveau stockage n'est ni un archivage exhaustif ni une preuve forensique immuable. Les événements et chemins d'origine sont des données non fiables : des messages peuvent être falsifiés par un service compromis. Un futur assistant IA devra les traiter comme des données et jamais comme des instructions.

Une réponse 403 du WAF sans réponse d'amont est classée `waf_block`. Une réponse 401/403 émise par l'application est classée `access_denied`. Les 429 et 5xx ont leurs propres événements. Les paiements confirmés et demandes de redémarrage autorisées sont visibles si le service source les émet. Aucun résultat métier ou paiement n'est inventé.

## Continuité, limites et disque

Collecte toutes les 5 secondes, fenêtre glissante de 60 secondes, maximum 1000 lignes par conteneur et 2 Mio par réponse Docker. Huit sources sont attendues. Un battement toutes les 20 secondes décrit explicitement `observed`, `failed` et `missing`. Le panneau des battements n'est pas à lui seul une preuve que les huit sources fonctionnent : lire ces listes ou exécuter la recette.

Le collecteur déduplique avec un identifiant de conteneur, un timestamp et le contenu filtré. Les 20 000 derniers identifiants sont persistés après acceptation par Loki. Une réponse perdue après stockage peut produire un rejeu ; Loki peut dédupliquer les événements identiques. Il n'existe pas de file durable de tous les messages non envoyés. Une interruption de plus de 60 secondes, une rotation des journaux, un gros débit dépassant 1000 lignes/minute/service ou la borne de 2 Mio peuvent entraîner des pertes. Les conteneurs TTY et formats Docker non multiplexés sont volontairement non pris en charge et apparaissent en échec. Cette configuration est adaptée au laboratoire à faible débit, pas à un journal de conformité exhaustif.

Volumes séparés : rearm_logs_loki_v1 et rearm_logs_checkpoint_v1. Aucune modification du volume PostgreSQL ni du volume Grafana. Rétention Loki 72 heures via le compactor, suppression différée de 2 heures, index journalier. Cette rétention n'est pas un quota disque : WAL, index et délai de compactage peuvent ajouter de l'espace. Surveiller l'espace Docker Desktop et conserver les sauvegardes en dehors de ces volumes. Un disque plein n'est pas réparé par cette étape.

Plafonds supplémentaires : Loki 512 Mio / 0,75 CPU ; passerelle 128 Mio / 0,25 CPU ; collecteur 128 Mio / 0,25 CPU, soit au plus 768 Mio de mémoire configurée. Ce sont des limites, pas une mesure réelle. Processus sans capacités Linux, racines en lecture seule et journaux techniques des trois nouveaux services limités à 3 × 5 Mio chacun. Le collecteur s'exécute sans privilège ; la passerelle nécessite l'accès au socket de l'hôte. Loki utilise l'utilisateur prévu par son image officielle.

## Dépannage et retour arrière

`docker compose ps -a loki log-gateway log-collector grafana`

`docker compose logs --since=2m --tail=30 log-collector loki log-gateway`

Ne pas coller de journaux bruts d'autres services contenant des identifiants. `collection_failed` indique une erreur ; un démarrage Loki peut nécessiter 30 à 60 secondes. Les services de collecte réessaient automatiquement.

Retour arrière : `python scripts/logging_rollback.py`, puis `docker compose up -d --no-deps --force-recreate grafana`. Le script vérifie qu'aucun fichier ciblé n'a été modifié entre-temps, restaure les fichiers précédents et retire les fichiers ajoutés par ce patch, après vérification. Il ne supprime ni secrets ni volumes. Arrêter ensuite les trois conteneurs devenus orphelins dans Docker Desktop, sans supprimer leurs volumes. Ne jamais exécuter `docker compose down -v` pour cette opération.

## Validation effectuée avant livraison

Tests du filtre, classification WAF/app, suppression de secrets et routes privées, trames Docker, bornage du périmètre, déduplication, réseau et socket. Contrôles des frontières WAF et supervision. Configuration vérifiée par le binaire Loki 3.7.9 officiel, téléchargé et contrôlé avec son SHA-256 publié. Exécution locale de Loki avec la vraie passerelle et le collecteur, une source Docker simulée, ingestion/query, checkpoint et toutes les expressions LogQL du tableau.

Docker Desktop, le matériel et le compte Stripe de l'utilisatrice ne sont pas accessibles dans cet environnement de construction. L'intégration Compose réelle et les parcours métier restent à valider sur le PC avec les étapes ci-dessus. Ce patch ne prouve pas la résistance à une attaque ni la récupération autonome complète du SI. L'absence de log d'erreur ne prouve pas l'absence d'incident. Aucun nouveau moteur de corrélation, SIEM, notification externe ou réparation n'est inclus.

## Sources officielles

- https://github.com/grafana/loki/releases/tag/v3.7.9
- https://grafana.com/docs/loki/latest/configure/
- https://grafana.com/docs/loki/latest/reference/loki-http-api/
- https://grafana.com/docs/loki/latest/operations/storage/retention/
- https://grafana.com/docs/loki/latest/operations/storage/filesystem/
- https://docs.docker.com/reference/api/engine/
