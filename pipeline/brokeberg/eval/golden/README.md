# Golden set

`items.yaml` — hand-labeled items scored by `make eval`. Labels mirror the pass outputs.

## Labeling rules

- **relevant** — would this belong in a US federal political-economic feed? Congress/Senate votes,
  bills and FEC filings are always relevant (the gate skips the LLM for them).
- **event_type** — one value from `taxonomy.EventType`.
- **entities** — canonical IDs of every *registry* entity named in the body (senators, states as
  `fips:NN`, races, FRED series, and the bill an item is about as `bill:<congress>-<type>-<n>`).
  Do **not** list the author, sponsor, or voters: those come from structured fields and are not
  scored. Do not list things with no registry yet (agencies, countries, companies) — they belong
  in the review queue, and listing them here would make recall unreachable.
- **topics** — every `taxonomy.Topic` the item is substantively about. Empty is fine.
- **stances** — `(canonical_id, topic, position)` only where the text shows that actor taking a
  position. "support" = supports the action/proposal the document describes on that topic.
- **verified** — set `true` only after a human checked every label on the item. `make eval
  --save-baseline` refuses while any item is unverified.

`synthetic: true` items are written for coverage (off-topic negatives, statement-style stance
cases, an ambiguous-name case). They quote real senators but **are not real statements**, so
`make eval` excludes them by default and the baseline is real items only. Run
`make eval ARGS="--include-synthetic"` for an extra, report-only view. Replace them with real
statement/news items over time; stance metrics currently rest on only two real items.
