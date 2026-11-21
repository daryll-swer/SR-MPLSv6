# SR-MPLSv6

SR-MPLSv6: Segment Routing over MPLS with IPv6-only underlay and overlay — protocol specification, architecture and Internet-Draft development

This repository contains the source of the Internet-Draft
**draft-swer-spring-sr-mplsv6**, *Segment Routing over MPLS with IPv6-Only
Underlay and Overlay (SR-MPLSv6)*, in RFC XML v3 format for
[xml2rfc](https://pypi.org/project/xml2rfc/).

Read the draft:

- [Editor's copy](https://next-hopself.github.io/SR-MPLSv6/) (HTML, published
  from `main`)
- [Plain text](draft-swer-spring-sr-mplsv6.txt), in this repository

## Summary

SR-MPLS ([RFC 8660](https://www.rfc-editor.org/info/rfc8660)) does not specify
how labelling works when the underlay and overlay are IPv6-only and IPv4
routing is provided by advertising IPv4 NLRI with IPv6 next hops
([RFC 8950](https://www.rfc-editor.org/info/rfc8950)). IPv4 packets in the
global table are then carried with a Prefix-SID that is bound to an IPv6
prefix, and the node that pops or replaces that label cannot tell from the
label alone that the packet beneath it is IPv4. Vendors have filled the gap in
non-interoperable ways, or with a 6PE-like extra label (e.g., BGP-LU or label 0
at the bottom of the stack) that consumes label stack depth and forces
explicit-null-only behaviour.

The draft proposes layer 3 (payload address family) awareness in the SR-MPLS
data plane. Depending on the Prefix-SID configuration, the penultimate hop
inspects the IP version of the payload and either transmits the packet with
the matching EtherType (implicit null) or imposes the matching Explicit NULL
label (explicit null). Open issues are tracked in the draft's "Open Issues"
appendix.

## Building

Requirements: Python 3 with `xml2rfc`, `make`, and Node.js (for `idnits`).

```sh
pip install xml2rfc   # or: pipx install xml2rfc
make                  # build/draft-swer-spring-sr-mplsv6-00.{txt,html}
make idnits           # check the draft with idnits 3
make submit           # build/draft-swer-spring-sr-mplsv6-00.xml (expanded, for upload)
```

`make` also refreshes the plain-text copy, `draft-swer-spring-sr-mplsv6.txt`,
when the XML changes; commit it together with the XML. The expanded XML from
`make submit` is the file to upload to the
[datatracker](https://datatracker.ietf.org/submit/).

CI renders the draft, checks that the plain-text copy is up to date, and runs
idnits on pull requests and on pushes to `main`; the rendered files are
attached to each run as the `internet-draft` artifact. Pushes to `main` also
publish the editor's copy to GitHub Pages.

## Contributing

Contributions to this repository are Contributions to the IETF Standards
Process; see [CONTRIBUTING.md](CONTRIBUTING.md). Authoring convention: one
sentence per line.
