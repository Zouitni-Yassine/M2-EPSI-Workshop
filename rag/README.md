# Assistant RAG — Domaine IA

Assistant conversationnel local destiné aux opérateurs confrontés à un incident.
Il répond en langage naturel à partir des procédures et documents de l'équipe
(procédures d'incident, description d'architecture, runbooks).

**Principe de sécurité :** l'assistant est en **lecture seule**. Il aide à comprendre
et à retrouver une procédure ; il ne déclenche aucune action sur le système et ne
dispose d'aucun accès privilégié. Il ne doit pas être confondu avec le moteur de
remédiation automatique.

## Architecture (RAG — Retrieval-Augmented Generation)

1. **Indexation** (`ingest.py`) : les documents de `docs/` sont découpés en segments,
   convertis en vecteurs (embeddings) et stockés dans une base vectorielle ChromaDB.
2. **Récupération + génération** (`chain.py`) : à chaque question, les segments les plus
   pertinents sont récupérés, puis fournis au modèle de langage, à qui l'on impose de
   répondre **uniquement** à partir de ce contexte (limitation des hallucinations).
3. **Interface** (`app.py`) : une interface de chat Streamlit pour la démonstration.

## Stack technique

| Composant | Choix | Rôle |
| --- | --- | --- |
| Runtime LLM local | Ollama | Exécution des modèles en local, sans appel externe |
| Génération | llama3.2:3b | Reformulation de la réponse à partir du contexte |
| Embeddings | nomic-embed-text | Vectorisation des documents et des questions |
| Base vectorielle | ChromaDB | Stockage et recherche par similarité |
| Orchestration | LangChain | Chaîne récupération → prompt → génération |
| Interface | Streamlit | Chat de démonstration |

## Choix du modèle de génération (arbitrage)

Le développement a d'abord été mené avec **llama3 (8B)**, puis le modèle a été remplacé
par **llama3.2:3b** après comparaison sur un même jeu de questions de test :

- **Qualité** : en configuration RAG, le modèle ne mobilise pas sa connaissance propre ;
  il reformule un contexte qui lui est fourni. Le modèle 3B s'est révélé au moins aussi
  pertinent que le 8B sur nos procédures, avec des réponses plus lisibles.
- **Latence** : l'inférence s'exécute sur **CPU** (pas de GPU disponible sur le poste de
  développement). Ollama reste exigeant pour cette machine ; le temps de réponse est donc
  contraint par le matériel, davantage que par la taille du modèle. Le gain du 3B sur la
  latence est modéré, mais le modèle plus léger réduit la charge mémoire.
- **Contrainte du sujet** : le modèle local doit rester ≤ 8B ; un modèle plus compact est
  recevable s'il est cohérent avec le matériel et l'usage. Le choix du 3B respecte cette
  contrainte et l'assume.

**Pistes d'amélioration des performances** (hors périmètre des 4 jours) :
- Exécution sur **GPU** (PC de délestage IA prévu par le sujet) : accélération de l'ordre
  de 10 à 50× par rapport au CPU.
- Garder le modèle chargé en mémoire (`OLLAMA_KEEP_ALIVE=-1`) pour supprimer le temps de
  rechargement entre deux requêtes.
- Réponse en streaming (affichage progressif) pour améliorer le ressenti utilisateur.

## Prérequis

- Ollama installé et démarré
- Les deux modèles tirés localement :

    ollama pull llama3.2:3b
    ollama pull nomic-embed-text

## Installation et lancement

    python -m venv .venv
    source .venv/bin/activate         # Windows : .venv\Scripts\activate
    pip install -r requirements.txt

    python ingest.py                  # indexe les documents de docs/
    streamlit run app.py              # lance l'interface de chat

> Après tout ajout ou modification d'un document dans `docs/`, relancer `python ingest.py`
> pour réindexer la base.

## Structure

    rag/
      docs/              documents sources (procédures, architecture...)
      ingest.py          indexation des documents dans ChromaDB
      chain.py           chaîne RAG (récupération + génération)
      app.py             interface de chat Streamlit
      requirements.txt   dépendances Python
      .gitignore         exclut .venv/ et chroma_db/ (régénérables)

## Limites connues

- La pertinence des réponses dépend directement de la **qualité et de la couverture des
  documents** de `docs/`. L'assistant ne peut répondre qu'à ce qui y est documenté.
- Les performances sont limitées par l'exécution **sur CPU** ; un GPU est recommandé en
  conditions réelles.
- La base vectorielle (`chroma_db/`) est **régénérable** et n'est pas versionnée ; elle est
  reconstruite par `ingest.py`.
