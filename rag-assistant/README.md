# Assistant documentaire local REARM

Ce module ajoute un second composant IA documentaire au projet. Il ne modifie pas le détecteur ou la remédiation.

## Installation Windows
Préconditions : Docker Desktop disponible, conteneur `rearm-ollama` démarré selon les commandes précédentes, port 8501 libre. Depuis la racine REARM, appeler `install.ps1` du kit avec l'opérateur `&`. Le script télécharge Qwen2.5 1.5B (1,54 milliard de paramètres) et nomic-embed-text:v1.5, copie uniquement cinq procédures explicitement autorisées, ajoute un réseau interne et déploie l'interface avec un projet Compose distinct. L'interface écoute seulement sur localhost:8501. En cas d'erreur, l'installation s'arrête. Si le dossier cible existe, elle refuse d'écraser les fichiers.

## Fonctionnement
Les fichiers Markdown sont découpés par LangChain en extraits de 850 caractères avec recouvrement de 120. OllamaEmbeddings calcule leurs vecteurs via nomic-embed-text. InMemoryVectorStore retrouve les quatre extraits proches de la question. ChatOllama transmet ces extraits et la question à Qwen2.5 1.5B. L'interface montre réponse et extraits sources, sans exécuter de commande. Le corpus est monté en lecture seule et son empreinte invalide le cache après modification. L'index n'est pas persistant : il est reconstruit au redémarrage. Aucune API de modèle externe ni traçage LangSmith n'est configuré.

## Périmètre et limites
L'assistant s'appuie sur les procédures, pas sur des journaux en direct. Il ne peut pas certifier l'état courant du SI ou inventer une transaction. Un petit modèle peut se tromper, citer imparfaitement ou ne pas respecter une consigne de refus. Les extraits affichés permettent de vérifier sa réponse. La recherche renvoie toujours quatre extraits au maximum et ne dispose pas encore d'un seuil de pertinence calibré. Ce prototype exige une recette qualitative, notamment sur les questions hors corpus et les instructions malveillantes contenues dans les documents.

Les conteneurs du RAG n'ont ni socket Docker ni secrets ni accès aux réseaux métier. Ollama conserve son bridge existant pour télécharger les modèles. L'interface sans authentification est exclusivement locale, pour l'opérateur du PC Hôte. Une exposition réseau exigerait authentification et revue des accès. Le RAG peut consommer de la RAM et du CPU : l'utilisation simultanée pendant le Clip Chrono doit être mesurée. Le modèle de réponse est déchargé après chaque requête, avec deux threads de calcul demandés.

## Exploitation depuis rag-assistant
`docker compose ps`
`docker compose logs --tail=50 rag-assistant`
`docker compose up -d --build` : reprise après installation interrompue, si modèles, corpus et réseau sont déjà présents.
`docker compose stop` : arrêt de l'assistant documentaire uniquement.
`docker start rearm-ollama` : démarrage du service de modèle si arrêté.
`docker compose up -d` : démarrage de l'interface.

Le script original de création du conteneur Ollama est :
`docker run -d --name rearm-ollama -p 127.0.0.1:11434:11434 -v rearm_ollama_models:/root/.ollama ollama/ollama`
Il faut créer puis connecter `rearm-rag-local` avant de démarrer le Compose RAG, ce que fait install.ps1. Les modèles restent dans rearm_ollama_models.

## Versions et remise
Le premier build résout les versions compatibles définies par requirements.txt et conserve le résultat dans /app/requirements-resolved.txt. Avant remise, exporter cette liste : `docker compose exec -T rag-assistant cat /app/requirements-resolved.txt`. Conserver aussi `docker exec rearm-ollama ollama list` et les identifiants des images pour la traçabilité. Les versions exactes du premier build ne sont pas encore verrouillées dans l'archive fournie. Vérifier que l'export final REARM inclut le dossier rag-assistant ; l'exporteur existant peut avoir une liste de fichiers autorisés.

## Validation du kit
Syntaxe Python vérifiée lors de la préparation. Docker et PowerShell ne sont pas disponibles dans l'environnement de construction : aucun build Docker, téléchargement de modèle ou résultat RAG réel n'y a été exécuté. La validation de bout en bout reste à effectuer sur le PC Hôte avec RECETTE.md.

## Références
https://ollama.com/library/qwen2.5:1.5b
https://ollama.com/library/nomic-embed-text
https://docs.langchain.com/oss/python/integrations/chat/ollama
https://docs.langchain.com/oss/python/integrations/embeddings/ollama
