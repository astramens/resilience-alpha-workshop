> Mise à jour REARM : suivre d’abord le README principal. Les routes caméra et LED sont désormais servies par le service `auth`, via le même port 3000. Les identifiants, jetons et empreintes existants restent valides. Le back-office est à `/admin`.

# Mise à jour : authentification par caméra USB du PC Hôte

Cette mise à jour s'applique à ResiliencePay 0.2.0. Les données de paiement restent dans PostgreSQL. Elle remplace la connexion par mot de passe seul. Les anciens tests `scripts/smoke_test.py` qui se connectaient sans visage ne sont donc plus applicables après activation.

## Périmètre livré

- Identifiant, capture sur la caméra du PC Hôte, comparaison du visage côté serveur, puis mot de passe.
- Trois empreintes cohérentes exigées ; refus d'une preuve fournie par le navigateur sans le secret de l'agent hôte.
- Preuve liée à un cookie HttpOnly, expirante et consommable une seule fois.
- Deux refus de visage pour un même identifiant entraînent un blocage de cinq minutes conservé en base. Le premier refus impose 30 secondes d'attente.
- Mot de passe refusé : commande rouge clignotante dix fois, puis reprise complète. Mot de passe correct : commande verte fixe de 30 secondes avant ouverture du back-office.
- Caméra libérée après capture réussie ; après visage refusé, elle reste active pendant le signal rouge de 30 secondes puis se ferme.
- Une seule utilisation de la caméra à la fois. Les autres navigateurs voient une indisponibilité temporaire ; ils ne peuvent pas valider le visage d'un autre navigateur.
- Premier enregistrement administrateur depuis un outil local avec le secret de l'agent ET le mot de passe existant. Cette initialisation se ferme dès qu'un administrateur actif a un visage enregistré.
- Onglet Utilisateurs : création des comptes, enregistrement/remplacement/révocation des visages, rôles et désactivation. Les changements d'accès révoquent les sessions concernées. Un administrateur ne peut pas modifier ses propres droits ni révoquer son propre visage.
- Rôles : administrateur (comptes et paiements), opérateur (paiements), lecteur (consultation sans paiement). Le refus du paiement lecteur est appliqué par l'API.

**ESP8266 : le contrat API et les commandes sont livrés, mais le firmware et le câblage restent à intégrer avec votre carte réelle.** Le programme ne prétend pas qu'une LED physique fonctionne tant que le module n'est pas raccordé et testé.

## Installation accompagnée : ne pas tout exécuter d'un coup

1. Depuis la racine du projet existant, lancer `python <chemin-vers-la-mise-a-jour>/install.py`. Le script vérifie les fichiers et sauvegarde ceux qu'il remplace. Il ne touche ni à `.env`, ni à `ai-engine`, ni aux données, et ne relance aucun service.
2. `python scripts/face_setup.py` ajoute les deux secrets distincts caméra/LED et crée `.camera-agent.json`. Ne partagez aucun de ces fichiers.
3. Créer un environnement caméra : `python -m venv .venv-camera`, puis `.\.venv-camera\Scripts\python.exe -m pip install -r host-camera/requirements.txt`. Le paquet OpenCV est épinglé à 4.13.0.92. Cette installation doit être vérifiée sur votre Windows/Python 3.14 ; le build conteneur backend reste Python 3.12.
4. Fermer l'application Windows Caméra. Lancer `.\.venv-camera\Scripts\python.exe host-camera/agent.py preview --index 0`. Vérifier physiquement qu'il s'agit de la caméra USB externe. Appuyer sur Q pour fermer, puis confirmer `oui`. Si c'est la caméra intégrée, recommencer avec `--index 1`, puis éventuellement 2. L'index choisi est conservé localement. Ne pas laisser l'aperçu ouvert.
5. `.\.venv-camera\Scripts\python.exe host-camera/agent.py models` télécharge les deux modèles OpenCV. Les empreintes SHA-256 sont vérifiées ; aucun visage n'est téléchargé.
6. Garder PostgreSQL démarré. Appliquer `python scripts/face_migrate.py`. Cette migration ajoute les colonnes et l'état d'authentification, conserve les paiements et révoque les anciennes sessions une seule fois.
7. `docker compose up -d --build --no-deps backend frontend`. Les services attendent désormais les nouvelles variables ; ne les reconstruire qu'après l'étape 2 et ne démarrer la nouvelle API qu'après la migration.
8. Enregistrer le premier visage : `.\.venv-camera\Scripts\python.exe host-camera/agent.py bootstrap`. Saisir l'identifiant initial et son mot de passe actuel, puis se placer seul devant la caméra USB. Le premier compte devient administrateur. Aucun secret ni visage ne doit être envoyé dans la conversation.
9. Lancer `.\.venv-camera\Scripts\python.exe host-camera/agent.py run` et laisser cette fenêtre ouverte sur le PC Hôte. La caméra reste éteinte hors des phases d'identification. Cet agent est volontairement natif Windows : aucune caméra du PC Attaquant n'est utilisée, et aucun passage USB vers Docker Desktop n'est supposé disponible.
10. Ouvrir http://localhost:3000, saisir l'identifiant et cliquer sur « Vérifier mon visage ». Après reconnaissance, saisir le mot de passe. Attendre la fin du signal de 30 secondes. L'enregistrement d'autres utilisateurs se fait ensuite depuis l'onglet Utilisateurs avec un administrateur connecté.

