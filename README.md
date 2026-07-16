# Embedding Service

This service allows automatically creating embeddings for instance based on some target expressions. Once an embedding exists for an instance, no new embeddings will be generated for it, not even on update.

## Config

Find the config and its default values in `./config.py`

Note: the config included by this service can be overridden by mounting config.py to /app/config.py specifically. This is because python didn't like importing from absolute paths without doing some ugly stuff.

`embedding_targets`: this variable holds a list of embedding targets. Every instance contains:

- `name` the name of the set of instances targeted
- `filter` a SPARQL snippet that filters instances that should receive embeddings. Should expose a variable called `?target`.
- `content_path` a SPARQL snippet that binds the value(s) to create embeddings for to the `?content` variable. In case there are multiple values that you want to concatenate, you can work with `UNION` statements and also expose an `?index` variable, ensuring the value for predicate 1 is always followed by the one for predicate 2.
- `embedding_predicate` the predicate to use to connect the instance to its embedding

`max_content_len`: max content length to send to ollama for generating an embedding. This depends on the context length of the model used to generate embeddings
`batch_size`: size of the batches sent to ollama to generate embeddings
`embedding_vector_chunk_size`: the embedding vectors can become too large to be stored in virtuoso, so they are broken up into rdf:Lists. This variable defines the number of dimensions per chunk (last chunk will be smaller or equal)
`embedding_graph`: the graph to write the embeddings to
`embedding_null`: to ensure an instance is marked as processed, even if it doesn't have content that can be turned into an embedding vector, this uri is used as an embedding value for such unprocessable entities (e.g. no match for `content_path`)
`embedding_model`: the model to use for embeddings, in `provider:model` format (e.g. `ollama:embeddinggemma:300m-qat-q4_0` or `mistralai:mistral-embed`)
`embedding_base_url`: the base URL for the embedding provider (defaults to `http://embedding-ollama:11434`, only used for ollama)
`embedding_api_key`: API key for remote embedding providers (e.g. Mistral)
`cron_schedule`: the cron string to use for automatically scheduling embedding runs, even if no deltas arrive

environment:

- `EMBEDDING_MODEL`: the model to use (default: `ollama:embeddinggemma:300m-qat-q4_0`)
- `EMBEDDING_BASE_URL`: base URL for the embedding provider (default: `http://embedding-ollama:11434`)
- `EMBEDDING_API_KEY`: API key for remote providers
- `EMBED_ON_STARTUP`: if not nil, start embeddings on startup

## Running Modes

### Ollama (local model)

By default, the service is configured to use a local Ollama instance. No extra configuration is needed beyond ensuring the Ollama service is reachable.

```yaml
services:
  embedding:
    environment:
      EMBEDDING_MODEL: "ollama:embeddinggemma:300m-qat-q4_0"
      # EMBEDDING_BASE_URL defaults to http://embedding-ollama:11434
  embedding-ollama:
    image: ollama/ollama:0.14.1
    volumes:
      - ./ollama-data:/root/.ollama
    command: serve && pull embeddinggemma:300m
```

### Remote model (e.g. Mistral)

To use a remote embedding provider such as Mistral, set `EMBEDDING_MODEL` to the provider-prefixed model name and provide the API key. The `base_url` parameter is only passed for ollama models, so no override is needed.

```yaml
services:
  embedding:
    environment:
      EMBEDDING_MODEL: "mistralai:mistral-embed"
      EMBEDDING_API_KEY: "<your-api-key>"
```

## Model

Embeddings created by this service are stored as instances of the type `<http://mu.semte.ch/vocabularies/ext/EmbeddingVector>`. Because the vectors themselves can be quite large (so they can no longer be stored as single string in virtuoso), they are stored in chunks in an `rdf:List`. The embedding vector points to its first chunk using `<http://mu.semte.ch/vocabularies/ext/hasChunkedValues>`, which then points to its next chunk using `rdf:rest` and its actual value using `rdf:first`. The final chunk points to `rdf:nil` as its `rdf:rest`. To easily order the chunks when required, every chunk has a sortable `<http://mu.semte.ch/vocabularies/ext/mainListIndex>` value.

# Multiple string values

Multiple values for a `content_path` in an `embedding_target`result in multiple embedding vectors being created, one for each value. In mu-search, these values will be averaged and normalized when they are added to elastic.

## Large sting values

Large string values will be cut off by the `max_content_len` property. This means only the first `max_content_len` characters of long strings are actually taken into account when generating embedding vectors. If this proves problematic, one can split the values of such instances with long strings into 'chunks' and index the chunks instead of the instances. Users of the search service should then be wary that they are searching on chunks and should still follow the path back to the original instance.

Chunking in such a way is not included in this service and should be done by a separate service.

## Handling updates

An extension for this service to allow handling updates to the properties that result in the embedding vector could be done in a number of ways, but likely some heuristic will have to be used to decide whether or not to update the vector based on the incoming delta. For instance:

- one could depend on a dct:modified date for the instance and store it in the embedding vector, if the modified date is different, recompute the vector and destroy the previous one
- if a delta comes in for a subject (ignoring deltas from self), always recompute the embedding vector
