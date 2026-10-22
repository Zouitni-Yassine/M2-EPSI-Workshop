from langchain_community.document_loaders import DirectoryLoader, TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma

# 1. Charger les documents Markdown et PDF du dossier docs/
md_loader = DirectoryLoader("docs/", glob="**/*.md", loader_cls=TextLoader)
pdf_loader = DirectoryLoader("docs/", glob="**/*.pdf", loader_cls=PyPDFLoader)
documents = md_loader.load() + pdf_loader.load()
print(f"{len(documents)} document(s) chargé(s)")

# 2. Découper en chunks (morceaux)
splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
chunks = splitter.split_documents(documents)
print(f"{len(chunks)} chunks créés")

# 3. Générer les embeddings et stocker dans ChromaDB
embeddings = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma.from_documents(chunks, embeddings, persist_directory="chroma_db")
print("Indexation terminée. Base vectorielle : ./chroma_db")