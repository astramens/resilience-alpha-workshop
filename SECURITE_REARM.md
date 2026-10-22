# REARM — sécurité et périmètre réel

Cette livraison transforme la démonstration de paiement en boutique de fiction. Elle n’est pas une déclaration de conformité ni l’achèvement de tout le workshop.

## Architecture livrée

Le seul port publié est `3000` sur le proxy Nginx. Il relaie vers Next.js, qui répartit les appels vers l’API commerce (`backend:8000`) et l’identité (`auth:8001`). Le service d’identité traite les comptes clients, les comptes d’équipe, l’agent caméra et l’ESP8266. Les images de visage restent sur l’hôte ; les empreintes sont des données sensibles en base.

Réseaux Compose : `web` pour proxy/frontend ; `application` pour frontend/API/identité ; `data` pour API/identité/PostgreSQL ; `control` pour détecteur/API/remédiation ; `docker_control` pour remédiation/passerelle Docker. Les quatre derniers réseaux sont internes et ne publient aucun port. La séparation réseau ne remplace pas des identités SQL de moindre privilège : l’API et l’identité utilisent encore le même rôle PostgreSQL du projet.

## Contrôles en place

- Accès équipe : preuve de visage attachée à une pré-session HttpOnly, mot de passe, temporisations et blocage après deux refus. Procédure hôte caméra et LED conservées. Absence de détection de vivacité : un test anti-photo reste à concevoir et à évaluer.
- Clients : mots de passe scrypt salés, sessions opaques hachées en base, cookies HttpOnly / SameSite strict, expiration huit heures. Un client n’obtient jamais de droits d’équipe.
- Autorisations serveur : administrateur pour catalogue/comptes ; opérateur pour préparation ; lecteur pour consultation ; client pour ses propres commandes uniquement.
- Requêtes SQL paramétrées. Prix calculé côté serveur. Verrouillage du stock, ordre stable des verrous, transactions et clé de commande idempotente. Version des fiches pour refuser une modification concurrente.
- Révocation des sessions à la désactivation d’un compte. Annulation contrôlée par une machine à états ; remise en stock une seule fois.
- Origine autorisée exigée sur les écritures. Débit limité sur le proxy et tentatives de connexion en base. La liste des origines vient du `.env` existant : vérifiez ses valeurs sans la partager.
- Proxy sans privilèges, taille maximale de requête 64 Kio, limites de débit et en-têtes anti-framing/nosniff. CSP locale ; les scripts/styles inline restent autorisés pour la compatibilité Next.js et nécessitent un durcissement par nonce ultérieur.
- API/identité sous UID non privilégié, système de fichiers en lecture seule, capacités Linux retirées. Secrets caméra et LED réservés à l’identité.
- Remédiation sans montage direct du socket Docker : la passerelle n’autorise que la consultation et le redémarrage du backend dont les labels correspondent exactement au projet Compose. Création, suppression, exec et autres conteneurs sont refusés. La passerelle reste un composant privilégié de confiance, car elle seule détient le socket.
- Sauvegarde locale PostgreSQL et journal métier en base. Aucun secret dans le ZIP distribué.

## Ce qui reste à construire / prouver pour le SI complet

1. WAF ModSecurity + OWASP CRS, réglage des faux positifs et corrélation des journaux. Le proxy Nginx livré est un reverse proxy renforcé, pas un WAF à règles d’attaque.
2. Collecte Prometheus/Grafana/Loki et véritable fonction SOC/SIEM. Le journal de commandes ne détecte pas une attaque.
3. Validation de l’IsolationForest sur des scénarios représentatifs : le détecteur existant reste limité aux sondes de disponibilité. Il ne recherche pas toutes les failles applicatives. Aucun score de précision n’est inventé.
4. Historisation complète détection → décision → action → preuve. Aujourd’hui le remédiateur vérifie `/health`, et répond explicitement `business_recovery_verified=false`. Le test métier doit ensuite réussir une nouvelle commande.
5. Assistant RAG local avec sources, corpus et refus des actions hors périmètre ; Ollama n’est pas inclus dans cette livraison.
6. Ansible, gestion chiffrée des secrets (Vault/SOPS), rotation, contrôle des droits SQL, certificats HTTPS et cookies Secure. HTTP local est conservé pour la compatibilité du laboratoire : aucune donnée réelle.
7. Exercice de restauration sur une base séparée, attaque autorisée depuis le second PC et vidéo continue de reprise. La commande `docker compose restart` ne constitue pas une preuve de réparation d’une faille.
8. EBIOS RM, PCA/PRA, analyses NIS2/DORA et livrables : décrire les contrôles réellement testés et leurs limites. Aucune conformité réglementaire n’est affirmée ici.

## Scénarios métier de recette

Créer un client fictif → choisir un article → commander → vérifier décrément stock → rejouer la même clé sans seconde commande → consulter son historique → préparer/retirer côté équipe. Un second client ne doit pas voir ni annuler la commande du premier. Annuler une commande confirmée remet le stock une seule fois. Archiver un article le retire du catalogue public.

## Continuité et retour arrière

Avant migration : `python scripts/backup_db.py`. Le dump contient aussi les empreintes faciales : ne pas le partager. Les sauvegardes de fichiers de l’installateur ne sauvegardent pas la base. La migration crée des tables préfixées `shop_` sans supprimer les tables de paiements. Le catalogue initial utilise `ON CONFLICT DO NOTHING` : une réexécution ne réinitialise ni vos modifications ni vos stocks.

Les tables `shop_` peuvent rester présentes en revenant au code précédent : cela n’altère pas les anciens paiements. Restaurer les fichiers de la sauvegarde et reconstruire les services avec l’ancien Compose ; vérifier la base et les sessions avant reprise. Ne pas exécuter `docker compose down -v`.
