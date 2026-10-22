# REARM — Exécution de la reprise par Ansible

Cette étape remplace le redémarrage direct par le SDK Docker dans le service de
remédiation. Le détecteur appelle toujours la même route interne authentifiée.
Le service lance un playbook Ansible fixe, lequel utilise le proxy Docker déjà
restreint au backend de ce projet. Les autres services, le schéma SQL, les
paiements, les secrets et le matériel ne sont pas modifiés.

## Ce qui change

Le chemin d'action devient : détecteur → `/alerts` authentifié → playbook
`recover_backend.yml` → module local `rearm_backend_restart` → docker-guard →
redémarrage du backend. Le moteur Ansible s'exécute dans le conteneur Linux
`remediation` ; aucune installation Ansible ni clé SSH n'est nécessaire sur
Windows. Il s'agit d'un playbook local qui pilote une API restreinte, pas de
l'administration générale du PC hôte.

Le module effectue un GET d'inventaire puis un GET d'inspection, vérifie le
projet Compose, le service `backend`, l'identifiant et éventuellement le nom
configuré. La cible doit être unique. Le proxy vérifie à nouveau les étiquettes
avant le seul POST autorisé : `restart?t=10`. Aucun nouvel accès au socket
Docker n'est ajouté. Ni commande shell, ni collection communautaire, ni URL,
ni nom de playbook fournis par une alerte ne sont utilisés.

Le conteneur de remédiation devient non privilégié (UID/GID 65532), avec racine
en lecture seule, espace temporaire limité à 64 Mio, mémoire limitée à 256 Mio,
capacités supprimées et aucun port publié. Les réseaux existants sont conservés.
Le processus Ansible reçoit une liste fermée de variables (projet, cible,
chemins internes et locale). Il ne reçoit ni jeton de remédiation, ni secret
Stripe, ni clé caméra, ni variables ANSIBLE/proxy injectées de l'extérieur.

Le token reste dans le parent FastAPI qui reçoit l'alerte et vérifie la sonde
interne. Le parent attend un résultat de callback JSON strict, un code de
sortie nul et exactement une action acquittée. Une erreur ou un résultat
inattendu ne peut pas être présenté comme une reprise technique réussie.

## Version et sources de référence

- `ansible-core==2.20.10`, publication du 5 octobre 2026, Python >= 3.12 :
  https://pypi.org/project/ansible-core/2.20.10/
- Modules locaux, interface `AnsibleModule`, support du mode contrôle :
  https://docs.ansible.com/projects/ansible/latest/dev_guide/developing_modules_general.html
- Compatibilité et maintenance du moteur :
  https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html

La dépendance directe est fixée. Les images de base et toutes les dépendances
transitives ne sont pas figées par ce correctif ; ce n'est pas une garantie de
reconstruction binaire identique ni une attestation d'absence de vulnérabilité.

## Installation, une étape à la fois

Conserver la fenêtre de l'agent caméra et celle du listener Stripe ouvertes.
Ne pas lancer de paiement pendant une recette de panne.

1. Extraire `REARM-Ansible.zip` à côté du projet existant. Depuis PowerShell
   ouvert dans le projet actuel, exécuter `python` suivi du chemin complet de
   `REARM-Ansible/install.py`. L'installateur vérifie les empreintes de l'export
   source(4), sauvegarde les fichiers remplacés et ne redémarre rien. En cas
   de fichier modifié depuis cet export, il s'arrête avant toute écriture.
2. `docker compose config --quiet` : aucune sortie signifie que la syntaxe
   et les variables requises sont acceptées. Ne pas afficher la configuration
   complète ni le fichier `.env` dans un échange.
3. `docker compose up -d --build --no-deps remediation log-gateway`
   Reconstruit seulement ces deux services. Ne pas redémarrer le détecteur,
   le backend, la base ou l'authentification. Aucune migration SQL n'est requise.
4. `docker compose restart grafana` pour charger les événements supplémentaires
   du tableau de reprise.
5. `python scripts/ansible_check.py` : exécute réellement Ansible `--check`,
   contrôle la cible unique et vérifie le refus d'une alerte sans jeton.
   Les seules opérations du module en mode contrôle sont des lectures GET.
   Aucun redémarrage, achat, paiement ou changement de configuration métier.
6. `python scripts/recovery_check.py` : le dossier de reprise précédent et sa
   preuve RA-00006 doivent toujours être présents. Le détecteur doit être
   calibré et le backend sain. Si le détecteur a été redémarré pour une autre
   raison, attendre sa calibration de 20 observations avant la suite.

Une sauvegarde de base est déjà faite avant l'étape de reprise. Cette mise à
jour ne modifie aucune table et n'exige pas de nouvelle migration.

## Recette réelle sur le PC, distincte du mode contrôle

Après réussite des contrôles, lancer une seule fois :

```powershell
python scripts/recovery_demo.py --stop-backend
```

Le script arrête seulement le backend, attend la récupération via l'automate
et mesure le délai depuis l'arrêt. Il vérifie les préconditions et attend un
NOUVEAU dossier INC-... dont la reprise technique est enregistrée. Sa commande
de secours, si elle est nécessaire, est explicitement signalée et invalide la
recette d'autonomie. Ne pas redémarrer manuellement les services pendant ce test.

