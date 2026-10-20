# Mise à jour caméra : installation progressive

Cette archive est un correctif à appliquer à votre projet actuel. Ce n'est pas un nouveau projet à lancer séparément.

1. Extraire entièrement le dossier `face-auth-update`.
2. Garder votre projet actuel et son `.env`. Ne supprimer aucun volume Docker.
3. Ouvrir PowerShell dans le dossier du projet actuel, celui qui contient `docker-compose.yml`.
4. Exécuter `python <chemin-vers-face-auth-update>/install.py` avec le chemin complet du script extrait.

Le script sauvegarde les fichiers remplacés dans `.face-backup-<date-heure>`, vérifie les empreintes des fichiers, et ne modifie ni les données, ni le `.env`, ni le détecteur corrigé. Il ne redémarre aucun conteneur.

Après cette copie, **ne reconstruisez pas encore Docker**. Continuer avec l'accompagnement et le guide `FACE_AUTH_README.md` installé dans le projet : préparer les secrets, l'environnement de caméra, la caméra externe, puis la migration de base avant de démarrer la nouvelle API.

Les anciennes sessions seront révoquées par la migration. Il faudra enregistrer le visage du premier administrateur depuis le PC Hôte avant de se reconnecter. Les paiements existants sont conservés.

L'archive livre la gestion de reconnaissance et les commandes serveur pour la LED. Le firmware ESP8266 et la recette matérielle viennent ensuite ; cette livraison ne prétend pas achever tout le workshop.
