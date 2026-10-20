# Vérifications du correctif caméra

Date : 20 octobre 2026.

## Vérifié ici

- Compilation de production Next.js/webpack et vérification TypeScript : réussies. Les dépendances ont été installées dans le dossier de validation avec `npm ci` ; le build final ne présente plus l'avertissement de traçage produit par le premier essai utilisant un lien vers les dépendances d'un autre dossier.
- 25 tests Python réussis. Les tests de parcours HTTP utilisent des doublures pour les accès SQL, sans appareil vidéo. Ils couvrent le refus d'un mot de passe seul, la protection du canal agent, le lien entre preuve et cookie, la preuve consommée, le délai avant ouverture, les deux refus de visage, la révocation, les rôles et les règles monétaires conservées.
- Migration exécutée sur le moteur PostgreSQL embarqué PGlite : conservation d'un paiement existant, révocation des anciennes sessions, création des nouvelles colonnes/tables, réapplication sans effacer une nouvelle session vérifiée. Ce contrôle de SQL ne remplace pas un essai psycopg2/PostgreSQL dans Docker Desktop.
- Installateur exécuté sur une copie de test : fichiers identiques au manifeste, sauvegarde des fichiers remplacés, `.env` et `ai-engine/detector.py` conservés.
- Syntaxe des modules Python vérifiée.
- Références et empreintes SHA-256 des modèles vérifiées dans le dépôt officiel OpenCV. La distribution Windows 64 bits du paquet OpenCV épinglé figure dans les métadonnées officielles PyPI.

## Reste à vérifier sur votre PC

- Installation du paquet OpenCV sous votre Python Windows 3.14.
- Acquisition de la caméra USB réelle du PC Hôte et extinction/libération à chaque état attendu.
- Résultats de reconnaissance sur les participants du groupe, réglage du seuil et résistance aux présentations de photo/vidéo : aucune garantie de vivacité n'est fournie.
- Construction/démarrage Docker et migration de votre base réelle.
- Parcours visuel dans votre navigateur. Aucun succès de test navigateur n'est revendiqué pour ce correctif.
- Raccordement du firmware ESP8266 à `/api/device/led`, câblage et séquences physiques. Le firmware n'est pas dans cette mise à jour.
- Reprise autonome après incident, WAF, observabilité complète, RAG, secrets chiffrés et autres exigences du workshop initial.

Ne pas déclarer la consigne additionnelle entièrement validée sur la seule base de ces tests de code.
