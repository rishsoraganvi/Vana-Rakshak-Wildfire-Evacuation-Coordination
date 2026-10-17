# API Coverage — Groq

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

| capability | decision | reason |
|---|---|---|
| chat.completions.create (non-streaming) | INTEGRATE | |
| completion metadata (response model, finish_reason, usage) | INTEGRATE | |
| reasoning controls for GPT-OSS (reasoning_effort, include_reasoning) | INTEGRATE | |
| request timeout | INTEGRATE | |
| models.list / models.retrieve | OPT-OUT | not needed at runtime: the model id is config (settings.llm_model); used only by the one-off served-model check in 02-06 Task 3 |
| streaming responses (stream=True) | OPT-OUT | not needed yet: one bounded rationale per run (D-09); no streaming consumer until the Phase 5 dashboard |
| tool / function calling | OPT-OUT | explicitly out of scope: D-09 limits the LLM to a grounded rationale; numeric and safety outputs are deterministic |
| JSON mode / structured outputs (response_format) | OPT-OUT | not needed yet: the rationale is free text (D-09); grounding and format checks are MD-10 (deferred) |
| client retry configuration (max_retries) | OPT-OUT | not needed yet: tracked as LO-09 (deferred) |
| async client (AsyncGroq) | OPT-OUT | not needed: LangGraph Coordinator nodes run synchronously in Phase 2 |
| audio transcription / translation / speech | OPT-OUT | explicitly out of scope: no audio in the Phase 2 pipeline |
| batches and files APIs | OPT-OUT | not needed: one synchronous call per Coordinator run |
| embeddings | OPT-OUT | not needed: no retrieval in Phase 2 |
