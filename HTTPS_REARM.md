# REARM — HTTPS local pour la boutique

## Résultat et périmètre

Après activation, ouvrir **https://localhost** sur le PC hôte. Sur le réseau
du laboratoire, l'adresse préparée par défaut est **https://192.168.137.1**.
Le certificat couvre localhost, 127.0.0.1, ::1 et l'IPv4 privée choisie. Le port
443 du PC est transmis au port non privilégié 8443 du conteneur edge existant.
Le WAF, la segmentation, les restrictions Docker et le circuit Ansible restent
en place. Aucun nouveau conteneur ne reçoit le socket Docker.

Le navigateur utilise TLS 1.2 ou 1.3. Les applications émettent les sessions
avec `COOKIE_SECURE=true` ; Nginx ajoute aussi Secure, HttpOnly et SameSite=Strict
aux cookies `ra_session` et `rc_session`. Le retour Stripe utilise HTTPS.

**Cette étape ne chiffre pas tous les flux du SI.** La terminaison TLS est sur
edge ; les échanges internes Docker restent en HTTP. La caméra native et l'ESP
gardent temporairement leur protocole et leurs URL existants. Le listener Stripe
conserve son URL de transfert HTTP locale. Le durcissement TLS de ces clients et
la rotation de leurs secrets sont des étapes distinctes. Ne pas présenter cette
installation comme un chiffrement de bout en bout, une PKI de production ou une
publication du site sur Internet.

Les journaux et les sondes existants restent accessibles. La sonde Prometheus
« Boutique via WAF » continue de contrôler le catalogue HTTP historique : elle
ne vérifie pas automatiquement le certificat HTTPS. La nouvelle recette
`https_check.py` effectue ce contrôle sur le PC. Grafana reste volontairement
sur http://localhost:3001 dans cette étape.

## Certificats et clés

mkcert 1.4.4 a déjà été installé avec WinGet. Le script le retrouve même lorsque
son alias n'est pas dans PATH, notamment dans le dossier WinGet observé sur le
PC de l'utilisateur. Sous Windows x64, l'empreinte SHA256 du binaire est comparée
à celle du manifeste Microsoft WinGet avant utilisation.

Une autorité dédiée à ce projet et un certificat serveur sont créés sous :

```text
%LOCALAPPDATA%\REARM-secrets\tls\<identifiant-du-chemin-du-projet>\
```

Le sous-dossier `ca` contient `rootCA.pem` (public) et `rootCA-key.pem` (privé).
Le sous-dossier `leaf` contient le certificat serveur, sa clé et la configuration
Nginx. Seul `leaf` est monté en lecture seule dans edge : **la clé privée CA
n'entre jamais dans Docker, dans une image ou dans le ZIP de sources**.

Les répertoires sont protégés avant la génération. Les fichiers sont ensuite
protégés et leurs DACL relues avec le mécanisme déjà validé sur ce PC : compte
courant et SYSTEM. La génération ne lance pas `mkcert -install`. La confiance
est ajoutée dans une commande séparée, uniquement au magasin Root du compte
Windows courant, avec `certutil -user` et le certificat public attendu.

Une autorité reconnue par un navigateur peut émettre des certificats acceptés
par ce navigateur. Sa clé doit donc rester privée. Ne jamais partager
`rootCA-key.pem` ou `key.pem`. La clé age et les trois fichiers runtime restent
également privés. La sauvegarde SOPS actuelle couvre toujours ses trois fichiers
de configuration : elle ne sauvegarde pas automatiquement les nouvelles clés
TLS. Prévoir leur garde séparée si cette autorité doit être conservée.

## Déploiement, une commande à la fois

Conserver la fenêtre de la caméra et celle du listener Stripe ouvertes. Utiliser
le compte Windows habituel. Ne pas avoir de paiement en cours lors du changement
des services. Les clients devront se reconnecter dans la page HTTPS pour obtenir
des cookies Secure ; les anciennes sessions de la base ne sont pas supprimées.

1. Extraire `REARM-HTTPS.zip` à côté du projet et lancer son installateur depuis
   PowerShell ouvert dans le projet existant. Il installe seulement les scripts,
   le modèle Nginx et ce guide. Il ne crée pas de certificat, ne modifie pas la
   confiance Windows et ne redémarre aucun service.

