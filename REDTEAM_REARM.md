# REARM : essai distant de ReDoS, laboratoire volontairement vulnerable

## Ce que cet ajout demontre

Une seule requete HTTPS provenant du second PC peut affamer la boucle evenementielle
de l'API avec une expression reguliere volontairement mauvaise. Le catalogue et la
sonde /health cessent alors reellement de repondre. Le detecteur existant observe la
panne, puis appelle le service de remediation ; Ansible redemarre le seul backend.
La preuve doit montrer les evenements concordants puis une nouvelle commande payee
avec Stripe TEST. Aucun paiement n'est execute par les scripts de cette recette.

Il s'agit d'une faiblesse CWE-1333 INTRODUITE pour le laboratoire, pas d'une faille
decouverte dans le code REARM initial. Le coach doit pouvoir comprendre ce choix.
Ce scenario ne prouve ni une correction generale du code par une IA, ni la reprise
de Windows/Docker, ni l'absence de compromission. Le ML existant ne change pas :
trois echecs de sante avec anomalie ML, ou six echecs par seuil de secours.
Il faut relever dans les journaux quel mecanisme a effectivement decide l'action.

Reference technique primaire : https://cwe.mitre.org/data/definitions/1333.html
OWASP : https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS

## Mecanisme et bornes

* Route pedagogique : GET /api/shop/lab/reference. Aucun appel Docker ni remediation
  dans cette route ; elle n'invente pas un statut de sante et n'emploie pas sleep.
* Expression fixe `^(a+)+$`, entree fixe : 34 lettres a puis un point d'exclamation.
  L'entree provoque un retour arriere exponentiel. Une inondation reseau est inutile.
* Le chemin vulnerable est ferme par defaut (404) et n'est pas arme au demarrage.
  Une preverification publique `?q=reference-ok` retourne seulement des metadonnees.
* Un operateur LOCAL possedant deja Docker peut armer un seul essai pour cinq
  minutes. Capacite aleatoire 256 bits, empreinte seule dans /tmp, permissions 0600,
  liee a un nonce d'instance de l'API. Aucun secret existant n'est reutilise.
* L'autorisation est consommee AVANT le calcul. Apres redemarrage, rejouer la meme
  requete ne relance pas le calcul. Rearmer reintroduit VOLONTAIREMENT la faiblesse.
  Cette fermeture est un confinement du laboratoire, pas un correctif logiciel general.
* Limites du backend : 1 CPU, 256 Mio, 96 processus/threads, tmpfs de 32 Mio.
  L'authentification, le WAF et la base ne changent pas de droits ou de reseaux.
* Un petit superviseur PID 1 lance l'API. Il ne la relance pas lui-meme : cela reste
  le role d'Ansible/Docker. L'API est un processus enfant, afin que le secours puisse
  la terminer (un enfant ne peut pas compter sur SIGKILL contre le PID 1 de Docker).
* Un enfant independant borne le calcul a 120 secondes. S'il doit tuer l'API, il
  emet `lab_safety_timeout` et Docker peut la relancer : la recette est alors ECHEC.
  Si le calcul finit naturellement (`lab_regex_returned`), la reprise autonome n'est
  pas prouvee non plus. `watch` refuse explicitement ces deux cas.
* Le kit attaquant n'accepte que https://192.168.137.1, sans proxy ni redirection,
  valide le certificat avec la CA publique fournie et envoie UNE requete sans retry.
  Les seules requetes suivantes lisent le catalogue, a faible cadence.

## Installation — PC Hote uniquement

Depuis le projet actuel, appliquer install.py de l'archive, puis :

```powershell
docker compose config --quiet
docker compose up -d --build --no-deps backend log-gateway
python scripts/redos_lab.py check
```

Ne pas activer de nouvel essai tant que check ne passe pas. La reconstruction du
backend provoque une courte interruption ; ne pas acheter pendant cette operation.
La calibration ML existante est conservee car ai-engine n'est pas redemarre.
Si une reprise est en attente de preuve metier, la terminer avant cette recette.
Il n'y a aucune migration SQL ni modification de .env, des certificats ou du firmware.

