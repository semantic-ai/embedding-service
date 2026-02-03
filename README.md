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
`embedding_model`: the ollama model to use for embeddings
`cron_schedule`: the cron string to use for automatically scheduling embedding runs, even if no deltas arrive

## Model
Embeddings created by this service are stored as instances of the type `<http://mu.semte.ch/vocabularies/ext/EmbeddingVector>`. Because the vectors themselves can be quite large (so they can no longer be stored as single string in virtuoso), they are stored in chunks in an `rdf:List`. The embedding vector points to its first chunk using `<http://mu.semte.ch/vocabularies/ext/hasChunkedValues>`, which then points to its next chunk using `rdf:rest` and its actual value using `rdf:first`. The final chunk points to `rdf:nil` as its `rdf:rest`. To easily order the chunks when required, every chunk has a sortable `<http://mu.semte.ch/vocabularies/ext/mainListIndex>` value.

## Handling updates

An extension for this service to allow handling updates to the properties that result in the embedding vector could be done in a number of ways, but likely some heuristic will have to be used to decide whether or not to update the vector based on the incoming delta. For instance:

- one could depend on a dct:modified date for the instance and store it in the embedding vector, if the modified date is different, recompute the vector and destroy the previous one
- if a delta comes in for a subject (ignoring deltas from self), always recompute the embedding vector
