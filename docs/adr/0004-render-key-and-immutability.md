# 0004. Render key and immutability

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** architecture, backend, AI/ML

## Context

The central economic claim of the product is that a generated segment is generated **once**
and reused by everyone who asks for a compatible rendering. That only works if "compatible"
is defined precisely, deterministically and in one place.

Two failure modes bracket the design:

- **Under-keyed** (key omits a field that affects output): two different-sounding renders
  collide, and a user hears the wrong voice. Silent, corrupting, hard to debug.
- **Over-keyed** (key includes something that varies without affecting output): every request
  is unique, the cache never hits, and unit economics collapse.

The second failure is more likely, because the natural instinct is to hash everything —
including free-text performance notes and the full persona prose.

## Decision

### 1. One canonical key function

`render_key(segment, voice_profile, model_binding, policy) -> "rk1:" + sha256(canonical_json(payload))`

Canonical JSON: sorted keys, no insignificant whitespace, explicit nulls, UTF-8, NFC.
Versioned with the `rk1:` prefix; changing the payload shape means `rk2:` and a background
re-render, never an in-place reinterpretation.

Payload fields, each justified:

| Field | Why it is in the key |
|---|---|
| `text` (normalised hash) | Different words, different audio |
| `phon` (after pronunciation lexicon) | "Read" vs "red" must not collide |
| `lang` | BCP-47; en-GB and en-US differ |
| `spk` | Character identity or `narrator` sentinel |
| `voice.src` + `voice.ref` (sha256) \| `preset_id` \| `design_hash` | The actual identity |
| `voice.rev` | Explicit revision so a change is opt-in |
| `model.id`, `model.ver`, `model.w` (weights sha256) | Different weights, different voice |
| `params` (seed, temperature, top_p, speed) | Decoder settings change output |
| `perf.emotion` (enum), `perf.intensity` (1–3), `perf.pace` (enum), `perf.style` (enum) | Performance direction *after discretisation* |
| `policy` (version) + `pre` (text preprocessing version) | Loudness/trim/denoise and normalisation affect the artefact |

### 2. Directives must be discretised

Emotion is a **closed enum** (`neutral, warm, tense, angry, afraid, sad, joyful, indignant,
tender, weary, urgent, amused`), intensity is **1–3**, pace is `slow|normal|fast`, style is a
small enum. Free-text direction ("bitterly disappointed, almost amused") is *not* in the key;
it is stored on the directive for human review and for possible future instruction models.

Rationale: with continuous or free-text directives, cardinality is unbounded and every
segment is a cache miss. With ~12 × 3 × 3 × 4 combinations, a book's segments collapse onto a
small set of distinguishable performances, which is also closer to how a narrator actually
works.

### 3. Audio artefacts are immutable

A render is written once and never modified. Object keys contain the render key. Regeneration
produces a new row and a new object; the old one stays until garbage collection. There is no
"update the audio in place" path in the codebase — the storage layer rejects `PUT` to an
existing key.

### 4. Fallback models are not silent

If the router falls back to a different model mid-book, the resulting audio belongs to a
different render set. We never mix models inside a chapter. The choice is: complete the
chapter on the primary model, or start a new render set for the remainder and tell the user.

## Consequences

**Good**
- Cache hits are the default path, not an optimisation.
- A user changing one character's voice re-renders exactly that character's segments.
- Cache correctness is testable: a golden test asserts that mutating any single payload field
  changes the key, and that semantically identical inputs produce identical keys.
- Provenance is free: the key *is* the recipe, and the render row stores the key plus the
  resolved provider call.

**Bad**
- Discretisation loses expressive range. A "slightly amused" line becomes "amused,
  intensity 1". Accepted: consistency and cost beat nuance at this stage.
- Pronunciation changes invalidate audio broadly. Mitigated by scoping pronunciation sets per
  book rather than globally.
- Any model upgrade orphans the old cache. This is correct, but it means model upgrades are
  a deliberate cost event, not a free improvement.

## Rejected alternatives

- **Cache on `(chapter, voice)` only.** Too coarse: one changed line re-renders the chapter.
- **Cache on text alone.** Ignores the voice entirely; wrong audio served.
- **Content-addressed by output hash.** You must generate to know the hash. Useless for
  avoiding generation.
- **Mutable audio with a version column.** Makes "which version did this user hear?" and
  CDN invalidation ambiguous, and invites partial-write corruption.

## Revisit when

- An instruction-following TTS model demonstrates stable, low-variance output from a fixed
  natural-language direction *and* a way to hash that direction semantically. Even then, the
  key would hash an embedding of the direction, not the string.
