# API Coverage — Groq

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
> Phase 3 starts again from the full-coverage baseline (Phase 2 opt-outs are re-decided here, not carried over).

| capability | decision | reason |
|---|---|---|
| chat.completions.create (non-streaming) | INTEGRATE | |
| completion metadata (response model, finish_reason, usage) | INTEGRATE | |
| reasoning controls for GPT-OSS (reasoning_effort, include_reasoning) | INTEGRATE | |
| request timeout | INTEGRATE | |
| JSON mode / structured outputs (response_format json_schema, strict) | INTEGRATE | |
| sampling controls (temperature) | INTEGRATE | |
| completion token cap (max_completion_tokens) | INTEGRATE | |
| models.list / models.retrieve | OPT-OUT | not needed at runtime: the model id comes from config (settings.llm_model) |
| streaming responses (stream=True) | OPT-OUT | explicitly out of scope: Groq strict structured outputs cannot be combined with streaming, and no streaming consumer exists until the Phase 5 dashboard |
| tool / function calling | OPT-OUT | explicitly out of scope: S4 and D-10 limit the LLM to a menu enum via structured output and grounded text; Groq does not support tool use together with strict structured outputs |
| client retry configuration (max_retries) | OPT-OUT | not needed yet: one repair retry is implemented explicitly in choose_fix_strategy (Rules 3), and any error falls back to the deterministic path |
| async client (AsyncGroq) | OPT-OUT | not needed: LLM calls run inside synchronous LangGraph nodes; parallel dispatch uses asyncio.to_thread for specialists, not for LLM calls |
| audio transcription / translation / speech | OPT-OUT | explicitly out of scope: no audio in the planning pipeline |
| batches and files APIs | OPT-OUT | not needed: a bounded number of synchronous calls per coordinator run |
| embeddings | OPT-OUT | not needed yet: pgvector shelter lookup is deferred (D-04) |
