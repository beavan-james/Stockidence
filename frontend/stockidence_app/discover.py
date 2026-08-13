"""Discover — place for stock discovery (work in progress)."""

import reflex as rx

from .components import top_nav


def discover() -> rx.Component:
    return rx.box(
        rx.vstack(
            top_nav(),
            rx.vstack(
                rx.icon("compass", size=28, color=rx.color("iris", 9)),
                rx.heading(
                    "Discover",
                    size="7",
                    weight="bold",
                    letter_spacing="-0.02em",
                ),
                rx.text(
                    "Stock discovery is coming soon.",
                    size="3",
                    color=rx.color("slate", 10),
                ),
                spacing="3",
                align="center",
                padding_y="10",
            ),
            spacing="5",
            align="center",
            width="100%",
            max_width="1000px",
            padding_bottom="10",
        ),
        width="100%",
        max_width="90%",
        margin="0 auto",
        padding_x="6",
        min_height="90vh",
    )