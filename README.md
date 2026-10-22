# Mise à jour visuelle et Stripe test

Cette édition remplace les illustrations affichées par des photos locales avec crédits et retire l’orange d’accent. Elle ajoute Stripe Checkout en mode test : les nouvelles commandes attendent une confirmation du prestataire. Les clés ne sont pas fournies et le paiement reste désactivé tant que la configuration n’est pas faite.

Après installation : sauvegarde `python scripts/backup_db.py`, migration `python scripts/rearm_migrate.py`, puis configuration selon [PAIEMENT_STRIPE.md](PAIEMENT_STRIPE.md). Aucun compte client, visage, commande, stock ou paramètre matériel n’est supprimé par cette migration. Les anciennes commandes gardent la mention de simulation historique.

Voir aussi [VISUELS_ET_LICENCES.md](VISUELS_ET_LICENCES.md) et [VALIDATION_VISUEL_PAIEMENT.md](VALIDATION_VISUEL_PAIEMENT.md). La documentation historique ci-dessous décrit l’édition précédente ; pour le paiement, les instructions Stripe ci-dessus font foi.

---

# REARM — atelier de seconde vie

Boutique fictive d’accessoires de cinéma reconditionnés, pour le workshop RESILIENCE-ALPHA. Les objets sont factices/inertes ; paiements et retraits sont simulés. Aucun prestataire de paiement ni donnée bancaire.

## Ce qui fonctionne dans cette version

- Catalogue PostgreSQL de 12 pièces, catégories, recherche, filtres d’état, tri, disponibilité et fiches/passeports d’atelier.
- Compte client (inscription, connexion, déconnexion), panier persistant local, commande avec prix serveur et stock transactionnel, historique privé et annulation.
- Clé idempotente par commande ; en cas de réponse incertaine, conservation de la même requête dans le navigateur pour la rejouer, y compris après rechargement. Le compte client d’origine doit être utilisé.
- Back-office `/admin` : authentification caméra USB du PC hôte puis mot de passe, LED physique, rôles administrateur/opérateur/lecteur, gestion du catalogue et des stocks, traitement des commandes, désactivation de clients, gestion de l’équipe et journal métier.
- Authentification déplacée dans un service `auth` séparé. PostgreSQL, frontend, API, détection existante et remédiation restent dans Compose. Le code du détecteur et le firmware ESP8266 ne sont pas modifiés. Les dépendances Python FastAPI/Starlette/Requests sont mises à jour pour supprimer les avis de sécurité identifiés.
- Proxy d’entrée, réseaux séparés, limites de débit, conteneurs applicatifs sans privilèges et passerelle Docker à actions limitées.

Le périmètre restant pour le SI complet est détaillé dans `SECURITE_REARM.md` : WAF, observabilité/SIEM, RAG, Ansible/secrets chiffrés, validation des scénarios d’attaque et de reprise. Ne pas présenter cette version comme un SI entièrement sécurisé ou une IA corrigeant toute faille.

## Mise à jour de votre installation existante

Exécuter chaque étape dans votre dossier actuel `C:\dev\resilience-alpha-corrige\resilience-alpha-corrige`. Conserver le `.env`, `.camera-agent.json`, le volume PostgreSQL, les modèles et `esp8266-led/include/secrets.h` sur votre PC.

1. Extraire le ZIP REARM-update dans un dossier séparé, sans supprimer votre projet. Lancer son `install.py` depuis le PowerShell positionné dans votre projet actuel. L’installateur sauvegarde les fichiers remplacés dans `.rearm-backup-<date>` ; il ne lance aucune commande Docker et ne modifie aucun secret.
2. Vérifier que la base actuelle fonctionne : `docker compose ps db`.
3. Sauvegarder : `python scripts/backup_db.py`. La sauvegarde doit réussir avant la suite. Elle contient des données sensibles et ne doit pas être partagée.
4. Migrer et ajouter le catalogue : `python scripts/rearm_migrate.py`. Les tables de paiements et les empreintes faciales existantes sont conservées. Cette migration est réexécutable et ne réinitialise pas les stocks.
5. Reconstruire : `docker compose up -d --build`.
6. Vérifier : `docker compose ps`. Attendre `healthy` pour `backend` et `auth`. Le nouveau service `edge` publie le port 3000 ; le frontend n’a plus de port directement publié.
7. Boutique : `http://localhost:3000`. Équipe : `http://localhost:3000/admin`. L’agent caméra doit continuer de tourner sur le PC hôte. L’ESP8266 utilise toujours `http://192.168.137.1:3000` et son jeton existant.
8. Créer un compte client fictif dans la boutique, ajouter un article, simuler le paiement, vérifier son historique et préparer la commande côté équipe.
9. Recette automatique complémentaire : `python scripts/shop_smoke.py`. Elle crée un client et une commande fictifs, vérifie le rejeu, puis annule la commande et contrôle le stock.

Ne pas relancer `scripts/configure.py` pour une mise à jour : il pourrait remplacer votre configuration. Ne pas exécuter `docker compose down -v`.

### Si le port 3000 est déjà occupé pendant la première reconstruction

Le port doit passer du frontend à `edge`. Compose doit recréer le frontend sans publication avant de démarrer edge. Si Docker signale malgré tout que 3000 est occupé, exécuter `docker compose stop frontend edge`, puis `docker compose up -d frontend edge`. Cela ne supprime pas les données.

### Démarrage d’un nouvel environnement

Exécuter `python scripts/configure.py`, puis `python scripts/face_setup.py`, `docker compose up -d db`, `python scripts/rearm_migrate.py`, puis `docker compose up -d --build`. Suivre `FACE_AUTH_README.md` pour le venv caméra, les modèles, le choix de la caméra USB et le bootstrap initial. La connexion initiale du personnel ne fonctionne pas tant qu’un visage n’a pas été enregistré.

## Rôles

| Identité | Droits |
|---|---|
| Visiteur | Catalogue et panier local |
| Client | Ses commandes, annulation avant préparation, aucun droit d’équipe |
| Lecteur | Consultation du back-office, sans modification |
| Opérateur | Consultation et progression des commandes |
| Administrateur | Catalogue, stocks, comptes clients et équipe, commandes |

Machine à états : confirmée → préparation → prête → retirée. Annulation possible par l’équipe jusqu’au retrait, par le client uniquement avant préparation. Une commande annulée reste dans l’historique. Un article archivé disparaît du catalogue mais reste dans les commandes déjà passées.

## Maintenance

- Export sans secrets : `python scripts/export_source.py` (conserve les migrations SQL et exclut les dumps).
- Sauvegarde de base : `python scripts/backup_db.py`.
- Logs : `docker compose logs --since=5m backend auth edge ai-engine remediation docker-guard`.
- Ne pas publier `.env`, `.camera-agent.json`, `secrets.h`, les dumps ni les sauvegardes de fichiers. Les identifiants clients de recette sont fictifs.

## Retour arrière

Les fichiers précédents sont dans la sauvegarde de l’installateur. Restaurer ceux-ci, conserver le `.env` et la base, puis reconstruire avec le Compose précédent. Les nouvelles tables `shop_` peuvent rester sans affecter les anciens paiements. Pour une restauration PostgreSQL complète, préparer une base distincte et vérifier le dump avant toute substitution ; ne pas restaurer à l’aveugle par-dessus les données actuelles.
