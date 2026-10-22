# REARM — supervision des métriques et de la disponibilité

Cette étape ajoute Prometheus, Grafana et Blackbox Exporter. Elle collecte des mesures réelles et rend visibles les alertes de disponibilité. Elle ne centralise pas encore les journaux, ne fournit pas encore un SIEM et n’ajoute pas de nouvelle action de réparation automatique. Le détecteur existant reste conservé.

## Installation guidée

Extraire `REARM-supervision` à côté du projet actuel. Depuis PowerShell placé dans le projet actuel, exécuter `python` suivi du chemin complet de l’installateur extrait. Les fichiers sont contrôlés et sauvegardés avant remplacement. L’installateur ne lance pas Docker et ne touche ni à la base, ni à `.env`, ni aux réglages Stripe/caméra/LED.

Ensuite, une commande à la fois :

```powershell
python scripts/monitoring_setup.py
docker compose config --quiet
docker compose pull prometheus blackbox grafana
docker compose up -d --build
```

Le script demande de choisir puis confirmer un mot de passe Grafana d’au moins 12 caractères, avec une saisie masquée. L’identifiant est **superviseur**. Conserver ce mot de passe localement ; ne pas envoyer `.env`. Le script ajoute seulement les deux variables de supervision et conserve toutes les autres lignes. Les variables sont obligatoires : il n’existe pas de mot de passe admin par défaut dans Compose. Une seconde exécution ne change pas le mot de passe déjà configuré.

Pour cette première installation, Grafana initialise un volume dédié, distinct des anciens volumes éventuels du projet. Lors d’un redémarrage ultérieur, sa base persistante conserve les comptes : modifier une variable d’environnement seule ne réinitialise pas le mot de passe d’un compte existant.

L’application et les sondes ont de nouveaux rattachements réseau. La commande recrée les services concernés ; une brève indisponibilité est possible. Éviter de faire la bascule pendant un paiement. L’agent caméra, l’ESP8266 et le listener Stripe restent dans leurs fenêtres habituelles.

## Utiliser le tableau de bord

Attendre environ 30 à 60 secondes après le démarrage, puis ouvrir **http://localhost:3001** sur le PC hôte. Se connecter avec `superviseur` et le mot de passe choisi. Ouvrir **Dashboards → REARM → REARM — Disponibilité du SI**. Le dashboard est provisionné automatiquement ; aucun import manuel n’est requis.

Il présente :

- Boutique et chemin WAF : le catalogue doit répondre HTTP 200 avec un corps de liste JSON et l’en-tête d’inspection WAF. Cela confirme le passage observé ; le pouvoir de blocage est vérifié séparément par `scripts/waf_check.py`.
- API et base : HTTP 200 sur la sonde API, qui interroge aussi PostgreSQL.
- Authentification et base : HTTP 200 sur sa sonde incluant PostgreSQL.
- Endpoint du remédiateur : santé de son serveur HTTP ; pas une preuve de redémarrage ou de réparation réussie.
- Durée des sondes, historique et disponibilité de la collecte.
- Proportion de 5xx et nombre de requêtes dans la fenêtre applicative existante : au maximum 100 requêtes `/api/`, en mémoire. Ce ne sont ni un total cumulatif ni des taux temporels ; un redémarrage réinitialise cette fenêtre.
- Alertes Prometheus actives ou en attente. Quand aucune alerte n’existe, la requête `ALERTS` ne renvoie pas de série.

Une sonde verte ne prouve pas qu’une connexion faciale ou un paiement aboutit. Une absence de mesures reste inconnue ; elle ne doit pas être interprétée comme un état sain. Le panneau SI du back-office lit également les observations Prometheus. Les libellés de chantiers restants évoluent selon les observations disponibles ; les journaux/SIEM et l’IA restent explicitement à réaliser.

## Vérifications sur le PC du workshop

```powershell
python scripts/monitoring_check.py
```

Ce script demande le mot de passe Grafana en saisie masquée, utilise la source Prometheus via Grafana, vérifie les quatre sondes, la collecte et la présence du dashboard. Il n’affiche pas le mot de passe et ne crée ni paiement ni réparation. Il attend au maximum environ une minute les premières mesures, hors temps des requêtes déjà en cours.

Contrôle de configuration avec le programme officiel inclus dans le conteneur :

```powershell
docker compose exec -T prometheus promtool check config /etc/prometheus/prometheus.yml
```

Vérifier ensuite une connexion administrateur par visage et mot de passe, puis une commande Stripe de test confirmée. Relever `docker stats --no-stream` et garder les résultats pour dimensionner les services suivants.

Une démonstration de panne contrôlée sera préparée après ces vérifications : les alertes de cette étape n’envoient aucune notification externe et ne déclenchent aucune nouvelle action automatique. Il ne faut pas arrêter la base ou supprimer un volume pour tester le dashboard.

## Réseaux et sécurité

Grafana est publié uniquement sur **127.0.0.1:3001**, donc depuis le PC hôte ; aucune exposition au hotspot n’est configurée. Le port public de la boutique reste 3000. Prometheus et Blackbox n’ont aucun port publié.

- `observability` : Grafana, Prometheus et Blackbox.
- `metrics_backend` : Prometheus lit les métriques API ; l’API lit les observations Prometheus pour son panneau SI.
- `probe_services` : Blackbox peut sonder API, authentification et remédiateur.
- `probe_public` : Blackbox accède au point d’entrée edge, qui conserve la chaîne WAF.

