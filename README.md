# SR-MPLSv6

SR-MPLSv6: Segment Routing over MPLS with IPv6-only underlay and overlay — protocol specification, architecture and Internet-Draft development

# Intro

SR-MPLS was defined in [RFC8660]; however, the specifications did not specify how labelling should work when the underlay and overlay are IPv6-only and IPv4 routing is enabled - i.e. the Point-to-Point IGP links are IPv6-only and the overlay BGP sessions between PEs are IPv6-only, with [RFC8950] enabled for IPv4 routing over IPv6 (SR-MPLSv6). This has led to different vendors interpreting the lack of direction in various non-interoperable ways. Some may have adopted a 6PE-like approach, where BGP-LU (or BGP-LU-like) is used as a crutch to provide the necessary labelling to support IPv4 routing over SR-MPLSv6 by exploiting the label stack depth and pushing label 0 (bottom-of-stack), which forces explicit null-only behaviour. The only known exception to this issue is for VRF-based implementations, where the labelling already identifies the correct VRF to drop a packet into, regardless of AFI.

# Proposed Solution
Introduce layer 3 awareness to the SR-MPLS data plane whereby, depending on the configuration, the first-hop, the penultimate hop or the ultimate hop inspects the layer 3 header to identify the AFI for further action.

Implicit Null:
The first-hop receives an IPv4 packet; the next-hop is the /128 IPv6 address of the ultimate hop's loopback. In this scenario, the standard [RFC8660] behaviour applies to the first-hop and the transit nodes (LERs), up until it reaches the Penultimate hop. Once the IPv4 packet has reached the Penultimate hop and all the labels are popped, the Penultimate hop inspects the frame's L3 headers to determine the AFI; if it's an IPv4 payload, then the penultimate hop writes EtherType 0x0800 into the frame and forwards the frame based on the destination MAC address of the Ultimate Hop. This ensures that when the Ultimate Hop receives the frame, it sees the correct EtherType and accordingly processes the packet for further routing or switching.

Explicit Null Null:
The first-hop receives an IPv4 packet; the next-hop is the /128 IPv6 address of the ultimate hop's loopback. In this scenario, the standard [RFC8660] behaviour applies to the first-hop and the transit nodes (LERs), up until it reaches the Penultimate hop. Once the IPv4 packet has reached the Penultimate hop and all the labels are popped, the Penultimate hop inspects the frame's L3 headers to determine the AFI; if it's an IPv4 payload, then the penultimate hop pushes label 0 to the frame and forwards it to the Ultimate Hop based on the regular IGP routing mechanism. This ensures that when the Ultimate Hop receives the frame, it sees the correct label 0 and accordingly processes the packet for further routing or switching in the main routing table.

# Example topologies to account for
ECMP and non-ECMP need verification.
```text
                       SR-MPLS CORE
                  (IPv6-only IGP: IS-IS)

                             P1
                          /      \
                         /        \
CE1 ----- PE1 ----------<          >---------- PE2 ----- CE2
                         \        /
                          \      /
                             P2

           PE1 <-- iBGP overlay (IPv6-only) --> PE2
```
```text
                                           SR-MPLS CORE
                                      (IPv6-only IGP: IS-IS)

                                                 +------+
                                                 |  P1  |
                                             /   +------+   \
                                         /           |          \
                                     /          /    |    \         \
                                 /            /      |     \            \
                             /              /        |      \               \
                  +------+                 /         |        \                 +------+
              ----| PE1  |                /          |          \               | PE3  |----
             /    +------+              /            |           \              +------+    \
            /         |   \           /              |            \            /    |        \
           /          |     \        /               |              \        /      |         \
          /           |      \      /                |                \     /       |          \
         /            |       \   /                  |                 \   /        |           \
CE1----<              |         X                    |                  X           |            >----CE2
         \            |        / \                   |                  / \         |           /
          \           |       /   \                  |                 /    \       |          /
           \          |     /       \                |               /       \      |         /
            \         |   /          \               |              /         \     |        /
             \    +------+            \              |             /            +------+    /
              ----| PE2  |              \            |           /              | PE4  |----
                  +------+               \           |          /               +------+
                             \            \          |         /            /
                                 \          \        |       /          /
                                     \       \       |      /       /
                                         \    \      |     /    /
                                             \  \+------+/  /
                                                 |  P2  |
                                                 +------+
```
```text
+--------------------------+-----------------------------------------+
| Connection               | Addressing / protocol                   |
+--------------------------+-----------------------------------------+
| PE <-> P (core links)    | IS-IS IPv6-only underlay links          |
|                          | (Carries SR-MPLS)                        |
+--------------------------+-----------------------------------------+
| PE <-> CE (access links) | Dual-Stack                              |
|                          | (IPv4 + IPv6)                           |
+--------------------------+-----------------------------------------+
| PE1 <-> PE2 (overlay)    | iBGP (IPv6-only)                        |
|                          | RFC 8950 handles IPv4-AFI/SAFI.        |
+--------------------------+-----------------------------------------+
```
