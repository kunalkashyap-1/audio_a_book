# 01. Product Requirements

## 1. Product statement

A public platform that turns books into multi-character audiobooks, and reuses every
expensive artefact it produces. The differentiator is not text-to-speech; it is that the
platform understands the book as a story, keeps characters consistent across chapters and
sequels, and never generates the same audio twice for two listeners.

## 2. Goals

| # | Goal | Measure | Target |
|---|---|---|---|
| G1 | Fast first listen for catalogue titles | p50 time-to-first-audio, cached chapter | < 2 s |
| G2 | Multi-character narration that is identifiable | blind speaker-identification accuracy | ≥ 80% |
| G3 | Voices never change inside a book | unplanned voice discontinuities per 10 h | 0 |
| G4 | Free tier is economically viable | marginal inference cost per audio hour | < $0.35 |
| G5 | Cache is the default path | share of listening minutes served from pre-existing renders | ≥ 70% |

Non-goals at MVP: studios, publishers, rights acquisition, marketing, social features.

## 3. Personas

**Casual listener.** Discovers a classic, presses play on a train. Judge the product on the
first 60 seconds. Cannot be asked to configure anything.

**Series reader.** Listens to trilogies in order and notices immediately if the same character
sounds different in book two. This persona is the reason the series identity registry exists,
and the reason voice profiles attach to series characters rather than to books.

**Self-publisher.** Uploads a manuscript, wants a proof-listen before hiring a human narrator.
Cares about cast control and per-chapter re-rendering more than about voice cloning.

**Curator (internal).** Approves catalogue imports, resolves uncertain attributions, merges
series characters. Needs to review a book's cast in under ten minutes.

**Operator (internal).** Changes providers, sets spend caps, kills inference in an incident.
Judges the platform by whether it can be run without a deploy.

## 4. Core journeys

### 4.1 Discover → play (the primary funnel)

1. Search the catalogue (title, author, subject, language).
2. Book page: cover, description, duration, rights badge, cast preview (2–3 voice samples).
3. Press play. If cached, audio starts immediately. If not, an honest ETA plus a preview.
4. Continue listening; chapter N+1 prefetches while N plays.
5. Resume on another device at the same position.

### 4.2 Upload → cast → listen

1. Upload an EPUB/TXT/PDF/DOCX/HTML file.
2. Parse, normalise, detect chapters. Show structure for confirmation if confidence is low.
3. Run story analysis; show cast with confidence and the uncertain attributions.
4. Adjust voices for 1–3 characters; preview each.
5. Generate chapter 1 first; listen while the rest renders.

### 4.3 Correct an attribution

Playback → "who said this?" → pick from the existing cast or create a character → only the
affected segments are invalidated → re-render on demand. Correction survives reprocessing.

### 4.4 Operator incident

Provider returns 5xx → router falls through the chain → if the chain is exhausted, the job
fails visibly and cached content keeps playing → admin sees provider health and spend on one
screen → can disable the provider without a deploy.

### 4.5 Budget stop

Monthly cap is reached → generation queues pause → cached playback continues → admin is
notified with burn rate and the top spenders.

## 5. Functional requirements

Priority: **M** must (MVP), **S** should (Phase 6–7), **C** could (later), **W** won't (now).

### Catalogue
| ID | Requirement | P |
|---|---|---|
| C-1 | Search across ≥2 connectors with a unified result shape | M |
| C-2 | Retrieve metadata, editions, formats, licence and territory per item | M |
| C-3 | Ingest a catalogue item on demand, not by mirroring everything | M |
| C-4 | Connector enable/disable, schedule, health, last-run status | M |
| C-5 | Manual metadata correction | S |
| C-6 | OCR for scanned PDFs | C |

### Ingestion
| ID | Requirement | P |
|---|---|---|
| I-1 | EPUB, TXT, DOCX, HTML, text-PDF | M |
| I-2 | Chapter detection with confidence; manual override | M |
| I-3 | Block segmentation into narration / dialogue / heading | M |
| I-4 | Content hash + normalised-text fingerprint | M |
| I-5 | Duplicate candidate detection across editions; never auto-merge | M |
| I-6 | Private-by-default uploads with an explicit rights basis | M |

### BookBrain
| ID | Requirement | P |
|---|---|---|
| B-1 | Versioned story representation per revision, reproducible from recorded inputs | M |
| B-2 | Character registry: canonical name, aliases, descriptions, evidence spans | M |
| B-3 | Relationships with type, description, evidence | M |
| B-4 | Dialogue attribution with explicit `certain/probable/uncertain/unattributed` states | M |
| B-5 | Human corrections stored as an overlay that survives reprocessing | M |
| B-6 | Scene detection with boundaries | M |
| B-7 | Chapter summaries and continuity notes | M |
| B-8 | Series-level character links, curator-confirmed | S |
| B-9 | Embeddings for retrieval over summaries and scenes | S |

