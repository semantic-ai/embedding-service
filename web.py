from fastapi import APIRouter, BackgroundTasks
from ollama import Client
from helpers import log, query, update, sparqlQuery, sparqlUpdate
from web import app
from fastapi_crons import Crons
import os
import time
import uuid
from config.config import embedding_targets, batch_size, embedding_vector_chunk_size, embedding_graph, embedding_model, cron_schedule

ollama_host = os.environ.get("OLLAMA_HOST", "http://embedding-ollama:11434")

router = APIRouter()
crons = Crons(app)

def prefixed_log(message: str):
    log(f"APP: {message}")

prefixed_log(f"Ollama host set to: {ollama_host}")

ollama = Client(
    host=ollama_host
)

prefixed_log("Pulling embedding model from Ollama...")
embedding = ollama.pull(embedding_model)
log("Embedding model pulled successfully.")

# we need to use sudo as we will be modifying data all across the database without a user triggering a request
sparqlQuery.customHttpHeaders["mu-auth-sudo"] = "true"
sparqlUpdate.customHttpHeaders["mu-auth-sudo"] = "true"

@router.get('/status')
def get_status():
    return {"status": "ok"}

# endpoint for testing, normally this service reacts to tasks or target documents to embed, this service should not be exposed publicly
@router.post('/embed')
def get_embed(request_body: dict):
    input_string = request_body.get("input", "")

    embedding = ollama.embed(
        model=embedding_model,
        input=[input_string]
    )
    return {"embedding": embedding.embeddings[0]}

currently_embedding = False
def embed_all_targets():
    global currently_embedding
    if currently_embedding:
        prefixed_log("Embedding process already running, skipping new trigger.")
        return
    currently_embedding = True
    for target_config in embedding_targets:
        keep_embedding_until_done(target_config)
    currently_embedding = False

@crons.cron(cron_schedule, name="embedding_cron")
def embedding_cron():
    embed_all_targets()

@router.post('/delta')
def handle_delta(background_tasks: BackgroundTasks):
    # naively start embedding on any incoming delta
    background_tasks.add_task(embed_all_targets)
    return {"status": "ok"}

def keep_embedding_until_done(target_config):
  config_name = target_config['name'] if 'name' in target_config else 'unnamed'
  prefixed_log(f"Starting embedding process for target config {config_name}")
  has_more = True
  while has_more:
      embeddings_created = generate_embeddings_for_targets(target_config)
      if embeddings_created == 0:
          has_more = False
  prefixed_log(f"Completed embedding process for target config {config_name}")

def generate_embeddings_for_targets(target_config):
    batch_of_available_targets = find_embedding_targets(target_config)
    if len(batch_of_available_targets) == 0:
        prefixed_log("No targets found to embed.")
        return 0
    count_todo = count_embeddings_todo(target_config)
    prefixed_log(f"Found {count_todo} targets to embed, starting batch of {len(batch_of_available_targets)}.")

    embeddings = batch_embed(batch_of_available_targets)

    prefixed_log(f"Storing {len(embeddings)} embeddings...")

    store_embeddings(target_config, embeddings)
    prefixed_log(f"Stored {len(embeddings)} embeddings.")
    return len(embeddings)

def batch_embed(found_targets):
    prefixed_log(f"Generating embeddings for {len(found_targets)} targets...")
    start = time.time()
    embeddings = ollama.embed(
        model=embedding_model,
        input=[result['content'] for result in found_targets]
    )

    end = time.time()
    prefixed_log(f"Generated embeddings in {end - start} seconds.")

    return [{ 'target': found_targets[i]['target'], 'embedding': embeddings.embeddings[i]} for i in range(len(found_targets))]

def count_embeddings_todo(target_config):
    count_result = query(f"""
      SELECT (COUNT(DISTINCT(?target)) AS ?count) WHERE {{
        {target_config['filter']}
        FILTER NOT EXISTS {{
          GRAPH <{embedding_graph}> {{
            ?target <{target_config['embedding_predicate']}> ?existingEmbedding .
          }}
        }}
      }}
    """)
    return int(count_result['results']['bindings'][0]['count']['value'])

# the embedding vector as a single string can be too large for our triple store to handle, so
# it's split into linked lists of size defined by the config
def create_embedding_lists(embedding):
    embedding_uuid = str(uuid.uuid4())
    embedding_uri = "http://mu.semte.ch/vocabularies/ext/embeddingVector/" + embedding_uuid
    chunks = [ embedding[i:i+embedding_vector_chunk_size] for i in range(0, len(embedding), embedding_vector_chunk_size) ]
    chunk_triples =[ build_list_item_triples(embedding_uuid, chunks, i) for i in range(len(chunks)) ]

    update(f"""
      PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
      PREFIX ext: <http://mu.semte.ch/vocabularies/ext/>

      INSERT DATA {{
        GRAPH <{embedding_graph}> {{
          <{embedding_uri}> a ext:EmbeddingVector ;
                ext:hasChunkedValues {build_chunk_uri(embedding_uuid, 0)} .
          {'\n'.join(chunk_triples)}
        }}
      }}
    """)
    return embedding_uri


def build_list_item_triples(embedding_uuid, chunks, i):
    chunk_values = ",".join([str(x) for x in chunks[i]])
    chunk_uri = build_chunk_uri(embedding_uuid, i)
    next_chunk_uri = None
    if i < len(chunks) - 1:
        next_chunk_uri = build_chunk_uri(embedding_uuid, i+1)
    return f"""
      {chunk_uri} a rdf:List ;
            rdf:first "{chunk_values}" ;
            {f"rdf:rest {next_chunk_uri} ." if next_chunk_uri else "rdf:rest rdf:nil ."}
    """

def build_chunk_uri(embedding_uuid, chunk_index):
    return f"<http://mu.semte.ch/vocabularies/ext/embeddingVector/{embedding_uuid}/chunk/{chunk_index}>"




def store_embeddings(target_config, embeddings):
    predicate = target_config['embedding_predicate']

    embedding_uris = [create_embedding_lists(item['embedding']) for item in embeddings]

    embedding_values = [ f"(<{embeddings[i]['target']}> <{embedding_uris[i]}>)" for i in range(len(embeddings)) ]
    embedding_values_s = "\n          ".join(embedding_values)

    update(f"""
      INSERT {{
        GRAPH <{embedding_graph}> {{
          ?target <{predicate}> ?embedding .
        }}
      }}
      WHERE {{
        VALUES (?target ?embedding) {{
          {embedding_values_s}
        }}
        GRAPH ?g {{
          ?target a ?thing .
        }}
      }}
    """)

def find_embedding_targets(targets):
    # unsafe inclusion of variables in query, but this comes from config file, not user input
    available_targets = query(f"""
      SELECT DISTINCT ?target ?content WHERE {{
        {targets['filter']}
        FILTER NOT EXISTS {{
          GRAPH <{embedding_graph}> {{
            ?target <{targets['embedding_predicate']}> ?existingEmbedding .
          }}
        }}
      }} limit {batch_size}
    """)

    return [{'target': row['target']['value'], 'content': row['content']['value']} for row in available_targets['results']['bindings']]
