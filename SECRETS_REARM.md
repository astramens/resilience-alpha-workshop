# REARM — Sauvegardes de configuration chiffrées avec SOPS et age

## Périmètre de cette étape

Cette étape crée une sauvegarde chiffrée des trois fichiers actuellement
nécessaires au laboratoire : `.env`, `.camera-agent.json` et
`esp8266-led/include/secrets.h`. Elle préserve exactement leurs octets, y compris
les caractères accentués, guillemets et fins de ligne. Elle ne change ni les
identifiants, ni les ports, ni le contenu du firmware, ni les services Docker.
La reprise Ansible validée en 30,4 s et la preuve RA-00007 restent inchangées.

**Les fichiers utilisés par Compose, la caméra et PlatformIO restent en clair
sur le PC.** Le correctif limite leurs droits d'accès et protège leurs copies
de sauvegarde avec SOPS/age. Ce n'est pas une injection de secrets chiffrés
directement dans les conteneurs, un coffre Vault, une rotation automatique ou
une suppression de toute trace de secrets en clair dans le SI. Les secrets
restent aussi accessibles aux processus qui doivent les utiliser, notamment
dans l'environnement des conteneurs et dans le firmware programmé sur l'ESP.

Le chiffrement des dumps PostgreSQL et leur restauration dans un SI séparé
constituent un autre exercice. Ces dumps, qui peuvent contenir des données
biométriques, ne sont pas inclus dans cette sauvegarde des trois configurations.

## Protection et fonctionnement

SOPS 3.12.2 utilise un destinataire age X25519 généré localement par age 1.3.2.
La clé privée est enregistrée hors du projet, pour le compte Windows courant :

```text
%LOCALAPPDATA%\REARM-secrets\keys.txt
```

Elle reste un fichier privé en clair, protégé par ses droits locaux ; elle ne
doit jamais être ajoutée au ZIP, au Git, à une capture ou à un message. Un
administrateur du poste ou un logiciel exécuté sous votre compte peut accéder
à ces fichiers. Le correctif ne remplace pas le chiffrement du disque ou d'un
support de sauvegarde et ne protège pas contre un poste déjà compromis.

Les copies chiffrées sont des fichiers versionnés dans `secrets/` à la racine
du projet. Chaque sauvegarde reçoit un nouveau nom ; aucune ancienne copie
chiffrée n'est supprimée automatiquement. Le fichier récent est déchiffré et
comparé aux originaux avant de déclarer la recette réussie. Si ce fichier est
altéré, le contrôle échoue : il ne revient pas silencieusement à un ancien état.

L'entrée binaire de SOPS chiffre l'intégralité d'une enveloppe contenant les
octets des trois fichiers. Les données en clair sont transmises à SOPS par son
entrée standard et récupérées dans la mémoire du script pour vérification.
Il n'y a pas de fichier intermédiaire en clair pour `setup`, `seal` ou `check`.
Les arguments de processus ne contiennent pas les mots de passe ou jetons.
Le MAC de SOPS est vérifié ; aucun mode ignorant ce contrôle n'est utilisé.
Les clés KMS, services distants, paramètres SSH et overrides SOPS hérités de
l'environnement sont écartés. Le script n'accepte pas de commande ou de service
de clés fourni par un client, et refuse les liens symboliques/jonctions.

Sous Windows, les DACL sont appliquées et relues via les API Win32 : héritage
désactivé, accès complet uniquement au SID de l'utilisateur et à SYSTEM. Sur
Linux, les fichiers privés ont le mode 600 et les dossiers le mode 700. Aucun
changement n'est appliqué à l'ensemble du dossier du projet ni à AppData.
Les fichiers sensibles ne sont pas modifiés par un contrôle `check`.

## Installation progressive

Utiliser le compte habituel du projet, dans un PowerShell normal. Ne pas
changer de compte ou lancer tout le projet comme administrateur pour contourner
une erreur de droits. La caméra, la LED et les conteneurs peuvent rester actifs.

1. Extraire `REARM-Secrets.zip` à côté du projet actuel. Depuis le dossier du
   projet, lancer `python` suivi du chemin complet vers le `install.py` extrait.
   L'installateur vérifie les empreintes de l'export source(5), crée une
   sauvegarde des fichiers remplacés et ne lit ni ne remplace les secrets.
