# Capability record: Gemini multimodal structured output (P0-C)

- **Capability / owning phases:** text + image input with schema-constrained JSON output (P0-C; used by P4 and P5).
- **Provider / tool / model:** Gemini Developer API, `google-genai` 3.3.0 (Python 3.12.3, uv venv), model `gemini-3.5-flash-lite`. The response reported `model_version: gemini-3.5-flash-lite`.
- **Account / project alias:** the owner's AI Studio project. The key lives in `.env.local` as `GEMINI_API_KEY`; its value is not recorded.
- **Checked at:** 2026-11-14 20:40 CT (`models.list`) and 20:51 CT (generation).
- **Documentation:** https://aistudio.google.com/docs/models, /docs/structured-output, /docs/image-understanding, /docs/rate-limits, /docs/billing (see P0-docs-verification.md).
- **Entitlement observed:**
  - `models.list` returned HTTP 200 with 64 models. They include `gemini-3.5-flash-lite`, `gemini-4-hydrogen`, `gemini-3.1-flash-lite`, `gemini-2.5-flash-lite`, `gemini-3.5-transcribe` and `gemini-3.5-transcribe-live` (bidi).
  - The owner confirmed the project is on the free tier with no billing linked (D20).
  - The response carried the header `x-gemini-service-tier: standard`. That most likely names the processing tier, not billing; still, check that the AI Studio usage page shows $0.
- **Real smoke test:** one request, PASS.
  - Input: a synthetic 854×480 ffmpeg `testsrc2` JPEG (26,820 bytes) plus the transcript line "Hi it's FaZeGavin and we'll be 1v1ing my friend FaZeNeville!".
  - Config: a Pydantic JSON schema via `response_json_schema`, `temperature=0`, `max_output_tokens=1024`.
  - Output: valid against the schema. `announced_future_challenge=true`; `participants=["FaZeGavin","FaZeNeville"]` (exact spelling kept); `contains_text=true`; a plausible scene summary.
  - Latency: 2.325 s end to end from the laptop.
  - Usage: prompt 1,161 tokens (**image 1,100**, text 61), output 102, total 1,263.
  - Reproduce with `spikes/p0-gemini/smoke.py <model> <jpeg>`. The key is read from the environment only and never printed.
- **Limits:**
  - Numeric free RPM/TPM/RPD: **UNVERIFIED**. They are visible only at https://aistudio.google.com/rate-limit; ask the owner to read them.
  - Limits apply per project, and RPD resets at midnight Pacific.
- **Budget implications (P4/P5):**
  - One 854×480 frame costs about 1,100 tokens, so the documented 258-tokens-per-tile estimate does not hold for this model.
  - Calls are event-triggered with few frames each. Before P4, downscaled or cropped frames, or a lower media resolution, should be measured.
  - At a 5 s cadence (720 requests/hour), each request with 3 frames would use about 3.4k tokens, so the daily quota must be checked against the RPD figure before choosing a cadence.
- **Cash required:** $0 on the free tier. Even at the paid rate, this request would have cost about $0.0006. The stop threshold is any sign of billing; disable the provider rather than switch keys.
- **Hardware:** not relevant (hosted API).
- **Selected primary path:** `gemini-3.5-flash-lite` via `generateContent`. It is labelled "legacy" but fully supported. Decide whether to move to the Interactions API before P4. Keep the model ID centralized.
- **Owner-approved fallback:** none paid. If the free quota is exhausted, pause proposals and use operator approval with canned fixtures, labelled as such.
- **Status:** VERIFIED for text + image + structured output on this account. Quota figures UNVERIFIED.

The record contains no key, phone number or personal data. The test image is synthetic.
