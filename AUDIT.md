# Audit de l’archive initiale et périmètre de correction

## Ce que l’archive contenait réellement

L’archive initiale contient une page React avec des tableaux de données fixes, une API FastAPI de paiement, un schéma PostgreSQL, un détecteur IsolationForest, un service de redémarrage Docker et un fichier Compose. Les icônes et illustrations sont des ressources génériques. Il n’y avait pas de README ni de tests.

### Défauts constatés dans le code initial

| Fichier | Constat vérifiable | Conséquence |
|---|---|---|
| `app/page.tsx` | Aucun appel fetch/API. Paiement validé par setTimeout et identifiant aléatoire | Aucun débit ni enregistrement depuis l’écran |
| `app/page.tsx` | Transactions, solde, services, incidents et horaires codés en dur | Supervision sans lien avec les mesures réelles |
| `app/page.tsx` | Boutons « Voir tout », rafraîchir et lancer un test sans gestionnaire | Contrôles inactifs |
| `app/page.tsx` | Bascule locale `incident` | L’incident graphique ne perturbe aucun service |
| `backend/main.py` | Aucun utilisateur, login, session ni contrôle d’accès | Toute personne atteignant l’API peut débiter le compte |
| `backend/main.py` | Montants float et absence de clé d’idempotence | Validation monétaire imprécise, risque de double demande |
| `docker-compose.yml` | API et moteur de remédiation publiés, identifiants de développement par défaut | Interfaces internes accessibles à l’hôte/réseau selon pare-feu |
| `frontend/Dockerfile` / Compose | variable publique localhost au lancement, inutilisée dans la page | Pas de raccordement front/API. En outre localhost désigne le PC du visiteur |
| `next.config.mjs` | `ignoreBuildErrors: true` | Erreurs TypeScript ignorées au build |
| `ai-engine/detector.py` | Modèle réentraîné sur une fenêtre contenant le point testé, mélange ML et règles | Évaluation ML insuffisante et risque d’apprendre les anomalies |
| `ai-engine/detector.py` | Surveillance injoignable entraîne une demande de redémarrage | Échec de collecte confondu avec panne métier |
| `ai-engine/detector.py` | Réponse de remédiation ignorée et délai de cinq secondes | Alerte considérée traitée même si remédiation échoue |
| `remediation/remediator.py` | Endpoint sans authentification avec accès au socket Docker | Action privilégiée trop accessible |
| `remediation/remediator.py` | Recherche de conteneur par service sans restriction au projet | Risque de cibler un autre projet Compose |
| `remediation/remediator.py` | Validation de reprise limitée à /health | Aucune preuve de nouvelle transaction réussie |
| `.env` et Compose | secrets/configuration de développement embarqués | Archive initiale incompatible avec l’exigence de rendu sans secrets en clair |

La page initiale prétendait notamment montrer OAuth2/JWT, ModSecurity, des scores ML et une règle WAF appliquée. Les services ou mécanismes correspondants ne sont pas présents dans l’archive.

## Changements de cette version

Interface en français refaite avec navigation persistante, connexion, paiement relié à PostgreSQL, messages d’erreur, historique, recherche, détails, export CSV et supervision de l’API. Les informations invérifiables ont été retirées.

Ajout de sessions serveur et de contrôles d’accès sur les routes métier, vérification Origin sur les mutations, mots de passe scrypt et blocage temporaire après cinq tentatives infructueuses dans la même fenêtre. L’authentification reste intégrée au backend et monorôle.

Montants Decimal limités à deux décimales, bénéficiaires explicitement fictifs, clé d’idempotence et refus d’utiliser une même clé pour une demande différente. Le verrou SQL et la transaction évitent de séparer le débit de l’enregistrement.

Relais HTTP côté Next pour une même origine navigateur, suppression des ports hôte 8000/9000, jeton interne de remédiation, sélection du backend limitée au projet Compose et délai minimum entre deux demandes de redémarrage. La remédiation reste très privilégiée car elle monte le socket Docker. Le cooldown est local au processus et ne constitue pas une file de travail durable.

Suppression des secrets livrés et génération locale, build TypeScript activé, utilisation du lock npm, suppression de l’analytique externe de la page et ajout de documentation/tests.

## Conformité au sujet : ce qu’il reste à réaliser

Le sujet national impose cinq piliers interconnectés. Une application de paiement corrigée ne suffit pas.

| Attendu | Situation de cette version | Prochaine preuve à produire |
|---|---|---|
| Interface, API, base et transactions | Implémentés, intégration Docker à valider sur l’hôte | Recette réelle et persistance après redémarrage |
| Authentification en microservice | Sessions intégrées à l’API | Service séparé et droits vérifiés |
| Déploiement Compose et Ansible | Compose fourni, Ansible absent | Déploiement reproductible par playbook |
| Prometheus / Grafana / Loki | Endpoint texte Prometheus ajouté, stack absente | Scraping, dashboard et journaux corrélés |
| ML sur données collectées | Prototype hérité insuffisamment évalué | Jeu normal, séparation entraînement/test, mesures et limites |
| Assistant Ollama / LangChain / RAG | Absent | Réponses sourcées dans les procédures locales |
| WAF et fonction SIEM/SOC | Absents | Règles appliquées, journaux et alertes visibles |
| Gestion des secrets Vault ou SOPS | Génération locale seulement | Chiffrement / distribution des secrets et politique d’accès |
| Attaque depuis un second PC | Aucun scénario fourni | Effet réel, maîtrisé, reproductible dans le seul laboratoire |
| Détection puis reprise autonome | Prototype de restart seulement | Incident, décision, action, paiement réussi sans correction humaine |
| EBIOS RM, PCA/PRA, NIS2/DORA | Absents | Documents reliés à l’architecture et aux essais réels |
| Clip 60 s, dossier et support jury | Absents | Livrables selon les noms prescrits |

Priorité : valider les paiements et les sessions sur Docker, puis choisir un seul incident démontrable avec les autres membres. Instrumenter cet incident avant de concevoir un entraînement ML. Enfin, vérifier la reprise par une opération métier et conserver les traces avant/pendant/après. Les mesures obtenues alimenteront le dossier et le clip, sans inventer de taux de disponibilité.

Sources examinées : sujet national PROJECT RESILIENCE-ALPHA, consignes particulières, présentation Workshop M2 et archive applicative fournis dans cette conversation. Il ne s’agit pas d’une attestation de conformité réglementaire ni d’un audit de sécurité exhaustif.