## Preparation d'un essai

Verifier que le second PC Windows est uniquement sur le PA du groupe et dispose de
Python. Les tests WAF et SOC deja effectues constituent une preuve complementaire.
Preparer Grafana sur le PC Hote et conserver les fenetres camera et Stripe ouvertes.
Ne pas enregistrer de secrets dans la video.

Sur le PC Hote :

```powershell
python scripts/redos_lab.py arm
```

Un dossier `REARM-PC-attaquant-<date>` est cree A COTE du projet, jamais dedans.
Copier ce dossier complet sur le second PC (support du groupe). Il contient le script,
la CA PUBLIQUE ca.pem et run.json, autorisation temporaire du seul essai. Ne pas
joindre run.json a un chat ni le placer dans Git. Aucun rootCA-key.pem, key.pem,
.env, visage ou jeton de production n'est copie. Si les cinq minutes passent,
utiliser disarm puis arm ; ne pas changer l'horloge ou contourner les controles.

Ouvrir PowerShell dans le dossier copie sur le second PC :

```powershell
python trigger_redos.py
```

Le script verifie TLS et le catalogue, demande de saisir REARM, puis envoie la
requete unique. Observer le catalogue et le dashboard. Une interruption de reponse
du script ne suffit pas a prouver la panne ; les sondes et les logs doivent concorder.
Ne pas envoyer d'autres charges pendant l'attente et ne pas passer de commande.

Sur le PC Hote, verifier les preuves sans declencher de reparation :

```powershell
python scripts/redos_lab.py watch
```

Ce controle exige `lab_redos_started`, une execution Ansible hors mode controle,
un redemarrage par docker-guard et une NOUVELLE ligne technique dans le registre.
Il refuse un secours de 120 secondes ou une terminaison naturelle du calcul.
Le delai et le lien avec le ML se mesurent dans les logs horodates, pas a partir
de la seule duree affichee par une sonde ou par une ancienne ligne du registre.

```powershell
docker compose logs --since=5m --tail=25 ai-engine
docker compose logs --since=5m remediation
```

Creer ENSUITE une NOUVELLE commande Stripe de TEST depuis https://localhost, la payer,
puis `python scripts/recovery_check.py`. L'incident doit devenir business_verified
avec cette commande. Un ancien paiement ou un retour navigateur ne suffit pas.

Fin de recette : `python scripts/redos_lab.py disarm`, puis supprimer le run.json
du kit copie sur le second PC. Les journaux et le registre restent disponibles.

## Echecs et retour arriere

Si `watch` echoue, ne pas annoncer une reprise validee et ne pas rearmer en boucle.
Consulter les observations du detecteur et les logs Ansible/guard. Le secours de
120 secondes doit rester signale comme ECHEC meme si le catalogue revient.
Un secours manuel `docker compose restart backend` est possible mais invalide
la demonstration autonome de cet essai. Ne pas arreter la base ou effacer les volumes.

Pour revenir au code precedent : desarmer si possible, puis
`python scripts/redos_rollback.py` et reconstruire backend/log-gateway comme indique.
Le retour arriere ne touche ni aux secrets, ni aux donnees, ni au HTTPS.

## Preuves et limites de validation de cette livraison

Tests locaux : calcul regex reel dans un serveur ASGI separe ; /health bloque ;
remplacement du processus et fermeture du laboratoire ; secours reel avec journal
et code de sortie du superviseur ; capacite expiree/invalide/rejouee refusee ;
kit limite a l'IP du groupe ; refus des fausses preuves. Tests de regression sur
les interfaces de reprise, Ansible, guard, filtrage des logs et API.

Le fournisseur n'a pas execute Docker Desktop Windows, votre WAF reel, votre modele
deja calibre, votre camera ou Stripe. L'execution de bout en bout doit donc encore
etre recettee sur vos machines ; les temps reels ne sont pas garantis.
Le Clip Chrono <= 60 s doit etre mesure sur une capture CONTINUE depuis le second
PC, avec etat avant/pendant/apres et verification metier. Un temps de reprise
technique inferieur a 60 s ne suffit pas a valider a lui seul toute la video.
