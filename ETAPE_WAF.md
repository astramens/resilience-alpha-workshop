# REARM — étape 1 : WAF ModSecurity et OWASP CRS

Cette livraison ajoute un WAF devant la boutique, avec les règles OWASP CRS en blocage (niveau 1, seuil entrant 5). Elle ne termine pas le durcissement complet et ne remplace pas le futur travail de surveillance, d’IA, de sauvegarde/restauration ou de HTTPS.

## Installer progressivement

Extraire `REARM-WAF` à côté du projet existant. Depuis PowerShell placé dans le projet actuel, lancer `python` suivi du chemin complet de `install.py` extrait. L’installateur contrôle la version des fichiers et garde une copie avant remplacement. Il ne modifie ni `.env`, ni la base, ni Stripe, ni les empreintes faciales, ni le firmware, ni le détecteur.

Puis, une commande à la fois :

```powershell
docker compose config --quiet
docker compose pull waf
docker compose up -d waf edge
```

La dernière commande recrée aussi le frontend si son réseau a changé ; cela est nécessaire pour le placer derrière le WAF. Aucun build du frontend n’est requis : son image n’a pas changé. Une brève indisponibilité est possible pendant cette bascule. Attendre la fin d’une éventuelle commande/paiement avant de la lancer. Garder l’agent caméra, l’ESP8266 et le listener Stripe dans leurs fenêtres habituelles.

Vérifier ensuite :

```powershell
docker compose ps
python scripts/waf_check.py
```

À la question URL, appuyer sur Entrée pour le PC hôte. Depuis le PC de test autorisé sur le hotspot, employer `http://192.168.137.1:3000` et exécuter une copie de ce même script, sans identifiant ni secret.

La recette attend : HTTP 200 pour le catalogue, HTTP 403 pour les deux chaînes XSS/SQLi inertes placées dans un paramètre ignoré du catalogue, HTTP 200 pour le catalogue après les sondes, HTTP 400 provenant du validateur de signature Stripe pour un faux webhook inoffensif. Aucun script n’est exécuté dans un navigateur, aucune commande SQL n’est exécutée par cette recette et aucun paiement ou stock n’est modifié.

Enfin tester les parcours réels : reconnaissance faciale, connexion administrateur et connexion client, puis une commande Stripe avec carte de test. La recette technique du WAF ne remplace pas ces contrôles. L’adresse de la boutique et les paramètres Stripe/caméra/LED restent inchangés.

## Architecture et réglages

Port public 3000 → edge Nginx (en-têtes et limitation de débit) → WAF → frontend → API/authentification. Le frontend ne partage plus de réseau avec edge. Le WAF est sur deux réseaux internes dédiés et ne partage aucun réseau avec la base, l’API, le service d’authentification, le détecteur, le remédiateur ou son accès Docker. Seul edge publie un port. L’arrêt du WAF rend la boutique indisponible ; il n’existe pas de contournement automatique vers le frontend.

Image officielle : `owasp/modsecurity-crs:nginx-alpine`, épinglée par le digest multiarchitecture `sha256:873ce68a658d2e3b61484a8a24d215f7d15456e7ce5aec5e7114bf000d743365`. Digest résolu dans le registre et configuration de l’image amd64 consultée le 21 octobre 2026 : utilisateur `nginx`, image créée le 18 octobre 2026. Cette vérification ne constitue pas un scan de vulnérabilités de l’image.

Limites : 512 Mio de mémoire, 1 CPU, 128 processus, 1 worker Nginx. Il s’agit d’un plafond, pas d’une consommation mesurée sur le PC. L’ajout du WAF doit être mesuré avant de dimensionner les services suivants sur les 11,6 Go disponibles dans Docker.

Inspection des corps entrants activée, JSON limité à une profondeur de 64 et corps limité à 64 Kio, comme l’edge et le proxy existants. Les réponses sortantes ne sont pas analysées par CRS à cette étape, pour éviter de bloquer le JavaScript Next et les données applicatives. Aucune règle n’est désactivée pour l’ensemble des endpoints caméra ou Stripe. Pas d’exclusion globale sur le paiement. Un faux positif doit être diagnostiqué et traité de façon ciblée, sans passer tout le moteur en DetectionOnly.

