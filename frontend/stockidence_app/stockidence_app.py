"""Stockidence — Reflex frontend for the stock confidence rating pipeline."""

import reflex as rx

from .components import (
    main_panel,
    profile_panel,
    side_panel,
    top_nav,
)
from .discover import discover
from .documentation import documentation
from .state import RatingState


def app_shell(content: rx.Component) -> rx.Component:
    return rx.box(
        rx.vstack(
            top_nav(),
            rx.flex(
                rx.box(
                    side_panel(),
                    align_self="start",
                    flex_shrink="0",
                ),
                rx.vstack(
                    content,
                    spacing="5",
                    align="center",
                    width="100%",
                    flex_grow="1",
                    max_width="1240px",
                    padding_bottom="10",
                ),
                spacing="6",
                align="start",
                justify="center",
                width="100%",
            ),
            spacing="5",
            align="stretch",
            width="100%",
        ),
        width="100%",
        max_width="90%",
        margin="0 auto",
        padding_x="6",
        min_height="90vh",
    )


def index() -> rx.Component:
    return app_shell(main_panel())


def stock_profile() -> rx.Component:
    return app_shell(profile_panel())


def discover_page() -> rx.Component:
    return app_shell(discover())


def documentation_page() -> rx.Component:
    return app_shell(documentation())


app = rx.App(
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap",
        "palette.css",
        "animations.css",
    ],
    head_components=[
        rx.el.link(
            rel="icon",
            type="image/svg+xml",
            href="/bull_logo.svg",
        ),
    ],
)
app.add_page(index, title="Stockidence — Stock Confidence Rating")
app.add_page(
    stock_profile,
    route="/stocks/[symbol]",
    title="Stock Profile — Stockidence",
    on_load=RatingState.load_profile,
)
app.add_page(discover_page, route="/discover", title="Discover — Stockidence")
app.add_page(documentation_page, route="/documentation", title="Documentation — Stockidence")