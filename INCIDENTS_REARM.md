# REARM — Détection et suivi des incidents

Ajout du 21 octobre 2026. Un moteur de corrélation de laboratoire lit Prometheus et les journaux filtrés de Loki, confirme les signaux sur deux observations et conserve les ouvertures/résolutions. Il n'exécute aucune réparation. Les mécanismes ML et de remédiation existants restent inchangés et séparés. Cette étape n'est ni un SIEM complet ni un détecteur universel de failles.

## Installation guidée

Depuis le dossier du projet, après extraction du ZIP à côté du projet :

1. Exécuter `install.py` avec son chemin complet. Aucun conteneur ni secret n'est modifié par une commande Docker à cette étape.
2. `docker compose config --quiet`
3. `docker compose up -d --build --no-deps incident-engine`
4. `docker compose restart prometheus grafana` : applique la nouvelle cible de collecte et recharge le tableau. Les données et le compte Grafana sont conservés. Une brève interruption des mesures et de l’interface Grafana est possible.
5. Attendre 45 à 60 secondes. Le fournisseur de tableaux Grafana relit les fichiers automatiquement ; un rafraîchissement du navigateur peut être nécessaire. Ouvrir http://localhost:3001 → Dashboards → REARM → **REARM — Incidents corrélés**.
6. `python scripts/incident_check.py` : mot de passe Grafana masqué. Attendre moteur collecté, cycle récent et 10 règles déterminées. Le contrôle est en lecture seule. Des incidents peuvent être ouverts : les lire plutôt que déduire que le SI est sain.
7. `python scripts/incident_demo.py` seulement dans le laboratoire REARM : six requêtes GET inertes, bornées, refusées par le WAF, puis vérification de l'ouverture ET de la résolution. Laisser le script attendre, sans appuyer sur F5 ou relancer les requêtes. Il ne passe aucune commande métier, n'exécute aucun JavaScript et ne demande aucune réparation. Voir ci-dessous les délais.
8. Vérifier le parcours personnel caméra puis mot de passe et un paiement Stripe de test (listener ouvert), et contrôler `docker stats --no-stream`.

Aucun nouveau mot de passe n'est requis. Ne pas partager `.env`, les fichiers caméra/firmware, les dumps ou les mots de passe.

## Règles et interprétation

Cycle nominal : 15 secondes, deux observations consécutives concordantes pour ouvrir ou résoudre. Une valeur indéterminée interrompt la série de confirmation, sans résoudre un incident ouvert. Les compteurs WAF ne sont lus que lorsque le collecteur indique huit sources lisibles, sans source manquante/en échec et avec un battement datant de moins de 45 secondes. Une réponse Loki valide sans série pour un événement dans la minute vaut zéro uniquement dans ce contexte. Une erreur réseau, une réponse invalide ou une collecte incomplète ne vaut jamais zéro.

| Règle | Ouverture | Résolution confirmée | Sévérité |
|---|---|---|---|
| backend_down | Sonde API+base en échec, collecte de sonde réussie | Sonde réussie | Critique |
| auth_down | Sonde authentification en échec, collecte réussie | Sonde réussie | Critique |
| store_down | Catalogue via WAF en échec, collecte réussie | Sonde réussie | Critique |
| remediation_down | Sonde HTTP remédiation en échec, collecte réussie | Sonde réussie | Critique |
| monitoring_gap | Au moins une mesure des quatre sondes manque ou sa collecte échoue | Quatre mesures fraîches et collectées | Avertissement |
| logging_gap | Battement absent, ancien, sources incomplètes ou requête de compteur en échec | Battement complet et requêtes réussies | Avertissement |
| waf_burst | Au moins 5 refus WAF dans la dernière minute | Au plus 2 dans la dernière minute | Avertissement |
| access_burst | Au moins 5 refus 401/403 d'amont vus au WAF dans la minute | Au plus 2 | Avertissement |
| rate_burst | Au moins 3 réponses 429 vues au WAF dans la minute | Au plus 1 | Avertissement |
| server_errors | Au moins 3 réponses 5xx vues au WAF dans la minute | Au plus 1 | Critique |

Chaque ligne requiert deux observations ; les compteurs utilisent une hystérésis entre les seuils d'ouverture et de clôture. Dans cette zone intermédiaire, l'état reste indéterminé. Le panneau « Règles observables » peut donc être inférieur à 10 même sans problème technique. La résolution signifie que le signal de cette règle est revenu à la normale ; elle ne prouve pas qu'une attaque est terminée ou qu'un paiement fonctionne.

Les statuts HTTP sont comptés uniquement au WAF pour éviter de compter la même requête au frontend et à l'API. Le classificateur distingue un refus WAF sans réponse d'amont d'un refus provenant de l'application. Un refus peut être légitime, un test ou un faux positif ; les données filtrées ne permettent pas d'attribuer une attaque, d'identifier un utilisateur ou de regrouper par IP. Le débit de logs reste soumis aux limites du collecteur précédent (60 secondes, 1000 lignes/service/fenêtre, borne de lecture). Le moteur n'a pas de garantie d'exhaustivité sous forte charge.

Un échec de collecte de sonde (`up=0`) n'est pas transformé en preuve de panne du service : il déclenche une lacune de supervision. Les échantillons de sondes et de `up` de plus de 45 secondes sont exclus. Les incidents de service déjà ouverts restent ouverts lorsque les observations deviennent inconnues.

## Modèle ML existant