Ne jamais utiliser `docker compose down -v` pour cette mise à jour. Ne pas relancer `scripts/configure.py`, qui recréerait une configuration distincte au lieu de préserver vos secrets existants.

## Recette avant de déclarer la consigne satisfaite

- Vérifier que la caméra externe choisie est physiquement sur le PC Hôte, pas la caméra intégrée et pas celle d'un navigateur distant.
- Vérifier qu'un appel direct à `/api/auth/login` avec seulement le mot de passe est refusé, même s'il est correct.
- Vérifier un visage correspondant, un visage différent et l'absence de visage. Mesurer les faux rejets et fausses acceptations sur les membres volontaires du groupe avant de fixer le seuil.
- Après deux refus, fermer/recharger le navigateur et redémarrer le backend : le blocage doit rester actif jusqu'à l'échéance de cinq minutes.
- Vérifier les 30 secondes de rouge fixe, les dix clignotements rouges, les 30 secondes de vert fixe et l'extinction physique de la caméra. Les états de l'API ne remplacent pas cette recette matérielle.
- Vérifier le refus d'un paiement avec un compte lecteur et le refus des actions administrateur pour un opérateur.
- Vérifier les paiements et l'historique après reconnexion. La modification n'efface pas les transactions existantes.

## ESP8266 : contrat à intégrer ensuite dans CLion + PlatformIO

L'ESP8266 appellera `/api/device/led` sur `http://192.168.137.1:3000` (adapter si nécessaire), avec `Authorization: Bearer <LED_DEVICE_TOKEN>`. Ne jamais lui donner `CAMERA_AGENT_TOKEN`.

Réponse : `mode`, `command_id`, `elapsed_ms`, `remaining_ms`. Les modes sont `off`, `green_blink`, `green_fixed`, `red_fixed`, `red_blink_10`. Pour ce dernier, une alternance 500 ms allumé / 500 ms éteint sur dix secondes produit dix clignotements. Utiliser `command_id` pour ne pas recommencer la séquence à chaque lecture. `elapsed_ms` permet de reprendre la phase en cours ; éteindre à l'expiration ou après perte prolongée du serveur.

Le câblage, la polarité de la LED et les GPIO dépendent de votre carte et de votre LED. Les identifier avant de flasher un firmware. Ne pas déduire les GPIO à partir du seul nom ESP8266.

## Limites à présenter honnêtement

- YuNet/SFace sont utilisés pour une vérification faciale du démonstrateur. Aucune détection fiable de présentation de photo/vidéo ni garantie de vivacité n'est implémentée. Ne pas présenter ce prototype comme une authentification biométrique industrielle résistante aux photos.
- Seules les empreintes sont stockées dans PostgreSQL ; les images restent en mémoire sur l'hôte. Ces empreintes restent des données biométriques sensibles. Limiter les inscriptions aux participants volontaires et supprimer les données d'essai après le workshop.
- Le seuil cosinus de 0,45 est une hypothèse initiale à évaluer sur le matériel et les utilisateurs du groupe, pas un taux de sécurité mesuré. Le seuil de référence OpenCV dépend du jeu de test et n'est pas une garantie pour votre contexte.
- L'agent hôte est un composant de confiance ; son secret doit rester sur le PC Hôte. La possession de ce secret permet de soumettre des empreintes au serveur.
- HTTP reste réservé au réseau de laboratoire. Le dispositif ne remplace ni Vault/SOPS, ni le WAF, ni le reste du sujet initial.
- L'authentification reste intégrée à l'API actuelle. Le découpage en microservice d'authentification distinct reste à traiter dans l'architecture globale.
- Le fonctionnement caméra et ESP8266 n'a pas été testé à distance sur vos appareils.

## Sources techniques des modèles

Documentation officielle OpenCV : https://docs.opencv.org/4.13.0/d0/dd4/tutorial_dnn_face.html

YuNet 2023mar, empreinte SHA-256 : `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
SFace 2021dec, empreinte SHA-256 : `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`.

Modèles et licences :
- https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface

L'archive ne redistribue pas les poids des modèles. L'agent télécharge les versions nommées depuis le dépôt officiel et refuse toute empreinte différente.
