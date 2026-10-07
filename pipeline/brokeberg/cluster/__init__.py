"""Pass 6: cluster member events into happenings and materialize the event object.

Clustering is code (cosine + entity overlap + thresholds); the LLM only breaks ties in the
ambiguous band and writes the event object's prose over stored spans.
"""