### Voice
| ID | Requirement | P |
|---|---|---|
| V-1 | Narrator plus character voices from a system library | M |
| V-2 | Per-character preview | M |
| V-3 | Per-character lock and swap | M |
| V-4 | Swap re-renders only that character's segments | M |
| V-5 | Voice cloning with a consent record | C |
| V-6 | User-uploaded reference voice | C |

### Playback
| ID | Requirement | P |
|---|---|---|
| P-1 | Web player: chapter nav, speed, bookmarks, sleep timer (mobile) | M |
| P-2 | Cross-device resume within 2 s | M |
| P-3 | Adaptive prefetch of the next chapter | M |
| P-4 | M4B export with chapter markers | M |
| P-5 | Android background playback, lock screen, Bluetooth, offline | S |

### Admin
| ID | Requirement | P |
|---|---|---|
| A-1 | Provider/model registry with capabilities and price schedules | M |
| A-2 | Capability-based routing with fallbacks | M |
| A-3 | Feature flags with audit | M |
| A-4 | Spend caps: global, provider, user, book | M |
| A-5 | Global inference kill switch with cache-only fallback | M |
| A-6 | Job monitor with retry/cancel | M |
| A-7 | Audit log for every mutation | M |
| A-8 | Cost dashboard split infra vs inference | M |

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| API latency | p95 < 300 ms for non-generation reads |
| Time to first audio | cached < 2 s; uncached chapter p50 < 45 s, p95 < 3 min |
| Job reliability | > 99% chapter success after 3 retries |
| Isolation | No cross-tenant read of uploads, private renders or voice references, ever |
| Cost guard | New provider calls stop within 60 s of a cap breach |
| Availability | 99.5%; degradation mode is "cached only", never a hard outage |
| Accessibility | WCAG 2.1 AA on the player and library |
| Data deletion | Account deletion purges private objects within 24 h, with a manifest |
| Reproducibility | Any shared asset can be traced to (revision, model, weights hash, voice profile revision, pipeline version) |

## 7. MVP boundary

**In:** catalogue (Gutenberg + Standard Ebooks), uploads in five formats, BookBrain v1,
chapter-scoped story analysis, narrator + 6–12 character voices, per-chapter audio with
segment checkpoints, shared cache, web app, minimal admin, English, one region.

**Out:** Android, voice cloning, OCR, multilingual UI, payments, social, SFX/music,
real-time streaming TTS, multi-region, self-service API.

The MVP is complete when a stranger can find a public-domain book, press play, and hear a
multi-voice chapter — and the same chapter is served from cache to the next stranger.

## 8. Security and privacy requirements

**Launch note (ADR-0007).** No OIDC or external identity provider at $0. The launch has two
optional local gates: `AAB_ADMIN_TOKEN` (shared operator token on write endpoints) and
`AAB_JWT_SECRET` (email+password accounts with argon2id, JWT access tokens and rotating
refresh cookies; roles `user/admin`, first registrant is admin). Both are off by default for
single-operator use. Uploads default to private and carry `owner_id` for signed-in users;
only public-domain works appear in the anonymous catalogue, private works and their media
return `404` unless the caller is the owner, an admin or the operator token, and no bytes are
proxied from a third party. The rows below describe the multi-user/cloud target.

- Authentication via OIDC (Cognito Lite); roles `user | curator | admin | finance`.
- Every private row carries `owner_id`; access goes through a repository that injects the
  predicate. A CI test asserts no raw query reaches the `private` schema.
- Audio is delivered by CloudFront signed URLs/cookies with short TTLs; the app never proxies
  bytes.
- Uploads: presigned PUT with content-length and content-type constraints; magic-byte
  validation before parsing; archives are not expanded (zip bombs); PDF page limit.
- Provider credentials encrypted at rest (SSM SecureString), write-only in the UI, never in
  API responses.
- Rate limits per user and per IP on expensive endpoints (search, upload intent, generation).
- Audit log is append-only at the database permission level.
- Voice cloning is off until consent, ownership verification and a blocklist exist.
- Private uploads are never sent to a provider whose terms permit training on customer data
  without an explicit per-user consent toggle.

## 9. Success metrics

Activation (first 5 minutes listened), cache hit ratio (minute-weighted), cost per audio hour,
attribution correction rate per book, re-render ratio after a voice change, D7/D30 retention,
share of listening served from pre-generated catalogue, and the p95 of "play → sound".

## 10. Explicitly out of scope

DRM circumvention; bulk scraping of sources that forbid it; claims of worldwide public-domain
status; automatic cross-book character merging without human confirmation; celebrity voice
imitation; a permanent GPU fleet; music or sound effects; publishing to external audiobook
stores.
