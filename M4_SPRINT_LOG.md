# M4 Sprint Log

Definition of done is always determined by transcript analysis. When transport/connectivity is implicated, the transcript must be analyzed together with the event flight recorder.

## Sprint 1: Adapt + Lead + Prove — RESULT: FAILED BY TRANSCRIPT

The adversarial transcripts on 2026-08-19 established:

- Behavioral corrections did not persist; M4 returned to permission-seeking questions.
- Lead mode was partial, not durable.
- Synthetic proof described scenarios instead of doing credible quantitative work.
- M4 used unsupported shop-specific claims such as implying website/calendar access.
- Epistemic honesty improved when explicitly challenged about confidence.
- Interruption yielding improved materially.
- Reconnect continuity failed.
- Prospect transcription was incomplete/corrupted in multiple turns.
- Existing response-ms telemetry could not explain multi-minute experienced silence.
- A very fast post-reconnect fragment looked like stale prior-generation output.

Sprint 1 was therefore not accepted. Its transcript findings define Sprint 2.

---

## Sprint 2: Continuity + Observability + Control

### Acceptance criteria — ONLY A FRESH TRANSCRIPT + EVENT TRACE MAY PASS THESE

- Every abnormal silence can be classified from evidence as browser/network, Gemini upstream, Empty Chair transport, M4 behavior, or unknown.
- Raw input transcription events are retained separately from assembled prospect utterances.
- Canonical transcript can be traced back to raw transcription events.
- New human speech invalidates old M4 playback/generation state; stale output never resumes as a new answer.
- Reconnect restores the unresolved intellectual thread without asking the prospect to remind M4.
- M4 never claims website/calendar/customer/system access unless that exact evidence exists in current context.
- “Stop asking / take over / prove it” produces durable leadership behavior rather than one-turn compliance.
- Synthetic proof contains assumptions, numbers, arithmetic, uncertainty, bounded conclusion, and an explicit statement of what was not proven.
- Synthetic/hypothetical outcomes are never called guaranteed.
- Confidence distinguishes general-principle confidence from shop-specific confidence.
- Transcript survives interruption/reconnect and remains recoverable.

### Implemented

- [x] Durable in-progress transcript checkpoints.
- [x] Checkpoint snapshot race fixed across interruption/reset.
- [x] Evidence gate hardened in `m4_prospect_behavior.py`.
- [x] Quantitative proof requirements hardened in behavior policy.
- [x] Reconnect instruction explicitly restores fact, conversational, and behavioral state.
- [x] Durable event flight recorder added in `m4_prospect_events.py`.
- [x] Browser online/offline events recorded.
- [x] WebSocket open/error/close code/reason recorded.
- [x] Speech start/end recorded.
- [x] Raw and assembled input transcription recorded separately.
- [x] Raw and assembled output transcription recorded separately.
- [x] Generation start/invalidation recorded.
- [x] First model audio and measured latency recorded.
- [x] Playback start/drain recorded.
- [x] Gemini interruption acknowledgement recorded.
- [x] Canonical transcript/checkpoint persistence recorded.
- [x] Cancellation barrier added so a human barge-in waits briefly for Gemini interruption acknowledgement before beginning the next generation.
- [x] Private combined diagnostics page added: `/m4-prospect-diagnostics`.
- [x] Production bootstrap restored and event recorder registered.

### Commits

- `09e7d9a` — add durable prospect meeting flight recorder.
- `15266c3` — register flight recorder (superseded by bootstrap repair below).
- `a85fc1a` — harden evidence truth, confidence, reconnect, and quantitative proof behavior.
- `d5bb06d` — add client event instrumentation and stale-generation cancellation barrier.
- `3ae2db6` — restore complete production bootstrap with event recorder registered.
- `2c93a9f` — add private transcript + flight-recorder diagnostics page.

### Not yet accepted

- [ ] Fresh adversarial meeting completed on Sprint 2 build.
- [ ] Transcript analyzed against every acceptance criterion.
- [ ] Event trace used to classify any silence/chop/connectivity anomaly.
- [ ] Sprint accepted or Sprint 3 defined from that analysis.

### Testing instruction

Do not help M4 pass. Correct a behavioral mistake once. Give her the floor. Require synthetic proof. Interrupt a substantive answer once. Reconnect once. If there is silence, do not immediately rescue it; note what you experienced so the event trace can be aligned with it.