Ces quatre réseaux sont internes. Le frontend ne partage toujours pas de réseau avec edge et le WAF ne partage toujours pas de réseau avec la base ni le contrôle Docker. Aucun des trois nouveaux services ne monte le socket Docker et ils ne reçoivent aucun secret Stripe, caméra, LED, remédiation ou PostgreSQL. Le compte Grafana est séparé des comptes clients et des comptes du personnel.

Les trois images officielles sont épinglées par digest. Ils tournent avec les capacités Linux retirées, `no-new-privileges`, une racine en lecture seule et des volumes spécifiques pour les données persistantes. Aucun plugin externe n’est préinstallé, l’inscription et l’accès anonyme sont désactivés. La télémétrie produit et les vérifications automatiques de mises à jour sont désactivées. Cela ne dispense pas de mettre les images à jour de façon contrôlée.

L’interface Grafana reste en HTTP sur la boucle locale à cette étape ; la boutique reste aussi sur le protocole actuel. Le chantier HTTPS doit tenir compte de l’agent Windows, du retour Stripe et du firmware ESP8266 avant tout basculement.

## Ressources et persistance

Plafonds supplémentaires : Prometheus 512 Mio / 0,75 CPU ; Blackbox 128 Mio / 0,25 CPU ; Grafana 512 Mio / 1 CPU. Total maximal de mémoire configurée pour ces trois services : **1,125 Gio**. La consommation réelle doit être mesurée sur le PC, pas déduite de ces plafonds.

Les données Prometheus et Grafana sont dans des volumes dédiés. Prometheus conserve au plus trois jours de blocs ou environ 512 Mo de blocs, selon la limite atteinte en premier. La limite des blocs ne borne pas strictement tout le disque : journal WAL et données courantes s’ajoutent. Les journaux Docker de chaque nouvel outil ont une rotation de trois fichiers de 5 Mo. Aucune donnée commerciale ou biométrique n’est copiée dans ces volumes par les configurations livrées.

## Alertes et limites

- Échec de sonde pendant 30 secondes : `RearmServiceDown`.
- Collecte de sonde interrompue pendant 30 secondes : `RearmProbeCollectionFailed`.
- Métriques API non collectées pendant 30 secondes : `RearmBackendMetricsMissing`.
- Durée de sonde supérieure à 1,5 seconde pendant deux minutes : `RearmProbeSlow`.

Une panne de collecte est distinguée d’une mesure de service en échec. Prometheus ne peut pas évaluer ses propres règles lorsqu’il est lui-même arrêté. Une panne de Docker ou du PC nécessitera une observation et une reprise extérieures à cette pile. L’IA actuelle, ses décisions et son efficacité de récupération métier ne sont pas encore supervisées ici. Aucun numéro de carte, mot de passe, visage ou panier n’est envoyé comme label de métrique.

## Diagnostic et retour arrière

```powershell
docker compose logs --tail=30 prometheus blackbox grafana
```

Si une image ne démarre pas ou si un contrôle échoue, conserver les dernières lignes sans partager de secret. Pour revenir aux fichiers antérieurs :

```powershell
python scripts/monitoring_rollback.py
docker compose up -d --build backend auth edge
```

Arrêter ensuite précisément les anciens conteneurs `prometheus`, `blackbox` et `grafana` depuis Docker Desktop s’ils restent actifs après la restauration du fichier Compose. Ne supprimer aucun volume. Les données de supervision restent conservées et les données commerciales ne sont pas affectées.

## Validation effectuée lors de la préparation

Tests de politique réseau et d’absence de secrets inutiles ; test de préservation de `.env` et de non-affichage du mot de passe ; contrôles du panneau SI en cas de mesures présentes/absentes ; tests WAF adaptés à l’ajout du seul port de gestion local. Configuration et quatre règles validées par `promtool` 3.15.0 ; tests de règles vérifiant le délai de déclenchement, la disparition à la reprise et le signalement d’une collecte manquante.

Prometheus 3.15.0 et Blackbox Exporter 0.29.0 ont été démarrés localement hors Docker, après contrôle des sommes SHA-256 officielles. Sur des serveurs HTTP de test : quatre sondes réussies, échec si l’en-tête WAF manque ou si le corps n’est pas un catalogue, puis observation de la séquence sain → HTTP 503 → rétabli. Toutes les expressions PromQL du dashboard ont été acceptées par Prometheus.

Ces essais emploient des services HTTP de test et un intervalle raccourci ; ils ne représentent pas les conteneurs de l’utilisatrice. Grafana, les montages Docker, les ressources réelles, le matériel et le paiement Stripe doivent être vérifiés sur le PC. Aucun démarrage Docker n’a été effectué dans l’environnement de préparation.

## Références officielles

- https://prometheus.io/docs/guides/multi-target-exporter/
- https://prometheus.io/docs/operating/security/
- https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/
- https://github.com/prometheus/blackbox_exporter/blob/master/CONFIGURATION.md
- https://grafana.com/docs/grafana/latest/administration/provisioning/
- https://grafana.com/docs/grafana/latest/setup-grafana/configure-docker/
- Versions : Prometheus 3.15.0, Blackbox Exporter 0.29.0, Grafana 13.2.4 ; publications stables et digests consultés le 21 octobre 2026.
