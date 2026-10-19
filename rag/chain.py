from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate

# Connexion à la base vectorielle créée par ingest.py
embeddings = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
retriever = db.as_retriever(search_kwargs={"k": 4})

# Le LLM local (on réutilise llama3)
llm = OllamaLLM(model="llama3.2:3b")

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
    docs = retriever.invoke(question)
    context = "\n\n".join(d.page_content for d in docs)
    prompt = PROMPT.format(context=context, question=question)
    return llm.invoke(prompt)

if __name__ == "__main__":
    question = "Que faire si l'API de paiement ne répond plus ?"
    print("Question :", question)
    print("Réponse :", ask(question))