2. Installer les outils pour ce compte uniquement :

   ```powershell
   python scripts/secrets_tools.py
   ```

   Le script télécharge les versions x64 fixées depuis les dépôts officiels
   GitHub. Il compare les SHA256 attendus avant d'installer et d'exécuter les
   outils. L'archive age est lue uniquement pour les exécutables attendus, sans
   extraction globale. Le PATH Windows et les services ne sont pas modifiés.
   Une deuxième exécution conserve les outils s'ils sont déjà vérifiés.

   La vérification est fondée sur TLS et des empreintes fixées à la préparation
   du correctif, comparées aux métadonnées des publications officielles. Ce
   script ne prétend pas effectuer une vérification Cosign ou de transparence.

3. Préparer la clé externe, les droits et la première sauvegarde :

   ```powershell
   python scripts/secrets_vault.py setup
   ```

   Les droits du répertoire d'outils sont déjà relus lors de l'étape précédente.
   La clé est générée en mémoire puis écrite dans un nouveau fichier dont les
   droits sont restreints AVANT l'écriture de son contenu. La génération échoue
   sans écriture de clé si cette protection ne peut pas être confirmée.
   Une clé existante est conservée. Si des sauvegardes chiffrées existent mais
   que la clé a disparu, le script refuse d'en générer silencieusement une autre.

4. Vérifier la sauvegarde et les droits :

   ```powershell
   python scripts/secrets_vault.py check
   ```

   Le message doit confirmer trois fichiers identiques, leur intégrité et les
   droits privés. Ne partager que les messages de contrôle, jamais les fichiers
   de configuration ni la clé.

5. Tester la restauration de configuration :

   ```powershell
   python scripts/secrets_vault.py restore-test
   ```

   Ce test crée un dossier privé temporaire sous le répertoire externe sécurisé,
   restaure les trois fichiers, compare leurs octets, puis supprime ce dossier.
   Le projet actif et les identifiants ne sont pas remplacés. Si le nettoyage
   échoue, la commande échoue ; examiner localement les dossiers `restore-test-*`
   de `%LOCALAPPDATA%\REARM-secrets` avant de déclarer la recette terminée.

6. Vérifier la configuration Compose sans la dévoiler :

   ```powershell
   docker compose config --quiet
   ```

   Puis contrôler le fonctionnement conservé :

   ```powershell
   python scripts/recovery_check.py
   ```

   Les dossiers déjà validés et leurs preuves RA-00006/RA-00007 doivent rester
   présents. Tester ensuite le parcours visage → mot de passe → espace équipe.
   Aucun nouveau paiement ou arrêt du backend n'est requis pour le chiffrement.

## Sauvegarder la clé avant de compter sur le chiffrement

La recette locale ne constitue pas une preuve de sauvegarde hors du PC.
Copier la clé privée vers un support séparé protégé, par exemple un support
chiffré conservé hors ligne. Conserver une copie du dossier `secrets/` ailleurs
que sur ce seul PC. **Ne pas conserver l'unique copie de la clé avec l'unique
copie des sauvegardes chiffrées.** Ne pas envoyer ces éléments dans cette
conversation. Vérifier localement que les copies sont lisibles avant de
considérer cette étape de continuité terminée.

Sans la clé privée correspondante ou sa copie, les sauvegardes ne pourront
pas être récupérées. Cette version n'ajoute pas de deuxième destinataire,
de clé d'équipe, d'escrow ou de procédure multi-administrateurs. Le responsable
de la garde et de la restitution de la clé doit être identifié dans le dossier
du workshop. Les empreintes locales des exécutables ne sont pas une barrière
contre un attaquant disposant déjà de votre compte Windows.

## Lorsque la configuration change

Les scripts existants peuvent toujours configurer Stripe ou le matériel.
Certains réécrivent `.env` ou la configuration caméra et peuvent recréer des
droits hérités. Après une modification volontaire, exécuter :

```powershell
python scripts/secrets_vault.py seal
python scripts/secrets_vault.py check
```

`seal` réapplique les droits, crée une nouvelle sauvegarde chiffrée et la
vérifie. Il ne modifie pas les identifiants. `check` refuse une sauvegarde qui
ne correspond plus aux fichiers actifs ; une réussite passée ne doit pas
masquer un changement récent. Les fichiers exécutables sont eux aussi comparés
aux empreintes installées avant toute opération cryptographique.

