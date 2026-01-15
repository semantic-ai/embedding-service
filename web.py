from fastapi import APIRouter
from ollama import Client
from helpers import log
import os

ollama_host = os.environ.get("OLLAMA_HOST", "http://embedding-ollama:11434")

router = APIRouter()

log(f"APP: Ollama host set to: {ollama_host}")

ollama = Client(
    host=ollama_host
)

log("APP: Pulling embedding model from Ollama...")
embedding = ollama.pull("embeddinggemma:300m-bf16")
log("APP: Embedding model pulled successfully.")

@router.get('/status')
def get_status():
    return {"status": "ok"}

# endpoint for testing, normally this service reacts to tasks or target documents to embed
@router.post('/embed')
def get_embed(request_body: dict):
    input_string = request_body.get("input", "")

    embedding = ollama.embed(
        model="embeddinggemma:300m-bf16",
        input=[input_string]
    )
    return {"embedding": embedding.embeddings[0]}