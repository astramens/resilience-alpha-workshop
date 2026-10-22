# Validation de la mise à jour — 21 octobre 2026

## Résultats obtenus

- `npm run build` : compilation de production et vérification TypeScript réussies. Routes `/`, `/admin`, `/a-propos`, `/credits` et proxy API générés.
- 59 tests Python réussis. Les 11 nouveaux scénarios Stripe couvrent : réservation non payée ; confirmation serveur ; réponse perdue et rejeu sans double réservation ; signature invalide ou périmée ; notification répétée ; montant/devise/mode live incohérents ; annulation d’une réservation avec expiration Stripe ; remboursement de test avant annulation ; expiration répétée ; droits du propriétaire ; préparation d’une commande impayée interdite ; clés réelles refusées ; rattachement par webhook après perte de réponse.
- Les tests d’intégration SQL utilisent PostgreSQL embarqué PGlite avec un adaptateur de test, et les vrais gestionnaires FastAPI. L’adaptateur sérialise les connexions : il ne démontre pas la contention de connexions indépendantes sur le serveur PostgreSQL Docker.
- La passerelle Stripe est remplacée par un substitut contrôlé pour les tests automatisés. Ils vérifient la logique et les écritures de REARM ; aucun appel de paiement réel ou de test au compte Stripe de l’utilisatrice n’a été fait ici.
- Chromium : chargement des 13 images affichées sur la boutique (bannière et 12 fiches), présence des crédits dans le détail, ajout au panier, connexion client, redirection vers l’URL de Checkout, page de 10 crédits et affichage mobile de 390 px sans débordement horizontal. Les API sont remplacées pour cette recette UI et la destination Stripe est interceptée : ce contrôle ne constitue pas un paiement de bout en bout chez Stripe.
- Fiches Wikimedia des dix photographies utilisées consultées : auteurs et licences/notices reportés dans le registre et la page de crédits. Les images restent des photographies illustratives du catalogue fictif.
- YAML Compose analysé : port public 3000 conservé ; secrets Stripe uniquement transmis au backend ; réseau sortant ajouté uniquement au backend pour le prestataire. Cela n’est pas un `docker compose up` exécuté ici.

## Validation à effectuer sur le PC du workshop

Sauvegarde puis migration, configuration du compte Stripe de test et du listener webhook, reconstruction Docker, transaction avec carte de test, refus, retour au site, vérification dans Stripe, historique et remboursement. Voir `PAIEMENT_STRIPE.md`.

Aucun accès au compte Stripe, au Docker local, à la caméra ou à l’ESP8266 de l’utilisatrice depuis cet environnement. La reconnaissance faciale et la LED ne sont pas modifiées par cette livraison. La couleur rouge observée après reconnaissance doit être diagnostiquée ensuite.

Les contrôles ci-dessus ne remplacent ni un audit de sécurité complet ni les composants SI restant au programme du workshop.
