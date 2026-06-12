"""Resolve an Indeed posting to the company's own application URL.

Many Indeed postings are mirrors of an ATS posting (Greenhouse, Lever, ...).
Following 'Apply on company site' upgrades the job from the assisted lane to
the auto-submit lane. Best-effort: Indeed bot-walls headless browsers some of
the time; failures return None and the job stays assisted.
"""

APPLY_LINK_SELECTORS = (
    "a:has-text('Apply on company site')",
    "a[aria-label*='company site' i]",
    "#applyButtonLinkContainer a",
    "#viewJobButtonLinkContainer a",
    "button[aria-label*='company site' i]",
)


def resolve_indeed(url: str, timeout_ms: int = 30000):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(2500)
            for selector in APPLY_LINK_SELECTORS:
                el = page.locator(selector)
                if el.count():
                    href = el.first.get_attribute("href")
                    if not href:
                        continue
                    if href.startswith("/"):
                        href = "https://www.indeed.com" + href
                    page.goto(href, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(2500)
                    final = page.url
                    return final if "indeed.com" not in final else None
            return None
        except Exception:
            return None
        finally:
            browser.close()
