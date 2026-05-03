# PHI Fields Inventory

Lists every field in the system that constitutes Patient Health Information and therefore requires encryption at rest, audit logging on access, and masking in anonymized reports.

The DB epic owner enforces encryption on these fields. The Reporting epic owner enforces masking when generating anonymized exports.

## Encrypted-at-rest required

| Field | Schema location | Why |
|-------|-----------------|-----|
| `patient_name` | `OCRResult.fields[patient_name].value` | Direct identifier |
| `medication` | `OCRResult.fields[medication].value` | Combined with name → identifies condition |
| `raw_text` | `OCRResult.raw_text` | May contain any of the above |
| (image bytes) | filesystem / object store | Contains everything visible on the document |

## Masked in anonymized reports

All fields above plus:

- `device_id` — can correlate to a specific clinic location, which combined with date narrows the patient set.
- `bounding_box` coordinates — by themselves harmless, but if the original image is reachable they enable re-identification.

## Pseudonymization strategy

For research exports, `patient_name` is replaced with a per-export salted hash:

```
hash = HMAC-SHA256(export_secret, normalize(patient_name))
```

Where `export_secret` is unique per export so cross-export linkage is impossible.

## Retention

- Active records: indefinite (subject to compliance team final say).
- Deleted records: cryptographic erasure (key destruction) within 30 days of deletion request.
- Audit log: minimum 6 years (regulatory floor — confirm with compliance for actual jurisdiction).

## Open questions

- Are doctor's reviewer notes (`ReviewResolution.reviewer_notes`) PHI? Treating as "yes" by default until compliance says otherwise.
- Bounding box: technically not PHI but combined with image is. Decide policy with the DB epic owner.