L’edge écrase l’adresse client et l’identifiant de corrélation avant le WAF. Le WAF préserve le Host avec son port, Origin, Authorization, les cookies et Stripe-Signature. Il n’effectue aucune réécriture du corps signé Stripe. Les réponses portent `X-Rearm-Inspection: active` et un identifiant de requête pour le diagnostic.

Les templates sont montés en lecture seule ; le conteneur WAF tourne sans capacités Linux et avec `no-new-privileges`. Son système de fichiers racine reste inscriptible, car l’image officielle prépare sa configuration au démarrage. Il n’a aucun volume de données ni montage Docker. Les templates read-only non publiés ne sont pas employés.

## Journaux limités et diagnostic

```powershell
docker compose logs --since=2m --tail=30 waf
docker stats --no-stream
```

Journal d’accès WAF JSON : événement, identifiant de corrélation, méthode, chemin sans paramètres de requête, statut HTTP, statut amont et durée. Un 403 avec statut amont vide indique un blocage avant le frontend ; un 403 renvoyé par l’application présente un statut amont 403. Le script de recette contrôle aussi le comportement du catalogue.

L’audit ModSecurity natif est limité aux parties A/Z (identifiant et métadonnées de transaction, sans en-têtes, corps ni messages détaillés de règles). Les diagnostics Nginx/CRS sont limités au niveau critique, car les messages de correspondance détaillés peuvent recopier une valeur sensible. Le journal d’accès garde la trace de l’issue HTTP mais pas l’identifiant de la règle CRS déclenchée. Ne pas activer les parties d’audit par défaut ou un niveau de debug sur de vrais mots de passe/biométries. Cette livraison ne prétend pas fournir un SIEM complet.

Rotation Docker des journaux WAF : trois fichiers de 5 Mo. L’état WAF ne figure pas encore dans la supervision du back-office ; le libellé WAF de sa liste de chantiers doit être remplacé par un indicateur observé lors de l’étape de supervision.

## Revenir à la configuration précédente

Si nécessaire, depuis le projet actuel :

```powershell
python scripts/waf_rollback.py
```

Le script choisit la dernière sauvegarde WAF, vérifie que les fichiers n’ont pas changé depuis l’installation, puis restaure les trois fichiers de routage précédents. Il ne modifie pas de données et ne lance pas Docker. Appliquer ensuite :

```powershell
docker compose up -d frontend edge
```

Après restauration, `waf` n’est plus déclaré par le fichier Compose de base. Arrêter précisément l’ancien conteneur WAF depuis Docker Desktop. Aucun `down -v` n’est nécessaire. Les anciennes versions des fichiers restent dans la sauvegarde.

## Ce qui a été vérifié ici

Cinq tests de politique passent : absence de chemin réseau direct edge/frontend, absence d’accès WAF vers la base et le contrôle, conservation des en-têtes et de la taille de requête, limitation des journaux sensibles, image épinglée et ressources bornées. YAML et syntaxe Python contrôlés ; contrôle de l’installateur/retour arrière sur une copie de l’export.

Pas de Docker daemon disponible dans l’environnement de préparation : ni démarrage du conteneur, ni traitement réel par le moteur CRS, ni test du matériel, ni nouveau paiement Stripe n’ont été exécutés ici. Les résultats de `waf_check.py` sur le PC du workshop feront foi pour cette étape.

## Suite du projet

Après validation du WAF : HTTPS avec prise en compte du client ESP8266 et de l’agent Windows ; identités SQL séparées et secrets protégés ; métriques et journaux centralisés ; détection et remédiations bornées avec historique, temporisation et vérification d’une nouvelle commande payée en test ; reprise des dépendances et de la base ; mécanisme extérieur aux conteneurs pour une panne Docker/Windows. Un modèle d’IA exécuté sur le même PC ne peut pas agir pendant l’arrêt de ce PC.

## Sources officielles consultées

- https://github.com/coreruleset/modsecurity-crs-docker
- https://github.com/coreruleset/modsecurity-crs-docker/blob/main/README.md
- https://github.com/coreruleset/modsecurity-crs-docker/blob/main/nginx/Dockerfile-alpine
- https://github.com/coreruleset/modsecurity-crs-docker/blob/main/nginx/templates/nginx.conf.template
- https://github.com/coreruleset/modsecurity-crs-docker/blob/main/nginx/templates/conf.d/modsecurity.conf.template
