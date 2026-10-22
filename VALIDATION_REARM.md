# Vérifications de la livraison REARM

## Exécuté dans l’environnement de préparation

- Compilation Next.js de production et vérification TypeScript. Dépendances installées dans le dossier du projet, sans lien symbolique pendant la vérification finale.
- 25 tests de contrat existants : primitives de mots de passe, montants, paiement idempotent, permissions et règles de preuve faciale. Ces tests ne constituent pas une nouvelle mesure de performance de la caméra.
- 12 tests commerce avec FastAPI TestClient et PGlite (moteur PostgreSQL embarqué) : comptes/sessions distincts, prix serveur, commande/rejeu, conflit de clé, stock insuffisant, annulation unique, isolation entre clients, statuts, rôles, modification concurrente de produit, archivage, révocation des sessions et blocage des tentatives. Réapplication des migrations avec commandes, stock, paiements et sessions vérifiées conservés.
- L’adaptateur de test sérialise les connexions PGlite : le scénario simultané vérifie l’issue métier mais ne remplace pas un essai de contention avec plusieurs connexions indépendantes sur le PostgreSQL Docker du PC hôte.
- Huit tests de validation supplémentaires : quantités entières et bornées, nom de plateau et produits en double, refus des illustrations externes.
- Trois tests de la passerelle Docker : refus des opérations non prévues, refus d’un autre projet, redémarrage limité au backend et suppression des variables d’environnement dans les réponses d’inspection. Le SDK Docker 7.1.0 avec Requests 2.34.2 est aussi exercé via cette passerelle et un moteur simulé. Pas de démon Docker disponible ici : le redémarrage réel doit être vérifié sur l’hôte.
- Audit npm des dépendances de production : sept alertes élevées dans la chaîne inutilisée de l’outil CLI shadcn, retiré. Audit après suppression : aucune vulnérabilité signalée dans cette base d’avis, à la date du contrôle. Cela ne prouve pas l’absence de faille ni l’état des images Docker.

- Navigateur Chromium avec les vrais handlers HTTP et le moteur PostgreSQL de test : recherche, fiche article, inscription, panier, commande, historique, annulation, back-office, édition produit et gestion de l’équipe. Le scénario de réponse perdue après enregistrement puis rechargement/rejeu conserve une seule commande. Affichage à 1440 px et 390 px contrôlé ; génération UUID testée avec crypto.randomUUID indisponible, comme sur une adresse HTTP du hotspot.

- Audit Python : anciennes dépendances Starlette et Requests signalées ; mises à jour vers FastAPI 0.150.0, Starlette 1.9.0 et Requests 2.34.2. Les 48 tests de contrat/métier passent avec FastAPI/Starlette mis à jour. Audit final groupé des dépendances API, remédiation et détecteur : aucune vulnérabilité connue signalée. Le SDK Docker et sa chaîne réseau sont également vérifiés.

## À exécuter sur le PC hôte après installation

1. Sauvegarde PostgreSQL réussie avant migration.
2. Migration sans suppression des paiements et visages existants ; réexécution sans remise à zéro des stocks.
3. `docker compose config --quiet`, construction des images, `backend` et `auth` healthy, accès au port 3000 via edge.
4. Caméra USB hôte, vérification du visage, mot de passe et signal LED vert. Mauvais mot de passe : rouge clignotant dix secondes ; visage refusé : rouge fixe trente secondes ; deux refus : blocage cinq minutes. Respecter les consignes matérielles fournies par l’enseignant.
5. `python scripts/shop_smoke.py` : compte fictif, commande, rejeu sans doublon, stock, annulation deux fois sans double remise en stock, déconnexion.
6. Parcours complet client → équipe : une commande confirmée, préparée, prête puis retirée ; nouvelle connexion après désactivation impossible.
7. Recette des services, des en-têtes et de la limitation de débit sur le proxy réel. Ne pas confondre un 429 de protection avec une indisponibilité à redémarrer.

## Limites

Le navigateur de validation utilise les vrais handlers FastAPI et le moteur PostgreSQL embarqué de test ; pas de services Docker ni d’accès caméra matériel dans cet environnement. Le firmware et les secrets présents sur le PC ne sont pas remplacés. Les tests de sécurité et de continuité du workshop complet restent ceux de `SECURITE_REARM.md`.
