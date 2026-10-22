import os

from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate

# Connexion à la base vectorielle créée par ingest.py
embeddings = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
# On récupère large (12), puis on garde les 6 meilleurs en plaçant d'abord les fiches de
# procédures : sinon la documentation technique des services, plus volumineuse, les évince.
TOP_K = int(os.getenv("RAG_TOP_K", "6"))
retriever = db.as_retriever(search_kwargs={"k": int(os.getenv("RAG_FETCH_K", "12"))})


def is_procedure(doc):
    source = doc.metadata.get("source", "")
    return "procedures" in source or "/infra/" in source or "infra-" in source

# Le LLM local. Modèle choisi par le déploiement (RAG_LLM_MODEL) : qwen3.8:27b sur le GPU de
# délestage, llama3.2:3b par défaut. reasoning=False coupe le mode « réflexion » des modèles
# qui en ont un (Qwen) : réponse directe, sans bloc <think>, nettement plus rapide.
llm = OllamaLLM(model=os.getenv("RAG_LLM_MODEL", "llama3.2:3b"), reasoning=False)

# Le prompt : on FORCE la réponse depuis le contexte (anti-hallucination)
PROMPT = ChatPromptTemplate.from_template(
    "Tu es un assistant pour les opérateurs d'une plateforme de paiement. "
    "Réponds UNIQUEMENT à partir du contexte ci-dessous. "
    "Si l'information n'y est pas, dis clairement que tu ne sais pas.\n\n"
    "Contexte :\n{context}\n\n"
    "Question : {question}\n\n"
    "Réponse :"
)

def ask(question):
    found = retriever.invoke(question)
    # Tri stable : l'ordre de pertinence est gardé à l'intérieur de chaque groupe
    docs = sorted(found, key=lambda d: not is_procedure(d))[:TOP_K]
    context = "\n\n".join(d.page_content for d in docs)
    prompt = PROMPT.format(context=context, question=question)
    return llm.invoke(prompt)

if __name__ == "__main__":
    question = "Que faire si l'API de paiement ne répond plus ?"
    print("Question :", question)
    print("Réponse :", ask(question))
