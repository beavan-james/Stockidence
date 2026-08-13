import reflex as rx

config = rx.Config(
    app_name="stockidence_app",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                accent_color="iris",
                gray_color="slate",
                appearance="dark",
                has_background=True,
            )
        ),
    ]
)