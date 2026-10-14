# Pending controls for BUK personnel payload

`Persona.buk_payload` stores the complete individual response from BUK. It may
contain financial, health, and family information, including information about
minors. Treat every value in this column as highly sensitive personal data.

The schema does not make the payload available in the personnel listing or the
Django Admin. Before production use, the application still needs:

- narrowly scoped VICMEAS authorization and active-company checks for every
  payload read, export, or support operation;
- an explicit purpose, data-minimization policy, and retention/deletion period;
- access auditing that records the actor and operation without recording payload
  values;
- a verified encryption-at-rest and backup-protection policy for the selected
  operational database;
- redaction rules for exceptions, diagnostics, jobs, and any future API
  responses or serializers;
- a review of access, correction, deletion, and incident-response procedures.

The monthly importer validates and normalizes RUTs and stores each worker's
individual BUK response in `buk_payload`. Its coverage uses synthetic data;
this does not authorize direct payload access or production use without the
controls listed above. The database rejects a null or empty normalized RUT so
SQL uniqueness cannot admit duplicate rows through NULL values. The schema
cannot establish RUT validity by itself.

## Django company and BUK company identifiers

The Importar Personas view still authorizes access using VICMEAS for the active
Django company in `session["empresa_id"]`. `Persona.company_id` is the source
identifier from BUK; there is no authorized mapping from that value to the
Django `Empresa` model. The existing listing reads from the configured
`BASE_EVALUACIONES` scope without matching BUK company IDs to the active
Django company. Its BUK-company filter only narrows records already returned
by that listing; it is not an authorization or tenant-isolation control.
Establish and review an explicit company mapping before relying on BUK
`company_id` for cross-company access isolation.
