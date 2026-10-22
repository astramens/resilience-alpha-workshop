# REARM — Stripe Checkout en mode test

Cette version intègre l’API Stripe Checkout et les notifications signées. Elle ne débite pas d’argent réel : seules les clés `sk_test_` sont acceptées. Aucun numéro de carte n’est transmis à REARM, PostgreSQL ou aux journaux applicatifs. L’ancienne commande RA-00001 et les autres commandes historiques restent identifiées comme des simulations historiques.

## Mise en place, après installation des fichiers

1. Depuis le dossier du projet, créer une sauvegarde : `python scripts/backup_db.py`.
2. Appliquer les migrations : `python scripts/rearm_migrate.py`.
3. Ouvrir ou créer un compte Stripe, puis choisir un environnement de test dans le tableau de bord. Aucun passage en production n’est nécessaire.
4. Installer la CLI officielle : https://docs.stripe.com/stripe-cli/install ; vérifier `stripe --version`, puis exécuter `stripe login` et autoriser ce compte depuis le navigateur.
5. Dans une fenêtre dédiée, lancer :

```powershell
stripe listen --events checkout.session.completed,checkout.session.expired,checkout.session.async_payment_succeeded --forward-to http://localhost:3000/api/shop/payments/webhook
```

Conserver cette fenêtre ouverte. Copier localement le secret `whsec_...` annoncé. Ne pas le partager dans un message ou une capture.

6. Dans une autre fenêtre PowerShell, depuis le projet, lancer `python scripts/payment_setup.py`. Laisser l’URL par défaut si la démonstration se fait sur le PC hôte. Saisir la clé **secrète de test** `sk_test_...` obtenue dans le tableau de bord et le secret `whsec_...` du listener. Les saisies sont masquées. Le script préserve les autres variables, y compris la caméra et la LED. Ne pas envoyer `.env`.
7. Vérifier `docker compose config --quiet`, puis lancer `docker compose up -d --build`. L’authentification caméra conserve son agent Windows dans sa fenêtre habituelle. Le port public reste 3000.
8. À chaque redémarrage du listener, vérifier que son secret correspond à la configuration. Si ce secret change, relancer `payment_setup.py`, puis recréer le backend avec `docker compose up -d backend`.

L’URL de retour est une valeur serveur présente dans `ALLOWED_ORIGINS` ; le navigateur ne la choisit pas. Pour une démonstration depuis un autre poste sur le hotspot, configurer `http://192.168.137.1:3000`, après en avoir vérifié l’accès depuis ce poste. Le backend a une connexion sortante dédiée pour joindre `api.stripe.com`. Le PC et le navigateur doivent avoir accès à Internet. Les photos, elles, sont locales et fonctionnent sans accès à Wikimedia.

## Recette à réaliser avec le compte Stripe de test

- Créer un compte client fictif, ajouter un article disponible, accepter le mode test et cliquer « Payer avec Stripe · test ».
- Vérifier que l’adresse devient `https://checkout.stripe.com/...` et que Stripe affiche son mode test.
- Utiliser uniquement la carte de test officielle `4242 4242 4242 4242`, une date future et trois chiffres quelconques pour le CVC. Ne pas saisir de carte bancaire réelle.
- Après paiement, le retour déclenche une vérification côté serveur. La commande doit devenir « Confirmée » avec « Stripe test : payé ». Une simple URL de retour ne suffit jamais à confirmer le paiement.
- Dans le tableau de bord Stripe de test, contrôler la transaction et son montant en EUR.
- Rafraîchir la boutique : une seule commande et un seul débit de test doivent exister.
- Tester un refus avec une carte de test de refus documentée par Stripe : la commande ne doit pas être confirmée ; le paiement peut être repris depuis « Mes commandes ».
- Annuler une commande payée avant sa préparation : attendre le remboursement de test confirmé et contrôler que le stock revient une seule fois. Une annulation depuis l’application demande le remboursement via Stripe avant de finaliser l’annulation locale.
- Pour une commande non payée, l’annulation expire d’abord la session Stripe avant de remettre en stock. Le simple retour avec « Annuler » depuis Stripe conserve la réservation et permet de reprendre le paiement.

Les sessions expirent après environ une heure. Une notification d’expiration ou le bouton « Vérifier le paiement » libère le stock une fois que Stripe confirme l’expiration. Garder le listener actif ; le retour de l’acheteur est une seconde voie de vérification. Il n’existe pas encore de tâche périodique de réconciliation. Si le listener est arrêté, les réservations ne se libèrent donc pas immédiatement toutes seules.

## Garanties et limites opérationnelles

Les prix viennent de PostgreSQL, jamais du navigateur. La réservation et la clé de commande sont enregistrées avant l’appel Stripe ; une réponse perdue doit être rejouée avec le même panier et la même clé. La création Stripe utilise une clé d’idempotence persistante propre à la tentative. Les notifications vérifient leur signature HMAC sur le corps brut, avec une tolérance de 5 minutes ; la session est aussi relue chez Stripe et son montant, EUR, identité de commande, tentative et mode test sont contrôlés. La préparation d’une commande non payée est interdite.

En cas de panne réseau après création Stripe mais avant réception de son identifiant, réessayer sans modifier la commande. Le webhook peut aussi raccorder la session grâce à l’identifiant de tentative. Si aucune session n’a été créée et que le délai de création est dépassé, une réservation peut nécessiter une intervention : on ne remet pas automatiquement un stock en vente tant qu’un paiement demeure incertain. Les remboursements doivent être initiés depuis REARM ; cette version ne synchronise pas les remboursements manuels lancés directement dans le tableau de bord Stripe.

Ne pas employer le compte Stripe de test pour un test de charge : utiliser un substitut local du prestataire. Le laboratoire reste sur HTTP ; une exploitation publique demanderait HTTPS, cookies Secure et les autres chantiers de sécurité du workshop. Cette livraison ne constitue pas une validation du SI complet.

## Références officielles

- https://docs.stripe.com/api/checkout/sessions/create
- https://docs.stripe.com/checkout/fulfillment
- https://docs.stripe.com/events/manage-webhook-endpoints
- https://docs.stripe.com/testing
- https://docs.stripe.com/api/checkout/sessions/expire
- https://docs.stripe.com/api/refunds/create
