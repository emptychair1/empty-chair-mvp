# M4 Sprint Log

## Sprint: Adapt + Lead + Prove

Definition of done is determined only by transcript analysis from a fresh adversarial meeting.

### Acceptance criteria
- A behavioral correction changes M4's behavior for the rest of the meeting.
- “Take over / show me / prove it / stop asking” switches M4 into leadership mode.
- In leadership mode, M4 stops permission-seeking and demonstrates judgment.
- M4 can use clearly labeled synthetic data to demonstrate reasoning without presenting synthetic output as real-shop evidence.
- Thinking presence is natural, sparse, and varied; no canned repeated reassurance.
- Mistakes produce brief recovery plus changed behavior, not an apology loop.
- Reconnect resumes the unresolved intellectual thread with minimal ceremony.
- M4 distinguishes known facts, inference, demonstration, and proof.
- Transcript capture is complete and recoverable.

### Progress
- [x] Sprint created from recovered transcript analysis.
- [x] Behavioral adaptation instructions implemented in `m4_prospect_behavior.py`.
- [x] Leadership/proof mode implemented in the prospect behavior policy.
- [x] Thinking-presence policy implemented: sparse, varied, no spontaneous silence checks.
- [x] Live transcript checkpoint infrastructure implemented for in-progress turns.
- [ ] Transcript integrity verified by a fresh meeting transcript.
- [ ] Fresh adversarial meeting completed.
- [ ] Transcript analyzed against acceptance criteria.
- [ ] Sprint accepted or next sprint defined.

### Commits
- `c7bdc0e` — start transcript-driven sprint log.
- `1d62f68` — add transcript-driven prospect behavior policy.
- `25ce435` — register behavior policy in production bootstrap without changing audio transport.
- `5a296de` — add durable in-progress transcript checkpoint storage and recovery reads.
- `31b42c5` — register checkpoint layer in production bootstrap.
- `535126f` — continuously checkpoint prospect and M4 transcription during the live meeting.

### Notes
The behavior layer is intentionally separate from Gemini realtime transport. Future transcript-driven behavior changes should land there first unless transcript evidence points to an audio/state-machine defect.

The durability bug found in this sprint was that canonical turn rows were written only after M4's response playback completed. The new checkpoint path preserves partial input/output transcription throughout the turn and exposes surviving checkpoint text through normal transcript/recovery reads. This is implemented but will not be considered verified until a fresh transcript demonstrates recovery and completeness.
