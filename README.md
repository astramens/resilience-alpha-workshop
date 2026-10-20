# RESILIENCE-ALPHA — base applicative corrigée

Cette version remplace la maquette par un frontal React/Next relié à une API FastAPI et PostgreSQL. Elle n’est pas encore le démonstrateur complet exigé par le workshop. Lire `AUDIT.md` pour le périmètre restant.

## Démarrage sur Windows / Docker Desktop

Prérequis : Python 3 et Docker Desktop démarré avec les conteneurs Linux / WSL2.
Depuis un terminal ouvert dans ce dossier :

```powershell
python scripts/configure.py
docker compose config --quiet
docker compose up --build -d
docker compose logs -f backend frontend
```

Ouvrir http://localhost:3000. L’identifiant initial est `operateur`. Le script affiche le mot de passe généré, également conservé dans votre `.env` local. Aucun mot de passe n’est livré dans cette archive. Ne partagez pas votre `.env`.

Depuis un autre PC du laboratoire : http://192.168.137.1:3000 si c’est bien l’adresse du PC Hôte. Pour une autre adresse, compléter `ALLOWED_ORIGINS` dans `.env`, puis `docker compose up -d`. Les origines doivent inclure le protocole et le port, sans slash final. Le navigateur passe par le frontal : il ne contacte jamais `localhost:8000`.

Le protocole HTTP et le cookie non Secure sont réservés au laboratoire isolé. Pour HTTPS, configurer `COOKIE_SECURE=true` et ajouter l’origine HTTPS. Le service de remédiation conserve le socket Docker : il reste très privilégié, malgré la suppression du port publié et le jeton interne. Ce risque est à traiter avant de parler de durcissement complet.

### En cas d’installation antérieure

Ne supprimez aucun volume. Sauvegardez votre ancienne configuration et les données avant de la remplacer. Cette archive ne migre pas automatiquement les secrets ni les données de l’ancien projet.

Le script ne remplace jamais un `.env` existant. Si vous conservez un volume PostgreSQL, conservez impérativement son ancien `POSTGRES_PASSWORD` et ajoutez les nouvelles variables de configuration. Modifier `.env` ne modifie pas le mot de passe PostgreSQL déjà initialisé.

Les scripts d’initialisation ne s’exécutent qu’au premier démarrage de la base. Pour appliquer les nouvelles tables à un volume existant :

```powershell
docker compose up -d db
docker compose exec db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/init.sql'
docker compose up --build -d
```

Le mot de passe opérateur ne sert qu’à créer le compte au premier démarrage de l’API. Le modifier dans `.env` ne change pas un compte déjà créé. La gestion et la rotation des comptes restent à implémenter. Il existe un seul opérateur partagé et un seul compte métier, ce n’est pas un modèle multi-utilisateur.

## Utilisation

- Se connecter avec le compte généré.
- Saisir un bénéficiaire fictif, par exemple `DEMO-CLIENT01`, un montant et éventuellement une référence.
- Le solde et l’historique sont chargés depuis PostgreSQL. Le débit et l’insertion utilisent la même transaction SQL et un verrou sur le compte.
- Après une réponse réseau incertaine, garder les mêmes champs et réessayer conserve l’identifiant de requête dans l’onglet courant. Après rechargement de page, vérifier d’abord l’historique. L’identifiant n’est pas conservé après fermeture/rechargement de l’onglet.
- Rechercher, charger 25 ou 100 transactions, consulter les détails et exporter les lignes filtrées en CSV.
- Dans Supervision : état API + SQL, latence et erreurs des 100 dernières requêtes API conservées en mémoire. Pas de faux score ML, de SLA, ni de RTO.

## Vérification sur votre machine

```powershell
python scripts/smoke_test.py
```

Ce test demande l’URL et les identifiants, crée un paiement fictif de **0,01 EUR**, rejoue la même demande et vérifie qu’un seul débit a eu lieu. Il teste aussi l’historique et la déconnexion. Aucune donnée bancaire réelle n’est utilisée.

Pour les tests de contrat de l’API :

```powershell
python -m pip install -r backend/requirements.txt pytest httpx
python -m pytest tests -q
```

Pour le frontal hors Docker : Node 22+, `npm ci`, `npm run build`. Définir `API_INTERNAL_URL=http://127.0.0.1:8000` au lancement si l’API tourne localement. Le dossier `frontend` contient seulement le Dockerfile du frontal.

## Services et interfaces

| Composant | Accès | Rôle |
|---|---|---|
| frontend | port hôte 3000 | React et relais `/api/*` côté serveur |
| backend | réseau Compose, 8000 | session, paiement, historique, mesures |
| db | réseau Compose, 5432 | données métier, comptes opérateurs, sessions |
| ai-engine | interne | ancien prototype IsolationForest, adaptation au nouveau endpoint de mesures |
| remediation | réseau Compose, 9000 | redémarrage du backend du projet configuré, jeton obligatoire |

L’authentification est intégrée à l’API : mots de passe scrypt salés, jetons de session aléatoires dont seule l’empreinte est enregistrée, cookie HttpOnly/SameSite, expiration après huit heures, déconnexion avec révocation en base. Un service d’authentification distinct reste requis pour répondre complètement au sujet.

Le détecteur existant reste un prototype à revoir. Le moteur de remédiation annonce `health_restored`, avec `business_recovery_verified=false` : un check HTTP/SQL ne prouve pas la reprise métier.

## État des vérifications effectuées

Voir `VALIDATION.md`. La recette sur votre PC avec Docker et PostgreSQL reste indispensable. Ne présentez pas les tests utilisant des doublures comme une preuve de fonctionnement de l’infrastructure complète.
