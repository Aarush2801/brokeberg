"""Pass 7: ground event objects against evidence. All code; selection is not verification.

Corroboration counts independent sources and numeric claims are checked against `indicators`;
together they set the event's `verification_status`. Stance flips are marked on the stance row,
not the event. The LLM plays no part here.
"""
