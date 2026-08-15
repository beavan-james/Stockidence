"""Discover — market movers, news & sentiment, IPO and earnings calendars."""

import reflex as rx

from .components import discover_panel


def discover() -> rx.Component:
    return discover_panel()