# 0003. Voice identity is a reference clip, not a text description

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** architecture, AI/ML

## Context

The product requirement is that a character sounds like the same person for ten hours, and
again in the sequel.

Open TTS models offer three ways to specify a voice:

1. **Preset** — a fixed speaker id from the model's bank (Qwen3-TTS CustomVoice has nine).
2. **Text description** — "a warm alto with clipped diction" (Qwen3-TTS VoiceDesign).
3. **Reference audio** — clone from a few seconds of speech (Qwen3-TTS Base, ~3 s).

Option 2 is the intuitive one for "cast this character" and is the wrong mechanism for
consistency, for a specific reason: instruction-conditioned models sample from a
*conditional distribution*, not a point. The same description at segment 3 and segment 3,000
lands in a similar region of voice space, not at the same point. Over a 4,000-segment book
this reads as the character ageing, drifting in pitch, or occasionally sounding like a
different person. It is also unmetered: there is no cheap way to assert "this is the same
voice" other than listening.

Option 3 collapses the distribution to a point. Conditioning on identical reference audio
gives near-deterministic speaker identity, and — critically — gives a cheap objective check
(speaker-embedding cosine similarity) that can gate a chapter before it ships.

## Decision

For every character we will:

1. **Manufacture one canonical reference clip** using preset or text-designed voices, generate
   6–10 candidates from a structured persona (timbre, age band, pitch, energy, accent evidence),
   transcribe each, and have a human curator select one for system voices.
2. **Store the clip as an immutable, content-addressed asset** (`reference.wav`, 24 kHz mono,
   with its transcript and duration).
3. **Clone-condition every segment** on that exact clip.
4. **Bind the profile to a model family**, not a specific model version, with an explicit
   compatibility list, so a 0.6B/1.7B swap does not silently become a new character.

The persona description is retained as **human-readable documentation and as the input to
regeneration**, never as a per-segment condition.

## Consequences

**Good**
- Voice identity is now a hash we can compare, embed and validate.
- Changing a character's voice is an explicit operation on one artefact (bump the profile
  revision), which propagates deterministically to render keys.
- Series continuity is inherited for free: the series-level character points at the same
  profile, so book 2 sounds like book 1.
- Drift detection is possible and cheap (embed every Nth segment, compare to reference).
- Accent policy becomes auditable: `accent.basis` records whether evidence existed, which is
  how we enforce "never infer accent from a name".

**Bad**
- Reference clips are an asset to manage: storage, consent records, deletion cascades.
- A bad reference clip poisons an entire book. Mitigated by curation and by the ABX gate in
  Phase 0.
- Cloning is a policy hazard. The feature is behind a flag, requires a consent record, and is
  off at launch (ADR-0006 overview; see spec 04).
- 3-second reference audio is sensitive to recording conditions. The factory must normalise
  (loudness, noise floor, sample rate) before storage.

## Rejected alternatives

- **Per-segment text description.** Drifts, unmeterable, and makes cache keys enormous and
  nondeterministic if the prose changes.
- **A single system voice for all characters.** Cheapest and simplest, but fails the core
  product promise of multi-character narration.
- **Voice cloning from a user-supplied recording at launch.** Highest quality for a specific
  author's book, highest legal exposure. Deferred to Phase 7 with consent infrastructure.
- **Deterministic seed alone.** Seeding helps within a model version, but does not survive
  hardware/kernel changes, quantization, or model upgrades.

## Revisit when

- A model ships instruction-conditioned generation with demonstrably stable identity across
  10k segments (measured, not claimed). The architecture would still keep the reference clip
  as the source of truth and use the description only as a fallback.
