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
- [x] Finished meetings can auto-export transcript + event trace to the owner's email for connected analysis.

### Not yet accepted

- [ ] Fresh adversarial meeting completed on Sprint 2 build.
- [ ] Transcript analyzed against every acceptance criterion.
- [ ] Event trace used to classify any silence/chop/connectivity anomaly.
- [ ] Sprint accepted or next sprint defined from that analysis.

---

## Sprint 3: Automated Synthetic Prospect Regression

Goal: remove the human founder from routine architecture regression. Human voice testing becomes final acceptance, not the primary debugging loop.

### Implemented

- [x] `m4_synthetic_harness.py` provides a deterministic meeting-state controller and transcript/event evaluator.
- [x] Real adversarial trigger phrases drive LEAD and PROOF meeting state.
- [x] Structured state persists question budget, permission-seeking prohibition, sales rejection, synthetic-data authorization, proof request, unresolved thread, and behavioral constraints.
- [x] Generation ownership model explicitly invalidates old generations and forbids invalidated playback.
- [x] Transcript evaluator detects unsupported website/calendar/system-access claims.
- [x] Transcript evaluator detects permission-seeking after a lead/takeover instruction.
- [x] Proof evaluator requires quantitative content, method/arithmetic, uncertainty/bounding, and rejects guarantee language.
- [x] Reconnect evaluator uses the exact `I'm back. Continue.` regression phrase.
- [x] Event evaluator verifies raw/assembled transcription visibility, required flight-recorder coverage, and stale-generation playback safety.
- [x] Historical bad transcripts are encoded as permanent fixtures under `tests/fixtures/m4_historical_regressions.json`.
- [x] Desired epistemic behavior is encoded as a positive regression fixture.
- [x] Pytest regression suite runs automatically with the repository test suite.
- [x] `m4_synthetic_live.py` conducts a full text-only adversarial meeting against the current M4 prospect instructions using Gemini, requiring no microphone or human participant.
- [x] `.github/workflows/m4-regression.yml` runs deterministic architecture regression on relevant pushes and supports model-in-loop regression when a Gemini API key is available to GitHub Actions.
- [x] Model-in-loop run uploads the complete synthetic transcript and evaluation as a workflow artifact.

### Automated acceptance contract

A routine architecture change is not ready for human testing unless:

1. deterministic regression passes;
2. historical failure fixtures remain detected;
3. desired-behavior fixture passes;
4. model-in-loop transcript passes evidence, lead-mode, proof, and reconnect checks when the API-enabled job is available;
5. transport architecture tests show no invalidated generation reaching playback.

Human acceptance is still required for voice cadence, perceived dead air, natural interruption feel, and buyer-level emotional/credibility judgment.

### Sprint 3 commits

- `4b5c7be` — synthetic M4 meeting-state and transcript/event evaluator.
- `04e1ce7` — architecture/adversarial regression tests.
- `5a6d1ed` — historical transcript regression fixtures.
- `6879c9b` — fixture enforcement tests.
- `51852b9` — model-in-loop synthetic prospect runner.
- `e8bf275` — dedicated automated M4 regression workflow.

### Status

Implementation complete. CI/model-run evidence determines pass/fail; no human meeting is required to debug routine architecture failures.