2. Préparer les certificats et les paramètres :

   ```powershell
   python scripts/https_setup.py
   ```

   Pour l'IPv4 proposée, appuyer sur Entrée si le PC utilise toujours
   192.168.137.1 pour le réseau RESILIENCE-G. Le script refuse une adresse hors
   des plages privées RFC1918. Il vérifie aussi que le port 443 n'est pas occupé
   ou réservé. En cas de conflit, ne pas arrêter un autre service au hasard :
   diagnostiquer le port avant de continuer.

   Un échange TLS local vérifie déjà la chaîne et les noms localhost et IPv4.
   Une sauvegarde SOPS est créée AVANT le changement de `.env` ; aucune copie
   supplémentaire de `.env` en clair n'est enregistrée pour le retour arrière.
   Seuls ALLOWED_ORIGINS, COOKIE_SECURE, PAYMENT_PUBLIC_URL et REARM_TLS_CERT_DIR
   sont ajustés. Les autres lignes et identifiants sont conservés.

   Un `docker-compose.override.yml` est créé. Compose le charge automatiquement
   avec le fichier de base, y compris lors des futures commandes normales.
   Le script refuse de remplacer une surcharge déjà existante. La nouvelle
   configuration conserve le port HTTP 3000 et ajoute 443 ; elle remplace le
   montage de la configuration edge par celui de la configuration TLS externe.

3. Ajouter explicitement la confiance locale au compte Windows :

   ```powershell
   python scripts/https_setup.py trust
   ```

   Cette commande importe seulement le certificat public de cette autorité dans
   le magasin Root de l'utilisateur, après vérification de son empreinte. Elle
   ne nécessite pas la clé privée dans le navigateur. Elle ne configure pas
   Firefox/NSS, les autres comptes ou les autres PC. Pour cette recette utiliser
   Chrome ou Edge, puis fermer/rouvrir le navigateur si nécessaire.

4. Vérifier Compose sans afficher les secrets :

   ```powershell
   docker compose config --quiet
   ```

5. Tester Nginx et la lecture de la clé depuis Docker Desktop AVANT d'appliquer :

   ```powershell
   docker compose run --rm --no-deps edge nginx -t
   ```

   Cette instance temporaire ne publie pas les ports du service. Elle doit
   confirmer la validité de la configuration. Si elle signale une erreur de
   certificat ou de droits, ne pas passer à la suite et ne pas élargir les
   permissions de la clé pour contourner le contrôle.

6. Appliquer les variables et l'entrée HTTPS :

   ```powershell
   docker compose up -d --no-deps --force-recreate backend auth edge
   ```

   Une courte indisponibilité est attendue. Il n'y a pas de reconstruction
   d'image, de migration SQL ou de suppression de données. Le modèle et la
   calibration du détecteur ne sont pas redémarrés par cette commande.

7. Exécuter la recette :

   ```powershell
   python scripts/https_check.py
   ```

   Elle vérifie le catalogue via WAF en HTTPS, la chaîne et le nom, la redirection
   HTTP, la conservation de la sonde historique et COOKIE_SECURE dans les deux
   services. Sur Windows, une seconde requête utilise aussi la confiance par
   défaut de Python/Windows, sans CA explicite. Aucun paiement, création de
   compte, envoi d'attaque ou arrêt de service n'est effectué par cette recette.
   Ne pas utiliser d'option désactivant la vérification TLS pour obtenir un OK.

8. Ouvrir https://localhost. Vérifier l'absence d'alerte de certificat. Se
   déconnecter puis reconnecter les comptes client et personnel dans HTTPS.
   Tester le parcours visage → mot de passe → espace équipe. Puis effectuer une
   NOUVELLE commande Stripe TEST pour vérifier le retour du paiement sur HTTPS
   et son état payé. Garder le listener Stripe existant : son URL de transfert
   n'a pas changé. Une simple page de retour n'est pas une preuve de paiement.

9. Mettre à jour la sauvegarde SOPS avec le nouveau `.env` :

   ```powershell
   python scripts/secrets_vault.py seal
   python scripts/secrets_vault.py check
   ```

   Jusqu'à ce scellement, une différence avec la dernière sauvegarde est normale
   après la modification HTTPS. La clé age et les anciens snapshots sont conservés.

10. `python scripts/recovery_check.py` pour contrôler le backend et les dossiers
    de reprise existants. La validation antérieure à 30,4 s reste une preuve du
    scénario précédent ; HTTPS n'est pas une nouvelle recette de panne en soi.

## Compatibilité HTTP maintenue et délimitation

Sur le port 3000, seules les routes suivantes continuent de passer par le WAF :

| Route | Usage |
| --- | --- |
| `/api/face-agent/*` | Agent caméra natif avec son jeton existant |
| `/api/device/led` (GET) | ESP8266 actuel |
| `/api/shop/payments/webhook` (POST) | Transfert local signé de Stripe CLI |
| `/api/shop/products` (GET) | Sonde et tests historiques du catalogue |

Le reste de la navigation est redirigé avec un HTTP 308 vers HTTPS. Le choix de
l'hôte de redirection est fermé : localhost, 127.0.0.1 ou l'IPv4 préparée ; une
valeur Host arbitraire ne peut pas fabriquer une redirection vers un site tiers.
Le port de redirection est le port standard 443, et non l'ancien port 3000.
`/healthz` reste masqué avec un 404.

