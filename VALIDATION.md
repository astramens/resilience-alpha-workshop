# Vérifications de cette version

Effectuées le 19 octobre 2026.

- `npm run build` : réussi, avec compilation webpack, vérification TypeScript, génération de la page et du relais API. Le build a été basculé sur webpack après un défaut du cache Turbopack dans cet environnement.
- `python -m pytest tests -q` : 12 tests réussis. Couverture : mots de passe salés, montants et bénéficiaires invalides, refus d’origines externes, protection des routes, rejeu de paiement sans nouveau débit dans la logique applicative, cookie de session et déconnexion avec révocation. Les accès SQL de ces tests sont remplacés par des doublures ; ils ne constituent pas une recette PostgreSQL.
- Syntaxe des quatre modules Python : vérifiée.
- Compose : YAML chargé et absence des publications des ports backend/remédiation vérifiée. Pas de validation par `docker compose config` car Docker indisponible ici.

## Vérifications non réalisées

- Construction et démarrage des images Docker, véritable connexion PostgreSQL, migrations et concurrence SQL.
- Scénario d’attaque et reprise autonome.
- Parcours et rendu visuel dans un navigateur. L’essai de lancement Chromium n’a pas abouti dans l’environnement de travail. Aucun test UI réussi n’est revendiqué.
- Qualité/efficacité du modèle ML et fiabilité du redémarrage Docker.

## Recette attendue sur le PC Hôte

Suivre README.md, puis lancer `python scripts/smoke_test.py`. Ce script vérifie réellement un paiement fictif de 0,01 EUR et son rejeu. Vérifier également les boutons et les affichages en navigateur, sur PC et mobile. Tester la persistance après redémarrage des conteneurs et la conservation du solde/historique. Ne pas détruire les volumes pour résoudre une erreur de configuration.

Une seule opération métier réussie après un incident n’est une preuve de reprise autonome que si l’incident, sa détection et l’action corrective sont eux aussi documentés et exécutés sans correction manuelle.
