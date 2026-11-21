# Contributing

This repository relates to activities in the Internet Engineering Task Force
([IETF](https://www.ietf.org/)). All material in this repository is considered
Contributions to the IETF Standards Process, as defined in the intellectual
property policies of the IETF currently designated as
[BCP 78](https://www.rfc-editor.org/info/bcp78),
[BCP 79](https://www.rfc-editor.org/info/bcp79), and the
[IETF Trust Legal Provisions (TLP) Relating to IETF Documents](https://trustee.ietf.org/license-info).

Any edit, commit, pull request, issue, comment, or other change made to this
repository constitutes a Contribution to the IETF Standards Process. You agree
to comply with all applicable IETF policies and procedures, including BCP 78,
BCP 79, the TLP, and the TLP rules regarding code components (e.g., being
subject to a Simplified BSD License) in Contributions. See the
[IETF Note Well](https://www.ietf.org/about/note-well/) for details.

## Editing the draft

- The source of truth is
  [`draft-swer-spring-sr-mplsv6.xml`](draft-swer-spring-sr-mplsv6.xml), written
  in RFC XML v3 ([RFC 7991](https://www.rfc-editor.org/info/rfc7991)).
- Authoring convention: one sentence per line, so that diffs stay reviewable.
- Keep artwork within 69 columns so that it fits the 72-column text output.
- Run `make` and `make idnits` before opening a pull request; CI runs both.
- Bump the revision in both `docName` and `<seriesInfo>` only when submitting a
  new version to the datatracker.
