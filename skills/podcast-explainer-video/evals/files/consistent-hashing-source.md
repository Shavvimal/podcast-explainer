# Consistent hashing (source notes for evaluation 01)

These notes stand in for a document the learner pastes into the session. Every number in the episode must trace to a line here.

## The problem

A cache cluster spreads keys over N servers. The naive rule is `server = hash(key) mod N`. When N changes from 4 to 5, a key keeps its server only if `hash mod 4` equals `hash mod 5`, which holds for about 1 key in 5. So about 80% of keys move, and the cache misses on almost every request until it refills.

## The idea

Consistent hashing places servers and keys on the same circle of hash values (a ring from 0 to 2^32 - 1). A key belongs to the first server found by walking clockwise from the key's position. When a server joins, it takes keys only from its clockwise neighbour. When a server leaves, only its keys move, to its clockwise neighbour. With N servers, a change moves about 1/N of the keys on average.

## Virtual nodes

With few servers, the arcs on the ring have very uneven lengths, so one server can own far more keys than another. The fix is to place each physical server on the ring many times, as virtual nodes. Karger et al. (1997) showed that with O(log N) virtual copies per server, the load is balanced with high probability. Amazon's Dynamo paper (DeCandia et al., 2007) describes virtual nodes as the way to spread load when a node becomes unavailable and to account for servers of different capacity.

## Sources

- Karger, Lehman, Leighton, Panigrahy, Levine, Lewin. "Consistent Hashing and Random Trees." STOC 1997.
- DeCandia et al. "Dynamo: Amazon's Highly Available Key-value Store." SOSP 2007.