Le délai de 30,6 s et la commande RA-00006 correspondent à la recette précédente
avec le SDK Docker. Ils ne prouvent PAS le fonctionnement du nouveau chemin
Ansible. Le nouveau test doit donner son propre délai, sans promesse de résultat
inférieur à 60 secondes sur toute machine. Le mode contrôle ne mesure pas ce délai.

Lorsque le script confirme la reprise technique, créer une NOUVELLE commande
sur la boutique et la payer avec Stripe TEST. Ne pas réutiliser RA-00006.
Après environ 20 secondes, exécuter `python scripts/recovery_check.py`.
Le nouveau dossier doit devenir `business_verified` avec le numéro de cette
nouvelle commande. Un succès Ansible ou un HTTP 200 n'est jamais une preuve
de paiement ; aucun paiement n'est automatisé par ce correctif.

Grafana : Dashboards → REARM → REARM — Reprise et preuve métier. Les événements
filtrés de remédiation comprennent `ansible_repair_completed` (exécution acquittée)
ou `ansible_repair_failed` (échec/incertitude), puis les signaux habituels
`scoped_backend_restart`, `recovery_reported` et `recovery_business_verified`.
La collecte est asynchrone ; une absence de log ne vaut jamais succès. Le log
Ansible n'inclut pas la référence INC : corréler par l'horaire et vérifier le
registre de reprise, qui reste l'autorité pour la preuve métier.

Vérifier ensuite le parcours visage → mot de passe → espace équipe. La mise
à jour conserve la correction du panneau des sondes et celle des doublons WAF.

## Bornes et échecs

Le processus Ansible est borné à 25 s. En cas de dépassement, son groupe de
processus local est arrêté et le service ne tente pas un second redémarrage.
Une requête déjà reçue par Docker peut néanmoins se terminer après cette
interruption : le résultat est alors incertain, jamais déclaré réussi.
Le contrôle technique après l'action est borné à une fenêtre de 25 s, avec
délais HTTP individuels ; l'objectif de 60 s doit être mesuré lors de la recette.

Les délais entre actions restent ceux du laboratoire : 60 s côté remédiation,
120 s côté détecteur. Ces temporisations et la calibration restent en mémoire
et sont réinitialisées par un redémarrage de leurs processus ; les rapports
hors ligne, le registre PostgreSQL et ses preuves restent persistants. Une
reconstruction pendant une panne n'est pas une opération anodine : terminer
ou diagnostiquer d'abord la recette en cours.

Un redémarrage est une action volontaire et non une convergence idempotente :
relancer le playbook hors mode contrôle redémarre à nouveau le backend. C'est
pourquoi l'API authentifiée et les temporisations encadrent son exécution. Ce
correctif n'ajoute aucune route d'exécution générique ni lancement de playbook
choisi par un client. L'entrée de diagnostic en ligne de commande accepte
uniquement `--check`.

Le module, le parent et le proxy constituent du code de confiance. Le proxy
Docker et le collecteur privilégié existants gardent un accès puissant au
socket ; le nouveau playbook ne transforme pas cette frontière en bac à sable
absolu. La politique reste limitée à la reprise du backend. Elle ne répare
pas toute vulnérabilité, toute corruption de base, la panne du PC, de Windows
ou de Docker. Un agent arrêté sur le même hôte ne peut pas relancer cet hôte.
L'extension multi-hôtes et la gestion chiffrée des secrets restent distinctes.

## Validation de préparation et validation sur site

Tests exécutés avant livraison : moteur Ansible 2.20.10 réel sur Python 3.12,
mode contrôle sans POST, un redémarrage demandé à un proxy HTTP simulé,
refus des cibles absentes/ambiguës/hors projet, refus d'une inspection incohérente,
résultat de processus non confirmé, arrêt du groupe en dépassement de délai,
filtrage de l'environnement et régressions du cycle reprise/paiement. Les tests
SQL utilisent PostgreSQL embarqué PGlite et un fournisseur Stripe simulé,
jamais votre base ou votre compte. Le démon Docker et le matériel ne sont pas
disponibles dans cet environnement de préparation : le contrôle et la recette
sur votre PC restent nécessaires. Les tests d'intégration réinitialisent leurs
tables de test : NE PAS les exécuter contre la base du projet en cours.

## Retour aux fichiers précédents

En cas de problème, ne pas déclencher de nouvelle panne. Depuis le projet :

```powershell
python scripts/ansible_rollback.py
```

Ce script vérifie qu'aucun fichier du correctif n'a été modifié depuis son
installation, restaure les fichiers sauvegardés et retire les fichiers ajoutés.
Il n'efface aucune donnée, aucun secret, aucune preuve ni volume Docker.
Appliquer ensuite les anciens services :

```powershell
docker compose up -d --build --no-deps remediation log-gateway
docker compose restart grafana
```

Conserver la sauvegarde `.rearm-backup-ansible-*` jusqu'à validation. Ne jamais
utiliser `docker compose down -v` pour revenir sur cette mise à jour.
