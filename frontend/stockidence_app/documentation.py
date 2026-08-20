"""Documentation — README, MODEL, API, and architecture rendered as markdown tabs."""

from pathlib import Path

import reflex as rx

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCS = [
    {
        "label": "README",
        "value": "readme",
        "file": "README.md",
        "description": "Project overview, data sources, and architecture decisions.",
    },
    {
        "label": "ARCHITECTURE",
        "value": "architecture",
        "file": "ARCHITECTURE.md",
        "description": "Layered warehouse design, incremental loads, and orchestration.",
    },
    {
        "label": "MODEL",
        "value": "model",
        "file": "MODEL.md",
        "description": "Scoring model, category weights, and methodology.",
    },
    {
        "label": "API",
        "value": "api",
        "file": "API.md",
        "description": "Complete list of API metrics per scoring category.",
    },
]


def _load_markdown(filename: str) -> str:
    path = REPO_ROOT / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return f"Could not load `{filename}`."


def documentation() -> rx.Component:
    return rx.vstack(
        rx.vstack(
            rx.icon("book_open", size=28, color=rx.color("iris", 9)),
            rx.heading(
                "Documentation",
                size="7",
                weight="bold",
                letter_spacing="-0.02em",
            ),
            rx.text(
                "Everything behind the rating — how the pipeline works, how the model scores, and what data feeds it.",
                size="3",
                color=rx.color("slate", 10),
                text_align="center",
                max_width="36em",
            ),
            rx.tabs.root(
                rx.tabs.list(
                    *[
                        rx.tabs.trigger(
                            doc["label"],
                            value=doc["value"],
                            size="2",
                            weight="medium",
                        )
                        for doc in DOCS
                    ],
                    width="100%",
                    justify="center",
                ),
                *[
                    rx.tabs.content(
                        rx.vstack(
                            rx.hstack(
                                rx.box(
                                    width="10px",
                                    height="10px",
                                    border_radius="full",
                                    bg=rx.color("iris", 9),
                                ),
                                rx.text(
                                    doc["description"],
                                    size="2",
                                    color=rx.color("slate", 10),
                                ),
                                spacing="3",
                                align="center",
                            ),
                            rx.card(
                                rx.box(
                                    rx.markdown(
                                        _load_markdown(doc["file"]),
                                        use_gfm=True,
                                        use_math=False,
                                        use_katex=False,
                                        use_unwrap_images=True,
                                        use_raw=True,
                                    ),
                                    class_name="md-table-wrap",
                                    width="100%",
                                    max_width="100%",
                                ),
                                width="100%",
                                padding="6",
                                align="start",
                            ),
                            align="start",
                            width="100%",
                            spacing="4",
                        ),
                        value=doc["value"],
                        width="100%",
                    )
                    for doc in DOCS
                ],
                default_value="readme",
                width="100%",
            ),
            spacing="5",
            align="center",
            width="100%",
        ),
        spacing="5",
        align="center",
        width="100%",
        max_width="1000px",
        padding_bottom="10",
    )