La caméra native actuelle utilise son HTTP de boucle locale et l'ESP son HTTP
sur le réseau Wi-Fi. Ces exceptions sont volontairement visibles et doivent
être retirées après une migration propre des clients, avec validation du
certificat par le firmware. Ne pas utiliser `setInsecure()` comme équivalent à
une telle migration. Les communications HTTP internes, Prometheus, Loki et
Grafana ne sont pas transformées en mTLS par ce correctif.

HSTS n'est pas ajouté : il s'applique au nom d'hôte et pourrait faire basculer
les autres ports de localhost, dont Grafana 3001, vers un TLS qu'ils ne servent
pas encore. Ce choix de transition ne doit pas être décrit comme un durcissement
HSTS complet. La CSP existante est conservée, y compris ses restrictions et ses
directives inline actuelles ; elle n'est pas présentée comme une CSP stricte.

## Accès depuis le second PC

Le second PC doit joindre l'IPv4 préparée sur le port 443 et reconnaître cette
autorité. Ne copier vers lui que le certificat PUBLIC `ca/rootCA.pem`, jamais
la clé CA ni la clé serveur. Comparer localement son empreinte SHA256 à celle
affichée à la préparation, puis installer cette autorité pour le compte de
laboratoire concerné. Les réglages du pare-feu Windows et le réseau doivent
être vérifiés avant d'ouvrir un accès supplémentaire ; aucun pare-feu n'est
désactivé par les scripts. Cette étape ne publie rien sur Internet.

Si un checkout doit être effectué depuis le second PC, configurer d'abord son
URL de retour Stripe sur l'adresse HTTPS du PC hôte : `https://localhost`
désignerait le second PC lors du retour. Cette configuration doit rester dans
ALLOWED_ORIGINS. Le script `payment_setup.py` existant peut la changer avec les
clés TEST conservées localement, puis il faut réappliquer backend et resceller
la configuration SOPS. Ne pas communiquer les clés dans la conversation.

## Réversibilité

Si la confiance locale doit être retirée pour ce compte, la commande explicite
suivante retire seulement ce certificat du magasin utilisateur :

```powershell
python scripts/https_setup.py untrust
```

Le serveur HTTPS resterait alors actif mais son certificat ne serait plus
reconnu par ce compte. Pour revenir à la configuration HTTP précédente :

```powershell
python scripts/https_rollback.py
docker compose up -d --no-deps --force-recreate backend auth edge
python scripts/secrets_vault.py seal
```

Le script récupère les anciennes valeurs gérées depuis le snapshot SOPS
authentifié, conserve les autres secrets éventuellement modifiés depuis, et
retire uniquement sa surcharge Compose reconnue. Il refuse un retour automatique
si ces éléments ont été modifiés entre-temps. Il conserve les certificats, clés,
données et preuves ; il ne retire pas silencieusement la confiance du navigateur.
L'action `untrust` peut aussi être utilisée après le retour.

Ne pas supprimer la CA pour renouveler un simple certificat serveur. Cette
version du script ne remplace pas automatiquement une configuration déjà
préparée. En cas de changement d'IP, d'expiration ou de déplacement du projet,
préparer une adaptation plutôt que désactiver la vérification TLS.

## Validation de préparation et limites pratiques

Dans l'environnement de préparation : vrais certificats mkcert 1.4.4, vérification
des noms et de la chaîne, Nginx 1.28.0 réel compilé pour les essais locaux, TLS
1.2/1.3 négociés, TLS 1.0/1.1 refusés, cookies renforcés et absence de redirection
ouverte. Les tests utilisent un faux upstream de catalogue sans opération métier.
Le Nginx d'essai utilise le seul UID disponible dans l'environnement isolé ; il
ne constitue pas une preuve du fonctionnement du bind mount Windows avec le
UID de l'image edge. L'image edge du projet et ses restrictions sont conservées.

Les régressions des paiements et de la reprise sont testées séparément avec
PostgreSQL embarqué et Stripe simulé. Aucun accès au compte Stripe, au Docker
Desktop ou au matériel de l'utilisateur n'a été utilisé pour ces tests.
La syntaxe/lecture du certificat dans l'image réelle et la confiance du navigateur
Windows doivent être validées avec les commandes ci-dessus sur le PC hôte.
Le certificat est destiné au laboratoire local, pas à un site marchand public.

Références officielles :

- mkcert : https://github.com/FiloSottile/mkcert
- Manifeste WinGet : https://github.com/microsoft/winget-pkgs/tree/master/manifests/f/FiloSottile/mkcert/1.4.4
- TLS Nginx : https://nginx.org/en/docs/http/ngx_http_ssl_module.html
- Fusion des montages/ports Compose : https://docs.docker.com/reference/compose-file/merge/