Le mot de passe Grafana et les comptes sont persistants en base : recopier un
ancien `.env` n'est pas une rotation des comptes existants. Ne pas effectuer
de rotation improvisée du mot de passe PostgreSQL, des jetons caméra/LED ou du
webhook sans synchroniser les composants concernés.

## Restauration réelle, sans écrasement du projet actif

Après remise en place des outils, de la bonne clé externe et du dossier chiffré,
la commande suivante restaure dans un dossier NOUVEAU, hors du projet :

```powershell
python scripts/secrets_vault.py restore --output-dir "C:\dev\REARM-configuration-restauree"
```

La commande refuse un dossier déjà existant ou situé dans le projet. Elle
restaure uniquement les trois chemins prévus, jamais un chemin arbitraire
provenant de la sauvegarde. **Ces copies restaurées sont en clair**, avec les
droits privés appliqués. Les examiner et ne les remettre dans le projet
qu'après coordination avec les clés Stripe, les services et le matériel.
Supprimer les copies devenues inutiles. Une suppression ordinaire n'est pas
une garantie d'effacement physique sur le disque ou dans d'autres sauvegardes.
La restauration de la base est une opération distincte et n'est pas exécutée ici.

## Export et limites

`scripts/export_source.py`, `.gitignore` et `.dockerignore` excluent le dossier
de sauvegarde chiffrée, les fichiers runtime, leurs copies usuelles, les clés
privées, dumps et liens. Les fichiers `.bak-*` sont également écartés. L'export
écrit un ZIP temporaire, puis remplace l'export final uniquement à sa fermeture.

Ces exclusions protègent les chemins prévus, mais ne remplacent pas une revue
du code : un secret copié manuellement dans un nouveau fichier au nom quelconque
pourrait y rester. Les règles Git n'effacent pas un secret déjà commité dans
l'historique ; une telle exposition demanderait une rotation coordonnée et
un traitement de l'historique. Les anciens ZIP déjà créés ne sont pas modifiés.
Les exclusions Docker à la racine concernent le build frontend ; les autres
Dockerfiles utilisent des copies explicites et ne reçoivent aucune clé age.

## Préparation vérifiée et recette sur Windows

Tests de préparation : vrais exécutables Linux officiels SOPS 3.12.2 et age
1.3.2, empreintes vérifiées ; chiffrement/déchiffrement, conservation exacte
des fins de ligne et octets, clé existante conservée, mauvaise clé et fichier
altéré refusés, dérive de configuration détectée, liens refusés et restauration
hors projet sans écrasement. Les régressions de la boutique, de la reprise
Ansible et de la supervision sont vérifiées sur des données fictives. Aucun
secret utilisateur n'est présent dans cet environnement de préparation.

Les API DACL Windows ne peuvent pas être exécutées dans cet environnement Linux.
Leur application et leur relecture réelles doivent réussir sur le PC Windows
avant de déclarer la protection locale validée. En cas d'erreur, conserver les
services actifs et envoyer uniquement le message du script. Ne pas afficher
`.env` ou `keys.txt` pour diagnostiquer.

Références officielles consultées pour cette version :

- SOPS et formats binaires : https://getsops.io/docs/usage/common-operations/
- Gestion des identités : https://getsops.io/docs/usage/identities/
- Publication SOPS : https://github.com/getsops/sops/releases/tag/v3.12.2
- Publication age : https://github.com/FiloSottile/age/releases/tag/v1.3.2
- DACL Win32 : https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfow

## Retour sur les fichiers du correctif

```powershell
python scripts/secrets_rollback.py
```

Le retour vérifie les fichiers installés avant de restaurer les versions
précédentes. Il ne supprime ni clé, ni sauvegarde chiffrée, ni identifiant, ni
donnée, et ne rétablit pas des droits plus larges sur les fichiers sensibles.
Les outils installés hors du projet restent présents. Les anciennes exclusions
d'export sont alors rétablies : ne pas relancer un export sans examiner ce
qu'il contient. Le dossier extrait du correctif conserve le guide et les
scripts si un accès de récupération est nécessaire. Aucun redémarrage Docker
ni migration SQL n'est nécessaire pour cette étape.