`ml_anomaly=true` désigne une observation atypique par rapport au petit jeu de calibration ; ce n'est ni une preuve d'attaque ni un score de vulnérabilité. Le détecteur actuellement déployé vérifie ses propres conditions avant de demander une récupération du backend. Le présent moteur n'a pas de modèle ML supplémentaire : il apporte des règles lisibles, des confirmations temporelles, un historique et la distinction entre absence de données et retour à la normale. Il ne reçoit pas de capacité d'exécuter des commandes. L'intégration ultérieure de l'assistant/RAG et de scénarios de reprise contrôlés reste un chantier distinct.

## Recette contrôlée

Le script de démonstration vérifie d'abord Grafana et le catalogue, refuse de démarrer si un incident WAF est déjà actif, puis envoie seulement six charges XSS inertes en paramètres de GET. Le WAF doit les refuser (403). Les requêtes ne sont pas exécutées dans un navigateur.

L'ouverture attend : collecte des logs (environ 5 s), deux observations moteur et la collecte Prometheus suivante (15 s). Le script laisse jusqu'à 90 s pour observer l'ouverture. La résolution attend la sortie de la fenêtre glissante d'une minute, deux confirmations et la collecte suivante ; elle peut prendre environ 60 à 100 s après les requêtes. Le script laisse 150 s après l'ouverture. Ces délais de corrélation de sécurité ne sont pas une démonstration de reprise métier en moins de 60 s.

Résultat attendu : `RECETTE CORRÉLATION OK`, avec événement `incident_opened`, puis `incident_resolved`, règle `waf_burst`, et `repair_executed=false`. Les horodatages sont UTC. Une activité parallèle peut maintenir le signal : ne pas forcer l'état à zéro pour réussir le test.

## Réseaux, privilèges et stockage

Un seul nouveau service, sans port publié, sans variable d'environnement secrète, sans socket Docker et sans accès réseau aux passerelles de contrôle Docker. Réseaux existants observability (Prometheus) et log_store (Loki). Processus Python sans privilège, capacités retirées, racine en lecture seule ; seul `/state` est persistant. Plafond 128 Mio de RAM, 0,25 CPU, 64 processus et logs techniques limités à 3 × 5 Mio. Le réseau d'accès Grafana `grafana_access` et la publication locale `127.0.0.1:3001:3000` sont conservés.

Le volume `rearm_incidents_v1` stocke SQLite : règle, date d'ouverture et de résolution, identifiant technique d'incident et événements sortants filtrés. Aucun nom client, texte libre de log, corps HTTP, clé, mot de passe ou visage n'y est inséré. Une seule ouverture active par règle est autorisée. Les incidents ouverts survivent au redémarrage ; les séries de confirmation repartent de zéro après redémarrage. L'historique résolu est conservé sept jours ; la purge logique ne constitue pas un quota disque.

Une boîte d'envoi persistante écrit les transitions dans Loki après confirmation locale. Les échecs d'envoi restent en attente. Les événements de plus de 3500 secondes sont marqués expirés pour éviter de bloquer sur le rejet des anciens échantillons de Loki ; ils ne sont pas présentés comme livrés. Les incidents actuels et l'historique SQLite restent disponibles. Le tableau expose le nombre d'événements en attente/expirés. Une confirmation réseau perdue après stockage peut occasionner un rejeu du même événement horodaté.

L'historique Grafana via Loki suit sa rétention actuelle de 72 h, indépendamment des sept jours SQLite. Le tableau ne remplace ni un archivage immuable, ni une investigation, ni un SIEM de production.

## Dépannage et retour arrière

`docker compose ps -a incident-engine prometheus`

`docker compose logs --since=2m --tail=25 incident-engine`

Les logs de ce moteur ne contiennent que des noms fixes de règle, identifiants techniques et types d'erreur. Une erreur de lecture entraîne des états inconnus ou des incidents de collecte ; elle ne déclenche aucune action Docker.

Retour arrière : `python scripts/incident_rollback.py`, puis `docker compose restart prometheus`. Arrêter le conteneur incident-engine devenu orphelin dans Docker Desktop, sans supprimer son volume. Le fournisseur Grafana conserve éventuellement le tableau même après retrait du fichier (disableDeletion) : il peut alors afficher des mesures anciennes/absentes et ne doit plus être utilisé. Aucun secret ni volume métier n'est supprimé. Ne pas exécuter `docker compose down -v`.

## Validation avant livraison et limites

Tests unitaires : confirmations, répétition, états inconnus, persistance, réouverture, distinction panne/collecte, fraîcheur et exhaustivité des battements, seuils/hystérésis, valeurs invalides, boîte d'envoi, métriques et frontières réseau. Validation Promtool de la configuration Prometheus. Exécution intégrée locale avec les vrais binaires Prometheus et Loki, des sources de sondes simulées, échecs/rétablissement, refus WAF filtrés et toutes les requêtes du tableau. Cette exécution accélère le scrape à 1 s et la fenêtre de comptage à 3 s ; les fichiers livrés gardent 15 s et 60 s.

La pile Compose réelle, Docker Desktop et les parcours avec le matériel/Stripe restent à vérifier sur le PC de l'utilisatrice. L'environnement de construction n'a pas son démon Docker ni ses secrets. Cette étape ne garantit ni la détection de toutes les attaques, ni une correction de vulnérabilité, ni une reprise du PC si Windows/Docker s'arrête. Les actions autonomes devront être bornées, tracées et validées par un retour métier, avec un mécanisme extérieur pour la panne de l'hôte.
