"""Choosing or creating a guest, without a dropdown of every guest ever.

Most bookings are for someone new, and the client list only ever grows, so the
old "pick from a list, or choose + New client" arrangement had it backwards: it
made the common case an extra step and the uncommon case unusable at scale.

Here the name is simply typed. Anyone already on file matching what has been
typed is offered underneath it, so a repeat guest is found by starting to type
their name or number - but doing nothing creates a new client, because that is
what usually happens.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from db import queries
from lib.models import Client

MIN_SEARCH = 2
MAX_MATCHES = 8


@dataclass(frozen=True)
class ClientChoice:
    """Who the booking or quote is for, once the picker has been used."""

    client_id: int | None
    name: str
    phone: str = ""
    email: str = ""

    @property
    def is_new(self) -> bool:
        return self.client_id is None

    @property
    def is_usable(self) -> bool:
        """A new guest needs a name; an existing one is already identified."""
        return self.client_id is not None or bool(self.name.strip())

    def commit(self) -> int | None:
        """Create the client if this is a new one, and return the id to store."""
        if self.client_id is not None:
            return self.client_id
        if not self.name.strip():
            return None
        return queries.create_client(self.name.strip(), self.phone.strip(), self.email.strip())


def _describe(client: Client) -> str:
    detail = " / ".join(part for part in (client.phone, client.email) if part)
    return f"{client.name}  ({detail})" if detail else client.name


def client_picker(key: str, current: Client | None = None) -> ClientChoice:
    """Render the guest fields and return who was chosen.

    `current` is the guest already on a record being edited. It is kept unless
    the user explicitly asks to change it, so editing a booking's dates cannot
    quietly create a second copy of the same guest.
    """
    if current is not None:
        held = st.columns([3, 2])
        held[0].markdown(f"**Guest:** {current.name}")
        held[1].caption(" / ".join(p for p in (current.phone, current.email) if p) or "no contact details")
        if not st.checkbox("Change guest", key=f"{key}_change"):
            return ClientChoice(current.id, current.name, current.phone, current.email)

    typed = st.text_input(
        "Guest name",
        key=f"{key}_name",
        placeholder="Start typing - anyone already on file will appear below",
    )

    matches = queries.find_clients(typed, MAX_MATCHES) if len(typed.strip()) >= MIN_SEARCH else []
    chosen: Client | None = None

    if matches:
        labels = [f"New guest: {typed.strip()}"] + [_describe(client) for client in matches]
        # Indexes rather than the labels themselves: two guests can share a
        # name, and Streamlit needs the options to be distinguishable.
        picked = st.radio(
            f"{len(matches)} already on file matching that",
            options=range(len(labels)),
            format_func=lambda index: labels[index],
            key=f"{key}_match",
        )
        if picked:
            chosen = matches[picked - 1]

    if chosen is not None:
        st.caption("Using the guest already on file, so their booking history stays in one place.")
        return ClientChoice(chosen.id, chosen.name, chosen.phone, chosen.email)

    contact = st.columns(2)
    phone = contact[0].text_input("Phone", key=f"{key}_phone")
    email = contact[1].text_input("Email", key=f"{key}_email")
    return ClientChoice(None, typed, phone, email)
