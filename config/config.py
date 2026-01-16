embedding_targets = [
  {
    "filter": """
      ?target a <http://data.europa.eu/eli/ontology#Expression> .
      ?target <https://data.europarl.europa.eu/def/epvoc#expressionContent> ?content .
    """,
    "embedding_predicate": "http://mu.semte.ch/vocabularies/ext/embeddingVector"
  }
]

batch_size = 100
embedding_vector_chunk_size = 50
embedding_graph = "http://mu.semte.ch/graphs/public"
#embedding_model = "embeddinggemma:300m-bf16" bigger, but slower
embedding_model = "embeddinggemma:300m-qat-q4_0"
cron_schedule = "*/5 * * * *" # every 5 minutes