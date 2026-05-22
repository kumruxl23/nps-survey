"""Helpers for the nomination row's sort-key encoding.

A stakeholder shared across multiple leaders produces multiple Nomination
rows. The DynamoDB sort key is ``email``; for the 2nd, 3rd, ... leader of
a shared stakeholder we suffix the key with ``#<leader>`` to keep rows
unique. The plain email always belongs to the FIRST leader written.

Helpers:

  * :func:`base_email` — strip the ``#leader`` suffix to get the deliverable
    email address for sending mail / Slack DMs.
  * :func:`encode_for_leader` — compute a unique sort key for ``(email, leader)``
    given the set of keys already taken by other rows in the cycle.
"""

from __future__ import annotations

NOM_SUFFIX_SEP = "#"


def base_email(suffixed_email: str) -> str:
    """Return the deliverable email address (no ``#leader`` suffix)."""
    if not suffixed_email:
        return suffixed_email
    return suffixed_email.split(NOM_SUFFIX_SEP, 1)[0]


def encode_for_leader(email: str, leader: str, taken_keys: set[str]) -> str:
    """Return a unique nomination sort-key for ``(email, leader)``.

    If the plain email isn't already in ``taken_keys``, that's used; the
    leader gets the unsuffixed primary row. Otherwise we append
    ``#<leader>`` so the key stays unique. Mutates ``taken_keys`` to
    record the chosen key.
    """
    base = (email or "").strip().lower()
    if base and base not in taken_keys:
        taken_keys.add(base)
        return base
    suffixed = f"{base}{NOM_SUFFIX_SEP}{(leader or '').strip()}"
    taken_keys.add(suffixed)
    return suffixed


def find_nomination_for_leader(nominations: list, email: str, leader: str):
    """Find the nomination row that matches ``(email, leader)``.

    Returns the matching ``Nomination`` (with ``.email`` possibly suffixed)
    or ``None`` if no row exists for that leader-stakeholder pair.
    """
    base = (email or "").strip().lower()
    target_leader = (leader or "").strip()
    for n in nominations:
        if base_email(n.email).lower() != base:
            continue
        if (n.leader or "").strip() == target_leader:
            return n
    return None
