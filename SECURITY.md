# Security Policy

## Supported versions

Security fixes are provided for the latest 1.x release.

## Reporting a vulnerability

Use the repository's [private vulnerability reporting
form](https://github.com/electrohire/applied-epistemic-engineering/security/advisories/new).
Do not disclose a suspected vulnerability in a public issue, discussion, or pull request, and do
not include secrets, regulated data, or customer artifacts in a report.

Please include affected versions, impact, reproduction steps or a proof of concept, and any known
mitigation. ElectroHire will acknowledge a report within three business days, provide a status
update within seven business days, and coordinate disclosure after a fix is available. If a report
is not accepted as a vulnerability, the response will explain why.

## Security boundaries

The hash-chain ledger is tamper-evident, not an identity, timestamp, truth, or non-repudiation
service. Use signed commits, trusted timestamps, access control, and independent evidence when
those properties are required.
