from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Open Perplexity web login in a real browser and save storage state for headless runs."
        )
    )
    parser.add_argument(
        "--storage-state",
        default="backend/data/perplexity_storage_state.json",
        help="Output path for Playwright storage state JSON.",
    )
    parser.add_argument(
        "--url",
        default="https://www.perplexity.ai",
        help="Perplexity URL to open.",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright is required. Install dependencies and run `python -m playwright install chromium`."
        ) from exc

    storage_path = Path(args.storage_state).expanduser().resolve()
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=120000)

        print("\nLog in to Perplexity in the opened browser window.")
        print("After login completes and home screen is visible, press Enter here to save session state.")
        input("Press Enter to continue...")

        context.storage_state(path=str(storage_path))
        print(f"Saved storage state to: {storage_path}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
