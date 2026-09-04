# Security and trust boundaries

## Data handling

The core library is offline and has no network dependencies. It only reads files explicitly
provided by the caller and writes to explicitly configured output paths.

Do not place secrets, export-controlled material, personal data, or privileged evidence in a
public repository. AEE records may reveal architecture, risks, and unresolved weaknesses.

## Model-backed enrichment

The core library does not contact a model. Host applications that add model-backed review must:

- classify model output as asserted or inferred;
- avoid sending protected data to an unauthorized provider;
- retain the model and policy identity in metadata;
- require independent evidence for high-impact gates; and
- preserve counterevidence and human overrides.

## Cryptographic scope

SHA-256 chaining detects local history mutation. It is not a digital signature, trusted timestamp,
identity proof, or truth oracle. See the [ledger guide](ledger.md).

